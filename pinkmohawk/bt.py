"""Behavior Tree ticker: schema validation, the three-valued tick, and per-actor state.

DECISIONS §8 (the architecture rules and `MAX_TICKS_PER_STEP`); schema, tick semantics and the
ticker pseudocode in docs/design/ai.md §2-§4. This module implements the ten decisions recorded in
`DECISIONS.md` §8 and resolved as items 23-30 in §14:

  1. Trees are immutable shared data; state is per actor (`BTState`).      §14.23
  2. Abandoning a RUNNING branch clears that subtree's ephemeral state,     §14.24
     never its cooldowns.
  3. Leaves reach game actions through an injected `eval_leaf` callback;    §8 layer law
     this module never imports `entities` or `rules`.
  4. Movement is one Step per decision step: a leaf returns RUNNING.        §14.28
  5. Leaves never spend Energy. A handler *records* its action through the
     context; the ticker reports that cost and the caller deducts it.       §14.25
  6. Cooldowns key on the node's `name` when it has one, else its path.     §14.26
  7. `MAX_TICKS_PER_STEP` turns an intra-step spin into a `BTLivelock`.      §14.27
  8. `repeat.times == 0` is one repetition per decision step, returning
     RUNNING each time rather than SUCCESS.                                 §14.28

MOCK LEAVES
-----------
`eval_leaf(name, args, ctx) -> Status` is the only way a tree reaches the world, so a tree can be
ticked with fake leaves and no world at all:

    tick(tree, BTState(), lambda name, args, ctx: Status.SUCCESS, TickContext())

    .venv/bin/python -m pinkmohawk.bt      # runs demo()
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import FrozenInstanceError, dataclass, field
from enum import Enum
from typing import Any, Final

from .constants import ENERGY_COSTS, MAX_TICKS_PER_STEP
from .errors import RuntimeFailure, ValidationError

#: The eight node types of DECISIONS §8, one spelling per concept (ai.md §2).
NODE_TYPES: Final = (
    "selector",
    "sequence",
    "condition",
    "action",
    "inverter",
    "succeeder",
    "cooldown",
    "repeat",
)
COMPOSITES: Final = ("selector", "sequence")
DECORATORS: Final = ("inverter", "succeeder", "cooldown", "repeat")
LEAVES: Final = ("condition", "action")

#: Keys allowed on each node type. Any other key is a load error (ai.md §2.2).
ALLOWED_KEYS: Final = {
    "selector": {"type", "name", "children", "reactive"},
    "sequence": {"type", "name", "children"},
    "condition": {"type", "name", "check", "args"},
    "action": {"type", "name", "action", "args"},
    "inverter": {"type", "name", "child"},
    "succeeder": {"type", "name", "child"},
    "cooldown": {"type", "name", "child", "passes"},
    "repeat": {"type", "name", "child", "times"},
}


class Status(Enum):
    """Three-valued by construction: a Condition never returns RUNNING (ai.md §3.2)."""

    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    RUNNING = "RUNNING"


class SchemaError(ValidationError):
    """The document is malformed, or validation was skipped. Nothing malformed reaches runtime."""


class BTLivelock(RuntimeFailure):
    """A tree resolved more leaves than MAX_TICKS_PER_STEP inside one decision step."""


class HandlerError(RuntimeFailure):
    """A leaf handler broke the leaf contract — e.g. a Condition returning RUNNING."""


# ----------------------------------------------------------------------------------------------
# The parsed, immutable tree
# ----------------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Node:
    """One node. Frozen: trees are shared between actors and must never hold state."""

    type: str
    path: str
    name: str | None = None
    kind: str | None = None  # "check" for conditions, "action" for actions
    args: Mapping[str, Any] = field(default_factory=dict)
    children: tuple[Node, ...] = ()
    child: Node | None = None
    passes: int = 0  # cooldown
    times: int = 0  # repeat
    reactive: bool = True  # selector

    @property
    def trace_name(self) -> str:
        return self.name or self.path


@dataclass(frozen=True, slots=True)
class Tree:
    id: str
    archetype: str | None
    params: Mapping[str, Any]
    root: Node


@dataclass(slots=True)
class BTState:
    """Everything mutable about one actor's use of a tree. One per actor; never shared."""

    resume: dict[str, int] = field(default_factory=dict)  # path -> child index to resume at
    cooldowns: dict[str, int] = field(default_factory=dict)  # name-or-path -> Passes remaining
    repeats: dict[str, int] = field(default_factory=dict)  # path -> completions so far
    running: dict[str, int] = field(default_factory=dict)  # path -> the RUNNING child index
    root_status: Status | None = None

    def clear_branch(self, node: Node) -> None:
        """Decision 2: drop ephemeral state for a subtree, keep cooldowns."""
        self.resume.pop(node.path, None)
        self.repeats.pop(node.path, None)
        self.running.pop(node.path, None)
        for child in node.children:
            self.clear_branch(child)
        if node.child is not None:
            self.clear_branch(node.child)

    def reset_tree(self) -> None:
        """The Pass boundary (ai.md §3.1): resume indices and repeat counters cleared."""
        self.resume.clear()
        self.repeats.clear()
        self.running.clear()
        self.root_status = None


@dataclass(slots=True)
class TickContext:
    """What a handler is given, and where it records what it did.

    A handler never charges Energy (decision 5). It calls `charge("attack")` to declare the action;
    the lookup happens here from the contract's table, so a handler cannot invent a cost, and the
    caller deducts the total once.
    """

    actor: Any = None
    extra: dict[str, Any] = field(default_factory=dict)
    cost: int = 0
    actions: list[tuple[str, int]] = field(default_factory=list)

    def charge(self, action_key: str, times: int = 1) -> None:
        if action_key not in ENERGY_COSTS:
            raise KeyError(f"unknown energy action {action_key!r}; see DECISIONS §5")
        amount = ENERGY_COSTS[action_key] * times
        self.cost += amount
        self.actions.append((action_key, amount))


# ----------------------------------------------------------------------------------------------
# Loading and validation (ai.md §2.2, §2.3) — all errors, then refusal
# ----------------------------------------------------------------------------------------------
def load(
    document: Mapping[str, Any],
    *,
    known_actions: Mapping[str, frozenset[str]],
    known_checks: Mapping[str, frozenset[str]],
) -> Tree:
    """Parse and validate a tree document, or raise SchemaError listing every problem.

    `known_actions` maps an action name to its declared arg keys; `known_checks` does the same for
    conditions. The catalogues live in `ai.py` (ai.md §7, §8); passing them in keeps this module
    free of the domain and lets tests supply fake ones.
    """
    errors: list[str] = []

    if not isinstance(document, Mapping):
        raise SchemaError(["E_DOCUMENT: a tree must be a JSON object"])
    for required in ("id", "root"):
        if required not in document:
            errors.append(f"E_MISSING_KEY document {required}")
    if errors:
        raise SchemaError(errors)

    if document.get("archetype") is not None and not isinstance(document["archetype"], str):
        errors.append("E_ARCHETYPE document archetype must be a string")
    params = document.get("params") or {}
    if not isinstance(params, Mapping):
        errors.append("E_PARAMS document params must be an object")
        params = {}

    seen_paths: list[str] = []

    def visit(raw: Any, path: str) -> Node | None:
        if not isinstance(raw, Mapping):
            errors.append(f"E_NOT_OBJECT {path} node must be an object")
            return None
        seen_paths.append(path)
        ntype = raw.get("type")
        if ntype not in NODE_TYPES:
            errors.append(
                f"E_UNKNOWN_NODE_TYPE {path} {ntype!r} is not one of {'|'.join(NODE_TYPES)}"
            )
            return None

        extra = set(raw) - ALLOWED_KEYS[ntype]
        if extra:
            errors.append(f"E_UNKNOWN_KEY {path} {sorted(extra)} not allowed on {ntype}")
        missing = ALLOWED_KEYS[ntype] - set(raw)
        missing -= {"type", "name", "args", "reactive"}  # optional on every type
        if missing:
            errors.append(f"E_MISSING_KEY {path} {ntype} requires {sorted(missing)}")
            return None

        name = raw.get("name")
        if name is not None and not isinstance(name, str):
            errors.append(f"E_NAME {path} name must be a string")
            name = None

        if ntype in COMPOSITES:
            kids = raw["children"]
            if not isinstance(kids, list) or not kids:
                errors.append(f"E_EMPTY_CHILDREN {path} {ntype} needs at least one child")
                return None
            built = tuple(
                n for i, k in enumerate(kids) if (n := visit(k, f"{path}.{i}")) is not None
            )
            reactive = raw.get("reactive", True)
            if not isinstance(reactive, bool):
                errors.append(f"E_REACTIVE {path} reactive must be a boolean")
            return Node(ntype, path, name, children=built, reactive=bool(reactive))

        if ntype in DECORATORS:
            child = visit(raw["child"], f"{path}.0")
            if ntype == "cooldown":
                passes = raw["passes"]
                if not isinstance(passes, int) or isinstance(passes, bool) or passes < 1:
                    errors.append(f"E_PASSES {path} passes must be an integer >= 1")
                    passes = 1
                return Node(ntype, path, name, child=child, passes=passes)
            if ntype == "repeat":
                times = raw["times"]
                if not isinstance(times, int) or isinstance(times, bool) or times < 0:
                    errors.append(f"E_TIMES {path} times must be an integer >= 0")
                    times = 1
                return Node(ntype, path, name, child=child, times=times)
            return Node(ntype, path, name, child=child)

        # leaves
        args = raw.get("args") or {}
        if not isinstance(args, Mapping):
            errors.append(f"E_ARGS {path} args must be an object")
            args = {}
        catalogue, key_name = (
            (known_checks, "check") if ntype == "condition" else (known_actions, "action")
        )
        key = raw[key_name]
        if key not in catalogue:
            errors.append(f"E_UNKNOWN_{key_name.upper()} {path} {key!r} is not in the catalogue")
            return Node(ntype, path, name, kind=key, args=args)
        undeclared = set(args) - set(catalogue[key])
        if undeclared:
            errors.append(f"E_UNDECLARED_ARGS {path} {key} does not declare {sorted(undeclared)}")
        return Node(ntype, path, name, kind=key, args=args)

    root = visit(document["root"], "root")
    if root is None and not errors:
        errors.append("E_ROOT root failed to parse")

    if errors:
        raise SchemaError(errors)
    assert root is not None  # unreachable with a bad root: the checks above have raised

    tree_id = document["id"]
    if not isinstance(tree_id, str) or not tree_id:
        raise SchemaError(["E_ID document id must be a non-empty string"])
    return Tree(tree_id, document.get("archetype"), params, root)


# ----------------------------------------------------------------------------------------------
# The ticker (ai.md §4.3) — an explicit stack, RESUMED from `state`, one leaf per tick
# ----------------------------------------------------------------------------------------------
@dataclass(slots=True)
class _Frame:
    node: Node
    phase: str  # "DESCEND" | "ASCEND"
    idx: int
    status: Status | None = None


def cooldown_key(node: Node) -> str:
    """Decision 6: the author's `name` when given, else the node's path."""
    return node.name or node.path


def _enter_index(node: Node, state: BTState) -> int:
    if node.type == "selector":
        return 0 if node.reactive else state.resume.get(node.path, 0)
    if node.type == "sequence":
        return state.resume.get(node.path, 0)
    return 0


def tick(
    tree: Tree,
    state: BTState,
    eval_leaf: Callable[[str, Mapping[str, Any], TickContext], Status],
    ctx: TickContext | None = None,
) -> tuple[Status, int]:
    """Resolve at most one atomic action. Returns (root status, Energy the caller must charge).

    The returned cost comes from what the handler declared through `ctx.charge(...)`; this function
    never mutates Energy (decision 5).
    """
    context = ctx if ctx is not None else TickContext()
    context.cost = 0
    context.actions.clear()

    stack: list[_Frame] = [_Frame(tree.root, "DESCEND", _enter_index(tree.root, state))]
    resolved = 0

    while stack:
        frame = stack[-1]
        node = frame.node

        if frame.phase == "DESCEND":
            ntype = node.type
            if ntype in LEAVES:
                # Decision 7 counts LEAF RESOLUTIONS, not frames: a finite `repeat` re-descends
                # within one tick, and a large `times` is exactly what spins.
                resolved += 1
                if resolved > MAX_TICKS_PER_STEP:
                    raise BTLivelock(
                        f"tree {tree.id}: more than {MAX_TICKS_PER_STEP} leaf resolutions in one "
                        f"step (deepest node {node.path})"
                    )
            if ntype == "condition":
                stack.pop()
                status = eval_leaf(node.kind or "", node.args, context)
                if status is Status.RUNNING:
                    raise HandlerError(
                        f"condition {node.trace_name} returned RUNNING; "
                        "conditions are predicates (ai.md §3.2)"
                    )
                _deliver(stack, state, status)
            elif ntype == "action":
                stack.pop()
                _deliver(stack, state, eval_leaf(node.kind or "", node.args, context))
            elif ntype == "selector":
                if frame.idx >= len(node.children):
                    state.resume[node.path] = 0
                    stack.pop()
                    _deliver(stack, state, Status.FAILURE)
                else:
                    child = node.children[frame.idx]
                    stack.append(_Frame(child, "DESCEND", _enter_index(child, state)))
            elif ntype == "sequence":
                if frame.idx >= len(node.children):
                    state.resume[node.path] = 0
                    stack.pop()
                    _deliver(stack, state, Status.SUCCESS)
                else:
                    child = node.children[frame.idx]
                    stack.append(_Frame(child, "DESCEND", _enter_index(child, state)))
            elif ntype in ("inverter", "succeeder"):
                assert node.child is not None
                stack.append(_Frame(node.child, "DESCEND", _enter_index(node.child, state)))
            elif ntype == "cooldown":
                if state.cooldowns.get(cooldown_key(node), 0) > 0:
                    stack.pop()
                    _deliver(stack, state, Status.FAILURE)
                else:
                    assert node.child is not None
                    stack.append(_Frame(node.child, "DESCEND", _enter_index(node.child, state)))
            elif ntype == "repeat":
                if node.times > 0 and state.repeats.get(node.path, 0) >= node.times:
                    state.repeats[node.path] = 0
                    stack.pop()
                    _deliver(stack, state, Status.SUCCESS)
                else:
                    assert node.child is not None
                    stack.append(_Frame(node.child, "DESCEND", _enter_index(node.child, state)))
            else:  # unreachable: validation refuses it
                raise SchemaError([f"E_UNKNOWN_NODE_TYPE {node.path} {ntype!r}"])

        else:  # ASCEND
            if frame.status is None:  # unreachable: _deliver always sets it before ASCEND
                raise HandlerError(f"internal: frame {node.path} ascended without a status")
            status = frame.status  # narrowed to Status by the check, not asserted
            ntype = node.type
            if ntype == "selector":
                if status is Status.FAILURE:
                    frame.idx += 1
                    frame.status = None
                    frame.phase = "DESCEND"
                elif status is Status.RUNNING:
                    _abandon_siblings(state, node, winner=frame.idx)
                    state.running[node.path] = frame.idx
                    state.resume[node.path] = frame.idx
                    stack.pop()
                    _deliver(stack, state, Status.RUNNING)
                else:
                    _abandon_siblings(state, node, winner=frame.idx)
                    state.resume[node.path] = 0
                    stack.pop()
                    _deliver(stack, state, Status.SUCCESS)
            elif ntype == "sequence":
                if status is Status.SUCCESS:
                    frame.idx += 1
                    frame.status = None
                    frame.phase = "DESCEND"
                elif status is Status.RUNNING:
                    state.resume[node.path] = frame.idx
                    stack.pop()
                    _deliver(stack, state, Status.RUNNING)
                else:
                    state.resume[node.path] = 0
                    stack.pop()
                    _deliver(stack, state, Status.FAILURE)
            elif ntype == "inverter":
                stack.pop()
                _deliver(
                    stack,
                    state,
                    Status.RUNNING
                    if status is Status.RUNNING
                    else (Status.SUCCESS if status is Status.FAILURE else Status.FAILURE),
                )
            elif ntype == "succeeder":
                stack.pop()
                _deliver(
                    stack, state, Status.RUNNING if status is Status.RUNNING else Status.SUCCESS
                )
            elif ntype == "cooldown":
                if status is Status.SUCCESS:
                    state.cooldowns[cooldown_key(node)] = node.passes  # arm on success only
                stack.pop()
                _deliver(stack, state, status)
            elif ntype == "repeat":
                if status is Status.FAILURE:
                    state.repeats[node.path] = 0
                    stack.pop()
                    _deliver(stack, state, Status.FAILURE)
                elif status is Status.RUNNING:
                    stack.pop()
                    _deliver(stack, state, Status.RUNNING)
                else:
                    state.repeats[node.path] = state.repeats.get(node.path, 0) + 1
                    if node.times == 0:  # decision 8: one rep per step
                        state.resume[node.path] = 0
                        stack.pop()
                        _deliver(stack, state, Status.RUNNING)
                    elif state.repeats[node.path] >= node.times:
                        state.repeats[node.path] = 0
                        stack.pop()
                        _deliver(stack, state, Status.SUCCESS)
                    else:
                        state.resume[node.path] = 0
                        frame.idx = 0
                        frame.status = None
                        frame.phase = "DESCEND"

    return state.root_status or Status.FAILURE, context.cost


def _deliver(stack: list[_Frame], state: BTState, status: Status) -> None:
    if not stack:
        state.root_status = status
    else:
        top = stack[-1]
        top.status = status
        top.phase = "ASCEND"


def _abandon_siblings(state: BTState, node: Node, winner: int) -> None:
    """Decision 2, applied at a selector: any branch that was RUNNING and lost is cleared.

    Without this, a half-finished sequence resumes at its third child (or a "wait 2 turns" leaf
    completes instantly) when the selector comes back to it.
    """
    previous = state.running.get(node.path)
    if previous is not None and previous != winner:
        state.clear_branch(node.children[previous])
        state.running.pop(node.path, None)


def tick_cooldowns(state: BTState) -> None:
    """Advance every armed cooldown by one Pass. Called at the Pass boundary, never per action."""
    for key in list(state.cooldowns):
        state.cooldowns[key] -= 1
        if state.cooldowns[key] <= 0:
            del state.cooldowns[key]


# ==============================================================================================
# Acceptance test
# ==============================================================================================
def demo() -> None:
    ACTIONS = {
        "act": frozenset(),
        "move": frozenset(),
        "shout": frozenset(),
        "with_arg": frozenset({"n"}),
    }
    CHECKS: dict[str, frozenset[str]] = {"yes": frozenset(), "no": frozenset()}

    def build(doc):
        return load(doc, known_actions=ACTIONS, known_checks=CHECKS)

    def scripted(results):
        """A leaf handler driven by a list: each call returns the next status.

        Costs come from the handler, not from the ticker (decision 5), and each action maps to its
        catalogue key - a move is a `step` at 1 Energy, not an `attack` at 10.
        """
        queue = list(results)
        cost_key = {"move": "step", "act": "attack", "shout": "attack", "with_arg": "attack"}

        def handler(name, args, ctx):
            out = queue.pop(0)
            if out is Status.SUCCESS and name in cost_key:
                ctx.charge(cost_key[name])
            return out

        return handler

    # ---- 1. loading: valid tree, exact paths assigned, immutability --------------------
    tree = build(
        {
            "id": "t",
            "root": {
                "type": "sequence",
                "children": [
                    {"type": "condition", "check": "yes"},
                    {"type": "action", "action": "act", "name": "strike"},
                ],
            },
        }
    )
    assert tree.id == "t"
    assert tree.root.path == "root"
    assert tree.root.children[1].path == "root.1"
    assert tree.root.children[1].trace_name == "strike"
    assert isinstance(tree.root, Node)
    try:
        tree.root.name = "nope"  # type: ignore[misc]  # deliberate: must raise
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError("Node must be immutable: trees are shared between actors")

    # ---- 2. validation reports every error at once, then refuses ----------------------
    bad = {
        "id": "b",
        "root": {
            "type": "selector",
            "children": [
                {"type": "sequencer", "children": []},
                {"type": "action", "action": "missing_action"},
                {"type": "condition", "check": "yes", "args": {"nope": 1}},
                {"type": "cooldown", "passes": 0, "child": {"type": "action", "action": "act"}},
            ],
        },
    }
    try:
        build(bad)
        raise AssertionError("a malformed tree must not load")
    except SchemaError as e:
        codes = " ".join(e.args[0])
        for expected in (
            "E_UNKNOWN_NODE_TYPE",
            "E_UNKNOWN_ACTION",
            "E_UNDECLARED_ARGS",
            "E_PASSES",
        ):
            assert expected in codes, f"{expected} missing from {codes}"
    # an unknown key on a node type is a load error, not a silent ignore
    try:
        build({"id": "k", "root": {"type": "action", "action": "act", "when": "never"}})
        raise AssertionError("E_UNKNOWN_KEY not enforced")
    except SchemaError as e:
        assert "E_UNKNOWN_KEY" in e.args[0][0]

    # ---- 3. sequence order, and conditions never return RUNNING ----------------------
    seq = build(
        {
            "id": "s",
            "root": {
                "type": "sequence",
                "children": [
                    {"type": "condition", "check": "yes"},
                    {"type": "action", "action": "act"},
                ],
            },
        }
    )
    st = BTState()
    status, cost = tick(seq, st, scripted([Status.SUCCESS, Status.SUCCESS]), TickContext())
    assert status is Status.SUCCESS and cost == ENERGY_COSTS["attack"]
    status, cost = tick(seq, st, scripted([Status.FAILURE]), TickContext())
    assert status is Status.FAILURE and cost == 0, "a failed condition must be free"

    def bad_handler(name, args, ctx):
        return Status.RUNNING

    try:
        tick(seq, BTState(), bad_handler, TickContext())
        raise AssertionError("a Condition returning RUNNING must be rejected")
    except HandlerError:
        pass

    # ---- 4. RUNNING resumes at the same child instead of restarting ------------------
    run = build(
        {
            "id": "r",
            "root": {
                "type": "sequence",
                "children": [
                    {"type": "condition", "check": "yes"},
                    {"type": "action", "action": "move"},
                ],
            },
        }
    )
    st = BTState()
    status, _ = tick(run, st, scripted([Status.SUCCESS, Status.RUNNING]), TickContext())
    assert status is Status.RUNNING and st.resume["root"] == 1
    calls = []

    def record_then_succeed(name, args, ctx):  # a named handler: the clever lambda that used to be
        calls.append(name)  # here returned nothing (mypy) and read badly
        return Status.SUCCESS

    status, _ = tick(run, st, record_then_succeed, TickContext())
    assert calls == ["move"], f"the satisfied condition must not re-run, got {calls}"
    assert status is Status.SUCCESS

    # ---- 5. inverter and succeeder --------------------------------------------------
    inv = build(
        {"id": "i", "root": {"type": "inverter", "child": {"type": "condition", "check": "yes"}}}
    )
    assert tick(inv, BTState(), scripted([Status.SUCCESS]), TickContext())[0] is Status.FAILURE
    assert tick(inv, BTState(), scripted([Status.FAILURE]), TickContext())[0] is Status.SUCCESS
    # RUNNING must come from an Action: a Condition may not return it (ai.md §3.2)
    inv_act = build(
        {"id": "ia", "root": {"type": "inverter", "child": {"type": "action", "action": "act"}}}
    )
    assert tick(inv_act, BTState(), scripted([Status.RUNNING]), TickContext())[0] is Status.RUNNING
    suc = build(
        {"id": "u", "root": {"type": "succeeder", "child": {"type": "condition", "check": "no"}}}
    )
    assert tick(suc, BTState(), scripted([Status.FAILURE]), TickContext())[0] is Status.SUCCESS

    # ---- 6. cooldown arms on SUCCESS only, and survives a tree reset (decision 1) ----
    cd = build(
        {
            "id": "c",
            "root": {
                "type": "cooldown",
                "passes": 3,
                "name": "shout_cd",
                "child": {"type": "action", "action": "shout"},
            },
        }
    )
    st = BTState()
    assert tick(cd, st, scripted([Status.SUCCESS]), TickContext())[0] is Status.SUCCESS
    assert st.cooldowns == {"shout_cd": 3}, st.cooldowns
    assert tick(cd, st, scripted([]), TickContext())[0] is Status.FAILURE, (
        "armed -> FAILURE at 0 cost"
    )
    st.reset_tree()
    assert st.cooldowns == {"shout_cd": 3}, "reset_tree must NOT clear cooldowns"
    tick_cooldowns(st)
    tick_cooldowns(st)
    tick_cooldowns(st)
    assert st.cooldowns == {}, "cooldowns tick down per Pass"

    # ---- 7. cooldown keying: name when given, else path (decision 6) -----------------
    unnamed = build(
        {
            "id": "n",
            "root": {"type": "cooldown", "passes": 2, "child": {"type": "action", "action": "act"}},
        }
    )
    st = BTState()
    tick(unnamed, st, scripted([Status.SUCCESS]), TickContext())
    assert list(st.cooldowns) == ["root"], f"expected the path as the key, got {st.cooldowns}"

    # ---- 8. repeat: times=0 is one repetition per step and stays RUNNING (decision 8) -
    rep = build(
        {
            "id": "p",
            "root": {"type": "repeat", "times": 0, "child": {"type": "action", "action": "act"}},
        }
    )
    st = BTState()
    for _ in range(3):
        assert tick(rep, st, scripted([Status.SUCCESS]), TickContext())[0] is Status.RUNNING, (
            "times:0 must not report SUCCESS: it is unbounded, one rep per step"
        )
    assert st.repeats["root"] == 3
    # A FINITE repeat is atomic within one decision step: `times: 3` resolves all three repetitions
    # and returns SUCCESS in a single tick. Only `times: 0` spans steps. That asymmetry is what makes
    # a large finite count the livelock risk the cap exists for, and it is worth knowing before
    # writing a tree with `times: 500`.
    rep3 = build(
        {
            "id": "p3",
            "root": {"type": "repeat", "times": 3, "child": {"type": "action", "action": "act"}},
        }
    )
    st = BTState()
    seen = [tick(rep3, st, scripted([Status.SUCCESS] * 3), TickContext())[0] for _ in range(2)]
    assert seen == [Status.SUCCESS, Status.SUCCESS], seen
    assert st.repeats.get("root", 0) == 0, "the counter resets once the repeat completes"

    # ---- 9. a preempted RUNNING branch is cleared, so it restarts fresh (decision 2) --
    pre = build(
        {
            "id": "pre",
            "root": {
                "type": "selector",
                "reactive": True,
                "children": [
                    {
                        "type": "sequence",
                        "children": [
                            {"type": "action", "action": "move"},
                            {"type": "action", "action": "act"},
                        ],
                    },
                    {"type": "condition", "check": "yes"},
                ],
            },
        }
    )
    st = BTState()
    assert tick(pre, st, scripted([Status.RUNNING]), TickContext())[0] is Status.RUNNING
    assert st.resume.get("root.0") == 0
    # next step branch 0 fails, the second branch wins, so branch 0 is abandoned and its state dropped
    assert (
        tick(pre, st, scripted([Status.FAILURE, Status.SUCCESS]), TickContext())[0]
        is Status.SUCCESS
    )
    assert "root.0" not in st.resume, f"abandoned branch kept its resume index: {st.resume}"
    assert st.running == {}, st.running

    # ---- 10. per-actor isolation: one shared tree, two states (decision 1) -----------
    shared = build(
        {
            "id": "sh",
            "root": {
                "type": "sequence",
                "children": [
                    {"type": "action", "action": "move"},
                    {"type": "action", "action": "act"},
                ],
            },
        }
    )
    a_state, b_state = BTState(), BTState()
    tick(shared, a_state, scripted([Status.RUNNING]), TickContext())
    tick(shared, b_state, scripted([Status.SUCCESS, Status.SUCCESS]), TickContext())
    assert a_state.resume == {"root": 0} and b_state.resume == {"root": 0}
    assert (
        tick(shared, b_state, scripted([Status.SUCCESS, Status.SUCCESS]), TickContext())[0]
        is Status.SUCCESS
    )
    assert a_state.root_status in (None, Status.RUNNING), "actor A's state must be untouched"

    # ---- 11. the livelock cap turns a spin into an error (decision 7) ---------------
    # A repeat with a large FINITE count and a cheap child resolves many leaves inside one tick;
    # that is the spin the cap exists for. A times:0 repeat cannot spin, because decision 8 makes it
    # return RUNNING once per decision step.
    spin = build(
        {
            "id": "spin",
            "root": {
                "type": "repeat",
                "times": 1000,
                "child": {"type": "succeeder", "child": {"type": "condition", "check": "yes"}},
            },
        }
    )
    try:
        tick(spin, BTState(), scripted([Status.SUCCESS] * 4000), TickContext())
    except BTLivelock as e:
        assert "spin" in str(e), e
    else:
        raise AssertionError("expected the livelock cap to trip")

    # ---- 12. Energy accounting belongs to the caller (decision 5) ------------------
    spend = build(
        {
            "id": "sp",
            "root": {
                "type": "sequence",
                "children": [
                    {"type": "action", "action": "move"},
                    {"type": "action", "action": "act"},
                ],
            },
        }
    )
    actor = type("A", (), {"energy": 10})()
    ctx = TickContext()
    status, cost = tick(spend, BTState(), scripted([Status.SUCCESS, Status.SUCCESS]), ctx)
    assert actor.energy == 10, "the ticker must not touch Energy: it does not know the actor"
    actor.energy -= cost  # the caller charges, exactly once
    assert status is Status.SUCCESS
    assert ctx.actions == [("step", 1), ("attack", 10)], ctx.actions
    assert cost == ENERGY_COSTS["step"] + ENERGY_COSTS["attack"] == 11
    assert actor.energy == 10 - cost
    try:
        TickContext().charge("teleport")
        raise AssertionError("an undeclared cost must be refused")
    except KeyError:
        pass

    print(
        f"OK  bt: schema validation ({len(ERROR_NAMES)} error codes), {len(NODE_TYPES)} node types, "
        f"RUNNING resume, cooldown arm-on-success, repeat times:0 per step, "
        f"livelock cap {MAX_TICKS_PER_STEP}, per-actor isolation"
    )


ERROR_NAMES: Final = (
    "E_DOCUMENT",
    "E_MISSING_KEY",
    "E_ARCHETYPE",
    "E_PARAMS",
    "E_NOT_OBJECT",
    "E_UNKNOWN_NODE_TYPE",
    "E_UNKNOWN_KEY",
    "E_NAME",
    "E_EMPTY_CHILDREN",
    "E_REACTIVE",
    "E_PASSES",
    "E_TIMES",
    "E_ARGS",
    "E_UNKNOWN_ACTION",
    "E_UNKNOWN_CHECK",
    "E_UNDECLARED_ARGS",
    "E_ROOT",
    "E_ID",
)

if __name__ == "__main__":
    demo()

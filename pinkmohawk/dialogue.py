"""Dialogue: the Dialogue Graph loader, condition evaluator, and runner.

ADR-0010 is the decision — a custom JSON graph with a hand-written runner, conditions over a shared
variable store, validation inside the runner. We build a graph and an interpreter, never a language.
`docs/design/dialogue.md` is the specification; this module implements it, and where the document and
`DECISIONS.md` disagree the contract wins (two such cases are named in the comments below).

The runner owns flow, conditions and effects. It does **not** own game state: it takes an injected
host, which is what makes a conversation testable headless, exactly as `bt.tick` takes an injected
`eval_leaf` and `ai.py` takes a registry. The seam is three Protocols at the bottom of this file:

- `Store`  — the variable store of dialogue.md section 5.2 (`get`, `set`, `has_item`, `snapshot`).
             `campaign.py` implements it over the campaign and the live Blackboards.
- `Presenter` — `line`, `choices`, `close`. `render.py` implements it for the screen;
             `RecordingPresenter` here implements it for tests.
- `Host`   — the effects that mutate state dialogue cannot reach: `tick_clock`, `give_item`,
             `on_test`, `pool_bonus`. The runner applies an effect's *bookkeeping* (the store writes)
             and delegates the *game* half to the host.

`VarStore` below is a working reference store, used by the `play` command, the transcripts and the
demo. It is not game state — no campaign rules live in it — so the module stays runnable on its own.

Never `eval`, never `exec`: the evaluator is a positive whitelist over `ast` (section 4).
`docs/design/dialogue.md` 4.1 has the argument, and section 4.2's table is the whole language.

Two divergences from the design document, both in the contract's favour, both deliberate:

- **The Clock event is `alarm_tripped`, not `alarm`.** `dialogue.md` 3.1 and its section 9 file write
  `alarm`; `DECISIONS.md` 9's table says "Alarm tripped" and `constants.CLOCK_TICKS` agrees. E34
  validates against `CLOCK_TICKS`, so `alarm` would be refused as an unknown reason. An alias would
  give one concept two spellings, which is the drift this package keeps catching.
- **Faction ids for W3 are the two `world.md` 10.4 names it, `corp_arasaka` and `street_kobun`.**
  No faction table exists yet — the roadmap puts factions in Phase 3 — and W3 is only a warning, so
  an id outside the pair loads with a note rather than failing.

    .venv/bin/python -m pinkmohawk.dialogue                       # the acceptance test
    .venv/bin/python -m pinkmohawk.dialogue validate data/dialogue/*.json
    .venv/bin/python -m pinkmohawk.dialogue play data/dialogue/fixer_offer.json \\
        --set crew.nuyen=2000 --choices "The pay is 12k, the risk is 15k.","I'm in." --transcript
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import random
import re
import sys
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from . import constants, rules
from .errors import PinkMohawkError, RuntimeFailure, ValidationError

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIALOGUE_DIR: Final = ROOT / "data" / "dialogue"

# dialogue.md 6.2: silent nodes loop inside _enter; this is the bound that makes a silent cycle a
# raised error instead of a hang. DECISIONS 16 (Auto advance budget).
AUTO_ADVANCE_BUDGET: Final = constants.AUTO_ADVANCE_BUDGET
MAX_NODES: Final = 100  # E47, data-model.md 1 (D <= 100)
LINE_UI_WIDTH: Final = 200  # W6: the UI holds ~180 characters

# The nine attribute slugs dialogue may read. `constants.ATTRIBUTES` is the eight base attributes;
# Edge is the ninth and lives beside them on the sheet (dialogue.md 5.2, DECISIONS 1).
ATTRIBUTE_SLUGS: Final = (*constants.ATTRIBUTES, "edge")
SKILL_SLUGS: Final = tuple(constants.SKILLS)

# E38's catalogue: DECISIONS 4's weapons and armour, DECISIONS 9's prices, plus the trauma patch
# whose price is its own constant (DECISIONS 16, [P5]). One composition, no second list.
GEAR_CATALOGUE: Final = (
    frozenset(constants.WEAPONS)
    | frozenset(constants.ARMOUR)
    | frozenset(constants.GEAR_PRICES)
    | {"trauma_patch"}
)

# W3's known factions. world.md 10.4 names these two and no document gives a table yet; Phase 3 owns
# the real list (roadmap.md Phase 2 non-goals: "no factions beyond the Fixer").
KNOWN_FACTIONS: Final = frozenset({"corp_arasaka", "street_kobun"})

CLOCK_REASONS: Final = frozenset(constants.CLOCK_TICKS)

KINDS: Final = ("choice", "condition", "line", "command", "jump", "end")
WAITING_KINDS: Final = ("choice", "line")
SILENT_KINDS: Final = ("condition", "command", "jump")

# Section 2.2: which fields each derived kind forbids, and what it requires. The table is the
# implementation; the precedence order of `kind_of` is what makes a line+choices node a `choice`.
FORBIDS: Final[Mapping[str, tuple[str, ...]]] = {
    "choice": ("cond", "then", "else", "goto", "end"),
    "condition": ("line", "choices", "effects", "goto", "end", "speaker"),
    "line": ("cond", "then", "else"),
    "command": ("cond", "then", "else", "line", "choices"),
    "jump": ("line", "choices", "cond", "then", "else", "effects", "end", "speaker"),
    "end": ("line", "choices", "cond", "then", "else", "effects", "goto", "speaker"),
}


# ======================================================================================
# Errors
# ======================================================================================
class DialogueError(PinkMohawkError):
    """Base for everything this module raises deliberately."""


class DialogueValidationError(ValidationError):
    """A conversation document is malformed. Carries every problem, not just the first."""

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = list(problems)
        super().__init__(self.problems)

    def __str__(self) -> str:
        return "\n".join(self.problems)


class DialogueParseError(DialogueValidationError):
    """A condition or expression does not parse, or uses syntax outside section 4.2."""


class DialogueConditionError(DialogueError, RuntimeFailure):
    """A condition failed at runtime: an undeclared name, or a non-boolean result."""


class DialogueEffectError(DialogueValidationError):
    """An effect cannot be applied: unknown key, read-only key, or a type mismatch."""


class DialogueRuntimeError(DialogueError, RuntimeFailure):
    """The runner cannot continue: a runaway auto-advance, or an unresolvable runtime jump."""


# ======================================================================================
# The variable schema - dialogue.md section 5's table
# ======================================================================================
@dataclass(frozen=True, slots=True)
class VarSpec:
    """One declared variable: its type, its scope, and whether dialogue may write it."""

    type: type
    scope: str  # "Job" (cleared at Extraction), "Run", or "world" (persists, ADR-0012)
    writable: bool
    default: Any = None


def _specs() -> dict[str, VarSpec]:
    """The exact table of section 5, built once. `test.*` and `flags.*` are added per file."""
    out: dict[str, VarSpec] = {
        "heat": VarSpec(int, "world", False, 0),
        "clock": VarSpec(int, "Run", False, 0),
        "rep.fixer": VarSpec(int, "world", True, 0),
        "job.id": VarSpec(str, "Job", False, None),
        "job.type": VarSpec(str, "Job", False, None),
        "job.payout_base": VarSpec(int, "Job", False, 0),
        "job.payout_agreed": VarSpec(int, "Job", True, 0),
        "job.accepted": VarSpec(bool, "Job", False, False),  # written by start_job only
        "job.state": VarSpec(str, "Job", False, "offered"),
        "job.intel_scouted": VarSpec(bool, "Job", False, False),
        "crew.nuyen": VarSpec(int, "world", True, constants.STARTING_NUYEN),
    }
    # The eight read-only npc.* keys and the two dialogue may write (section 5.1).
    for key, kind in (
        ("morale", int),
        ("objective", str),
        ("noise_pos", tuple),
        ("target", int),
        ("last_known_pos", tuple),
        ("home_pos", tuple),
        ("cover_pos", tuple),
    ):
        out[f"npc.{key}"] = VarSpec(kind, "Run", False, None)
    out["npc.alert_level"] = VarSpec(int, "Run", True, 0)  # raise-only, section 3.1
    out["npc.pacified"] = VarSpec(bool, "Run", True, False)
    for slug in SKILL_SLUGS:
        out[f"skill.{slug}"] = VarSpec(int, "Run", False, 0)
    for slug in ATTRIBUTE_SLUGS:
        out[f"attr.{slug}"] = VarSpec(int, "Run", False, 0)
    return out


DECLARED: Final[Mapping[str, VarSpec]] = _specs()


def spec_for(
    key: str, *, test_keys: Iterable[str] = (), flags: Iterable[str] = ()
) -> VarSpec | None:
    """The spec for `key`, resolving the four wildcard namespaces. None means undeclared."""
    if key in DECLARED:
        return DECLARED[key]
    if key.startswith("rep.faction."):
        return VarSpec(
            int, "world", True, 0
        )  # an unknown faction is neutral, so a typo degrades softly
    if key.startswith("flags."):
        return VarSpec(bool, "Job", True, False) if key[6:] in set(flags) else None
    head, _, rest = key.partition(".")
    if head == "test" and rest:
        name, _, field_name = rest.partition(".")
        if name in set(test_keys) and field_name in ("hits", "net"):
            return VarSpec(int, "Job", False, 0)
        if name in set(test_keys) and field_name == "glitch":
            return VarSpec(bool, "Job", False, False)
    return None


def rep_key(who: str) -> str:
    """`who` from a change_rep effect to the store key it moves (section 3.1, E37)."""
    if who == "fixer":
        return "rep.fixer"
    if who.startswith("faction:") and len(who) > len("faction:"):
        return f"rep.faction.{who.split(':', 1)[1]}"
    raise DialogueEffectError([f"unknown rep target {who!r}"])


# ======================================================================================
# The condition evaluator - dialoge.md section 4
# ======================================================================================
BINOP: Final[Mapping[type[ast.operator], Any]] = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Mod: lambda a, b: a % b,
}
CMPOP: Final[Mapping[type[ast.cmpop], Any]] = {
    ast.Eq: lambda a, b: a == b,
    ast.NotEq: lambda a, b: a != b,
    ast.Lt: lambda a, b: a < b,
    ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b,
    ast.GtE: lambda a, b: a >= b,
}
BOOLOP: Final[Mapping[type[ast.boolop], Any]] = {ast.And: all, ast.Or: any}


@dataclass(frozen=True, slots=True)
class Fn:
    """One whitelisted call: its arity, its argument types, and what it does."""

    arity: int
    types: tuple[type, ...]
    impl: Any

    def call(self, store: Any, *args: object) -> Any:
        if len(args) != self.arity:
            raise DialogueParseError([f"has_item takes {self.arity} argument"])
        for value, want in zip(args, self.types, strict=True):
            if not isinstance(value, want):
                raise DialogueParseError(
                    [f"has_item expects {want.__name__}, got {type(value).__name__}"]
                )
        return self.impl(store, *args)


# dialogue.md 4.2: the one Call the language has. Inventory is not addressable any other way, and a
# whitelist entry is a lambda rather than an attribute lookup, so the sandbox has no surface.
WHITELIST: Final[Mapping[str, Fn]] = {
    "has_item": Fn(arity=1, types=(str,), impl=lambda store, item: store.has_item(item)),
}


def flatten(node: ast.expr) -> str | None:
    """`skill.negotiation` -> the string 'skill.negotiation'. None if it is not a dotted name.

    The evaluator never does attribute access. It flattens the chain and looks the *string* up in the
    store, so `rep.fixer.__class__` is not a class lookup, it is an undeclared key. One rule, no
    object traversal anywhere: a dotted chain is legal iff its flattened text is a declared key.
    """
    parts: list[str] = []
    cur: ast.expr = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if not isinstance(cur, ast.Name):
        return None
    parts.append(cur.id)
    return ".".join(reversed(parts))


def _bad_syntax(expr: str, node: ast.AST) -> str:
    return f"unsupported syntax {type(node).__name__} in condition '{expr}'"


def _op_syntax(expr: str, op: ast.AST) -> str:
    """A forbidden operator is reported by the operator's own name (4.4: `unsupported syntax Pow`)."""
    return f"unsupported syntax {type(op).__name__} in condition '{expr}'"


def _column(expr: str, exc: SyntaxError) -> int:
    """The 1-based column of a parse error.

    CPython 3.14's PEG parser reports `offset=0` when it hits the end of the input, so an
    unterminated expression carries no position at all: `heat +` is exactly that case. Falling back
    to the end of the expression is where the parser actually stopped, and it reproduces
    dialogue.md 4.4's worked example (`heat +` -> col 7) instead of a column only an older parser had.
    """
    return exc.offset or len(expr) + 1


def scan_condition(expr: str, *, declared: Any) -> tuple[set[str], list[str]]:
    """Walk a condition the way `evaluate` will, recording names and collecting problems.

    This is the loader's half of the evaluator (section 4.3): the same walk with a stub store, so
    `unknown variable` and `unsupported syntax` become load errors with the offending expression
    instead of runtime surprises in front of the player. `declared(key) -> bool` answers whether a
    flattened name is a store key.
    """
    problems: list[str] = []
    names: set[str] = set()
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        col = _column(expr, exc)
        raise DialogueParseError(
            [f"condition does not parse: {exc.msg} at col {col}: '{expr}'"]
        ) from exc

    def walk(node: ast.AST) -> None:
        if isinstance(node, ast.Expression):
            walk(node.body)
        elif isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float, bool, str)):
                problems.append(_bad_syntax(expr, node))
        elif isinstance(node, (ast.Name, ast.Attribute)):
            key = flatten(node)
            if key is None:
                problems.append(_bad_syntax(expr, node))
            elif not declared(key):
                problems.append(f"unknown variable '{key}' in condition '{expr}'")
            else:
                names.add(key)
        elif isinstance(node, ast.BoolOp):
            if type(node.op) not in BOOLOP:
                problems.append(_op_syntax(expr, node.op))
            for value in node.values:
                walk(value)
        elif isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.Not):
                walk(node.operand)
            elif isinstance(node.op, ast.USub) and isinstance(node.operand, ast.Constant):
                if not isinstance(node.operand.value, (int, float)):
                    problems.append(_op_syntax(expr, node.op))
            else:
                problems.append(_op_syntax(expr, node.op))
        elif isinstance(node, ast.BinOp):
            if type(node.op) not in BINOP:
                problems.append(_op_syntax(expr, node.op))
            walk(node.left)
            walk(node.right)
        elif isinstance(node, ast.Compare):
            for op in node.ops:
                if type(op) not in CMPOP:
                    problems.append(_op_syntax(expr, op))
            walk(node.left)
            for comparator in node.comparators:
                walk(comparator)
        elif isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in WHITELIST:
                name = node.func.id if isinstance(node.func, ast.Name) else type(node.func).__name__
                problems.append(f"unsupported call '{name}' in condition '{expr}'")
                return
            entry = WHITELIST[node.func.id]
            if node.keywords:
                problems.append(f"unsupported call '{node.func.id}' in condition '{expr}'")
                return
            if len(node.args) != entry.arity:
                problems.append(f"{node.func.id} takes {entry.arity} argument")
            for arg in node.args:
                walk(arg)
        else:
            problems.append(_bad_syntax(expr, node))

    walk(tree)
    return names, problems


def evaluate_expression(expr: str, store: Any) -> Any:
    """Evaluate a whitelisted expression to a value. Raises DialogueParseError.

    Two public entry points, because the language has two jobs: a `cond` must be a bool (4.3), and an
    effect's `expr` must be a value (`job.payout_base + 100 * test.haggle.net`, 3.1). The whitelist and
    the walker are identical; only the result contract differs, which is why this is one walker.
    """
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        col = _column(expr, exc)
        raise DialogueParseError(
            [f"condition does not parse: {exc.msg} at col {col}: '{expr}'"]
        ) from exc

    def ev(node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, (ast.Name, ast.Attribute)):
            key = flatten(node)
            if key is None:
                raise DialogueParseError([_bad_syntax(expr, node)])
            return store.get(key)  # undeclared -> DialogueConditionError, raised by the store
        if isinstance(node, ast.BoolOp):
            if type(node.op) not in BOOLOP:  # the whitelist holds on both paths, load and runtime
                raise DialogueParseError([_op_syntax(expr, node.op)])
            return BOOLOP[type(node.op)](ev(value) for value in node.values)  # short-circuits
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not ev(node.operand)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -ev(node.operand)
        if isinstance(node, ast.BinOp):
            if type(node.op) not in BINOP:
                raise DialogueParseError([_op_syntax(expr, node.op)])
            return BINOP[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.Compare):
            left = ev(node.left)
            for op, comparator in zip(node.ops, node.comparators, strict=True):
                if type(op) not in CMPOP:
                    raise DialogueParseError([_op_syntax(expr, op)])
                right = ev(comparator)
                if not CMPOP[type(op)](left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.Call):
            func = node.func
            if not isinstance(func, ast.Name) or func.id not in WHITELIST or node.keywords:
                shown = func.id if isinstance(func, ast.Name) else type(func).__name__
                raise DialogueParseError([f"unsupported call '{shown}' in condition '{expr}'"])
            return WHITELIST[func.id].call(store, *(ev(arg) for arg in node.args))
        raise DialogueParseError([_bad_syntax(expr, node)])

    return ev(tree)


def evaluate(expr: str, store: Any) -> bool:
    """A condition to a bool (4.3). A non-boolean result is a condition error, never a False."""
    result = evaluate_expression(expr, store)
    if not isinstance(result, bool):
        raise DialogueConditionError(f"condition is not boolean: '{expr}'")
    return result


class ConditionCache:
    """`ast.parse` is the only real cost in a condition, and files reuse the same text (6.2)."""

    __slots__ = ("_cache",)

    def __init__(self) -> None:
        self._cache: dict[str, str] = {}

    def evaluate(self, expr: str, store: Any) -> bool:
        if expr not in self._cache:
            self._cache[expr] = expr
        return evaluate(expr, store)


# ======================================================================================
# Text placeholders - section 2.4
# ======================================================================================
PLACEHOLDER: Final = re.compile(r"\{([^{}]*)\}")


def placeholders(text: str) -> tuple[list[tuple[str, bool]], list[str]]:
    """Every `{key}` / `{key:,}` in `text`. Returns ([(key, grouped)], problems)."""
    found: list[tuple[str, bool]] = []
    problems: list[str] = []
    for match in PLACEHOLDER.finditer(text):
        inner = match.group(1)
        grouped = inner.endswith(":,")
        name = inner[:-2] if grouped else inner
        if not name or ":" in name or "{" in name or not re.fullmatch(r"[a-z0-9_.]+", name):
            problems.append(f"malformed placeholder '{match.group(0)}'")
            continue
        found.append((name, grouped))
    # A brace that is not part of a well-formed placeholder is an error (2.4).
    stripped = PLACEHOLDER.sub("", text)
    if "{" in stripped or "}" in stripped:
        stray = re.search(r"[{}]", stripped)
        problems.append(
            f"malformed placeholder '{text[max(0, (stray.start() if stray else 0) - 1) :][:12]}'"
        )
    return found, problems


def interpolate(text: str, store: Any) -> str:
    """Resolve placeholders for display. A known key holding None renders `<MISSING:key>` (2.4)."""

    def one(match: re.Match[str]) -> str:
        inner = match.group(1)
        grouped = inner.endswith(":,")
        name = inner[:-2] if grouped else inner
        value = store.get(name)
        if value is None:
            return f"<MISSING:{name}>"
        return f"{value:,}" if grouped else f"{value}"

    return PLACEHOLDER.sub(one, text)


# ======================================================================================
# Effects - section 3
# ======================================================================================
@dataclass(frozen=True, slots=True)
class Effect:
    """One normalised effect: `op` plus its own arguments (section 3.1's `(op, args)` pair)."""

    op: str
    args: Mapping[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.op}({', '.join(f'{k}={v!r}' for k, v in self.args.items())})"


EFFECT_NAMES: Final = ("set", "give_item", "start_job", "change_rep", "tick_clock", "test")


@dataclass(frozen=True, slots=True)
class TestSpec:
    """A `test` effect's authored form, validated at load (E29-E32)."""

    key: str
    skill: str
    attribute: str
    threshold: int | None = None
    opposed_pool: int | None = None


def normalise_effect(raw: Mapping[str, Any]) -> tuple[Effect | None, list[str]]:
    """Flat authoring shape -> `(op, args)`. Naming zero or two effects is E21."""
    names = [name for name in raw if name in EFFECT_NAMES]
    if len(names) != 1:
        return None, [f"effect must name exactly one effect (got {sorted(raw)})"]
    op = names[0]
    payload = raw[op]
    if op == "set":
        key = raw.get("set")
        if not isinstance(key, str):
            return None, ["effect 'set' is missing 'key'"]
        if ("value" in raw) == ("expr" in raw):
            return None, ["set takes exactly one of 'value' or 'expr'"]
        args = {"key": key}
        if "value" in raw:
            args["value"] = raw["value"]
        else:
            args["expr"] = raw["expr"]
        return Effect("set", args), []
    if op == "give_item":
        if not isinstance(payload, Mapping):
            return None, ["effect 'give_item' needs an object with 'id' and optional 'qty'"]
        if "id" not in payload:
            return None, ["effect 'give_item' is missing 'id'"]
        return Effect("give_item", dict(payload)), []
    if op == "start_job":
        if payload is not True:
            return None, ["start_job takes the literal true"]
        return Effect("start_job"), []
    if op == "change_rep":
        if not isinstance(payload, Mapping):
            return None, ["effect 'change_rep' needs an object with 'who' and 'delta'"]
        for needed in ("who", "delta"):
            if needed not in payload:
                return None, [f"effect 'change_rep' is missing '{needed}'"]
        return Effect("change_rep", dict(payload)), []
    if op == "tick_clock":
        if not isinstance(payload, str):
            return None, ["tick_clock takes an event id string"]
        return Effect("tick_clock", {"reason": payload}), []
    if not isinstance(payload, Mapping):
        return None, ["effect 'test' needs an object"]
    return Effect("test", dict(payload)), []


def apply_effect(
    effect: Effect,
    snapshot: Any,
    store: Any,
    dice: Any,
    host: Any,
    *,
    context: str,
    conversation_id: str,
) -> None:
    """Apply one effect. RHS reads come from `snapshot`; writes go to `store` (section 3.3.3)."""
    args = effect.args
    if effect.op == "set":
        key = str(args["key"])
        value: Any = (
            evaluate_expression(str(args["expr"]), snapshot) if "expr" in args else args["value"]
        )
        spec = store.spec(key)
        if spec is not None and type(value) is not spec.type:
            raise DialogueEffectError(
                [f"'{key}' is {spec.type.__name__}, got {type(value).__name__}"]
            )
        if key == "npc.alert_level":  # raise-only (section 3.1): a botched bribe cannot calm
            value = max(int(snapshot.get(key) or 0), int(value))
        store.set(key, value)
    elif effect.op == "give_item":
        qty = int(args.get("qty", 1))
        host.give_item(str(args["id"]), qty)
    elif effect.op == "start_job":
        # Engine writes: `job.accepted` and `job.state` are read-only to an authored `set` (E25), which
        # is the reason this effect exists instead of a `set`.
        store.set("job.accepted", True)
        store.set("job.state", "accepted")
    elif effect.op == "change_rep":
        key = rep_key(str(args["who"]))
        delta = int(args["delta"])
        current = int(snapshot.get(key) or 0)
        store.set(key, max(constants.REP_MIN, min(constants.REP_MAX, current + delta)))
    elif effect.op == "tick_clock":
        reason = str(args["reason"])
        host.tick_clock(reason, constants.CLOCK_TICKS[reason])
    elif effect.op == "test":
        _resolve_test(
            args, snapshot, store, dice, host, context=context, conversation_id=conversation_id
        )
    else:  # pragma: no cover - the loader refuses anything else
        raise DialogueEffectError([f"unknown effect {effect.op!r}"])


def _resolve_test(
    args: Mapping[str, Any],
    snapshot: Any,
    store: Any,
    dice: Any,
    host: Any,
    *,
    context: str,
    conversation_id: str,
) -> None:
    """section 3.2: roll the pool, resolve, expose three read-only keys, report to the host."""
    key = str(args["key"])
    pool = int(snapshot.get(f"attr.{args['attribute']}")) + int(
        snapshot.get(f"skill.{args['skill']}")
    )
    pool += int(host.pool_bonus())  # the Wound Modifier seam; 0 with an unwounded Runner
    threshold = args.get("threshold")
    opponent = None
    if threshold is None:  # an Opposed Test supplies the defender's dice first (10.4)
        opponent = rules.classify(dice.roll(int(dict(args["opposed"])["pool"])))
    own = rules.classify(dice.roll(pool))
    net = own.hits - (
        int(threshold) if threshold is not None else (opponent.hits if opponent else 0)
    )
    store.set(f"test.{key}.hits", own.hits)  # engine writes: read-only to an authored `set` (E25)
    store.set(f"test.{key}.net", net)
    store.set(f"test.{key}.glitch", own.glitch)
    if own.critical and context == "site":
        # The only Clock tick the runner applies itself (3.2 step 5); never in a hub conversation.
        host.tick_clock("critical_glitch", 1)
    host.on_test(conversation_id, key, own, net)


# ======================================================================================
# Nodes and conversations - sections 1 and 2
# ======================================================================================
@dataclass(frozen=True, slots=True)
class Choice:
    text: str
    goto: str
    index: int  # the author index, which is what keeps the once-ledger stable (6.2)
    cond: str | None = None
    effects: tuple[Effect, ...] = ()


@dataclass(frozen=True, slots=True)
class Node:
    id: str
    kind: str
    index: int
    speaker: str | None = None
    line: str | None = None
    choices: tuple[Choice, ...] = ()
    cond: str | None = None
    then: str | None = None
    otherwise: str | None = None  # `else` is a keyword; the JSON key is still "else"
    effects: tuple[Effect, ...] = ()
    goto: str | None = None
    end: bool = False

    def targets(self) -> Iterator[str]:
        """Every node id this node can flow to, in author order."""
        if self.kind == "choice":
            for choice in self.choices:
                yield choice.goto
        elif self.kind == "condition":
            if self.then:
                yield self.then
            if self.otherwise:
                yield self.otherwise
        elif self.goto:
            yield self.goto


@dataclass(frozen=True, slots=True)
class Conversation:
    id: str
    context: str
    cast: Mapping[str, str]
    pc: str
    start: str
    nodes: tuple[Node, ...]
    by_id: Mapping[str, Node]
    source: str
    vars: Mapping[str, bool] = field(default_factory=dict)
    on_empty: str | None = None
    interlocutor: str | None = None
    warnings: tuple[str, ...] = ()
    test_keys: tuple[str, ...] = ()

    def node(self, node_id: str) -> Node:
        return self.by_id[node_id]

    def declared(self, key: str) -> bool:
        return spec_for(key, test_keys=self.test_keys, flags=self.vars) is not None


def kind_of(fields: Mapping[str, Any]) -> str | None:
    """Section 2.2's precedence. `line` + `choices` is a `choice`: the line is displayed with them."""
    if "choices" in fields:
        return "choice"
    if "cond" in fields or "then" in fields or "else" in fields:
        return "condition"
    if "line" in fields:
        return "line"
    if "effects" in fields:
        return "command"
    if "goto" in fields:
        return "jump"
    if "end" in fields:
        return "end"
    return None


class _Report:
    """Collects every problem the way section 7 requires: one raise, all the complaints."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def at(self, index: int | None, node_id: str | None, message: str) -> str:
        where = "nodes" if index is None else f"nodes[{index}]"
        named = f" ('{node_id}')" if node_id else ""
        return f"dialogue: {self.source}:{where}{named}: {message}"

    def err(self, index: int | None, node_id: str | None, message: str) -> None:
        self.errors.append(self.at(index, node_id, message))

    def warn(self, index: int | None, node_id: str | None, message: str) -> None:
        self.warnings.append(self.at(index, node_id, message))


def load_conversation(
    path: str | pathlib.Path, *, known_flags: Mapping[str, bool] | None = None
) -> Conversation:
    """Load and validate one conversation. Raises DialogueValidationError with every problem."""
    file = pathlib.Path(path)
    try:
        raw = json.loads(file.read_text())
    except json.JSONDecodeError as exc:
        raise DialogueValidationError([f"dialogue: {file.name}: invalid JSON: {exc}"]) from exc
    if not isinstance(raw, Mapping):
        raise DialogueValidationError([f"dialogue: {file.name}: top level must be an object"])
    return parse_conversation(raw, source=file.name, known_flags=known_flags)


def parse_conversation(
    raw: Mapping[str, Any],
    *,
    source: str = "<memory>",
    known_flags: Mapping[str, bool] | None = None,
) -> Conversation:
    """Validate a conversation document and build it. Every rule of section 7 lands here."""
    report = _Report(source)
    conv_id = raw.get("id")
    if not isinstance(conv_id, str) or not re.fullmatch(r"[a-z0-9_]+", conv_id):
        report.err(None, None, f"id '{conv_id}' must match [a-z0-9_]+")
        conv_id = "invalid"
    elif source.endswith(".json") and conv_id != pathlib.Path(source).stem:
        report.err(None, None, f"'{conv_id}' does not match the filename")

    context = raw.get("context")
    if context not in ("hub", "site"):
        report.err(None, None, "context: must be 'hub' or 'site'")
        context = "hub"

    cast_raw = raw.get("cast", {})
    cast: dict[str, str] = {}
    if isinstance(cast_raw, Mapping):
        for slug, name in cast_raw.items():
            if not isinstance(slug, str) or not re.fullmatch(r"[a-z0-9_]+", slug):
                report.err(None, None, f"cast slug '{slug}' must match [a-z0-9_]+")
            elif not isinstance(name, str) or not name.strip():
                report.err(None, None, f"cast entry '{slug}' has no display name")
            else:
                cast[slug] = name
    else:
        report.err(None, None, "cast must be an object of slug -> display name")

    pc = raw.get("pc", "pc")
    if not isinstance(pc, str) or pc not in cast:
        report.err(None, None, f"'{pc}' is not in the cast")
    interlocutor = raw.get("interlocutor")
    if interlocutor is not None and (not isinstance(interlocutor, str) or interlocutor not in cast):
        report.err(None, None, f"'{interlocutor}' is not in the cast")
        interlocutor = None

    vars_raw = raw.get("vars", {})
    flags: dict[str, bool] = {}
    if isinstance(vars_raw, Mapping):
        for name, value in vars_raw.items():
            if not isinstance(value, bool):
                report.err(None, None, f"vars: flag '{name}' must be a bool")
            elif not re.fullmatch(r"[a-z0-9_]+", str(name)):
                report.err(None, None, f"vars: flag '{name}' must match [a-z0-9_]+")
            else:
                flags[str(name)] = value
                if (
                    known_flags is not None
                    and str(name) in known_flags
                    and known_flags[str(name)] != value
                ):
                    # W2: two files declaring one flag with different defaults.
                    report.warn(
                        None, None, f"flag '{name}' already declared with a different default"
                    )
    else:
        report.err(None, None, "vars must be an object of flag -> bool default")

    raw_nodes = raw.get("nodes")
    if not isinstance(raw_nodes, Sequence) or isinstance(raw_nodes, (str, bytes)):
        report.err(None, None, "nodes must be an array")
        raise DialogueValidationError(report.errors)
    if len(raw_nodes) > MAX_NODES:
        report.err(None, None, f"nodes: {len(raw_nodes)} nodes exceeds the v1 limit of {MAX_NODES}")

    test_keys = _collect_test_keys(raw_nodes, report)
    flags_ref = set(flags)

    def spec_of(key: str) -> VarSpec | None:
        return spec_for(key, test_keys=test_keys, flags=flags_ref)

    nodes: list[Node] = []
    seen_ids: dict[str, int] = {}
    for index, raw_node in enumerate(raw_nodes):
        if not isinstance(raw_node, Mapping):
            report.err(index, None, "node must be an object")
            continue
        node = _parse_node(
            raw_node,
            index,
            report,
            spec_of=spec_of,
            context=context,
            cast=cast,
            interlocutor=interlocutor,
            conv_id=conv_id,
        )
        node_id = raw_node.get("id")
        if isinstance(node_id, str):
            if node_id in seen_ids:
                report.err(
                    index,
                    node_id,
                    f"duplicate node id '{node_id}' (first at nodes[{seen_ids[node_id]}])",
                )
            else:
                seen_ids[node_id] = index
            if not re.fullmatch(r"[a-z0-9_]+", node_id):
                report.err(index, None, f"node id '{node_id}' must match [a-z0-9_]+")
            # W6's id clause is deliberately not implemented: E45 above already restricts ids to
            # [a-z0-9_]+, and under that charset every id is snake_case - `open`, `offer` and
            # `guard_hail` alike are what the design document's own files use. A warning that fires on
            # every node in both shipped conversations would be noise, not a signal.
        if node is not None:
            nodes.append(node)

    by_id: dict[str, Node] = {}
    for node in nodes:
        by_id.setdefault(node.id, node)

    start = raw.get("start")
    if not isinstance(start, str) or start not in by_id:
        report.err(None, None, f"start: unknown node '{start}'")
        start = ""
    on_empty = raw.get("on_empty")
    if on_empty is not None and (not isinstance(on_empty, str) or on_empty not in by_id):
        report.err(None, None, f"on_empty: unknown node '{on_empty}'")
        on_empty = None

    # E2: every target resolves. E4: start must not resolve straight to an end.
    for node in nodes:
        for target in node.targets():
            if target not in by_id:
                report.err(node.index, node.id, f"dangling goto '{target}'")
    if start and by_id[start].kind == "end":
        report.err(
            None, start, f"start: node '{start}' is an end node (the conversation has no content)"
        )

    # E15: a silent cycle has no line, choices or end to stop it.
    cycle = _silent_cycle(by_id, start)
    if cycle:
        report.err(
            by_id[cycle[0]].index,
            cycle[0],
            f"silent cycle through {cycle} has no line, choices, or end",
        )

    _check_reachability(nodes, by_id, start, on_empty, report)
    _check_unused_cast(cast, nodes, report)
    _check_listen(conv_id, nodes, by_id, report)

    if report.errors:
        raise DialogueValidationError(report.errors)
    return Conversation(
        id=conv_id,
        context=context,
        cast=cast,
        pc=pc,
        start=start,
        nodes=tuple(nodes),
        by_id=by_id,
        source=source,
        vars=flags,
        on_empty=on_empty,
        interlocutor=interlocutor,
        warnings=tuple(report.warnings),
        test_keys=tuple(test_keys),
    )


def _collect_test_keys(raw_nodes: Sequence[Any], report: _Report) -> set[str]:
    """Harvest `test.<key>.*` so a read of a key no effect writes is an unknown variable (5.2).

    A duplicate `key` is E31, not a deduplication: ADR-0006 pays one obstacle once per Job, so two
    `test`s sharing a key would be two rolls against one obstacle.
    """
    keys: set[str] = set()
    for index, raw_node in enumerate(raw_nodes):
        if not isinstance(raw_node, Mapping):
            continue
        node_id = raw_node.get("id") if isinstance(raw_node.get("id"), str) else ""
        arrays = [raw_node.get("effects")]
        arrays += [c.get("effects") for c in raw_node.get("choices", []) if isinstance(c, Mapping)]
        for effects in arrays:
            if not isinstance(effects, Sequence) or isinstance(effects, (str, bytes)):
                continue
            for raw_effect in effects:
                if isinstance(raw_effect, Mapping) and "test" in raw_effect:
                    payload = raw_effect["test"]
                    if not isinstance(payload, Mapping) or not isinstance(payload.get("key"), str):
                        continue
                    key = payload["key"]
                    if key in keys:
                        report.err(index, node_id, f"duplicate test key '{key}'")
                    keys.add(key)
    return keys


def _unknown(key: str) -> str:
    """E27 for a flag, E6 otherwise: a flag has a home to declare it in, and the message says where."""
    if key.startswith("flags."):
        return f"unknown flag '{key[6:]}' (declare it in 'vars')"
    return f"unknown variable '{key}'"


def _parse_node(
    raw: Mapping[str, Any],
    index: int,
    report: _Report,
    *,
    spec_of: Any,
    context: str,
    cast: Mapping[str, str],
    interlocutor: str | None,
    conv_id: str,
) -> Node | None:
    node_id: str = raw["id"] if isinstance(raw.get("id"), str) else ""
    kind = kind_of(raw)
    if kind is None:
        report.err(
            index,
            node_id,
            "node has no payload (needs one of: line, choices, cond, effects, goto, end)",
        )
        return None
    # E13: at most one terminator.
    terminators = [name for name in ("goto", "end") if name in raw]
    if raw.get("choices"):
        terminators.append("choices")
    if kind == "condition":
        terminators = []  # then/else is its terminator by construction
    if len(terminators) > 1:
        report.err(index, node_id, f"two terminators: '{terminators[0]}' and '{terminators[1]}'")
    # E16: a field the derived kind forbids.
    for forbidden in FORBIDS[kind]:
        if forbidden in raw:
            report.err(index, node_id, f"{kind} node cannot carry a '{forbidden}'")
    # E12 payload checks the table states as requirements.
    if kind == "line" and not isinstance(raw.get("speaker"), str):
        report.err(index, node_id, "node has a line but no speaker")
    if kind == "condition":
        for field_name in ("then", "else"):
            if not isinstance(raw.get(field_name), str):
                report.err(index, node_id, f"condition node needs a '{field_name}'")

    speaker = raw.get("speaker")
    if isinstance(speaker, str) and speaker not in cast:
        report.err(index, node_id, f"speaker '{speaker}' is not in the cast")
    line = raw.get("line")
    if isinstance(line, str):
        if len(line) > LINE_UI_WIDTH:
            report.warn(index, node_id, f"line is {len(line)} characters (UI holds ~180)")
        found, malformed = placeholders(line)
        for problem in malformed:
            report.err(index, node_id, problem)
        for name, _grouped in found:
            if spec_of(name) is None:
                report.err(index, node_id, _unknown(name))
        if "npc." in line and interlocutor is None:
            report.err(
                index, node_id, "'npc.' variable used but the file declares no 'interlocutor'"
            )

    cond = raw.get("cond")
    if isinstance(cond, str):
        _scan_into(cond, report, index, node_id, spec_of=spec_of, interlocutor=interlocutor)
    elif cond is not None:
        report.err(index, node_id, "'cond' must be a string")

    choices: list[Choice] = []
    raw_choices = raw.get("choices")
    if raw_choices is not None:
        if not isinstance(raw_choices, Sequence) or isinstance(raw_choices, (str, bytes)):
            report.err(index, node_id, "'choices' must be an array")
        elif not raw_choices:
            report.err(index, node_id, "'choices' is empty")
        else:
            unconditional = False
            for position, raw_choice in enumerate(raw_choices):
                if not isinstance(raw_choice, Mapping):
                    report.err(index, node_id, f"choice[{position}] must be an object")
                    continue
                if not isinstance(raw_choice.get("text"), str) or not raw_choice.get("text"):
                    report.err(None, node_id, f"choice[{position}]: choice has no text")
                    continue
                if "goto" not in raw_choice:
                    report.err(None, node_id, f"choice[{position}]: choice has no goto")
                    continue
                choice_cond = raw_choice.get("cond")
                if choice_cond is None:
                    unconditional = True
                elif not isinstance(choice_cond, str):
                    report.err(None, node_id, f"choice[{position}]: 'cond' must be a string")
                else:
                    _scan_into(
                        choice_cond,
                        report,
                        index,
                        node_id,
                        spec_of=spec_of,
                        interlocutor=interlocutor,
                    )
                text = str(raw_choice["text"])
                found, malformed = placeholders(text)
                for problem in malformed:
                    report.err(None, node_id, problem)
                for name, _grouped in found:
                    if spec_of(name) is None:
                        report.err(None, node_id, _unknown(name))
                effects, _empty = _parse_effects(
                    raw_choice.get("effects"),
                    report,
                    index,
                    node_id,
                    spec_of=spec_of,
                    context=context,
                    conv_id=conv_id,
                    interlocutor=interlocutor,
                )
                choices.append(
                    Choice(
                        text=text,
                        goto=str(raw_choice["goto"]),
                        index=position,
                        cond=choice_cond if isinstance(choice_cond, str) else None,
                        effects=effects,
                    )
                )
            if not unconditional:
                report.err(
                    index,
                    node_id,
                    "choice node has no unconditional choice (every choice has a 'cond')",
                )

    effects, _ = _parse_effects(
        raw.get("effects"),
        report,
        index,
        node_id,
        spec_of=spec_of,
        context=context,
        conv_id=conv_id,
        interlocutor=interlocutor,
    )

    return Node(
        id=node_id,
        kind=kind,
        index=index,
        speaker=speaker if isinstance(speaker, str) else None,
        line=line if isinstance(line, str) else None,
        choices=tuple(choices),
        cond=cond if isinstance(cond, str) else None,
        then=raw.get("then") if isinstance(raw.get("then"), str) else None,
        otherwise=raw.get("else") if isinstance(raw.get("else"), str) else None,
        effects=effects,
        goto=raw.get("goto") if isinstance(raw.get("goto"), str) else None,
        end=raw.get("end") is True,
    )


def _scan_into(
    expr: str,
    report: _Report,
    index: int,
    node_id: str,
    *,
    spec_of: Any,
    interlocutor: str | None,
) -> set[str]:
    """Load-time condition walk. Parse errors and unknown names become E5/E6/E7/E8."""
    try:
        names, problems = scan_condition(expr, declared=lambda key: spec_of(key) is not None)
    except DialogueParseError as exc:
        report.err(index, node_id, exc.problems[0])
        return set()
    for problem in problems:
        if problem.startswith("unknown variable '"):
            name = problem.split("'")[1]
            report.err(index, node_id, f"{_unknown(name)} in condition '{expr}'")
        else:
            report.err(index, node_id, problem)
    if interlocutor is None and any(name.startswith("npc.") for name in names):
        report.err(index, node_id, "'npc.' variable used but the file declares no 'interlocutor'")
    return names


def _parse_effects(
    raw_effects: Any,
    report: _Report,
    index: int,
    node_id: str,
    *,
    spec_of: Any,
    context: str,
    conv_id: str,
    interlocutor: str | None,
) -> tuple[tuple[Effect, ...], bool]:
    """Validate one effects array (E20-E39). Returns the parsed effects and whether it was empty."""
    if raw_effects is None:
        return (), False
    if not isinstance(raw_effects, Sequence) or isinstance(raw_effects, (str, bytes)):
        report.err(index, node_id, "'effects' must be an array")
        return (), False
    if not raw_effects:  # E20: present but empty is an error, absent is not
        report.err(index, node_id, "'effects' is empty")
        return (), True
    out: list[Effect] = []
    for position, raw_effect in enumerate(raw_effects):
        if not isinstance(raw_effect, Mapping):
            report.err(index, node_id, f"effect {position} must be an object")
            continue
        effect, problems = normalise_effect(raw_effect)
        for problem in problems:
            if "exactly one effect" in problem:
                names = sorted(n for n in raw_effect if n in EFFECT_NAMES)
                report.err(
                    index, node_id, f"effect {position} must name exactly one effect (got {names})"
                )
            elif "missing" in problem:
                name = next((n for n in EFFECT_NAMES if n in raw_effect), "?")
                report.err(index, node_id, f"effect '{name}' is missing the field it needs")
            else:
                report.err(index, node_id, problem)
        if effect is None:
            continue
        _check_effect(
            effect,
            report,
            index,
            node_id,
            spec_of=spec_of,
            context=context,
            interlocutor=interlocutor,
        )
        out.append(effect)
    return tuple(out), False


def _check_effect(
    effect: Effect,
    report: _Report,
    index: int,
    node_id: str,
    *,
    spec_of: Any,
    context: str,
    interlocutor: str | None,
) -> None:
    args = effect.args
    if effect.op == "set":
        key = str(args["key"])
        spec = spec_of(key)
        if spec is None:
            report.err(index, node_id, f"cannot write undeclared variable '{key}'")
            return
        if not spec.writable:
            report.err(index, node_id, f"cannot write read-only variable '{key}'")
            return
        if "value" in args and type(args["value"]) is not spec.type:
            report.err(
                index,
                node_id,
                f"'{key}' is {spec.type.__name__}, got {type(args['value']).__name__}",
            )
        if "expr" in args:
            _scan_into(
                str(args["expr"]),
                report,
                index,
                node_id,
                spec_of=spec_of,
                interlocutor=interlocutor,
            )
    elif effect.op == "give_item":
        item = args.get("id")
        if item not in GEAR_CATALOGUE:
            report.err(index, node_id, f"unknown item '{item}'")
        qty = args.get("qty", 1)
        if not isinstance(qty, int) or isinstance(qty, bool) or qty < 1:
            report.err(index, node_id, f"give_item qty {qty} must be an integer >= 1")
    elif effect.op == "start_job":
        if context != "hub":
            report.err(index, node_id, "start_job is only allowed in a 'hub' conversation")
    elif effect.op == "change_rep":
        who, delta = str(args.get("who")), args.get("delta")
        if who != "fixer" and not who.startswith("faction:"):
            report.err(index, node_id, f"unknown rep target '{who}'")
        elif who.startswith("faction:") and who.split(":", 1)[1] not in KNOWN_FACTIONS:
            report.warn(index, node_id, f"'{who}' is not a declared faction; treated as 0")
        if (
            not isinstance(delta, int)
            or isinstance(delta, bool)
            or delta == 0
            or abs(delta) > constants.REP_DELTA_MAX
        ):
            report.err(
                index,
                node_id,
                f"change_rep delta {delta} must be a non-zero integer in "
                f"-{constants.REP_DELTA_MAX}..{constants.REP_DELTA_MAX}",
            )
    elif effect.op == "tick_clock":
        reason = args.get("reason")
        if context != "site":
            report.err(
                index,
                node_id,
                "tick_clock is not allowed in a 'hub' conversation (the Security Clock is not running)",
            )
        if reason not in CLOCK_REASONS:
            report.err(
                index, node_id, f"tick_clock reason '{reason}' is not a Security Clock event"
            )
    elif effect.op == "test":
        _check_test(args, report, index, node_id, spec_of=spec_of, interlocutor=interlocutor)


def _check_test(
    args: Mapping[str, Any],
    report: _Report,
    index: int,
    node_id: str,
    *,
    spec_of: Any,
    interlocutor: str | None,
) -> None:
    key = args.get("key")
    if not isinstance(key, str) or not key:
        report.err(index, node_id, "effect 'test' is missing 'key'")
        return
    skill, attribute = args.get("skill"), args.get("attribute")
    if skill not in constants.SKILLS:
        report.err(index, node_id, f"unknown skill '{skill}'")
    if attribute not in ATTRIBUTE_SLUGS:
        report.err(index, node_id, f"unknown attribute '{attribute}'")
    elif skill in constants.SKILLS:
        linked = constants.SKILLS[skill]
        # W1: the linked attribute is DECISIONS 2's. `sorcery` links to the caster's tradition,
        # which is not an attribute slug, so it is exempt rather than warned about forever.
        if linked in ATTRIBUTE_SLUGS and linked != attribute:
            report.warn(
                index,
                node_id,
                f"test '{key}': skill '{skill}' is linked to '{linked}', not '{attribute}'",
            )
    threshold, opposed = args.get("threshold"), args.get("opposed")
    if (threshold is None) == (opposed is None):
        report.err(index, node_id, f"test '{key}' needs exactly one of 'threshold' or 'opposed'")
    elif threshold is not None:
        if not isinstance(threshold, int) or isinstance(threshold, bool) or not 1 <= threshold <= 4:
            report.err(
                index, node_id, f"threshold {threshold} is outside the v1 range 1-4 (DECISIONS 3)"
            )
    elif (
        not isinstance(opposed, Mapping)
        or not isinstance(opposed.get("pool"), int)
        or opposed["pool"] < 1
    ):
        report.err(index, node_id, f"test '{key}' needs opposed.pool as an integer >= 1")


def _silent_cycle(by_id: Mapping[str, Node], start: str) -> list[str]:
    """E15: a cycle reachable through silent nodes only."""
    colour: dict[str, int] = {}
    path: list[str] = []

    def visit(node_id: str) -> list[str] | None:
        node = by_id.get(node_id)
        if node is None or node.kind not in SILENT_KINDS:
            return None
        if colour.get(node_id) == 1:
            return path[path.index(node_id) :] + [node_id]
        if colour.get(node_id) == 2:
            return None
        colour[node_id] = 1
        path.append(node_id)
        for target in node.targets():
            found = visit(target)
            if found:
                return found
        path.pop()
        colour[node_id] = 2
        return None

    return visit(start) or []


def _check_reachability(
    nodes: Sequence[Node],
    by_id: Mapping[str, Node],
    start: str,
    on_empty: str | None,
    report: _Report,
) -> None:
    """E17: unreachable is an error, not a warning. `on_empty` is exempt (the runner reaches it)."""
    reached: set[str] = set()
    frontier = [start] if start else []
    while frontier:
        node_id = frontier.pop()
        if node_id in reached or node_id not in by_id:
            continue
        reached.add(node_id)
        frontier.extend(by_id[node_id].targets())
    for node in nodes:
        if node.id not in reached and node.id != on_empty:
            report.err(node.index, node.id, f"unreachable node (no path from '{start}')")


def _check_unused_cast(cast: Mapping[str, str], nodes: Sequence[Node], report: _Report) -> None:
    """W4: a cast entry no speaker uses."""
    used = {node.speaker for node in nodes if node.speaker}
    for slug in cast:
        if slug not in used:
            report.warn(None, None, f"cast entry '{slug}' is never used")


def _check_listen(
    conv_id: str, nodes: Sequence[Node], by_id: Mapping[str, Node], report: _Report
) -> None:
    """W5: a test whose result keys no node anywhere reads (a file-wide census, not per node)."""
    referenced: set[str] = set()
    for node in nodes:
        referenced.update(re.findall(r"test\.(\w+)\.", " ".join(_texts_of(node))))
    for node in nodes:
        for effect in (*node.effects, *(e for c in node.choices for e in c.effects)):
            if effect.op == "test" and str(effect.args.get("key")) not in referenced:
                report.warn(
                    node.index, node.id, f"test '{effect.args.get('key')}' result is never read"
                )


def _texts_of(node: Node) -> list[str]:
    """Every string a node carries that could read a variable: conditions, lines and set-exprs."""
    out: list[str] = []
    if node.line:
        out.append(node.line)
    if node.cond:
        out.append(node.cond)
    for choice in node.choices:
        if choice.text:
            out.append(choice.text)
        if choice.cond:
            out.append(choice.cond)
    for effect in (*node.effects, *(e for c in node.choices for e in c.effects)):
        if effect.op == "set" and "expr" in effect.args:
            out.append(str(effect.args["expr"]))
    return out


# ======================================================================================
# The store and the presenter
# ======================================================================================
class Store:
    """The store API of dialogue.md 5.2. `campaign.py` implements this over the campaign.

    A Protocol by shape: `get`, `set`, `has_item`, `snapshot`, plus `spec` for the declared type of
    a key (used by `set`'s type check and by the raise-only rule).
    """

    def get(self, key: str) -> Any:  # pragma: no cover - protocol
        raise NotImplementedError

    def set(self, key: str, value: Any) -> None:  # pragma: no cover - protocol
        raise NotImplementedError

    def has_item(self, item_id: str) -> bool:  # pragma: no cover - protocol
        raise NotImplementedError

    def snapshot(self) -> Any:  # pragma: no cover - protocol
        raise NotImplementedError

    def spec(self, key: str) -> VarSpec | None:  # pragma: no cover - protocol
        raise NotImplementedError


class Host:
    """The effects that touch game state, which is not the runner's to own.

    `tick_clock` — add segments to the Security Clock, keyed by the authored reason.
    `give_item`  — append to the Crew's inventory.
    `on_test`    — report a resolved roll, for ADR-0006's XP and Perk payout.
    `pool_bonus` — the Wound Modifier on the speaking Runner's pool (DECISIONS 4).
    """

    def tick_clock(self, reason: str, segments: int) -> None:  # pragma: no cover - protocol
        raise NotImplementedError

    def give_item(self, item_id: str, qty: int) -> None:  # pragma: no cover - protocol
        raise NotImplementedError

    def on_test(
        self, conversation_id: str, key: str, roll: Any, net: int
    ) -> None:  # pragma: no cover
        raise NotImplementedError

    def pool_bonus(self) -> int:  # pragma: no cover - protocol
        raise NotImplementedError


class Presenter:
    """What the runner tells the screen. `render.py` implements it; this module never draws."""

    def line(self, speaker: str, text: str) -> None:  # pragma: no cover - protocol
        raise NotImplementedError

    def choices(self, texts: Sequence[str]) -> None:  # pragma: no cover - protocol
        raise NotImplementedError

    def close(self, reason: str) -> None:  # pragma: no cover - protocol
        raise NotImplementedError


class Dice:
    """A source of d6 values. `random.Random` in play; scripted in a transcript."""

    def roll(self, count: int) -> list[int]:  # pragma: no cover - protocol
        raise NotImplementedError


@dataclass
class RandomDice:
    """The game's dice: Mersenne Twister from a seeded stream (DECISIONS 9)."""

    rng: random.Random

    def roll(self, count: int) -> list[int]:
        return [self.rng.randint(1, 6) for _ in range(max(0, count))]


@dataclass
class ScriptedDice:
    """A transcript's dice: exact values, in order (dialogue.md 10.4)."""

    values: list[int]
    used: list[int] = field(default_factory=list)

    def roll(self, count: int) -> list[int]:
        if len(self.values) < count:
            raise DialogueRuntimeError(
                f"the transcript supplies {len(self.values)} dice but {count} were asked for"
            )
        taken = self.values[:count]
        self.values = self.values[count:]
        self.used.extend(taken)
        return taken


@dataclass
class VarStore:
    """The reference store: declared keys, typed writes, and an inventory.

    Used by the `play` command, the transcripts and the demo. It holds no campaign rules, which is
    what keeps this module runnable without `campaign.py`; the game injects its own `Store`.
    """

    test_keys: tuple[str, ...] = ()
    flags: Mapping[str, bool] = field(default_factory=dict)
    inventory: list[str] = field(default_factory=list)
    values: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for key, spec in DECLARED.items():
            self.values.setdefault(key, spec.default)
        for name, default in self.flags.items():
            self.values.setdefault(f"flags.{name}", default)
        for key in self.test_keys:
            self.values.setdefault(f"test.{key}.hits", 0)
            self.values.setdefault(f"test.{key}.net", 0)
            self.values.setdefault(f"test.{key}.glitch", False)

    def spec(self, key: str) -> VarSpec | None:
        return spec_for(key, test_keys=self.test_keys, flags=self.flags)

    def declare(self, key: str, value: Any) -> None:
        """Seed a value. Never overwrites (5.2)."""
        self.values.setdefault(key, value)

    def get(self, key: str) -> Any:
        if key not in self.values:
            if self.spec(key) is None:
                raise DialogueConditionError(f"unknown variable '{key}'")
            return None
        return self.values[key]

    def set(self, key: str, value: Any) -> None:
        """Write a value. An unknown key or a type mismatch raises; *writability is the validator's*.

        dialogue.md 5.2 lists read-only as a store error, but 7.2's E24/E25 are load-time rules about
        an authored `set` effect, and the same document gives the engine write access to keys an author
        may not touch (`test.<key>.hits`, `job.accepted`). Enforcing writability here would make the
        engine's own writes fail, so it is enforced once, in the validator, where a file can actually
        be refused for it.
        """
        spec = self.spec(key)
        if spec is None:
            raise DialogueEffectError([f"cannot write undeclared variable '{key}'"])
        if type(value) is not spec.type:
            raise DialogueEffectError(
                [f"'{key}' is {spec.type.__name__}, got {type(value).__name__}"]
            )
        self.values[key] = value

    def has_item(self, item_id: str) -> bool:
        return item_id in self.inventory

    def snapshot(self) -> VarStore:
        """A copy for one effects array, so every RHS reads the pre-array store (3.3.3)."""
        return VarStore(
            test_keys=self.test_keys,
            flags=self.flags,
            inventory=list(self.inventory),
            values=dict(self.values),
        )


@dataclass
class HeadlessHost:
    """A `Host` that records instead of mutating: what a transcript and the demo need."""

    pool_bonus_value: int = 0
    ticks: list[tuple[str, int]] = field(default_factory=list)
    items: list[tuple[str, int]] = field(default_factory=list)
    tests: list[tuple[str, str, int]] = field(default_factory=list)

    def tick_clock(self, reason: str, segments: int) -> None:
        self.ticks.append((reason, segments))

    def give_item(self, item_id: str, qty: int) -> None:
        self.items.append((item_id, qty))

    def on_test(self, conversation_id: str, key: str, roll: Any, net: int) -> None:
        self.tests.append((conversation_id, key, net))

    def pool_bonus(self) -> int:
        return self.pool_bonus_value


@dataclass
class RecordingPresenter:
    """A `Presenter` that keeps the transcript: speaker/line pairs, and the choice sets shown."""

    lines: list[tuple[str, str]] = field(default_factory=list)
    shown: list[list[str]] = field(default_factory=list)
    closed: str | None = None

    def line(self, speaker: str, text: str) -> None:
        self.lines.append((speaker, text))

    def choices(self, texts: Sequence[str]) -> None:
        self.shown.append(list(texts))

    def close(self, reason: str) -> None:
        self.closed = reason

    def transcript(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for speaker, text in self.lines:
            out.append({"line": [speaker, text]})
        if self.closed:
            out.append({"end": self.closed})
        return out


# ======================================================================================
# The runner - section 6
# ======================================================================================
class RunnerState:
    """The state machine of 6.1, as plain strings rather than an Enum for a readable transcript."""

    IDLE: Final = "IDLE"
    RUNNING: Final = "RUNNING"
    WAITING_CONTINUE: Final = "WAITING_CONTINUE"
    WAITING_CHOICE: Final = "WAITING_CHOICE"
    DONE: Final = "DONE"


END: Final = "\x00END"  # a sentinel, not a node id (6.2)


@dataclass
class DialogueRunner:
    """Walks a `Conversation`. Injected store, presenter, dice and host (see the module docstring)."""

    conversation: Conversation
    store: Any
    presenter: Any
    dice: Any
    host: Any
    localize: Any = None
    ledger: set[tuple[Any, ...]] = field(default_factory=set)

    def __post_init__(self) -> None:
        if self.localize is None:
            self.localize = lambda text: text  # noqa: E731 - identity in v1 (Open question 7)
        self.nodes = self.conversation.by_id
        self.cond_cache = ConditionCache()
        self.state = RunnerState.IDLE
        self.pending: Any = None
        self.actors: Mapping[str, Any] = {}
        self.pc: Any = None

    # ---- lifecycle ------------------------------------------------------
    def start(self, actors: Mapping[str, Any] | None = None, pc_actor: Any = None) -> None:
        """Begin. `actors` maps a cast slug to an actor ref; `pc_actor` is the speaking Runner."""
        self.actors = dict(actors or {})
        self.pc = pc_actor
        self._bind_job()
        self.state = RunnerState.RUNNING
        self._enter(self.conversation.start)

    def _bind_job(self) -> None:
        """`job.payout_agreed` defaults to `job.payout_base` (5.2's default column)."""
        try:
            base = self.store.get("job.payout_base")
            agreed = self.store.get("job.payout_agreed")
        except DialogueConditionError:
            return
        if base is not None and not agreed:
            self.store.set("job.payout_agreed", int(base))

    # ---- the loop of 6.2 ------------------------------------------------
    def _enter(self, node_id: str) -> None:
        for _ in range(AUTO_ADVANCE_BUDGET):
            node = self.nodes.get(node_id)
            if node is None:  # cannot happen post-validation; close rather than stall (6.3)
                return self._error(node_id, f"goto '{node_id}' does not resolve at runtime")
            self._fire(node.effects, (self.conversation.id, node.id))
            if node.kind == "end":
                return self._finish("end")
            if node.kind == "condition":
                try:
                    taken = self.cond_cache.evaluate(node.cond or "False", self.store)
                except (DialogueConditionError, DialogueParseError, TypeError) as exc:
                    return self._error(
                        node.id, f"condition failed at runtime: {exc}: '{node.cond}'"
                    )
                target = node.then if taken else node.otherwise
                if target is None:  # pragma: no cover - E-checks require both
                    return self._error(node.id, "condition node has no taken branch")
                node_id = target
                continue
            if node.kind in ("jump", "command"):
                node_id = node.goto or END
                if node_id is END:
                    return self._error(node.id, "silent node has no goto")
                continue
            if node.kind == "line":
                self.presenter.line(self._speaker(node), self._text(node.line or ""))
                self.pending = END if node.end else node.goto
                self.state = RunnerState.WAITING_CONTINUE
                return
            if node.kind == "choice":
                if node.line:
                    self.presenter.line(self._speaker(node), self._text(node.line))
                try:
                    shown = self._filter(node.choices)
                except (DialogueConditionError, DialogueParseError, TypeError) as exc:
                    # 4.5: a load-valid gate can still fail on types (`'low' < 3`). An error, never a
                    # silent False, because an all-false gate set is indistinguishable from an
                    # authored refusal and would bury the bug.
                    return self._error(node.id, f"condition failed at runtime: {exc}")
                if not shown:
                    return self._dead_end(node)
                self.pending = (node.id, shown)
                self.presenter.choices([self._text(choice.text) for choice, _index in shown])
                self.state = RunnerState.WAITING_CHOICE
                return
        raise DialogueRuntimeError(f"runaway auto-advance at '{node_id}'")

    def advance(self) -> None:
        """Continue past a `line` node. A no-op in any other state, so a key repeat cannot skip."""
        if self.state != RunnerState.WAITING_CONTINUE:
            return
        target = self.pending
        self.pending = None
        self.state = RunnerState.RUNNING
        if target is END:
            self._finish("end")
        else:
            self._enter(target)

    def choose(self, index: int) -> None:
        """Select the `index`-th *shown* choice. Its author index keys the once-ledger (6.2)."""
        if self.state != RunnerState.WAITING_CHOICE:
            return
        node_id, shown = self.pending
        if not 0 <= index < len(shown):
            # A presenter bug must not surface as an IndexError in front of the player.
            raise DialogueRuntimeError(
                f"choice {index} is out of range: '{node_id}' shows {len(shown)}"
            )
        choice, position = shown[index]
        self._fire(choice.effects, (self.conversation.id, node_id, position))
        self.state = RunnerState.RUNNING
        self.pending = None
        self._enter(choice.goto)

    # ---- pieces ---------------------------------------------------------
    def _filter(self, choices: Sequence[Choice]) -> list[tuple[Choice, int]]:
        """Author order; a hidden choice is absent, never greyed out. A condition error propagates."""
        out: list[tuple[Choice, int]] = []
        for choice in choices:
            if choice.cond is None:
                out.append((choice, choice.index))
                continue
            out.append((choice, choice.index)) if self.cond_cache.evaluate(
                choice.cond, self.store
            ) else None
        return out

    def _fire(self, effects: Sequence[Effect], ledger_key: tuple[Any, ...]) -> None:
        """At most once per Job, and every RHS reads the store as it was before the array (3.3)."""
        if not effects or ledger_key in self.ledger:
            return
        self.ledger.add(ledger_key)
        snapshot = self.store.snapshot()
        for effect in effects:
            apply_effect(
                effect,
                snapshot,
                self.store,
                self.dice,
                self.host,
                context=self.conversation.context,
                conversation_id=self.conversation.id,
            )

    def _speaker(self, node: Node) -> str:
        slug = node.speaker or self.conversation.pc
        return str(self.conversation.cast.get(slug, slug))

    def _text(self, text: str) -> str:
        return self.localize(interpolate(text, self.store))

    def _dead_end(self, node: Node) -> None:
        """6.3: `on_empty` if declared, else close. The player is never left in a stall."""
        if self.conversation.on_empty:
            return self._enter(self.conversation.on_empty)
        self._finish("dead_end")

    def _error(self, node_id: str, message: str) -> None:
        """4.5: show a visible error and close. Never a silent stall."""
        self.presenter.line("<DIALOGUE ERROR>", f"<DIALOGUE ERROR {node_id}>")
        self._finish("error")

    def _finish(self, reason: str) -> None:
        self.state = RunnerState.DONE
        self.presenter.close(reason)

    # ---- convenience for callers ----------------------------------------
    @property
    def done(self) -> bool:
        return self.state == RunnerState.DONE


# ======================================================================================
# Transcripts - dialogue.md 10.4
# ======================================================================================
class TranscriptError(DialogueError, RuntimeFailure):
    """A transcript step did not match the conversation it recorded."""


def run_transcript(
    path: str | pathlib.Path, *, directory: pathlib.Path | None = None
) -> dict[str, Any]:
    """Replay one transcript and assert every step. The transcript IS the test (10.4)."""
    file = pathlib.Path(path)
    doc = json.loads(file.read_text())
    conv_id = doc["conversation"]
    conv_path = (directory or DIALOGUE_DIR) / f"{conv_id}.json"
    conversation = load_conversation(conv_path)
    store = VarStore(test_keys=conversation.test_keys, flags=conversation.vars)
    for key, value in doc.get("seed", {}).items():
        _seed(store, key, value)
    dice = ScriptedDice(list(doc.get("dice", [])))
    host = HeadlessHost()
    presenter = RecordingPresenter()
    runner = DialogueRunner(conversation, store, presenter, dice, host)
    runner.start(actors={conversation.interlocutor or "npc": "stub"}, pc_actor="stub")
    asserted: tuple[str, str] | None = None
    for position, step in enumerate(doc.get("steps", [])):
        # A transcript step continues past a line only once that line has been asserted. That is what
        # makes 10.4's example read as straight-line prose - line, choose, line, end - while still
        # checking the line `start()` displayed without skipping over it.
        if (
            runner.state == RunnerState.WAITING_CONTINUE
            and presenter.lines
            and presenter.lines[-1] == asserted
        ):
            runner.advance()
        if "choose" in step:
            asserted = None
            wanted = step["choose"]
            if not presenter.shown:
                raise TranscriptError(f"{file.name}: step {position}: no choices were shown")
            shown = presenter.shown[-1]
            if isinstance(wanted, str) and wanted.startswith("#"):
                index = int(wanted[1:]) - 1
            elif isinstance(wanted, str) and wanted in shown:
                index = shown.index(wanted)
            elif isinstance(wanted, int):
                index = wanted
            else:
                raise TranscriptError(
                    f"{file.name}: step {position}: choice {wanted!r} is not among {shown}"
                )
            runner.choose(index)
        if "expect_line" in step:
            want_speaker, want_text = step["expect_line"]
            if not presenter.lines or presenter.lines[-1] != (want_speaker, want_text):
                raise TranscriptError(
                    f"{file.name}: step {position}: expected line {step['expect_line']!r}, "
                    f"got {presenter.lines[-1] if presenter.lines else None!r}"
                )
            asserted = presenter.lines[-1]
        if "expect_end" in step and presenter.closed != step["expect_end"]:
            raise TranscriptError(
                f"{file.name}: step {position}: expected end {step['expect_end']!r}, "
                f"got {presenter.closed!r}"
            )
        if "expect_store" in step:
            for key, value in step["expect_store"].items():
                actual = store.get(key)
                if actual != value:
                    raise TranscriptError(
                        f"{file.name}: step {position}: expected {key} == {value!r}, got {actual!r}"
                    )
        if "expect_clock" in step:
            total = sum(segments for _reason, segments in host.ticks)
            if total != step["expect_clock"]:
                raise TranscriptError(
                    f"{file.name}: step {position}: expected {step['expect_clock']} Clock segments, "
                    f"got {total} ({host.ticks})"
                )
    return {
        "conversation": conv_id,
        "lines": presenter.lines,
        "closed": presenter.closed,
        "store": store.values,
        "ticks": host.ticks,
    }


def _seed(store: VarStore, key: str, value: Any) -> None:
    """A transcript seeds by assignment. An undeclared key is added, so a scenario can carry extras."""
    spec = store.spec(key)
    if spec is not None and type(value) is not spec.type:
        raise TranscriptError(f"seed {key!r} is {spec.type.__name__}, got {type(value).__name__}")
    store.values[key] = value


# ======================================================================================
# The two commands - section 7.3
# ======================================================================================
def validate_paths(paths: Sequence[str | pathlib.Path]) -> tuple[list[str], list[str]]:
    """Batch validation: every error in every file, plus the cross-file warnings (W2)."""
    errors: list[str] = []
    warnings: list[str] = []
    flags: dict[str, bool] = {}
    flag_source: dict[str, str] = {}
    for path in paths:
        discovered = sorted(pathlib.Path(path).parent.glob(pathlib.Path(path).name))
        for file in discovered:
            try:
                conv = load_conversation(file)
            except DialogueValidationError as exc:
                errors.extend(exc.problems)
                continue
            warnings.extend(conv.warnings)
            for name, default in conv.vars.items():
                if name in flags and flags[name] != default:
                    warnings.append(
                        f"dialogue: {file.name}: warning: flag '{name}' already declared by "
                        f"'{flag_source[name]}'"
                    )
                flags.setdefault(name, default)
                flag_source.setdefault(name, file.name)
    return errors, warnings


def paths_report(conversation: Conversation) -> list[str]:
    """`--paths`: every node from which no end is reachable (7.3's static complement to E14).

    A cycle of choice nodes with no end anywhere in it is legal at load - E15 only refuses *silent*
    cycles - and the player who walks it can never finish the conversation. Reverse reachability from
    the end nodes is the cheap fixpoint that names those nodes.
    """
    can_end = {n.id for n in conversation.nodes if n.kind == "end" or (n.kind == "line" and n.end)}
    changed = True
    while changed:
        changed = False
        for node in conversation.nodes:
            if node.id in can_end:
                continue
            if any(target in can_end for target in node.targets()):
                can_end.add(node.id)
                changed = True
    return [
        f"dialogue: {conversation.source}:nodes[{node.index}] ('{node.id}'): no end is reachable"
        for node in conversation.nodes
        if node.id not in can_end
    ]


# ======================================================================================
# Acceptance test
# ======================================================================================
def demo() -> None:
    """Every rule this module claims, asserted. Run: python -m pinkmohawk.dialogue"""
    # ---- section 2.2: the six kinds, derived by precedence ------------------------------
    six = {
        "id": "kinds",
        "context": "site",
        "cast": {"npc": "NPC", "pc": "Runner"},
        "start": "open",
        "nodes": [
            {"id": "open", "goto": "a"},
            {"id": "a", "cond": "heat >= 0", "then": "b", "else": "c"},
            {"id": "b", "speaker": "npc", "line": "Hi.", "goto": "d"},
            {"id": "c", "effects": [{"set": "flags.seen", "value": True}], "goto": "d"},
            {
                "id": "d",
                "speaker": "npc",
                "line": "Choose.",
                "choices": [{"text": "Bye.", "goto": "e"}],
            },
            {"id": "e", "end": True},
        ],
        "vars": {"seen": False},
    }
    conv = parse_conversation(six, source="kinds.json")
    assert [n.kind for n in conv.nodes] == [
        "jump",
        "condition",
        "line",
        "command",
        "choice",
        "end",
    ], [n.kind for n in conv.nodes]
    assert conv.by_id["a"].kind == "condition", "cond wins over nothing else present"
    assert (
        kind_of({"line": "x", "choices": [{"text": "t", "goto": "g"}], "speaker": "npc"})
        == "choice"
    ), "a line with choices is a choice: precedence 1"
    assert kind_of({"speaker": "npc", "line": "x"}) == "line"
    # Precedence 3 beats 6: a line carrying `end` is a line whose terminator is an end, not an end
    # node. Only a node with `end` and nothing else derives the `end` kind, and the runner treats
    # both the same way (`pending = END if node.end`).
    assert kind_of({"speaker": "npc", "line": "x", "end": True}) == "line"
    assert kind_of({"end": True}) == "end"
    assert kind_of({}) is None, "no payload"

    # ---- section 4: the evaluator's allowed surface -------------------------------------
    store = VarStore(flags={"seen": False})
    store.values.update(
        {
            "heat": 3,
            "rep.fixer": -1,
            "skill.negotiation": 4,
            "crew.nuyen": 2000,
            "clock": 2,
            "attr.charisma": 3,
        }
    )
    for expr, want in (
        ("heat >= 3", True),
        ("heat > 3", False),
        ("heat <= 3", True),
        ("heat < 3", False),
        ("heat == 3", True),
        ("heat != 3", False),
        ("heat >= 1 and rep.fixer < 0", True),
        ("heat >= 9 or rep.fixer < 0", True),
        ("not (heat >= 9)", True),
        ("heat - 1 == 2", True),
        ("heat * 2 == 6", True),
        ("heat % 2 == 1", True),
        ("-heat == -3", True),
        ("1 <= heat <= 4", True),
        ("heat >= 3 and flags.seen == False", True),
        ("rep.fixer < 0 and heat >= 3", True),
        ("has_item('medkit')", False),
    ):
        assert evaluate(expr, store) is want, (expr, want)
    store.inventory.append("medkit")
    assert evaluate("has_item('medkit')", store) is True, "the one whitelisted call"

    # Rejected syntax, each with the message shape of 4.4's table.
    for expr, fragment in (
        ("heat / 2 == 1", "unsupported syntax Div"),
        ("9 ** 9 > 1", "unsupported syntax Pow"),
        ("[x for x in heat] == []", "unsupported syntax ListComp"),
        ("eval('1')", "unsupported call 'eval'"),
        ("__import__('os')", "unsupported call '__import__'"),
        ("len('a') > 0", "unsupported call 'len'"),
        ("has_item('x', True)", "has_item takes 1 argument"),
        ("has_item(heat)", "has_item expects str"),
        ("rep.fixer.__class__ >= 7", "unknown variable 'rep.fixer.__class__'"),
        ("skill.negotiation >= 4 if True else False", "unsupported syntax IfExp"),
        ("f'{heat}' == '3'", "unsupported syntax JoinedStr"),
        ("(heat := 3) >= 0", "unsupported syntax NamedExpr"),
    ):
        try:
            evaluate(expr, store)
        except DialogueParseError as exc:
            assert any(fragment in problem for problem in exc.problems), (
                expr,
                fragment,
                exc.problems,
            )
        except DialogueConditionError as exc:
            assert fragment in str(exc), (expr, fragment, str(exc))
        else:
            raise AssertionError(f"{expr!r} should not have evaluated")
    try:
        evaluate("heat +", store)
    except DialogueParseError as exc:
        assert "condition does not parse" in exc.problems[0] and "at col 7" in exc.problems[0], (
            exc.problems
        )
    else:
        raise AssertionError("a syntax error must be a parse error")
    try:
        evaluate("heat", VarStore())  # a non-boolean result
    except DialogueConditionError as exc:
        assert "not boolean" in str(exc)
    else:
        raise AssertionError("a non-boolean condition must be a condition error")

    # ---- section 2.4: placeholders ------------------------------------------------------
    assert interpolate("{crew.nuyen:,}", store) == "2,000"
    assert interpolate("{rep.fixer}", store) == "-1"
    store.values["npc.target"] = None
    assert interpolate("{npc.target}", store) == "<MISSING:npc.target>", (
        "None renders, never crashes"
    )
    _found, problems = placeholders("keeps {heat:>3} weird")
    assert problems and "malformed placeholder" in problems[0]
    _found, problems = placeholders("a { brace")
    assert problems and "malformed placeholder" in problems[0]

    # ---- section 3: validation of every effect ------------------------------------------
    def problems_for(document: Mapping[str, object]) -> list[str]:
        try:
            parse_conversation(document, source="probe.json")
        except DialogueValidationError as exc:
            return exc.problems
        return []

    base_node = {"id": "open", "goto": "n"}

    def doc_with(node: Mapping[str, object], **extra: object) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": "probe",
            "context": "site",
            "cast": {"npc": "NPC", "pc": "Runner"},
            "interlocutor": "npc",
            "start": "open",
            "vars": {"seen": False},
            "nodes": [
                base_node,
                {"id": "end_", "speaker": "npc", "line": "Bye.", "end": True},
                node,
            ],
        }
        out.update(extra)
        return out

    checks: list[tuple[dict[str, Any], str | None]] = [
        (
            {"id": "n", "effects": [{"set": "heat", "value": 3}], "goto": "end_"},
            "cannot write read-only variable 'heat'",
        ),
        (
            {"id": "n", "effects": [{"set": "wut.key", "value": 3}], "goto": "end_"},
            "cannot write undeclared variable 'wut.key'",
        ),
        (
            {"id": "n", "effects": [{"set": "crew.nuyen", "value": "lots"}], "goto": "end_"},
            "'crew.nuyen' is int, got str",
        ),
        (
            {
                "id": "n",
                "effects": [{"set": "flags.seen", "value": True, "expr": "1"}],
                "goto": "end_",
            },
            "set takes exactly one of 'value' or 'expr'",
        ),
        (
            {
                "id": "n",
                "effects": [
                    {"set": "flags.seen", "value": True},
                    {"set": "flags.seen", "value": 1},
                ],
                "goto": "end_",
            },
            "'flags.seen' is bool, got int",
        ),
        (
            {
                "id": "n",
                "effects": [{"give_item": {"id": "heavy_pistol", "qty": 2}}],
                "goto": "end_",
            },
            None,
        ),
        (
            {"id": "n", "effects": [{"give_item": {"id": "soul", "qty": 1}}], "goto": "end_"},
            "unknown item 'soul'",
        ),
        (
            {"id": "n", "effects": [{"give_item": {"id": "medkit", "qty": 0}}], "goto": "end_"},
            "give_item qty 0 must be an integer >= 1",
        ),
        (
            {"id": "n", "effects": [{"start_job": True}], "goto": "end_"},
            "start_job is only allowed in a 'hub' conversation",
        ),
        (
            {"id": "n", "effects": [{"change_rep": {"who": "fixer", "delta": 3}}], "goto": "end_"},
            "change_rep delta 3 must be a non-zero integer in -2..2",
        ),
        (
            {"id": "n", "effects": [{"change_rep": {"who": "nobody", "delta": 1}}], "goto": "end_"},
            "unknown rep target 'nobody'",
        ),
        ({"id": "n", "effects": [{"tick_clock": "alarm_tripped"}], "goto": "end_"}, None),
        (
            {"id": "n", "effects": [{"tick_clock": "alarm"}], "goto": "end_"},
            "tick_clock reason 'alarm' is not a Security Clock event",
        ),
        (
            {
                "id": "n",
                "effects": [{"tick_clock": "gunfire", "set": "flags.seen"}],
                "goto": "end_",
            },
            "must name exactly one effect",
        ),
        (
            {"id": "n", "effects": [{"teleport": True}], "goto": "end_"},
            "must name exactly one effect",
        ),
        ({"id": "n", "effects": [], "goto": "end_"}, "'effects' is empty"),
        (
            {
                "id": "n",
                "effects": [
                    {
                        "test": {
                            "key": "t",
                            "skill": "negotiation",
                            "attribute": "charisma",
                            "threshold": 9,
                        }
                    }
                ],
                "goto": "end_",
            },
            "threshold 9 is outside the v1 range 1-4",
        ),
        (
            {
                "id": "n",
                "effects": [
                    {
                        "test": {
                            "key": "t",
                            "skill": "negotiation",
                            "attribute": "charisma",
                            "threshold": 2,
                            "opposed": {"pool": 4},
                        }
                    }
                ],
                "goto": "end_",
            },
            "needs exactly one of 'threshold' or 'opposed'",
        ),
        (
            {
                "id": "n",
                "effects": [
                    {
                        "test": {
                            "key": "t",
                            "skill": "basketweaving",
                            "attribute": "charisma",
                            "threshold": 2,
                        }
                    }
                ],
                "goto": "end_",
            },
            "unknown skill 'basketweaving'",
        ),
        (
            {
                "id": "n",
                "effects": [
                    {
                        "test": {
                            "key": "t",
                            "skill": "negotiation",
                            "attribute": "charisma",
                            "threshold": 3,
                        }
                    }
                ],
                "goto": "end_",
            },
            None,
        ),
        (
            # E31: two tests sharing a key would be two rolls against one obstacle (ADR-0006).
            {
                "id": "n",
                "effects": [
                    {
                        "test": {
                            "key": "t",
                            "skill": "negotiation",
                            "attribute": "charisma",
                            "threshold": 2,
                        }
                    },
                    {
                        "test": {
                            "key": "t",
                            "skill": "negotiation",
                            "attribute": "charisma",
                            "threshold": 3,
                        }
                    },
                ],
                "goto": "end_",
            },
            "duplicate test key 't'",
        ),
        (
            # E27: a flag has a home to declare it in, and the message names it.
            {"id": "n", "cond": "flags.nope == True", "then": "end_", "else": "end_"},
            "unknown flag 'nope' (declare it in 'vars')",
        ),
    ]
    for node, wanted in checks:
        found = problems_for(doc_with(node))
        if wanted is None:
            assert not found, (node, found)
        else:
            assert any(wanted in problem for problem in found), (node, wanted, found)

    # W1 is a warning, not an error: a test whose attribute is not the skill's linked one loads and
    # notes itself, because a conversation may legitimately roll Intimidation off Willpower one day.
    linked_doc = doc_with(
        {
            "id": "n",
            "effects": [
                {
                    "test": {
                        "key": "t",
                        "skill": "negotiation",
                        "attribute": "agility",
                        "threshold": 2,
                    }
                }
            ],
            "goto": "end_",
        }
    )
    try:
        parsed_linked = parse_conversation(linked_doc, source="probe.json")
    except DialogueValidationError as exc:  # pragma: no cover
        raise AssertionError(exc.problems) from exc
    assert any("is linked to 'charisma', not 'agility'" in w for w in parsed_linked.warnings), (
        parsed_linked.warnings
    )

    # A hub conversation cannot tick the Clock; a site conversation can (E33).
    hub_doc = doc_with(
        {"id": "n", "effects": [{"tick_clock": "gunfire"}], "goto": "end_"}, context="hub"
    )
    assert any("not allowed in a 'hub' conversation" in p for p in problems_for(hub_doc))

    # ---- section 7: the structural errors ------------------------------------------------
    dangling = doc_with(
        {"id": "n", "effects": [{"set": "flags.seen", "value": True}], "goto": "nowhere"}
    )
    assert any("dangling goto 'nowhere'" in p for p in problems_for(dangling))
    two_term = doc_with({"id": "n", "speaker": "npc", "line": "Hi.", "goto": "end_", "end": True})
    assert any("two terminators: 'goto' and 'end'" in p for p in problems_for(two_term))
    bad_cond = doc_with({"id": "c", "cond": "heat +", "then": "end_", "else": "end_"})
    assert any("condition does not parse" in p for p in problems_for(bad_cond))
    bad_name = doc_with({"id": "c", "cond": "creww.nuyen > 1", "then": "end_", "else": "end_"})
    assert any("unknown variable 'creww.nuyen'" in p for p in problems_for(bad_name))
    floating = doc_with({"id": "orphan", "speaker": "npc", "line": "Lost.", "end": True})
    assert any("unreachable node" in p for p in problems_for(floating))
    no_speaker = doc_with({"id": "n", "speaker": "ghost", "line": "Boo.", "end": True})
    assert any("speaker 'ghost' is not in the cast" in p for p in problems_for(no_speaker))
    no_exit = doc_with(
        {
            "id": "n",
            "speaker": "npc",
            "line": "Pick.",
            "choices": [{"text": "A", "cond": "heat >= 0", "goto": "end_"}],
        }
    )
    assert any("no unconditional choice" in p for p in problems_for(no_exit))

    # W5: a test whose result nothing reads still loads, with the warning.
    unread = doc_with(
        {
            "id": "n",
            "effects": [
                {
                    "test": {
                        "key": "t",
                        "skill": "negotiation",
                        "attribute": "charisma",
                        "threshold": 2,
                    }
                }
            ],
            "goto": "end_",
        }
    )
    try:
        parsed = parse_conversation(unread, source="probe.json")
        assert any("test 't' result is never read" in w for w in parsed.warnings), parsed.warnings
    except DialogueValidationError as exc:  # pragma: no cover
        raise AssertionError(exc.problems) from exc

    # ---- section 3.3: firing order, snapshot semantics and the once-ledger ----------------
    order_doc = {
        "id": "order",
        "context": "hub",
        "cast": {"npc": "NPC", "pc": "Runner"},
        "start": "open",
        "vars": {"first": False, "second": False},
        "nodes": [
            {
                "id": "open",
                "speaker": "npc",
                "line": "Pick.",
                "choices": [
                    {
                        "text": "Swap.",
                        "goto": "swap",
                        "effects": [{"set": "flags.first", "value": True}],
                    },
                ],
            },
            {
                "id": "swap",
                "effects": [
                    {"set": "crew.nuyen", "expr": "job.payout_agreed"},
                    {"set": "job.payout_agreed", "value": 7},
                ],
                "goto": "report",
            },
            {
                "id": "report",
                "speaker": "npc",
                "line": "{crew.nuyen} {job.payout_agreed}",
                "end": True,
            },
        ],
    }
    conv_order = parse_conversation(order_doc, source="order.json")
    store_order = VarStore(flags=conv_order.vars)
    store_order.values["crew.nuyen"] = 5
    store_order.values["job.payout_base"] = 12000
    store_order.values["job.payout_agreed"] = 12000
    host_order = HeadlessHost()
    presenter_order = RecordingPresenter()
    runner = DialogueRunner(conv_order, store_order, presenter_order, ScriptedDice([6]), host_order)
    runner.start()
    assert runner.state == RunnerState.WAITING_CHOICE
    runner.choose(0)
    assert store_order.get("crew.nuyen") == 12000, (
        "the RHS reads the pre-array snapshot, so `a: b` then `b: 7` still swaps"
    )
    assert store_order.get("job.payout_agreed") == 7
    assert presenter_order.lines[-1][1] == "12000 7", (
        "interpolation happens at display time, after effects"
    )
    runner.advance()  # a line carrying `end` still waits for the continue key
    assert presenter_order.closed == "end"

    # The once-ledger: the same node's effects cannot fire twice in one Job (3.3.5).
    presenter2 = RecordingPresenter()
    runner2 = DialogueRunner(
        conv_order, store_order, presenter2, ScriptedDice([]), host_order, ledger=set(runner.ledger)
    )
    store_order.values["crew.nuyen"] = 1
    runner2.start()
    runner2.choose(0)
    assert store_order.get("crew.nuyen") == 1, (
        "the ledger already holds this node, so nothing fires"
    )

    # ---- section 3.2: `test` resolves, exposes three keys, and reports to the host --------
    test_doc = {
        "id": "rolls",
        "context": "site",
        "cast": {"npc": "NPC", "pc": "Runner"},
        "interlocutor": "npc",
        "start": "open",
        "vars": {},
        "nodes": [
            {
                "id": "open",
                "speaker": "npc",
                "line": "Haggle?",
                "choices": [{"text": "Yes.", "goto": "roll"}],
            },
            {
                "id": "roll",
                "effects": [
                    {
                        "test": {
                            "key": "haggle",
                            "skill": "negotiation",
                            "attribute": "charisma",
                            "opposed": {"pool": 4},
                        }
                    }
                ],
                "goto": "result",
            },
            {"id": "result", "cond": "test.haggle.net >= 2", "then": "big", "else": "small"},
            {"id": "big", "speaker": "npc", "line": "Fine. {job.payout_agreed:,}", "end": True},
            {"id": "small", "speaker": "npc", "line": "The number stands.", "end": True},
        ],
    }
    conv_test = parse_conversation(test_doc, source="rolls.json")
    assert not any("never read" in w for w in conv_test.warnings), conv_test.warnings
    store_test = VarStore(test_keys=conv_test.test_keys, flags=conv_test.vars)
    store_test.values.update(
        {
            "skill.negotiation": 4,
            "attr.charisma": 3,
            "job.payout_base": 12000,
            "job.payout_agreed": 12000,
        }
    )
    host_test = HeadlessHost()  # the opposition rolls first (10.4), then the Runner
    presenter_test = RecordingPresenter()
    # The opposition rolls first (10.4): four 1s, no hits. Then the Runner's seven dice: three hits.
    runner_test = DialogueRunner(
        conv_test,
        store_test,
        presenter_test,
        ScriptedDice([1, 1, 1, 1, 6, 6, 5, 4, 4, 4, 4]),
        host_test,
    )
    runner_test.start()
    runner_test.choose(0)
    assert store_test.get("test.haggle.hits") == 3, store_test.values["test.haggle.hits"]
    assert store_test.get("test.haggle.net") == 3, (
        "3 hits against 0: the opposition rolled three 1s"
    )
    assert store_test.get("test.haggle.glitch") is False, "the Runner's own dice hold no 1s"
    assert presenter_test.lines[-1][1] == "Fine. 12,000", "the big branch was taken"
    assert host_test.tests == [("rolls", "haggle", 3)], host_test.tests

    # A critical glitch ticks the Clock, once, and only in a site conversation (3.2 step 5).
    store_crit = VarStore(test_keys=conv_test.test_keys, flags=conv_test.vars)
    store_crit.values.update(
        {
            "skill.negotiation": 1,
            "attr.charisma": 0,
            "job.payout_base": 12000,
            "job.payout_agreed": 12000,
        }
    )
    host_crit = HeadlessHost()
    runner_crit = DialogueRunner(
        conv_test, store_crit, RecordingPresenter(), ScriptedDice([6, 6, 6, 6, 1]), host_crit
    )
    runner_crit.start()
    runner_crit.choose(0)
    assert store_crit.get("test.haggle.hits") == 0
    assert store_crit.get("test.haggle.glitch") is True
    assert host_crit.ticks == [("critical_glitch", 1)], host_crit.ticks

    # ---- section 3.1: raise-only alert_level, change_rep clamp ---------------------------
    clamp_doc = {
        "id": "clamps",
        "context": "site",
        "cast": {"npc": "NPC", "pc": "Runner"},
        "interlocutor": "npc",
        "start": "open",
        "vars": {},
        "nodes": [
            {
                "id": "open",
                "speaker": "npc",
                "line": "Halt.",
                "choices": [
                    {
                        "text": "Calm down.",
                        "goto": "calm",
                        "effects": [
                            {"set": "npc.alert_level", "value": 0},
                            {"change_rep": {"who": "fixer", "delta": -2}},
                        ],
                    },
                    {"text": "Leave.", "goto": "bye"},
                ],
            },
            {
                "id": "calm",
                "speaker": "npc",
                "line": "Hm.",
                "effects": [{"change_rep": {"who": "fixer", "delta": -2}}],
                "choices": [
                    {"text": "Keep going.", "goto": "calm2"},
                    {"text": "Leave.", "goto": "bye"},
                ],
            },
            {
                "id": "calm2",
                "speaker": "npc",
                "line": "Enough.",
                "effects": [{"change_rep": {"who": "fixer", "delta": -2}}],
                "choices": [{"text": "Leave.", "goto": "bye"}],
            },
            {"id": "bye", "speaker": "npc", "line": "Go.", "end": True},
        ],
    }
    conv_clamp = parse_conversation(clamp_doc, source="clamps.json")
    store_clamp = VarStore(test_keys=conv_clamp.test_keys, flags=conv_clamp.vars)
    store_clamp.values["npc.alert_level"] = 2
    store_clamp.values["rep.fixer"] = 0
    runner_clamp = DialogueRunner(
        conv_clamp, store_clamp, RecordingPresenter(), ScriptedDice([]), HeadlessHost()
    )
    runner_clamp.start()
    runner_clamp.choose(0)  # the choice's −2, then the entered node's −2, are two separate arrays
    assert store_clamp.get("npc.alert_level") == 2, "alert_level is raise-only: 0 cannot lower a 2"
    assert store_clamp.get("rep.fixer") == -4, store_clamp.get("rep.fixer")
    runner_clamp.choose(0)  # a third array takes it past the floor
    assert store_clamp.get("rep.fixer") == constants.REP_MIN, "rep clamps at the floor, not −6"

    # ---- section 6.2/6.3: on_empty, the budget, and a visible error ----------------------
    # E14 makes a dead end unreachable from a valid file, so the runtime fallback is proven the way
    # the budget is: the graph is built in memory, and the file that would need it is refused at load.
    gated_only = {
        "id": "empties",
        "context": "hub",
        "cast": {"npc": "NPC", "pc": "Runner"},
        "start": "open",
        "vars": {},
        "on_empty": "leave",
        "nodes": [
            {
                "id": "open",
                "speaker": "npc",
                "line": "Gated.",
                "choices": [{"text": "Rich only.", "cond": "crew.nuyen >= 99999", "goto": "leave"}],
            },
            {"id": "leave", "speaker": "npc", "line": "Move along.", "end": True},
        ],
    }
    try:
        parse_conversation(gated_only, source="empties.json")
    except DialogueValidationError as exc:
        assert any("no unconditional choice" in p for p in exc.problems), exc.problems
    else:
        raise AssertionError("a choice node with no unconditional choice must be refused (E14)")

    def empty_conv(*, on_empty: str | None) -> Conversation:
        gate = Node(
            id="open",
            kind="choice",
            index=0,
            speaker="npc",
            line="Gated.",
            choices=(Choice(text="Rich only.", goto="leave", index=0, cond="crew.nuyen >= 99999"),),
        )
        leave = Node(id="leave", kind="line", index=1, speaker="npc", line="Move along.", end=True)
        return Conversation(
            id="empties",
            context="hub",
            cast={"npc": "NPC", "pc": "Runner"},
            pc="pc",
            start="open",
            nodes=(gate, leave),
            by_id={"open": gate, "leave": leave},
            source="memory",
            vars={},
            on_empty=on_empty,
        )

    presenter_empty = RecordingPresenter()
    runner_empty = DialogueRunner(
        empty_conv(on_empty="leave"), VarStore(), presenter_empty, ScriptedDice([]), HeadlessHost()
    )
    runner_empty.start()
    assert presenter_empty.lines[-1][1] == "Move along.", (
        "an empty choice set falls back to on_empty"
    )
    runner_empty.advance()  # the fallback line still waits for the continue key
    assert presenter_empty.closed == "end"

    presenter_dead = RecordingPresenter()
    runner_dead = DialogueRunner(
        empty_conv(on_empty=None), VarStore(), presenter_dead, ScriptedDice([]), HeadlessHost()
    )
    runner_dead.start()
    assert presenter_dead.closed == "dead_end", "with no on_empty the conversation closes cleanly"

    # The budget is defence in depth: validation refuses a silent cycle (E15), so this builds the
    # cycle in memory to prove the guard itself exists rather than trusting the load path.
    silent = {
        "id": "loop",
        "context": "hub",
        "cast": {"npc": "NPC", "pc": "Runner"},
        "start": "a",
        "nodes": [
            {"id": "a", "goto": "b"},
            {"id": "b", "goto": "a"},
            {"id": "unused", "speaker": "npc", "line": "x", "end": True},
        ],
    }
    try:
        parse_conversation(silent, source="loop.json")
    except DialogueValidationError as exc:
        assert any("silent cycle" in p for p in exc.problems), exc.problems
    else:
        raise AssertionError("a silent cycle must be refused at load")
    node_a = Node(id="a", kind="jump", index=0, goto="b")
    node_b = Node(id="b", kind="jump", index=1, goto="a")
    cycling = Conversation(
        id="loop",
        context="hub",
        cast={"npc": "NPC"},
        pc="npc",
        start="a",
        nodes=(node_a, node_b),
        by_id={"a": node_a, "b": node_b},
        source="memory",
        vars={},
    )
    try:
        DialogueRunner(
            cycling, VarStore(), RecordingPresenter(), ScriptedDice([]), HeadlessHost()
        ).start()
    except DialogueRuntimeError as exc:
        assert "runaway auto-advance" in str(exc)
    else:
        raise AssertionError("the auto-advance budget must catch a silent cycle")

    # A runtime condition error shows an error and closes; it is not treated as False (4.5).
    cond_node = Node(
        id="open",
        kind="condition",
        index=0,
        cond="crew.nuyen >= 99999",
        then="leave",
        otherwise="leave",
    )
    leave_node = Node(id="leave", kind="line", index=1, speaker="npc", line="Go.", end=True)
    typed = Conversation(
        id="typed",
        context="hub",
        cast={"npc": "NPC"},
        pc="npc",
        start="open",
        nodes=(cond_node, leave_node),
        by_id={"open": cond_node, "leave": leave_node},
        source="memory",
        vars={},
    )
    store_bad = VarStore()
    store_bad.values["crew.nuyen"] = "lots"  # a string against an int, exactly 4.5's example
    presenter_bad = RecordingPresenter()
    runner_bad = DialogueRunner(typed, store_bad, presenter_bad, ScriptedDice([]), HeadlessHost())
    runner_bad.start()
    assert "<DIALOGUE ERROR" in presenter_bad.lines[-1][1], presenter_bad.lines
    assert presenter_bad.closed == "error"

    # `advance()` and `choose()` are no-ops in the wrong state, so a key repeat cannot skip a line.
    store_guard = VarStore(flags=conv_order.vars)
    presenter_guard = RecordingPresenter()
    runner_guard = DialogueRunner(
        conv_order, store_guard, presenter_guard, ScriptedDice([]), HeadlessHost()
    )
    runner_guard.advance()
    runner_guard.choose(0)
    assert presenter_guard.lines == [] and runner_guard.state == RunnerState.IDLE

    # W3, W4 and W6, so all six warnings of 7.1 have been seen to fire.
    unknown_faction = doc_with(
        {
            "id": "n",
            "effects": [{"change_rep": {"who": "faction:corps", "delta": 1}}],
            "goto": "end_",
        }
    )
    try:
        parsed_faction = parse_conversation(unknown_faction, source="probe.json")
    except DialogueValidationError as exc:  # pragma: no cover
        raise AssertionError(exc.problems) from exc
    assert any("not a declared faction" in w for w in parsed_faction.warnings), (
        parsed_faction.warnings
    )
    long_line = doc_with({"id": "n", "speaker": "npc", "line": "x" * 250, "goto": "end_"})
    try:
        parsed_long = parse_conversation(long_line, source="probe.json")
    except DialogueValidationError as exc:  # pragma: no cover
        raise AssertionError(exc.problems) from exc
    assert any("characters (UI holds ~180)" in w for w in parsed_long.warnings), (
        parsed_long.warnings
    )
    assert any(
        "cast entry 'pc' is never used" in w
        for w in load_conversation(DIALOGUE_DIR / "fixer_offer.json").warnings
    ), "W4: the pc slug speaks nowhere in the Fixer's conversation"

    # ---- the two authored conversations --------------------------------------------------
    for name in ("fixer_offer", "corp_guard_bribe"):
        path = DIALOGUE_DIR / f"{name}.json"
        assert path.exists(), f"missing authored conversation {path}"
        authored = load_conversation(path)
        assert not authored.warnings or all("warning" in w or ":" in w for w in authored.warnings)
        walk = _walk_to_end(authored)
        assert walk["closed"] in ("end", "dead_end"), (name, walk)

    # The Fixer's reputation gate closes the conversation before any offer.
    refused = _walk_to_end(
        load_conversation(DIALOGUE_DIR / "fixer_offer.json"),
        seed={"rep.fixer": -1},
        choices=["Not interested."],
    )
    assert refused["closed"] == "end" and refused["lines"][0][1].startswith("You're the crew")
    assert refused["store"]["flags.fixer_refused"] is True, refused["store"]

    # The full haggle: a choice gated on skill.negotiation, a test driving payout_agreed, and a
    # choice that disappears once its flag is set.
    haggle = _walk_to_end(
        load_conversation(DIALOGUE_DIR / "fixer_offer.json"),
        seed={
            "skill.negotiation": 4,
            "attr.charisma": 5,
            "job.payout_base": 12000,
            "job.payout_agreed": 12000,
            "crew.nuyen": 2000,
        },
        choices=["The pay is 12k, the risk is 15k.", "I'm in."],
        # 8's walk: the Fixer's 4 dice roll one hit, the Runner's 9 roll four, so net = 3.
        dice=[6, 4, 4, 4, 6, 6, 5, 5, 4, 4, 4, 4, 4],
    )
    assert haggle["closed"] == "end", haggle["closed"]
    assert haggle["store"]["job.payout_agreed"] == 12_300, haggle["store"]["job.payout_agreed"]
    assert haggle["store"]["job.accepted"] is True and haggle["store"]["job.state"] == "accepted"
    assert any("12,300" in text for _speaker, text in haggle["lines"]), haggle["lines"]

    # The guard: a bribe gated on nuyen, the social channel written, effects once per Job.
    bribe = _walk_to_end(
        load_conversation(DIALOGUE_DIR / "corp_guard_bribe.json"),
        seed={"crew.nuyen": 2000, "rep.faction.corp_arasaka": 0, "npc.alert_level": 1},
        choices=["You look bored. 500 says you never saw me.", "Hand it over."],
    )
    assert bribe["closed"] == "end" and bribe["store"]["npc.pacified"] is True
    assert bribe["store"]["crew.nuyen"] == 1500, bribe["store"]["crew.nuyen"]
    assert bribe["store"]["flags.guard_bribed"] is True
    assert bribe["ticks"] == [], "a clean bribe costs no Clock"

    # The burned bribe and the failed Intimidation both tick the Clock and escalate.
    burned = _walk_to_end(
        load_conversation(DIALOGUE_DIR / "corp_guard_bribe.json"),
        seed={"crew.nuyen": 2000, "rep.faction.corp_arasaka": -1},
        choices=["You look bored. 500 says you never saw me.", "Hand it over."],
    )
    assert burned["ticks"] == [("alarm_tripped", 2)], burned["ticks"]
    assert burned["store"]["npc.alert_level"] == 2
    assert burned["store"]["npc.pacified"] is False, "a burned bribe does not pacify"
    lost = _walk_to_end(
        load_conversation(DIALOGUE_DIR / "corp_guard_bribe.json"),
        seed={"skill.intimidation": 5, "attr.charisma": 4, "npc.alert_level": 1},
        choices=["Back off or I put you through that wall."],
        dice=[1, 1, 1, 1, 1, 1, 1, 2, 2],  # nine dice, seven 1s and no hits: a critical glitch
    )
    assert lost["store"]["test.intimidation.glitch"] is True, lost["store"]
    assert lost["ticks"] == [("critical_glitch", 1), ("gunfire", 2)], lost["ticks"]

    # ---- transcripts: the shipped evidence for both conversations ------------------------
    transcripts_dir = DIALOGUE_DIR / "tests"
    if transcripts_dir.exists():
        files = sorted(transcripts_dir.glob("*.json"))
        assert len(files) >= 4, (
            "10.4: every test in a file needs at least a pass and a fail transcript"
        )
        for file in files:
            run_transcript(file)
        print(f"    {len(files)} transcripts replayed")

    # ---- the batch command's engine ------------------------------------------------------
    errors, _warnings = validate_paths([DIALOGUE_DIR / "*.json"])
    assert not errors, errors

    # `--paths`: both authored conversations can finish, and a choice cycle with no end is named.
    for name in ("fixer_offer", "corp_guard_bribe"):
        assert not paths_report(load_conversation(DIALOGUE_DIR / f"{name}.json")), name
    loop_doc = {
        "id": "endless",
        "context": "hub",
        "cast": {"npc": "NPC", "pc": "Runner"},
        "start": "a",
        "nodes": [
            {
                "id": "a",
                "speaker": "npc",
                "line": "Round.",
                "choices": [{"text": "Again.", "goto": "b"}],
            },
            {
                "id": "b",
                "speaker": "npc",
                "line": "And round.",
                "choices": [{"text": "Again.", "goto": "a"}],
            },
        ],
    }
    endless = parse_conversation(loop_doc, source="endless.json")
    assert len(paths_report(endless)) == 2, paths_report(endless)

    print(
        f"OK  dialogue: {len(DECLARED)} declared keys, "
        f"{len(constants.SKILLS)} skills, evaluator whitelist {sorted(WHITELIST)}, "
        f"2 authored conversations green, batch validate clean"
    )


def _walk_to_end(
    conversation: Conversation,
    *,
    seed: Mapping[str, Any] | None = None,
    choices: Sequence[str] | None = None,
    dice: Sequence[int] | None = None,
) -> dict[str, Any]:
    """Play a conversation by choice text until it closes. The demo's driver."""
    store = VarStore(test_keys=conversation.test_keys, flags=conversation.vars)
    for key, value in (seed or {}).items():
        _seed(store, key, value)
    host = HeadlessHost()
    presenter = RecordingPresenter()
    runner = DialogueRunner(conversation, store, presenter, ScriptedDice(list(dice or [])), host)
    runner.start(actors={conversation.interlocutor or "npc": "stub"}, pc_actor="stub")
    queue = list(choices or [])
    for _ in range(64):
        if runner.done:
            break
        if runner.state == RunnerState.WAITING_CONTINUE:
            runner.advance()
            continue
        if runner.state == RunnerState.WAITING_CHOICE:
            shown = presenter.shown[-1]
            wanted = queue.pop(0) if queue else None
            if wanted is None:
                # No script left: take the last shown choice, which is the authored escape hatch.
                runner.choose(len(shown) - 1)
                continue
            if wanted not in shown:
                raise AssertionError(f"choice {wanted!r} is not among {shown}")
            runner.choose(shown.index(wanted))
    if not runner.done:
        raise AssertionError("the walk did not terminate")
    return {
        "lines": presenter.lines,
        "closed": presenter.closed,
        "store": dict(store.values),
        "ticks": host.ticks,
    }


# ======================================================================================
# Entry points
# ======================================================================================
def _cmd_validate(paths: Sequence[str]) -> int:
    errors, warnings = validate_paths(paths)
    for warning in warnings:
        print(f"  warn {warning}")
    for error in errors:
        print(f"  ERROR {error}")
    if errors:
        print(f"\n{len(errors)} error(s) in {len(paths)} file pattern(s)")
        return 1
    print(f"\nOK  {len(warnings)} warning(s), no errors")
    return 0


def _choice_script(text: str) -> list[str]:
    """Parse `--choices`. A comma-separated list is 7.3's format, and it cannot express a choice text
    that itself contains a comma, so a JSON array is accepted for those and `#N` is the index escape
    hatch (the shipped conversations have a choice with a comma in it, which is how this surfaced).
    """
    if not text:
        return []
    if text.lstrip().startswith("["):
        parsed = json.loads(text)
        return [str(item) for item in parsed]
    return text.split(",")


def _cmd_play(args: argparse.Namespace) -> int:
    conversation = load_conversation(args.path)
    for warning in conversation.warnings:
        print(f"  warn {warning}")
    store = VarStore(test_keys=conversation.test_keys, flags=conversation.vars)
    for pair in args.set:
        key, _, value = pair.partition("=")
        store.values[key] = (
            json.loads(value)
            if value[:1] in "[{" or value in ("true", "false")
            else int(value)
            if value.lstrip("-").isdigit()
            else value
        )
    rng = random.Random(args.seed)
    host = HeadlessHost()
    presenter = RecordingPresenter()
    runner = DialogueRunner(conversation, store, presenter, RandomDice(rng), host)
    actors = {conversation.interlocutor or "npc": "stub"}
    for pair in args.actors:
        slug, _, _ref = pair.partition("=")
        actors[slug] = "stub"
    runner.start(actors=actors, pc_actor="stub")
    queue = _choice_script(args.choices)
    for _ in range(64):
        if runner.done:
            break
        if runner.state == RunnerState.WAITING_CONTINUE:
            runner.advance()
        elif runner.state == RunnerState.WAITING_CHOICE:
            shown = presenter.shown[-1]
            wanted = queue.pop(0) if queue else None
            if wanted is None:
                print("  choices: " + " | ".join(f"{i + 1}. {t}" for i, t in enumerate(shown)))
                break
            if wanted.startswith("#"):
                index = int(wanted[1:]) - 1
            elif wanted in shown:
                index = shown.index(wanted)
            else:
                print(f"  no such choice: {wanted!r}; shown: {shown}")
                return 1
            if not 0 <= index < len(shown):
                print(f"  choice {wanted!r} is out of range; shown: {shown}")
                return 1
            runner.choose(index)
    for speaker, text in presenter.lines:
        print(f"  {speaker}: {text}")
    print(f"  -- closed: {presenter.closed}")
    if args.transcript:
        print(
            json.dumps(
                {
                    "lines": presenter.lines,
                    "closed": presenter.closed,
                    "store": store.values,
                    "ticks": host.ticks,
                },
                indent=2,
            )
        )
    if args.paths:
        problems = paths_report(conversation)
        for problem in problems:
            print(f"  path problem: {problem}")
        if not problems:
            print("  every node can reach an end")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pinkmohawk.dialogue", description=__doc__.splitlines()[0]
    )
    sub = parser.add_subparsers(dest="command")
    validate = sub.add_parser("validate", help="validate every conversation in each pattern")
    validate.add_argument("paths", nargs="+")
    play = sub.add_parser("play", help="run one conversation headless")
    play.add_argument("path")
    play.add_argument("--choices", default="", help="comma-separated choice texts, or #N")
    play.add_argument("--set", action="append", default=[], help="seed a store key: key=value")
    play.add_argument("--actors", action="append", default=[], help="bind a cast slug: slug=ref")
    play.add_argument("--seed", type=int, default=0)
    play.add_argument("--transcript", action="store_true")
    play.add_argument("--paths", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "validate":
        return _cmd_validate(args.paths)
    if args.command == "play":
        return _cmd_play(args)
    demo()
    return 0


if __name__ == "__main__":
    sys.exit(main())

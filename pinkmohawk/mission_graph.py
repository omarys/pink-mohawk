"""Mission Graph: the objective structure a Site is embedded from.

ADR-0011 (objective-first generation); node types, edge constraints and the builder in
docs/design/world.md §5. DECISIONS §10 owns the ceilings.

Generation is two stages, always in this order: build this graph, then embed it into a tile map.
The graph is where the *reason* for a layout lives — which room matters, where the gate is, what is
optional — so the embedder can only be as interesting as the graph it is handed.

Two graph algorithms, and they are not interchangeable:

* **Reachability** (every objective reachable from entry, exit reachable from every objective) is a
  forward BFS from a start node.
* **Acyclicity** is Kahn's algorithm (repeatedly strip a zero in-degree node) or a DFS with colours.
  Union-find *cannot* do this: it answers "are these connected", not "is this ordered", and a cycle
  is perfectly connected. The design docs call this out because the temptation to reuse the
  union-find from the connectivity check is strong and the bug is invisible.

`embed` later reuses union-find for a different question — is every *room* in the tile map reachable
— which is genuinely a connectivity question about an undirected structure.

Generator parameters (`JOB_GRAPH`, `SIDE_CHAIN_P`, `SIDE_CHAIN_MAX`, `MAX_IN_DEGREE`) are world.md
§5.2/§5.3 values, not DECISIONS values, so they live here with the generator rather than in
`constants.py`. Move them if the contract adopts them.

    .venv/bin/python -m pinkmohawk.mission_graph      # runs demo()
"""

from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass, field
from typing import Final

from .errors import ValidationError

# --- generator parameters (docs/design/world.md §5.2, §5.3) -----------------------------------
MAX_IN_DEGREE: Final = 2  # [P12]: a second in-edge makes a merge, the only legal diamond
SIDE_CHAIN_MAX: Final = 2  # [P11]: side nodes in a single chain
SIDE_CHAIN_P: Final = 0.25  # chance a side node grows a side child

# NOTE ON `side_max`: it counts side *branches*, not side nodes. world.md §5.1's "side 0-3" row
# reads as nodes, but §5.6's own worked example draws "2 side branches of a possible 3, each 2
# nodes deep" = 4 side nodes, so branches is the reading the document itself uses. A graph can
# therefore hold up to side_max * SIDE_CHAIN_MAX side nodes.

JOB_GRAPH: Final = {
    # sec_pre: security nodes between entry and the first objective
    # sec_post: security nodes between the last objective and exit
    "extraction": {"sec_pre": 2, "sec_post": 1, "objectives": 1, "side_max": 3, "min_len": 5},
    "sabotage": {"sec_pre": 1, "sec_post": 1, "objectives": 2, "side_max": 2, "min_len": 5},
    "protection": {"sec_pre": 1, "sec_post": 1, "objectives": 1, "side_max": 1, "min_len": 4},
    "courier": {"sec_pre": 1, "sec_post": 0, "objectives": 1, "side_max": 2, "min_len": 3},
}

ENTRY, SECURITY, OBJECTIVE, SIDE, EXIT = "entry", "security", "objective", "side", "exit"
KINDS: Final = (ENTRY, SECURITY, OBJECTIVE, SIDE, EXIT)


class GraphError(ValidationError):
    """A structural rule from world.md §5.2 was violated at build time."""


@dataclass(slots=True)
class Node:
    id: int
    kind: str
    outgoing: list[int] = field(default_factory=list)
    incoming: list[int] = field(default_factory=list)

    @property
    def side_marker(self) -> bool:
        """Read by the embedder when seeding optional loot (world.md §5.4, §7)."""
        return self.kind == SIDE


class MissionGraph:
    """Typed DAG of objective nodes. `add` then `link`; both enforce the constraints."""

    __slots__ = ("nodes", "job_type", "_next_id")

    def __init__(self, job_type: str | None = None) -> None:
        self.nodes: dict[int, Node] = {}
        self.job_type = job_type
        self._next_id = 0

    # -- construction ---------------------------------------------------------------------
    def add(self, kind: str) -> int:
        if kind not in KINDS:
            raise GraphError(f"unknown node kind {kind!r}")
        nid = self._next_id
        self._next_id += 1
        self.nodes[nid] = Node(nid, kind)
        return nid

    def link(self, parent: int, child: int) -> int:
        """Add parent -> child after checking the structural rules. Returns child."""
        self._check_link(parent, child)
        self.nodes[parent].outgoing.append(child)
        self.nodes[child].incoming.append(parent)
        return child

    def _link_unchecked(self, parent: int, child: int) -> int:
        """Test-only: bypass the rules so the validators can be shown to catch what they claim."""
        self.nodes[parent].outgoing.append(child)
        self.nodes[child].incoming.append(parent)
        return child

    def _check_link(self, parent: int, child: int) -> None:
        if parent not in self.nodes or child not in self.nodes:
            raise GraphError(f"unknown node in link {parent}->{child}")
        if parent == child:
            raise GraphError(f"self link at {parent}")
        p, c = self.nodes[parent], self.nodes[child]
        if c.kind == ENTRY:
            raise GraphError("entry must have in-degree 0")
        if p.kind == EXIT:
            raise GraphError("exit must have out-degree 0")
        if child in p.outgoing:
            raise GraphError(f"duplicate edge {parent}->{child}")
        if len(c.incoming) >= MAX_IN_DEGREE:
            raise GraphError(f"in-degree > {MAX_IN_DEGREE} at node {child}")
        if p.kind == SIDE:
            if c.kind != SIDE:
                raise GraphError("side branches dead-end: a side node may only lead to side nodes")
            if self.side_chain_len(parent) >= SIDE_CHAIN_MAX:
                raise GraphError(f"side chain longer than {SIDE_CHAIN_MAX}")
        if c.kind == SIDE and p.kind in (ENTRY, EXIT):
            raise GraphError("a side branch hangs off the main path, never off entry or exit")

    # -- queries --------------------------------------------------------------------------
    def of_kind(self, kind: str) -> list[int]:
        return [n for n, node in self.nodes.items() if node.kind == kind]

    def edges(self) -> list[tuple[int, int]]:
        """Every (parent, child) edge. The embedder carves one corridor per edge."""
        return [(n, c) for n, node in self.nodes.items() for c in node.outgoing]

    def single(self, kind: str) -> int:
        found = self.of_kind(kind)
        if len(found) != 1:
            raise GraphError(f"expected exactly one {kind}, found {len(found)}")
        return found[0]

    def side_chain_len(self, node: int) -> int:
        """How many side nodes lead into `node`, including it. 1 for a lone side node."""
        length: int = 0
        cur: int | None = node
        while cur is not None and self.nodes[cur].kind == SIDE:
            length += 1
            parents = self.nodes[cur].incoming
            cur = parents[0] if parents else None
        return length

    def reachable_from(self, start: int) -> set[int]:
        """Forward BFS. Reachability, not connectivity: direction matters and cycles are illegal."""
        seen = {start}
        q = deque([start])
        while q:
            for nxt in self.nodes[q.popleft()].outgoing:
                if nxt not in seen:
                    seen.add(nxt)
                    q.append(nxt)
        return seen

    def is_dag(self) -> bool:
        """Kahn's algorithm: if a topological order cannot consume every node, there is a cycle."""
        in_deg = {n: len(node.incoming) for n, node in self.nodes.items()}
        q = deque([n for n, d in in_deg.items() if d == 0])
        consumed = 0
        while q:
            node = q.popleft()
            consumed += 1
            for nxt in self.nodes[node].outgoing:
                in_deg[nxt] -= 1
                if in_deg[nxt] == 0:
                    q.append(nxt)
        return consumed == len(self.nodes)

    def depth(self) -> dict[int, int]:
        """Node id -> longest distance from entry, in edges. Longest, because a merge must sit
        after every branch that feeds it."""
        order = dict.fromkeys(self.nodes, 0)
        for _ in range(len(self.nodes)):  # DAG + ids in topological-ish order
            changed = False
            for n, node in self.nodes.items():
                for nxt in node.outgoing:
                    if order[nxt] < order[n] + 1:
                        order[nxt] = order[n] + 1
                        changed = True
            if not changed:
                break
        return order

    def shortest_path_len(self, start: int, goal: int) -> int:
        """Nodes on the shortest start -> goal path, inclusive. 0 when unreachable."""
        if start == goal:
            return 1
        seen, q = {start}, deque([(start, 1)])
        while q:
            node, d = q.popleft()
            for nxt in self.nodes[node].outgoing:
                if nxt == goal:
                    return d + 1
                if nxt not in seen:
                    seen.add(nxt)
                    q.append((nxt, d + 1))
        return 0

    def main_path(self) -> list[int]:
        """One entry -> exit path through the objectives, for side-parent sampling."""
        entry, exit_ = self.single(ENTRY), self.single(EXIT)
        path, cur = [entry], entry
        while cur != exit_:
            # Walk the route that is closest to the exit, so the "main path" is the shortest
            # entry -> exit route through the objectives rather than any arbitrary walk.
            nxt = [
                n for n in self.nodes[cur].outgoing if n == exit_ or exit_ in self.reachable_from(n)
            ]
            if not nxt:
                raise GraphError(f"no route to exit past node {cur}")
            cur = min(nxt, key=lambda n: self.shortest_path_len(n, exit_))
            path.append(cur)
        return path

    def pick_side_parents(self, rng: random.Random, count: int) -> list[int]:
        """Sample main-path nodes without replacement, weighted toward the middle of the path."""
        candidates = [n for n in self.main_path() if self.nodes[n].kind not in (ENTRY, EXIT)]
        if not candidates or count <= 0:
            return []
        candidates.sort(key=lambda n: self.depth()[n])
        third = max(1, len(candidates) // 3)
        middle = set(candidates[third : max(third + 1, len(candidates) - third)])
        pool = list(candidates)
        weights = [3.0 if n in middle else 1.0 for n in pool]
        picked: list[int] = []
        for _ in range(min(count, len(pool))):
            target, acc = rng.random() * sum(weights), 0.0
            for index in range(len(weights)):
                acc += weights[index]
                if target <= acc:
                    picked.append(pool.pop(index))
                    weights.pop(index)
                    break
        return picked

    # -- validation ----------------------------------------------------------------------
    def validate(self) -> list[str]:
        """Every world.md §5.2 rule plus the two graph-wide properties. Empty list == valid."""
        bad: list[str] = []
        entries, exits = self.of_kind(ENTRY), self.of_kind(EXIT)
        if len(entries) != 1:
            bad.append(f"expected exactly one entry, found {len(entries)}")
        if len(exits) != 1:
            bad.append(f"expected exactly one exit, found {len(exits)}")
        if not len(self.of_kind(SECURITY)) >= 1:
            bad.append("at least one security node is required")
        if not self.of_kind(OBJECTIVE):
            bad.append("at least one objective is required")

        for n, node in self.nodes.items():
            if node.kind == ENTRY and (node.incoming or not node.outgoing):
                bad.append(f"entry {n} must have in-degree 0 and out-degree >= 1")
            if node.kind == EXIT and (node.outgoing or not node.incoming):
                bad.append(f"exit {n} must have out-degree 0 and in-degree >= 1")
            if node.kind == SECURITY and (not node.incoming or not node.outgoing):
                bad.append(f"security node {n} is terminal or a source")
            if len(node.incoming) > MAX_IN_DEGREE:
                bad.append(f"node {n} has in-degree {len(node.incoming)}")
            if node.kind == SIDE:
                if len(node.incoming) != 1:
                    bad.append(f"side node {n} must have exactly one parent")
                if self.side_chain_len(n) > SIDE_CHAIN_MAX:
                    bad.append(f"side node {n} is in a chain longer than {SIDE_CHAIN_MAX}")
                for nxt in node.outgoing:
                    if self.nodes[nxt].kind != SIDE:
                        bad.append(
                            f"side node {n} leads to a {self.nodes[nxt].kind}, not a dead end"
                        )

        if not self.is_dag():
            bad.append("graph contains a cycle")

        if len(entries) == 1:
            reach = self.reachable_from(entries[0])
            for obj in self.of_kind(OBJECTIVE):
                if obj not in reach:
                    bad.append(f"objective {obj} is not reachable from entry")
            for obj in self.of_kind(OBJECTIVE):
                if exits and exits[0] not in self.reachable_from(obj):
                    bad.append(f"exit is not reachable from objective {obj}")
            for n in self.nodes:
                if n not in reach:
                    bad.append(f"node {n} is unreachable from entry")
        return bad


def build_graph(job_type: str, rng: random.Random, max_attempts: int = 8) -> MissionGraph:
    """Build a Mission Graph for a Job type, re-rolling from the same stream while too short."""
    if job_type not in JOB_GRAPH:
        raise GraphError(f"unknown job type {job_type!r}")
    cfg = JOB_GRAPH[job_type]

    for _ in range(max_attempts):
        g = MissionGraph(job_type)
        cur = g.add(ENTRY)

        for _ in range(cfg["sec_pre"]):
            cur = g.link(cur, g.add(SECURITY))

        if cfg["objectives"] == 1:
            cur = g.link(cur, g.add(OBJECTIVE))
        else:
            objs = [g.add(OBJECTIVE) for _ in range(cfg["objectives"])]
            for o in objs:
                g.link(cur, o)
            merge = g.add(SECURITY)  # the one legal diamond
            for o in objs:
                g.link(o, merge)
            cur = merge

        for _ in range(cfg["sec_post"]):
            cur = g.link(cur, g.add(SECURITY))
        g.link(cur, g.add(EXIT))

        for parent in g.pick_side_parents(rng, rng.randint(0, cfg["side_max"])):
            node = g.add(SIDE)
            g.link(parent, node)
            while rng.random() < SIDE_CHAIN_P and g.side_chain_len(node) < SIDE_CHAIN_MAX:
                node = g.link(node, g.add(SIDE))

        if g.validate():
            continue
        if g.shortest_path_len(g.single(ENTRY), g.single(EXIT)) < cfg["min_len"]:
            continue  # too short: re-roll from the same stream
        return g

    raise GraphError(f"{job_type}: no valid graph in {max_attempts} attempts")


# ======================================================================================
# Acceptance test
# ======================================================================================
def demo() -> None:
    # ---- 1. every job type builds, validates, and meets its minimum length --------------
    for job_type, cfg in JOB_GRAPH.items():
        for seed in range(40):
            g = build_graph(job_type, random.Random(seed))
            assert g.validate() == [], f"{job_type}/{seed}: {g.validate()}"
            assert g.is_dag(), "a generated graph must be acyclic"
            assert len(g.of_kind(ENTRY)) == 1 and len(g.of_kind(EXIT)) == 1
            assert 1 <= len(g.of_kind(SECURITY)) <= 3, len(g.of_kind(SECURITY))
            assert len(g.of_kind(OBJECTIVE)) == cfg["objectives"]
            assert len(g.of_kind(SIDE)) <= cfg["side_max"] * SIDE_CHAIN_MAX
            length = g.shortest_path_len(g.single(ENTRY), g.single(EXIT))
            assert length >= cfg["min_len"], f"{job_type}: main path {length} < {cfg['min_len']}"

    # ---- 2. side branches dead-end and never shorten the route --------------------------
    g = build_graph("extraction", random.Random(11))
    for s in g.of_kind(SIDE):
        assert g.nodes[s].side_marker is True
        assert len(g.nodes[s].incoming) == 1
        assert all(g.nodes[c].kind == SIDE for c in g.nodes[s].outgoing)
        assert g.side_chain_len(s) <= SIDE_CHAIN_MAX
    entry, exit_ = g.single(ENTRY), g.single(EXIT)
    main = set(g.main_path())
    assert entry in main and exit_ in main
    assert all(s not in main for s in g.of_kind(SIDE)), "a side node is not on the main path"

    # ---- 3. the two graph-wide properties hold from every entry point -------------------
    reach = g.reachable_from(entry)
    assert all(o in reach for o in g.of_kind(OBJECTIVE)), "an objective is unreachable"
    assert all(exit_ in g.reachable_from(o) for o in g.of_kind(OBJECTIVE)), "exit unreachable"

    # ---- 4. the builder refuses structurally illegal links ------------------------------
    def refuses(fn) -> bool:
        try:
            fn()
        except GraphError:
            return True
        return False

    probe = MissionGraph()
    e, s1, o1 = probe.add(ENTRY), probe.add(SECURITY), probe.add(OBJECTIVE)
    probe.link(e, s1)
    probe.link(s1, o1)
    assert refuses(lambda: probe.link(o1, e)), "entry must refuse an inbound edge"
    assert refuses(lambda: probe.link(s1, s1)), "self links are illegal"
    assert refuses(lambda: probe.link(e, s1)), "duplicate edges are illegal"
    assert refuses(lambda: probe.link(o1, o1)), "self link again, from a different node"

    # A side branch off a main-path security gate is the COMMON shape (world.md §5.6 hangs two off
    # one gate), so this must be allowed; what is illegal is a side branch off entry or exit.
    x1 = probe.add(SIDE)
    assert probe.link(s1, x1) == x1, "side branches may hang off a main-path node"
    assert refuses(lambda: probe.link(s1, x1)), "a side node has exactly one parent"
    x2 = probe.add(SIDE)
    assert refuses(lambda: probe.link(e, x2)), "a side branch may not hang off entry"

    deep = MissionGraph()
    d0, d1, d2 = deep.add(SIDE), deep.add(SIDE), deep.add(SIDE)
    h = deep.add(OBJECTIVE)
    deep.link(h, d0)
    deep.link(d0, d1)
    assert refuses(lambda: deep.link(d1, d2)), f"side chains stop at {SIDE_CHAIN_MAX}"

    x3 = probe.add(EXIT)
    assert refuses(lambda: probe.link(x3, o1)), "exit must refuse an outbound edge"

    # ---- 5. in-degree cap, and the one legal diamond ------------------------------------
    fan = MissionGraph()
    fan_in = fan.add(ENTRY)
    a1, a2 = fan.add(OBJECTIVE), fan.add(OBJECTIVE)
    fan.link(fan_in, a1)
    fan.link(fan_in, a2)
    merge = fan.add(SECURITY)
    fan.link(a1, merge)
    fan.link(a2, merge)
    third = fan.add(OBJECTIVE)
    assert refuses(lambda: fan.link(third, merge)), f"in-degree is capped at {MAX_IN_DEGREE}"

    # ---- 6. the validators can fail: corrupt a graph and watch them complain ------------
    broken = build_graph("sabotage", random.Random(5))
    an_objective = broken.of_kind(OBJECTIVE)[0]
    parent = broken.nodes[an_objective].incoming[0]
    broken.nodes[parent].outgoing.remove(an_objective)
    broken.nodes[an_objective].incoming.clear()
    problems = broken.validate()
    assert any("not reachable from entry" in p for p in problems), problems
    assert any("unreachable from entry" in p for p in problems), problems

    cyclic = MissionGraph()
    c_in, c_a, c_b = cyclic.add(ENTRY), cyclic.add(SECURITY), cyclic.add(OBJECTIVE)
    c_out = cyclic.add(EXIT)
    cyclic.link(c_in, c_a)
    cyclic.link(c_a, c_b)
    cyclic.link(c_b, c_out)
    cyclic._link_unchecked(c_out, c_a)  # bypass the builder to make a cycle
    assert not cyclic.is_dag(), "Kahn's algorithm must see the cycle"
    assert any("cycle" in p for p in cyclic.validate())

    smeared = build_graph("extraction", random.Random(3))
    side = smeared.of_kind(SIDE)[0]
    smeared._link_unchecked(side, smeared.single(EXIT))
    assert any("not a dead end" in p for p in smeared.validate()), (
        "a side->exit edge must be caught"
    )

    # ---- 7. determinism, and that the seed actually matters ----------------------------
    def shape(g: MissionGraph) -> list[tuple[int, str, tuple[int, ...]]]:
        return [(n, node.kind, tuple(node.outgoing)) for n, node in sorted(g.nodes.items())]

    assert shape(build_graph("extraction", random.Random(77))) == shape(
        build_graph("extraction", random.Random(77))
    ), "the same seed must give the same graph"
    shapes = {tuple(shape(build_graph("extraction", random.Random(s)))) for s in range(30)}
    assert len(shapes) > 1, "30 seeds produced a single graph shape: the seed is being ignored"

    # ---- 8. side parents are sampled without replacement and favour the middle ----------
    picker = MissionGraph()
    p0 = picker.add(ENTRY)
    chain = [p0]
    for _ in range(7):
        chain.append(picker.link(chain[-1], picker.add(SECURITY)))
    picker.link(chain[-1], picker.add(EXIT))
    rng = random.Random(2)
    chosen = picker.pick_side_parents(rng, 3)
    assert len(set(chosen)) == len(chosen), "side parents must be distinct"
    assert all(picker.nodes[n].kind not in (ENTRY, EXIT) for n in chosen)
    picks = [picker.pick_side_parents(random.Random(s), 1)[0] for s in range(60)]
    middle = [p for p in picks if 2 <= picker.depth()[p] <= 5]
    assert len(middle) > len(picks) * 0.6, "side parents should cluster in the middle of the path"

    print(
        f"OK  mission_graph: {len(JOB_GRAPH)} job types x 40 seeds validate, side branches "
        f"dead-end, Kahn catches injected cycles, {len(shapes)} shapes from 30 seeds"
    )


if __name__ == "__main__":
    demo()

"""Embedding: turn a Mission Graph into a walkable tile map.

ADR-0011 (objective-first: graph first, then space); the algorithm, room sizes, retry policy and
verification rules are in docs/design/world.md §6. DECISIONS §9 fixes the Site at 60x60.

    .venv/bin/python -m pinkmohawk.embed      # the acceptance test, currently red

WHY THIS IS THE HARD ONE
------------------------
docs/design/data-model.md §16 ranks this the project's number-one risk, above the Behavior Tree
ticker and shadowcasting, and the reason is that **it fails silently and visually**. A bad
embedding still passes every assert you can think of: the graph is valid, the rooms exist, the
connectivity check succeeds — and the Site reads like noise. The vault sits next to the entrance,
the exit is the first room you find, two corridors punch through the vault wall, and nothing
crashes. So build the structural asserts first (they are written below), get them green, and only
then work on how it *looks*.

WHAT IS ALREADY DONE FOR YOU
----------------------------
* `Room`, `Site`, `EmbedError` — the data contract.
* `verify(site, graph)` — the acceptance oracle, fully implemented over the finished `unionfind`
  and `pathfinding` modules. It is deliberately written independently of the generator, so it can
  disagree with it: if your embedder and this verifier disagree, one of them is wrong and the
  disagreement is the bug report. `embed()` must call it before returning a Site.
* `demo()` — the acceptance test, complete. It currently fails at the first call to `embed`.

WHAT IS YOURS
-------------
Five functions, in dependency order:

| Function | What it must do |
|---|---|
| `bsp_leaves` | recursively split the grid into exactly `count` rectangles, splitting the longer axis, never below `MIN_LEAF_EDGE` on either side |
| `place_rooms` | one room per leaf, sized from `ROOM_INTERIOR`/`OBJECTIVE_INTERIOR` by node type, positioned with at least `WALL_MARGIN` of wall, **never overlapping another room** |
| `carve_corridor` | an L-corridor, 1 cell wide, between two rooms, plus a doorway cell in each room's wall — H-then-V or V-then-H by a coin flip |
| `embed` | orchestrate: split, order leaves by graph depth, place, carve one corridor per graph edge, verify, and **retry on a fresh derived stream**, falling back to the spine after `MAX_EMBED_ATTEMPTS` |
| `spine_layout` | the guaranteed fallback: rooms left-to-right in depth order at fixed y, straight horizontal corridors. Cannot fail verification by construction |

THE PART THAT IS ACTUALLY DESIGN
--------------------------------
Step 2 of §6.2 is the reason a Site reads as a proposition rather than a scatter: **order the leaves
along the graph's depth ordering and walk them in a serpentine, so nodes that are close in the
graph are close on the Site.** Get that wrong and you get a legally correct maze. `main_path()` and
`depth()` on `MissionGraph` are there to help; `pick_side_parents` already biases side branches to
the middle of the path, so the leaf order should put side leaves *off* the spine, not on it.

Determinism: attempt `i` draws from `random.Random(derive(run_seed, f"gen.embed:{i}"))`, never from
a shared stream. A failed attempt must be discarded whole — reusing rooms or corridors from a failed
attempt is how one bad layout leaks into the next.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from .constants import SITE_H, SITE_W, TILE_FLOOR, TILE_WALL
from .grid import TileMap
from .mission_graph import ENTRY, EXIT, OBJECTIVE, SECURITY, SIDE, MissionGraph
from .pathfinding import a_star
from .rng import derive
from .unionfind import DisjointSet

Coord = tuple[int, int]

# --- generator parameters (docs/design/world.md §6) ------------------------------------------
MAX_EMBED_ATTEMPTS: Final = 8       # [P16]
MIN_LEAF_EDGE: Final = 8            # §6.2 step 1
WALL_MARGIN: Final = 1              # §6.2 step 3
CORRIDOR_WIDTH: Final = 1           # DEC §10
JUNCTION: Final = 3                 # §6.1: 3x3 where corridors meet
# [P13] has no numeric value in DECISIONS or world.md; 12 is proposed here and should move into the
# contract once the first playable Site shows whether 12 is actually far enough apart.
MIN_OBJECTIVE_DISTANCE: Final = 12

# --- room interiors, walls excluded (world.md §6.1) ------------------------------------------
ROOM_INTERIOR: Final = {
    ENTRY: (10, 8),
    EXIT: (10, 8),
    SECURITY: (8, 6),
    SIDE: (6, 5),
}
OBJECTIVE_INTERIOR: Final = {
    "extraction": (14, 10),
    "sabotage": (10, 8),
    "protection": (12, 10),
    "courier": (6, 5),
}


class EmbedError(RuntimeError):
    """Embedding failed. A Site that would fail verification is never handed to the player."""


@dataclass(frozen=True)
class Room:
    """One room, in map coordinates, interior only (the wall ring is not part of w/h)."""

    node_id: int
    kind: str
    x: int
    y: int
    w: int
    h: int

    @property
    def center(self) -> Coord:
        return (self.x + self.w // 2, self.y + self.h // 2)

    @property
    def cells(self) -> list[Coord]:
        return [(self.x + i, self.y + j) for j in range(self.h) for i in range(self.w)]

    def contains(self, x: int, y: int) -> bool:
        return self.x <= x < self.x + self.w and self.y <= y < self.y + self.h

    def intersects(self, other: Room) -> bool:
        return not (self.x + self.w <= other.x or other.x + other.w <= self.x
                    or self.y + self.h <= other.y or other.y + other.h <= self.y)


@dataclass
class Site:
    """A generated, verified Site. `rooms` is keyed by Mission Graph node id."""

    map: TileMap
    rooms: dict[int, Room]
    spawn: Coord
    exit_cell: Coord
    attempts: int = 1               # which attempt succeeded; >1 means retries happened
    used_fallback: bool = False     # True when the spine layout was used (a bug report, not a win)
    carved: set[Coord] = field(default_factory=set)   # cells the generator carved

    def room_of(self, node_id: int) -> Room:
        return self.rooms[node_id]


# ======================================================================================
# YOURS: the generator
# ======================================================================================
def bsp_leaves(width: int, height: int, count: int, rng) -> list[tuple[int, int, int, int]]:
    """Split (0, 0, width, height) into exactly `count` rectangles: (x, y, w, h).

    Recursive BSP: split the longer axis, at least `MIN_LEAF_EDGE` on both sides of the cut, until
    the leaf count is reached. Return the leaves in the order you want step 2 to walk them (the
    embedder re-orders by graph depth, so any deterministic order is acceptable here).
    """
    raise NotImplementedError("implement bsp_leaves() — see the module docstring")


def place_rooms(graph: MissionGraph, leaves: list[tuple[int, int, int, int]],
                rng, width: int = SITE_W, height: int = SITE_H) -> dict[int, Room]:
    """One room per Mission Graph node, inside its leaf, sized by node type, never overlapping.

    `objective` sizes come from OBJECTIVE_INTERIOR[graph.job_type]. Nodes must be assigned to leaves
    in graph-depth order (world.md §6.2 step 2) so graph-adjacent nodes are spatially adjacent.
    """
    raise NotImplementedError("implement place_rooms() — see the module docstring")


def carve_corridor(site: Site, a: Room, b: Room, rng) -> set[Coord]:
    """Carve a 1-wide L-corridor between two room centres and open a doorway in each room's wall.

    Returns the cells carved. Overlapping corridors are absorbed, never widened.
    """
    raise NotImplementedError("implement carve_corridor() — see the module docstring")


def embed(graph: MissionGraph, run_seed: int, *, width: int = SITE_W, height: int = SITE_H,
          max_attempts: int = MAX_EMBED_ATTEMPTS) -> Site:
    """Build a verified Site, or raise EmbedError.

    Attempt `i` draws from `random.Random(derive(run_seed, f"gen.embed:{i}"))`. A failed attempt is
    discarded whole. After `max_attempts` failures, return `spine_layout(...)` with
    `used_fallback=True` — the fallback is a bug report, not a design outcome.
    """
    raise NotImplementedError("implement embed() — see the module docstring")


def spine_layout(graph: MissionGraph, width: int = SITE_W,
                 height: int = SITE_H) -> Site:
    """The fallback: rooms left-to-right in graph depth order at fixed y, straight corridors.

    Guaranteed connected by construction, and therefore cannot fail verification.
    """
    raise NotImplementedError("implement spine_layout() — see the module docstring")


# ======================================================================================
# MINE: the acceptance oracle. Independent of the generator on purpose.
# ======================================================================================
def verify(site: Site, graph: MissionGraph) -> list[str]:
    """Every world.md §6.3 rule plus the structural invariants. Empty list == valid."""
    bad: list[str] = []
    rooms = site.rooms
    m = site.map

    # --- rooms exist for every node, exactly one each, sized by type ----------------------
    for nid, node in graph.nodes.items():
        if nid not in rooms:
            bad.append(f"node {nid} ({node.kind}) has no room")
            continue
        room = rooms[nid]
        want = (OBJECTIVE_INTERIOR.get(graph.job_type or "", (10, 8)) if node.kind == OBJECTIVE
                else ROOM_INTERIOR.get(node.kind))
        if want and (room.w, room.h) != want:
            bad.append(f"node {nid} ({node.kind}) room is {room.w}x{room.h}, expected {want}")
        if len(room.cells) != room.w * room.h:
            bad.append(f"node {nid} room cell count mismatch")

    if len(rooms) != len(graph.nodes):
        bad.append(f"{len(rooms)} rooms for {len(graph.nodes)} nodes")

    # --- rooms are inside the map with a wall ring, and never overlap ---------------------
    ids = sorted(rooms)
    for nid in ids:
        r = rooms[nid]
        if r.x < WALL_MARGIN or r.y < WALL_MARGIN \
                or r.x + r.w > m.w - WALL_MARGIN or r.y + r.h > m.h - WALL_MARGIN:
            bad.append(f"node {nid} room {r} pokes out of the map or its wall margin")
        for (x, y) in r.cells:
            if m.is_wall(x, y):
                bad.append(f"node {nid} room interior includes wall cell {(x, y)}")
                break
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if rooms[a].intersects(rooms[b]):
                bad.append(f"rooms {a} and {b} overlap: {rooms[a]} vs {rooms[b]}")

    # --- spawn and exit are inside their rooms -------------------------------------------
    if not rooms:
        return bad or ["no rooms at all"]
    entry_id, exit_id = graph.single(ENTRY), graph.single(EXIT)
    if not rooms[entry_id].contains(*site.spawn):
        bad.append(f"spawn {site.spawn} is not inside the entry room {rooms[entry_id]}")
    if not rooms[exit_id].contains(*site.exit_cell):
        bad.append(f"exit cell {site.exit_cell} is not inside the exit room {rooms[exit_id]}")

    # --- one corridor per graph edge, and it is reasonably direct ------------------------
    for parent, child in graph.edges():
        if parent not in rooms or child not in rooms:
            continue
        c1, c2 = rooms[parent].center, rooms[child].center
        path = a_star(m, c1, c2)
        if path is None:
            bad.append(f"no corridor between nodes {parent} and {child}")
            continue
        manhattan = abs(c1[0] - c2[0]) + abs(c1[1] - c2[1])
        if len(path) - 1 > manhattan + 2 * (WALL_MARGIN + 1) + 2:
            bad.append(f"corridor {parent}->{child} wanders: {len(path) - 1} steps for "
                       f"manhattan {manhattan}")

    # --- connectivity, verified two ways because they fail differently --------------------
    # union-find answers "one component"; A* answers "there is a walkable path" (a corridor can be
    # carved and then blocked by a later room's wall). world.md §6.3 runs both.
    index = {nid: i for i, nid in enumerate(ids)}
    uf = DisjointSet(len(ids))
    for parent, child in graph.edges():
        if parent in index and child in index:
            if a_star(m, rooms[parent].center, rooms[child].center) is not None:
                uf.union(index[parent], index[child])
    root = uf.find(index[entry_id])
    for nid in ids:
        if uf.find(index[nid]) != root:
            bad.append(f"room {nid} is in a different component from the entry")

    reach = {site.spawn}
    if a_star(m, site.spawn, site.exit_cell) is None:
        bad.append("entry -> exit is not walkable as a tile path")
    for nid in ids:
        if a_star(m, site.spawn, rooms[nid].center) is None:
            bad.append(f"node {nid} room is unreachable from the spawn")

    # --- the named failure mode: the vault must not sit next to the entrance --------------
    objectives = graph.of_kind(OBJECTIVE)
    if objectives:
        nearest = min(abs(rooms[o].center[0] - rooms[entry_id].center[0])
                      + abs(rooms[o].center[1] - rooms[entry_id].center[1]) for o in objectives)
        if nearest < MIN_OBJECTIVE_DISTANCE:
            bad.append(f"nearest objective is {nearest} from the entry, "
                       f"minimum is {MIN_OBJECTIVE_DISTANCE}")

    return bad


# ======================================================================================
# Acceptance test
# ======================================================================================
def demo() -> None:
    import random

    from .mission_graph import JOB_GRAPH, build_graph

    def build(job_type: str, run_seed: int):
        g = build_graph(job_type, random.Random(run_seed))
        return g, embed(g, run_seed)

    # ---- 1. every job type embeds and verifies, across seeds ----------------------------
    sites: dict[int, Site] = {}
    for job_type in JOB_GRAPH:
        for seed in range(12):
            g, site = build(job_type, seed)
            problems = verify(site, g)
            assert problems == [], f"{job_type}/{seed}: {problems}"
            assert not site.used_fallback, f"{job_type}/{seed} fell back to the spine layout"
            sites[seed] = site

    # ---- 2. rooms: one per node, right sizes, inside the map, never overlapping ----------
    g, site = build("extraction", 3)
    assert len(site.rooms) == len(g.nodes)
    assert set(site.rooms) == set(g.nodes)
    for nid, room in site.rooms.items():
        assert room.x >= WALL_MARGIN and room.y >= WALL_MARGIN
        assert room.x + room.w <= site.map.w - WALL_MARGIN
        assert room.y + room.h <= site.map.h - WALL_MARGIN
        assert all(not site.map.is_wall(x, y) for x, y in room.cells)
    ids = sorted(site.rooms)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            assert not site.rooms[a].intersects(site.rooms[b]), f"rooms {a}/{b} overlap"
    assert site.rooms[g.single(ENTRY)].w == 10, "entry rooms are 10 wide"
    assert site.rooms[g.single(EXIT)].w == 10
    assert site.rooms[g.of_kind(OBJECTIVE)[0]].w == 14, "the extraction vault is the largest room"

    # ---- 3. every room is walkable from the spawn, and the corridors are direct ----------
    for nid, room in site.rooms.items():
        assert a_star(site.map, site.spawn, room.center) is not None, f"room {nid} unreachable"
    for parent, child in g.edges():
        c1, c2 = site.rooms[parent].center, site.rooms[child].center
        manhattan = abs(c1[0] - c2[0]) + abs(c1[1] - c2[1])
        path = a_star(site.map, c1, c2)
        assert path is not None and len(path) - 1 <= manhattan + 4, \
            f"corridor {parent}->{child} wanders ({len(path) - 1} steps vs {manhattan})"

    # ---- 4. the vault is not next to the entrance (ADR-0011's named failure) ------------
    entry_c = site.rooms[g.single(ENTRY)].center
    for o in g.of_kind(OBJECTIVE):
        d = abs(site.rooms[o].center[0] - entry_c[0]) + abs(site.rooms[o].center[1] - entry_c[1])
        assert d >= MIN_OBJECTIVE_DISTANCE, f"objective is only {d} from the entry"

    # ---- 5. determinism, and that the seed actually changes the Site --------------------
    _, again = build("extraction", 3)
    assert bytes(again.map.tiles) == bytes(site.map.tiles), "the same seed must give the same Site"
    assert again.rooms == site.rooms
    layouts = set()
    for seed in range(20):
        _, s = build("extraction", seed)
        layouts.add((bytes(s.map.tiles), tuple(sorted((n, r.x, r.y) for n, r in s.rooms.items()))))
    assert len(layouts) > 1, "20 seeds produced one identical Site: the seed is being ignored"

    # ---- 6. the generator refuses impossible geometry instead of returning junk ---------
    g_small = build_graph("courier", random.Random(1))
    try:
        embed(g_small, 5, width=12, height=12, max_attempts=2)
    except EmbedError:
        pass
    else:
        raise AssertionError("a 12x12 map cannot hold 5 rooms and must raise EmbedError")

    # ---- 7. the fallback path verifies, and is flagged -----------------------------------
    fallback = spine_layout(g)
    assert verify(fallback, g) == [], f"the spine layout must verify: {verify(fallback, g)}"
    assert fallback.used_fallback is True, "the fallback must be flagged, never passed off as normal"

    # ---- 8. the Oracle can fail: break a Site and watch verify() complain ---------------
    def clone(s: Site) -> Site:
        m = TileMap(s.map.w, s.map.h)
        m.tiles[:] = bytes(s.map.tiles)
        return Site(m, dict(s.rooms), s.spawn, s.exit_cell, s.attempts, s.used_fallback, set(s.carved))

    # (a) wall off a corridor -> connectivity must fail, both ways
    broken = clone(site)
    victim_parent, victim_child = g.edges()[1]
    c1, c2 = broken.rooms[victim_parent].center, broken.rooms[victim_child].center
    path = a_star(broken.map, c1, c2)
    assert path, "sanity: the corridor exists before we break it"
    for (x, y) in path[len(path) // 2:len(path) // 2 + CORRIDOR_WIDTH + 2]:
        broken.map.tiles[broken.map.idx(x, y)] = TILE_WALL
    problems = verify(broken, g)
    assert any("no corridor" in p or "different component" in p or "unreachable" in p
               for p in problems), f"sealing a corridor must be caught: {problems}"

    # (b) overlap two rooms -> the overlap rule must fire
    shoved = clone(site)
    ids2 = sorted(shoved.rooms)
    a_room, b_room = shoved.rooms[ids2[0]], shoved.rooms[ids2[1]]
    moved = Room(b_room.node_id, b_room.kind, a_room.x, a_room.y, b_room.w, b_room.h)
    shoved.rooms[b_room.node_id] = moved
    for (x, y) in moved.cells:
        shoved.map.tiles[shoved.map.idx(x, y)] = TILE_FLOOR
    assert any("overlap" in p for p in verify(shoved, g)), "overlapping rooms must be caught"

    # (c) wrong room size -> the sizing rule must fire
    resized = clone(site)
    r0 = resized.rooms[ids2[0]]
    resized.rooms[ids2[0]] = Room(r0.node_id, r0.kind, r0.x, r0.y, r0.w + 2, r0.h)
    for (x, y) in resized.rooms[ids2[0]].cells:
        if resized.map.in_bounds(x, y):
            resized.map.tiles[resized.map.idx(x, y)] = TILE_FLOOR
    assert verify(resized, g), "a room that is the wrong size must be caught"

    print(f"OK  embed: {len(JOB_GRAPH)} job types x 12 seeds verify, retry raises on impossible "
          f"geometry, spine fallback verifies, oracle catches sealed corridors, overlaps and sizing")


if __name__ == "__main__":
    demo()

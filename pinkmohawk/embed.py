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
| `bsp_leaves` | size-aware BSP: one leaf per room, cutting so each subtree can host the rooms it holds, returning leaves in room order |
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

import random

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
MAX_EMBED_ATTEMPTS: Final = 8  # [P16]
CANDIDATE_LIMIT: Final = 16  # bounds the cut search so backtracking cannot blow up
MIN_LEAF_EDGE: Final = 8  # §6.2 step 1
WALL_MARGIN: Final = 1  # §6.2 step 3
CORRIDOR_WIDTH: Final = 1  # DEC §10
JUNCTION: Final = 3  # §6.1: 3x3 where corridors meet
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
        return not (
            self.x + self.w <= other.x
            or other.x + other.w <= self.x
            or self.y + self.h <= other.y
            or other.y + other.h <= self.y
        )


@dataclass
class Site:
    """A generated, verified Site. `rooms` is keyed by Mission Graph node id."""

    map: TileMap
    rooms: dict[int, Room]
    spawn: Coord
    exit_cell: Coord
    attempts: int = 1  # which attempt succeeded; >1 means retries happened
    used_fallback: bool = (
        False  # True when the spine layout was used (a bug report, not a win)
    )
    carved: set[Coord] = field(default_factory=set)  # cells the generator carved

    def room_of(self, node_id: int) -> Room:
        return self.rooms[node_id]


def _room_size(graph: MissionGraph, kind: str) -> tuple[int, int]:
    """The vault's size depends on the Job, not just the node kind: a courier drop is a doorway."""
    if kind == OBJECTIVE:
        return OBJECTIVE_INTERIOR.get(graph.job_type or "", (10, 8))
    return ROOM_INTERIOR[kind]


def _ordered_nodes(graph: MissionGraph) -> list[int]:
    """Entry first, exit last, side nodes beside their parent (depth = parent + 1)."""
    depths = graph.depth()
    return sorted(graph.nodes, key=lambda n: (depths[n], n))


def _ordered_sizes(graph: MissionGraph) -> list[tuple[int, int]]:
    return [_room_size(graph, graph.nodes[n].kind) for n in _ordered_nodes(graph)]


def _feasible(sizes: list[tuple[int, int]], w: int, h: int) -> bool:
    """
    Necessary conditions for a subtree rect to host these rooms somewhere inside it.

    Deliberately cheap and conservative: a room wider than the rect can never fit in any descendant,
    and the rooms plus their margins need the area.
    It prunes the cut search; the recursion decides the rest.
    """
    if not sizes:
        return True
    if max(s[0] for s in sizes) + 2 * WALL_MARGIN > w:
        return False
    if max(s[1] for s in sizes) + 2 * WALL_MARGIN > h:
        return False
    needed = sum((s[0] + 2 * WALL_MARGIN) * (s[1] + 2 * WALL_MARGIN) for s in sizes)
    return needed <= w * h


def _carve_interiors(site: Site) -> None:
    """A fresh TileMap is ALL WALL, so rooms to be dug out before anything can walk in them."""
    for room in site.rooms.values():
        for x, y in room.cells:
            site.map.tiles[site.map.idx(x, y)] = TILE_FLOOR


def _finish(
    graph: MissionGraph,
    rooms: dict[int, Room],
    width: int,
    height: int,
    rng,
    attempts: int,
    used_fallback: bool,
) -> Site:
    site = Site(
        TileMap(width, height),
        rooms,
        (0, 0),
        (0, 0),
        attempts=attempts,
        used_fallback=used_fallback,
    )
    _carve_interiors(site)
    for parent, child in graph.edges():
        carve_corridor(site, rooms[parent], rooms[child], rng)
    site.spawn = rooms[graph.single(ENTRY)].center
    site.exit_cell = rooms[graph.single(EXIT)].center
    return site


def _split(x: int, y: int, w: int, h: int, sizes: list[tuple[int, int]], rng):
    """
    Size-aware BSP. Returns a leaf per room, IN ROOM ORDER, or None if this rect cannot host them.

    Splitting the ordered list in half and rectangle to match is what keeps the graph's order spatial:
    leaves come back in the same sequence as `sizes`, so node i+1 is always in a leaf near node i.
    That is the whole trick - a count-based splitter has no idea that the vault needs 16x12.
    """
    if len(sizes) == 1:
        return [(x, y, w, h)] if _feasible(sizes, w, h) else None

    k = len(sizes) // 2
    left, right = sizes[:k], sizes[k:]
    axes = ("h", "v") if w >= h else ("v", "h")  # try the longer side first

    for axis in axes:
        span = w if axis == "h" else h
        if span < 2 * MIN_LEAF_EDGE:
            continue
        cuts = list(range(MIN_LEAF_EDGE, span - MIN_LEAF_EDGE + 1))
        # Near-balanced cuts first, with a little jitter so layouts vary: a balanced split keeps
        # leaves squarish, which keeps rooms off the map edge.
        cuts.sort(key=lambda c: abs(c - span / 2) + rng.random() * 4)
        for cut in cuts[:CANDIDATE_LIMIT]:
            if axis == "h":
                if not (_feasible(left, cut, h) and _feasible(right, w - cut, h)):
                    continue
                a = _split(x, y, cut, h, left, rng)
                b = _split(x + cut, y, w - cut, h, right, rng)
            else:
                if not (_feasible(left, w, cut) and _feasible(right, w, h - cut)):
                    continue
                a = _split(x, y, w, cut, left, rng)
                b = _split(x, y + cut, w, h - cut, right, rng)
            if a is not None and b is not None:
                return a + b
    return None


# ======================================================================================
# YOURS: the generator
# ======================================================================================
def bsp_leaves(width: int, height: int, sizes, rng):
    """One leaf per room, in room order, or None when the map cannot host them."""
    return _split(0, 0, width, height, list(sizes), rng)


def place_rooms(
    graph: MissionGraph, leaves, rng, width: int = SITE_W, height: int = SITE_H
) -> dict[int, Room]:
    nodes = _ordered_nodes(graph)
    if len(leaves) != len(nodes):
        raise EmbedError(f"{len(leaves)} leaves for {len(nodes)} nodes")
    rooms: dict[int, Room] = {}
    for nid, (lx, ly, lw, lh) in zip(nodes, leaves):
        rw, rh = _room_size(graph, graph.nodes[nid].kind)
        if rw + 2 * WALL_MARGIN > lw or rh + 2 * WALL_MARGIN > lh:
            raise EmbedError(f"node {nid} needs {rw}x{rh}, leaf is {lw}x{lh}")
        # Random position inside the leaf, never touching the leaf's own edge.
        # Rooms living in disjoint leaves with a margin each is why overlap is impossible rather than merely checked
        # for: partition does the work
        x = lx + rng.randint(WALL_MARGIN, lw - rw - WALL_MARGIN)
        y = ly + rng.randint(WALL_MARGIN, lh - rh - WALL_MARGIN)
        rooms[nid] = Room(nid, graph.nodes[nid].kind, x, y, rw, rh)
    return rooms


def carve_corridor(site: Site, a: Room, b: Room, rng) -> set[tuple[int, int]]:
    """Carve a 1-wide L-corridor between two room centres and open a doorway in each room's wall.

    Returns the cells carved. Overlapping corridors are absorbed, never widened.
    """
    (ax, ay), (bx, by) = a.center, b.center
    cells: set[tuple[int, int]] = set()
    if rng.random() < 0.5:
        cells |= {(x, ay) for x in range(min(ax, bx), max(ax, bx) + 1)}  # H then V
        cells |= {(bx, y) for y in range(min(ay, by), max(ay, by) + 1)}
    else:
        cells |= {(ax, y) for y in range(min(ay, by), max(ay, by) + 1)}  # V then H
        cells |= {(x, by) for x in range(min(ax, bx), max(ax, bx) + 1)}
    for x, y in cells:
        if site.map.in_bounds(x, y):
            # 1 cell wide, and an overlap is simply abosrbed - never widened. Carving centre to
            # centre is also what punches each room's doorway: the L has to cross both wall rings
            # to get out of one room and into another
            site.map.tiles[site.map.idx(x, y)] = TILE_FLOOR
    site.carved |= cells
    return cells


def embed(
    graph: MissionGraph,
    run_seed: int,
    *,
    width: int = SITE_W,
    height: int = SITE_H,
    max_attempts: int = MAX_EMBED_ATTEMPTS,
) -> Site:
    """Build a verified Site, or raise EmbedError.

    Attempt `i` draws from `random.Random(derive(run_seed, f"gen.embed:{i}"))`. A failed attempt is
    discarded whole. After `max_attempts` failures, return `spine_layout(...)` with
    `used_fallback=True` — the fallback is a bug report, not a design outcome.
    """
    sizes = _ordered_sizes(graph)
    for attempt in range(max_attempts):
        # One derived stream per attempt: a retry is a different deterministic layout
        # The whole sequence stays reproducible from the stored run_seed. never one RNG shared across attempts
        rng = random.Random(derive(run_seed, f"gen.embed:{attempt}"))
        leaves = bsp_leaves(width, height, sizes, rng)
        if leaves is None:
            continue
        try:
            rooms = place_rooms(graph, leaves, rng, width, height)
        except EmbedError:
            continue
        site = _finish(graph, rooms, width, height, rng, attempt + 1, False)
        if not verify(site, graph):
            return site
    # Fallback. Flagged, because a fallback that fires is a bug report, not a design outcome.
    site = spine_layout(graph, width, height)  # may raise on impossible geometry
    site.used_fallback = True
    return site


def spine_layout(
    graph: MissionGraph, width: int = SITE_W, height: int = SITE_H
) -> Site:
    """The fallback: rooms left-to-right in graph depth order at fixed y, straight corridors.

    Guaranteed connected by construction, and therefore cannot fail verification.
    """
    rng = random.Random(0)
    ordered = _ordered_nodes(graph)
    # Objectives go ON the spine, never in the side column. A Job with two objectives (sabotage)
    # routes main_path() through only one of them; the other woudl land beside the entry in the side
    # column, ~11 cells way horizontally, and break MIN_OBJECTIVE_DISTANCE.  Stacking every
    # non-side node in the depth order puts each objective at least two rooms below the entry, which
    # clears the rule by a wide margin
    spine = [n for n in ordered if graph.nodes[n].kind != SIDE]
    side = [n for n in ordered if graph.nodes[n].kind == SIDE]

    rooms: dict[int, Room] = {}
    # Vertical, not horizontal: the main path's rooms are wider than 60 once five separating walls
    # are added, but their stacked hights fit.
    cursor = WALL_MARGIN
    for nid in spine:
        rw, rh = _room_size(graph, graph.nodes[nid].kind)
        if cursor + rh > height - WALL_MARGIN:
            raise EmbedError(f"spine layout does not fit: node {nid} at y={cursor}")
        rooms[nid] = Room(nid, graph.nodes[nid].kind, WALL_MARGIN, cursor, rw, rh)
        cursor += rh + 1

    # Side rooms in a second column, still beside their parent, so each correidor stays a short
    # direct L. Nothing measured by verify() lives in this column.
    right_x = (
        WALL_MARGIN + max(_room_size(graph, graph.nodes[n].kind)[0] for n in spine) + 1
    )
    cursor = WALL_MARGIN
    for nid in side:
        rw, rh = _room_size(graph, graph.nodes[nid].kind)
        if right_x + rw > width - WALL_MARGIN or cursor + rh > height - WALL_MARGIN:
            raise EmbedError(f"spine layout does not fit: node {nid} at y={cursor}")
        rooms[nid] = Room(nid, graph.nodes[nid].kind, right_x, cursor, rw, rh)
        cursor += rh + 1

    site = _finish(graph, rooms, width, height, rng, 0, True)
    problems = verify(site, graph)
    if problems:
        # "Cannot fail" applies to connectivity, not to impossible geometry or the spacing rule.
        raise EmbedError(f"spine layout failed verification: {problems[:3]}")
    return site

    # Side


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
        want = (
            OBJECTIVE_INTERIOR.get(graph.job_type or "", (10, 8))
            if node.kind == OBJECTIVE
            else ROOM_INTERIOR.get(node.kind)
        )
        if want and (room.w, room.h) != want:
            bad.append(
                f"node {nid} ({node.kind}) room is {room.w}x{room.h}, expected {want}"
            )
        if len(room.cells) != room.w * room.h:
            bad.append(f"node {nid} room cell count mismatch")

    if len(rooms) != len(graph.nodes):
        bad.append(f"{len(rooms)} rooms for {len(graph.nodes)} nodes")

    # --- rooms are inside the map with a wall ring, and never overlap ---------------------
    ids = sorted(rooms)
    for nid in ids:
        r = rooms[nid]
        if (
            r.x < WALL_MARGIN
            or r.y < WALL_MARGIN
            or r.x + r.w > m.w - WALL_MARGIN
            or r.y + r.h > m.h - WALL_MARGIN
        ):
            bad.append(f"node {nid} room {r} pokes out of the map or its wall margin")
        for x, y in r.cells:
            if m.is_wall(x, y):
                bad.append(f"node {nid} room interior includes wall cell {(x, y)}")
                break
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            if rooms[a].intersects(rooms[b]):
                bad.append(f"rooms {a} and {b} overlap: {rooms[a]} vs {rooms[b]}")

    # --- spawn and exit are inside their rooms -------------------------------------------
    if not rooms:
        return bad or ["no rooms at all"]
    entry_id, exit_id = graph.single(ENTRY), graph.single(EXIT)
    if not rooms[entry_id].contains(*site.spawn):
        bad.append(f"spawn {site.spawn} is not inside the entry room {rooms[entry_id]}")
    if not rooms[exit_id].contains(*site.exit_cell):
        bad.append(
            f"exit cell {site.exit_cell} is not inside the exit room {rooms[exit_id]}"
        )

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
            bad.append(
                f"corridor {parent}->{child} wanders: {len(path) - 1} steps for "
                f"manhattan {manhattan}"
            )

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
        nearest = min(
            abs(rooms[o].center[0] - rooms[entry_id].center[0])
            + abs(rooms[o].center[1] - rooms[entry_id].center[1])
            for o in objectives
        )
        if nearest < MIN_OBJECTIVE_DISTANCE:
            bad.append(
                f"nearest objective is {nearest} from the entry, "
                f"minimum is {MIN_OBJECTIVE_DISTANCE}"
            )

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
            assert (
                not site.used_fallback
            ), f"{job_type}/{seed} fell back to the spine layout"
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
        for b in ids[i + 1 :]:
            assert not site.rooms[a].intersects(site.rooms[b]), f"rooms {a}/{b} overlap"
    assert site.rooms[g.single(ENTRY)].w == 10, "entry rooms are 10 wide"
    assert site.rooms[g.single(EXIT)].w == 10
    assert (
        site.rooms[g.of_kind(OBJECTIVE)[0]].w == 14
    ), "the extraction vault is the largest room"

    # ---- 3. every room is walkable from the spawn, and the corridors are direct ----------
    for nid, room in site.rooms.items():
        assert (
            a_star(site.map, site.spawn, room.center) is not None
        ), f"room {nid} unreachable"
    for parent, child in g.edges():
        c1, c2 = site.rooms[parent].center, site.rooms[child].center
        manhattan = abs(c1[0] - c2[0]) + abs(c1[1] - c2[1])
        path = a_star(site.map, c1, c2)
        assert (
            path is not None and len(path) - 1 <= manhattan + 4
        ), f"corridor {parent}->{child} wanders ({len(path) - 1} steps vs {manhattan})"

    # ---- 4. the vault is not next to the entrance (ADR-0011's named failure) ------------
    entry_c = site.rooms[g.single(ENTRY)].center
    for o in g.of_kind(OBJECTIVE):
        d = abs(site.rooms[o].center[0] - entry_c[0]) + abs(
            site.rooms[o].center[1] - entry_c[1]
        )
        assert d >= MIN_OBJECTIVE_DISTANCE, f"objective is only {d} from the entry"

    # ---- 5. determinism, and that the seed actually changes the Site --------------------
    _, again = build("extraction", 3)
    assert bytes(again.map.tiles) == bytes(
        site.map.tiles
    ), "the same seed must give the same Site"
    assert again.rooms == site.rooms
    layouts = set()
    for seed in range(20):
        _, s = build("extraction", seed)
        layouts.add(
            (
                bytes(s.map.tiles),
                tuple(sorted((n, r.x, r.y) for n, r in s.rooms.items())),
            )
        )
    assert (
        len(layouts) > 1
    ), "20 seeds produced one identical Site: the seed is being ignored"

    # ---- 6. the generator refuses impossible geometry instead of returning junk ---------
    g_small = build_graph("courier", random.Random(1))
    try:
        embed(g_small, 5, width=12, height=12, max_attempts=2)
    except EmbedError:
        pass
    else:
        raise AssertionError(
            "a 12x12 map cannot hold 5 rooms and must raise EmbedError"
        )

    # ---- 7. the fallback verifies for EVERY graph, not just the one above ---------------
    # Seeding this with one graph hid a real bug: sabotage has two objectives, main_path() routes
    # through only one, and the other landed beside the entry breaking MIN_OBJECTIVE_DISTANCE.
    for job_type in JOB_GRAPH:
        for seed in range(12):
            fb_graph = build_graph(job_type, random.Random(seed))
            fb = spine_layout(fb_graph)
            assert fb.used_fallback is True, "the fallback must be flagged"
            fb_problems = verify(fb, fb_graph)
            assert fb_problems == [], f"{job_type}/{seed} spine layout: {fb_problems}"
    fallback = spine_layout(g)
    assert (
        verify(fallback, g) == []
    ), f"the spine layout must verify: {verify(fallback, g)}"
    assert (
        fallback.used_fallback is True
    ), "the fallback must be flagged, never passed off as normal"

    # ---- 8. the Oracle can fail: break a Site and watch verify() complain ---------------
    def clone(s: Site) -> Site:
        m = TileMap(s.map.w, s.map.h)
        m.tiles[:] = bytes(s.map.tiles)
        return Site(
            m,
            dict(s.rooms),
            s.spawn,
            s.exit_cell,
            s.attempts,
            s.used_fallback,
            set(s.carved),
        )

    # (a) seal the entry room entirely -> connectivity must fail, whatever alternate routes exist
    broken = clone(site)
    entry_room = broken.rooms[g.single(ENTRY)]
    ring = [
        (x, y)
        for y in range(entry_room.y - 1, entry_room.y + entry_room.h + 1)
        for x in range(entry_room.x - 1, entry_room.x + entry_room.w + 1)
        if not entry_room.contains(x, y)
    ]
    for x, y in ring:
        if broken.map.in_bounds(x, y):
            broken.map.tiles[broken.map.idx(x, y)] = TILE_WALL
    problems = verify(broken, g)
    # Sealing five cells of one corridor is NOT enough: with ten rooms the corridor network has
    # alternate routes, so the Site stays connected and the test passes for the wrong reason. The
    # ring seals every way in at once. (Found by running it.)
    assert any(
        "different component" in p or "unreachable" in p or "not walkable" in p
        for p in problems
    ), f"sealing the entry room must be caught: {problems}"

    # (b) overlap two rooms -> the overlap rule must fire
    shoved = clone(site)
    ids2 = sorted(shoved.rooms)
    a_room, b_room = shoved.rooms[ids2[0]], shoved.rooms[ids2[1]]
    moved = Room(b_room.node_id, b_room.kind, a_room.x, a_room.y, b_room.w, b_room.h)
    shoved.rooms[b_room.node_id] = moved
    for x, y in moved.cells:
        shoved.map.tiles[shoved.map.idx(x, y)] = TILE_FLOOR
    assert any(
        "overlap" in p for p in verify(shoved, g)
    ), "overlapping rooms must be caught"

    # (c) wrong room size -> the sizing rule must fire
    resized = clone(site)
    r0 = resized.rooms[ids2[0]]
    resized.rooms[ids2[0]] = Room(r0.node_id, r0.kind, r0.x, r0.y, r0.w + 2, r0.h)
    for x, y in resized.rooms[ids2[0]].cells:
        if resized.map.in_bounds(x, y):
            resized.map.tiles[resized.map.idx(x, y)] = TILE_FLOOR
    assert verify(resized, g), "a room that is the wrong size must be caught"

    print(
        f"OK  embed: {len(JOB_GRAPH)} job types x 12 seeds verify, retry raises on impossible "
        f"geometry, spine fallback verifies, oracle catches sealed corridors, overlaps and sizing"
    )


if __name__ == "__main__":
    demo()

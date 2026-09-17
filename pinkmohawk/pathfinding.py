"""Pathfinding: A* over 8-connected uniform-cost ground, plus BFS flow maps.

DECISIONS §13 rows 3 and 4; rationale and complexity in docs/design/data-model.md §3, §4.

THIS FILE IS A STUB. `chebyshev` is done; the four functions below it raise NotImplementedError.
`demo()` is complete and is your acceptance test — it currently fails at the first call, which is
the point: the checks exist before the implementation does.

    .venv/bin/python -m pinkmohawk.pathfinding       # fails until you implement the four functions

The cost model, which everything here follows from
--------------------------------------------------
Eight directions, every Step costs 1 Energy (DECISIONS §5), so the cost of a path is the number of
steps and, on unobstructed ground, that equals Chebyshev distance `max(|dx|, |dy|)`.

That single fact decides the heuristic. `h = max(dx, dy)` is *exact* for an unobstructed path, so it
never overestimates — the admissibility requirement for A* — and it is consistent (`h(n) <= cost +
h(n')`), so no node ever needs re-expanding. Octile distance (`dx + dy` weighted by sqrt(2)) assumes
diagonals cost 1.414 and therefore **overestimates** here. An overestimating heuristic does not
crash: it silently returns a too-long path. This exact mistake was in the design docs and was caught
in review; `demo()` asserts optimality against a brute-force oracle so it cannot come back.

Because every step costs 1, the multi-source field is a plain **BFS** (a deque, no heap) — Dijkstra
would be doing priority-queue work on a graph where all edge weights are equal. If you find yourself
reaching for `heapq` in `flow_map`, the cost model has been misread.

Complexity at this project's sizes (V <= 3600, 8 neighbours each):

| | time | space |
|---|---|---|
| `a_star` | O(E log V), and far less in practice — Chebyshev aims the search at the goal | O(V) |
| `flow_map` | O(V) — every cell enter/left once | O(V) |

`a_star` uses **lazy deletion**: push a node every time a cheaper route to it is found, and discard
the entry on pop if its recorded cost is stale. A real decrease-key needs an indexed heap, and at
V = 3600 the duplicate entries are cheaper than the bookkeeping. Keep the stale-entry check, or the
search returns a path it has already improved on.

Determinism
-----------
Equal-cost paths must resolve identically on every run, or a seeded Site stops being reproducible.
Order the heap key as `(f, h, tie, x, y)` where `tie` is a monotonically increasing insertion
counter: `f` first (search quality), then `h` (prefer what looks closer to the goal, which explores
fewer cells), then insertion order (so two identical-score nodes never depend on dict or set
iteration order). Never `sorted(set(...))` for neighbour expansion.

One decision the contract does not cover
----------------------------------------
**No corner cutting.** A diagonal step `(x, y) -> (x+1, y+1)` is legal only if at least one of the
two orthogonal cells sharing that corner — `(x+1, y)` or `(x, y+1)` — is passable. Rationale: it
stops a body squeezing through a diagonal wall seam, and it mirrors FOV, which already treats a
diagonal wall pair as occluding (`fov.demo()` asserts exactly that). The alternative (allow it) is
one flag away; `demo()` has a case for each so the choice is visible rather than accidental.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Final

from .grid import TileMap

type Coord = tuple[int, int]

#: The eight compass offsets, orthogonal first. Diagonals are the four odd-dx, odd-dy pairs.
DIRECTIONS: Final[tuple[Coord, ...]] = (
    (0, -1), (1, 0), (0, 1), (-1, 0),
    (1, -1), (1, 1), (-1, 1), (-1, -1),
)

#: Marked in flow fields for a wall, an out-of-bounds cell, or anything unreachable.
UNREACHABLE: Final = 255


def chebyshev(a: Coord, b: Coord) -> int:
    """Unobstructed step count between two cells. The A* heuristic, and the BFS ground truth."""
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def neighbors(m: TileMap, x: int, y: int, *,
              allow_corner_cutting: bool = False) -> Iterator[Coord]:
    """Passable neighbours of (x, y), in DIRECTIONS order.

    Implements the corner rule from the module docstring: a diagonal is yielded only when at least
    one of the two shared orthogonal cells is passable. Out-of-bounds cells are never yielded —
    `m.is_wall` already reports them as walls, but yielding them would put a phantom node in the
    search.
    """
    raise NotImplementedError("implement neighbors() — see the module docstring")


def a_star(m: TileMap, start: Coord, goal: Coord, *,
           allow_corner_cutting: bool = False) -> list[Coord] | None:
    """Shortest path from start to goal inclusive, or None when unreachable.

    Returns `[start]` when start == goal, and None when either endpoint is a wall or out of bounds.
    The returned list must be a valid path: consecutive cells are neighbours, no cell is a wall, and
    its length minus one equals the minimum step count (asserted against an oracle in demo()).
    """
    raise NotImplementedError("implement a_star() — see the module docstring")


def step_toward(m: TileMap, start: Coord, goal: Coord, *,
                allow_corner_cutting: bool = False) -> Coord | None:
    """The first cell of an optimal path, or None. What a Behavior Tree's `move_to` needs.

    None when start == goal (you have arrived) or when the goal is unreachable. This exists so AI
    can move one step per decision step without materialising a full path it will not follow.
    """
    raise NotImplementedError("implement step_toward() — see the module docstring")


def flow_map(m: TileMap, sources: Iterable[Coord], *,
             allow_corner_cutting: bool = False) -> bytearray:
    """Cost-in-steps from every passable cell to the NEAREST source. `UNREACHABLE` elsewhere.

    One BFS with all sources seeded at 0 gives the whole field in O(V) — this is the project's
    biggest algorithmic win: one computation per turn serves every enemy, instead of each enemy
    running its own search. Sources that are walls or out of bounds are ignored. Walls and
    unreachable cells carry `UNREACHABLE`.
    """
    raise NotImplementedError("implement flow_map() — see the module docstring")


def step_downhill(field: bytearray, width: int, x: int, y: int, *,
                  allow_corner_cutting: bool = False) -> Coord | None:
    """The neighbour of (x, y) with the lowest field cost, or None if none is lower.

    None at a source (cost 0), on a wall, or on an `UNREACHABLE` cell. Deterministic: ties resolve
    in DIRECTIONS order, never by iteration over a set.
    """
    raise NotImplementedError("implement step_downhill() — see the module docstring")


# ======================================================================================
# Acceptance test. Do not weaken these; if one is wrong, fix the implementation.
# ======================================================================================
def demo() -> None:
    import random
    from collections import deque

    def open_map(w: int, h: int) -> TileMap:
        m = TileMap(w, h)
        m.fill(1)                                     # 1 = floor
        return m

    def cost(path: list[Coord] | None) -> int | None:
        return None if path is None else len(path) - 1

    # ---- 1. straight line and diagonal, on open ground ---------------------------------
    m = open_map(9, 9)
    assert cost(a_star(m, (0, 0), (5, 0))) == 5
    assert cost(a_star(m, (0, 0), (3, 3))) == 3, "a diagonal Step costs 1 Energy, not sqrt(2)"
    assert a_star(m, (2, 2), (2, 2)) == [(2, 2)], "start == goal is a zero-length path"

    # ---- 2. the heuristic is exact, so cost equals Chebyshev on open ground --------------
    for _ in range(50):
        a, b = (random.randrange(9), random.randrange(9)), (random.randrange(9), random.randrange(9))
        assert cost(a_star(m, a, b)) == chebyshev(a, b), f"{a}->{b} is not Chebyshev-exact"

    # ---- 3. path validity: continuous, wall-free, endpoints right -----------------------
    def check_valid(m: TileMap, start: Coord, goal: Coord, path: list[Coord] | None,
                    allow_corner_cutting: bool = False) -> None:
        if path is None:
            return
        assert path[0] == start and path[-1] == goal, f"endpoints wrong: {path[:2]}..{path[-1]}"
        for (x, y), (nx, ny) in zip(path, path[1:]):
            assert (nx - x, ny - y) in DIRECTIONS, f"not adjacent: {(x, y)}->{(nx, ny)}"
            assert not m.is_wall(nx, ny), f"path crosses a wall at {(nx, ny)}"
            if nx != x and ny != y and not allow_corner_cutting:
                assert not (m.is_wall(nx, y) and m.is_wall(x, ny)), \
                    f"corner cut through {(nx, y)}/{(x, ny)} at {(x, y)}"

    # ---- 4. optimality against an independent oracle (BFS), on random maps --------------
    # NOTE: the oracle shares neighbors(), so it validates the SEARCH (heap bookkeeping, g/f,
    # tie-breaks, optimality) but not the neighbour rule. neighbors() is checked directly in 6.
    def oracle(m: TileMap, start: Coord, goal: Coord, acc: bool = False) -> int | None:
        if m.is_wall(*start) or m.is_wall(*goal):
            return None
        seen = {start}
        q = deque([(start, 0)])
        while q:
            (x, y), d = q.popleft()
            if (x, y) == goal:
                return d
            for nb in neighbors(m, x, y, allow_corner_cutting=acc):
                if nb not in seen:
                    seen.add(nb)
                    q.append((nb, d + 1))
        return None

    rng = random.Random(20260917)
    for trial in range(200):
        mm = TileMap(12, 12)
        for y in range(12):
            for x in range(12):
                mm.tiles[mm.idx(x, y)] = 0 if rng.random() < 0.28 else 1
        start, goal = (0, 0), (11, 11)
        mm.tiles[mm.idx(*start)] = 1
        mm.tiles[mm.idx(*goal)] = 1
        path = a_star(mm, start, goal)
        check_valid(mm, start, goal, path)
        expected = oracle(mm, start, goal)
        assert cost(path) == expected, f"trial {trial}: A* {cost(path)} vs BFS {expected}"

    # ---- 5. unreachable, out of bounds, and start-in-wall -------------------------------
    walled = open_map(7, 7)
    for y in range(7):
        walled.tiles[walled.idx(3, y)] = 0            # full vertical wall
    assert a_star(walled, (0, 3), (6, 3)) is None, "a sealed wall must return None"
    assert step_toward(walled, (0, 3), (6, 3)) is None
    small = open_map(5, 5)
    assert a_star(small, (0, 0), (9, 9)) is None, "goal out of bounds"
    assert a_star(open_map(5, 5), (0, 0), (0, 0)) is not None
    assert step_toward(small, (2, 2), (2, 2)) is None, "already there: no step to take"

    # ---- 6. neighbors(): the corner rule, checked directly rather than via the oracle ---
    o = open_map(5, 5)
    assert len(list(neighbors(o, 2, 2))) == 8, "open ground has 8 neighbours"
    assert len(list(neighbors(o, 0, 0))) == 3, "a corner has 3, and never an out-of-bounds cell"
    sealed = open_map(5, 5)
    sealed.tiles[sealed.idx(3, 2)] = 0
    sealed.tiles[sealed.idx(2, 3)] = 0
    assert (3, 3) not in set(neighbors(sealed, 2, 2)), "diagonal between two walls is illegal"
    assert (3, 3) in set(neighbors(sealed, 2, 2, allow_corner_cutting=True)), \
        "the flag must reopen that diagonal"

    # ---- 7. the corner rule is load-bearing: a diagonal seam is a wall ------------------
    seam = open_map(7, 7)
    for wx, wy in ((3, 0), (2, 1), (1, 2), (0, 3)):
        seam.tiles[seam.idx(wx, wy)] = 0
    assert a_star(seam, (0, 0), (4, 4)) is None, "the diagonal seam must not be squeezable"
    assert a_star(seam, (0, 0), (4, 4), allow_corner_cutting=True) is not None, \
        "with corner cutting the seam opens"
    assert chebyshev((0, 0), (4, 4)) == 4

    # ---- 8. determinism: same inputs, identical list, every time ------------------------
    d = TileMap(12, 12)
    rng2 = random.Random(7)
    for y in range(12):
        for x in range(12):
            d.tiles[d.idx(x, y)] = 0 if rng2.random() < 0.25 else 1
    d.tiles[d.idx(0, 0)] = 1
    d.tiles[d.idx(11, 11)] = 1
    first = a_star(d, (0, 0), (11, 11))
    assert all(a_star(d, (0, 0), (11, 11)) == first for _ in range(5)), "A* is not deterministic"

    # ---- 9. step_toward agrees with a_star ---------------------------------------------
    st = a_star(d, (0, 0), (11, 11))
    assert st is not None
    assert step_toward(d, (0, 0), (11, 11)) == st[1], "step_toward must return the first step"

    # ---- 10. flow_map: exact on open ground, and each source is 0 ----------------------
    f = flow_map(o, [(2, 2)])
    assert f[o.idx(2, 2)] == 0
    for y in range(5):
        for x in range(5):
            assert f[o.idx(x, y)] == chebyshev((x, y), (2, 2)), f"field wrong at {(x, y)}"

    fs = flow_map(o, [(0, 0), (4, 4)])
    assert fs[o.idx(0, 0)] == 0 and fs[o.idx(4, 4)] == 0
    for y in range(5):
        for x in range(5):
            want = min(chebyshev((x, y), (0, 0)), chebyshev((x, y), (4, 4)))
            assert fs[o.idx(x, y)] == want, f"nearest-source field wrong at {(x, y)}"

    # ---- 11. walls and sealed regions are UNREACHABLE ----------------------------------
    fw = flow_map(walled, [(0, 3)])
    assert all(fw[walled.idx(3, y)] == UNREACHABLE for y in range(7)), "a wall is not a cell"
    assert fw[walled.idx(6, 3)] == UNREACHABLE, "the sealed side must be unreachable"
    assert fw[walled.idx(2, 3)] == 2, "the open side is still measured"

    # ---- 12. the gradient is consistent: walking downhill reaches a source in f[cell] steps
    fm = flow_map(d, [(0, 0)])
    for y in range(12):
        for x in range(12):
            here = fm[d.idx(x, y)]
            if here in (0, UNREACHABLE):
                continue
            cur, steps = (x, y), 0
            while fm[d.idx(*cur)] != 0:
                nxt = step_downhill(fm, d.w, *cur)
                assert nxt is not None, f"no downhill step from {cur} (cost {fm[d.idx(*cur)]})"
                assert fm[d.idx(*nxt)] == fm[d.idx(*cur)] - 1, "downhill must drop by exactly 1"
                cur, steps = nxt, steps + 1
                assert steps <= here, "gradient walk exceeded the field value"
            assert cur == (0, 0), f"walk from {(x, y)} ended at {cur}, not the source"
            assert steps == here, f"walk from {(x, y)} took {steps} steps, field said {here}"

    assert step_downhill(fm, d.w, 0, 0) is None, "a source has nowhere downhill to go"
    assert step_downhill(fw, walled.w, 3, 3) is None, "a wall has no downhill step"

    # ---- 13. the field agrees with A*: differential, on a sample of cells ---------------
    for _ in range(30):
        y, x = rng.randrange(12), rng.randrange(12)
        if fm[d.idx(x, y)] in (0, UNREACHABLE):
            continue
        to_source = a_star(d, (x, y), (0, 0))
        assert cost(to_source) == fm[d.idx(x, y)], f"field/A* disagree at {(x, y)}"

    print("OK  a_star + flow_map: optimal against BFS on 200 random maps, corner rule enforced, "
          "gradient walks land on the source, field agrees with A*")


if __name__ == "__main__":
    demo()

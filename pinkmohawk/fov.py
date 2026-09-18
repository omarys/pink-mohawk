"""Field of view: recursive shadowcasting over 8 octants.

DECISIONS §13 row 2; algorithm, complexity and the symmetry caveat in docs/design/data-model.md §2.
Canonical reference: Bjorn Bergstrom, "FOV using recursive shadowcasting", RogueBasin.

Written by hand rather than using `tcod.map.compute_fov` — ADR-0004: tcod owns the window, we own
the algorithms. This module therefore imports nothing but `grid` and `constants`.

Properties this file is responsible for, each asserted in demo():
  * O(R^2): every cell in the disc is visited once (one `_cast` call per octant).
  * A wall occludes a whole wedge, not a single ray, so a pillar casts one clean shadow.
  * Walls inside the radius ARE lit. You must see the wall you are standing next to.
  * The map border never leaks: out-of-bounds reads as wall (grid's border rule), and writes are
    bounds-guarded so Python's negative-index wrap cannot corrupt the far edge.
  * Not symmetric: A seeing B does not imply B seeing A (Bergstrom's algorithm; accepted in the
    contract, with the "may only target what it can see and that sees it" fairness rule instead).

    .venv/bin/python -m pinkmohawk.fov       # runs demo()
"""

from __future__ import annotations

from .constants import FOV_RADIUS, TILE_FLOOR
from .grid import TileMap

# Octant transforms, in Bergstrom's order. Each maps a local (dx, dy) into map space, which is
# what lets one routine serve all eight octants. A wrong tuple mirrors exactly one octant and the
# bug shows up in one direction only.
MULT: tuple[tuple[int, int, int, int], ...] = (
    (1, 0, 0, 1),
    (0, 1, 1, 0),
    (0, -1, 1, 0),
    (-1, 0, 0, 1),
    (-1, 0, 0, -1),
    (0, -1, -1, 0),
    (0, 1, -1, 0),
    (1, 0, 0, -1),
)


def _lit(m: TileMap, x: int, y: int) -> int:
    """Mark a cell visible, returning 1 if it was newly lit. Bounds-guarded: idx(-1, y) aliases
    the last column, so an unguarded write here would light the far edge of the map."""
    if not m.in_bounds(x, y):
        return 0
    i = m.idx(x, y)
    if m.visible[i]:
        return 0
    m.visible[i] = 1
    return 1


def _cast(
    m: TileMap,
    cx: int,
    cy: int,
    row: int,
    start: float,
    end: float,
    radius: int,
    xx: int,
    xy: int,
    yx: int,
    yy: int,
) -> int:
    """Walk one octant outward, recursing into the wedge left past each wall. Returns cells lit."""
    if start < end:  # wedge is fully shadowed
        return 0

    radius_sq = radius * radius
    new_start = start
    lit = 0

    for j in range(row, radius + 1):
        dx, dy = -j - 1, -j
        blocked = False
        while dx <= 0:
            dx += 1
            x = cx + dx * xx + dy * xy
            y = cy + dx * yx + dy * yy
            l_slope = (dx - 0.5) / (dy + 0.5)
            r_slope = (dx + 0.5) / (dy - 0.5)

            if start < r_slope:  # left of the lit range
                continue
            if end > l_slope:  # right of the lit range
                break

            if dx * dx + dy * dy <= radius_sq:
                lit += _lit(m, x, y)

            if blocked:
                if m.is_wall(x, y):
                    new_start = r_slope  # still inside the wall: keep narrowing
                    continue
                blocked = False  # emerged: resume the wider range
                start = new_start
            elif m.is_wall(x, y) and j < radius:
                blocked = True
                lit += _cast(m, cx, cy, j + 1, start, l_slope, radius, xx, xy, yx, yy)
                new_start = r_slope

        if blocked:  # the rest of this wedge is dark
            break

    return lit


def compute_fov(m: TileMap, cx: int, cy: int, radius: int = FOV_RADIUS) -> int:
    """Rewrite m.visible from (cx, cy). Returns the number of cells lit (handy in tests).

    `explored` is deliberately untouched: Memory is folded in by TileMap.remember() once per turn.
    """
    m.clear_visible()
    if not m.in_bounds(cx, cy):
        return 0
    lit = _lit(m, cx, cy)
    for xx, xy, yx, yy in MULT:
        lit += _cast(m, cx, cy, 1, 1.0, 0.0, radius, xx, xy, yx, yy)
    return lit


# --------------------------------------------------------------------------------------
# A deliberately wrong implementation. Its only purpose is to prove the asserts below can fail:
# a test that nothing can violate is not a test.
# --------------------------------------------------------------------------------------
def _leaky_fov(m: TileMap, cx: int, cy: int, radius: int) -> int:
    """Marks the whole disc visible and ignores walls entirely."""
    m.clear_visible()
    lit = 0
    for y in range(cy - radius, cy + radius + 1):
        for x in range(cx - radius, cx + radius + 1):
            if (x - cx) ** 2 + (y - cy) ** 2 <= radius * radius:
                lit += _lit(m, x, y)
    return lit


def _open_map(w: int, h: int) -> TileMap:
    m = TileMap(w, h)
    m.fill(TILE_FLOOR)
    return m


def demo() -> None:
    # ---- open ground, radius bound, origin -------------------------------------------------
    m = _open_map(21, 21)
    base = compute_fov(m, 10, 10, 8)
    assert m.visible[m.idx(10, 10)] == 1, "origin is always visible"
    assert m.visible[m.idx(18, 10)] == 1, "distance 8 is inside the radius"
    assert m.visible[m.idx(19, 10)] == 0, "distance 9 is outside the radius"
    assert m.visible[m.idx(17, 17)] == 0, "diagonal distance 9.9 is outside the radius"
    assert base > 150, f"only {base} cells lit on open ground at R=8"
    # The disc's exact lattice count, derived rather than hardcoded: 197 for R=8. The area pi*R^2
    # is ~201, and the data-model complexity table quotes that as an estimate of work done -- an
    # estimate, not a count. Deriving it here means the assertion cannot drift into being wrong.
    disc = sum(1 for dx in range(-8, 9) for dy in range(-8, 9) if dx * dx + dy * dy <= 64)
    assert base == disc, f"open ground must light the whole disc: {base} != {disc}"
    assert disc == 197, f"the R=8 lattice count moved: {disc}"

    # ---- walls are lit, and a pillar removes cells (differential, so no slope guessing) -----
    p = _open_map(21, 21)
    p.tiles[p.idx(11, 11)] = 0  # one pillar, diagonally adjacent to the viewer
    with_pillar = compute_fov(p, 10, 10, 8)
    assert p.visible[p.idx(11, 11)] == 1, "a wall in view must be lit: the renderer needs it"
    assert with_pillar < base, "a pillar must occlude something"

    # ---- straight-line occlusion: the cell directly behind a wall is dark -------------------
    o = _open_map(11, 11)
    o.tiles[o.idx(2, 5)] = 0
    compute_fov(o, 1, 5, 8)
    assert o.visible[o.idx(2, 5)] == 1, "the wall itself is lit"
    assert o.visible[o.idx(3, 5)] == 0, "the cell behind the wall must be dark"

    # ---- the border never leaks, and Python's negative-index wrap is contained --------------
    e = _open_map(11, 11)
    compute_fov(e, 0, 5, 8)
    assert e.visible[e.idx(0, 5)] == 1
    assert all(e.visible[e.idx(10, y)] == 0 for y in range(11)), (
        "the far edge was lit: an out-of-bounds write wrapped via idx(-1, y)"
    )

    # ---- recomputing clears the previous result, and never touches Memory -------------------
    r = _open_map(11, 11)
    compute_fov(r, 0, 0, 3)
    assert r.visible[r.idx(0, 0)] == 1
    r.remember()
    compute_fov(r, 10, 10, 1)
    assert r.visible[r.idx(0, 0)] == 0, "visible must be cleared between recomputes"
    assert r.explored[r.idx(0, 0)] == 1, "FOV must not write Memory"

    # ---- diagonal seam: two diagonal walls occlude more than open ground --------------------
    d_open = _open_map(13, 13)
    open_count = compute_fov(d_open, 2, 2, 8)
    d_wall = _open_map(13, 13)
    d_wall.tiles[d_wall.idx(4, 4)] = 0
    d_wall.tiles[d_wall.idx(5, 5)] = 0
    closed_count = compute_fov(d_wall, 2, 2, 8)
    assert closed_count < open_count, "a diagonal wall pair must occlude the wedge behind it"

    # ---- the checks can fail: a leaky implementation breaks occlusion and the border ---------
    leak = _open_map(11, 11)
    leak.tiles[leak.idx(2, 5)] = 0
    _leaky_fov(leak, 1, 5, 8)
    assert leak.visible[leak.idx(3, 5)] == 1, "sanity: the leaky reference does leak"
    assert leak.visible[leak.idx(3, 5)] != o.visible[o.idx(3, 5)], (
        "the occlusion assertion must distinguish a correct FOV from a permissive one"
    )

    print(
        f"OK  compute_fov: open ground R=8 -> {base} cells, pillar -> {with_pillar} "
        f"(occludes {base - with_pillar}), diagonal pair occludes {open_count - closed_count}"
    )


if __name__ == "__main__":
    demo()

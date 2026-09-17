"""Map storage: dense tile array plus `explored` and `visible` byte arrays.

DECISIONS §13 row 1; interface and rationale in docs/design/data-model.md §1.

Three separate arrays rather than a struct per cell, because the three access patterns are
disjoint: generation writes `tiles` once, FOV rewrites `visible` wholesale, and the renderer
reads `visible` then `explored` per cell. Interleaved structs would touch 3x the cache lines
per sweep for no benefit.

The border rule is the whole point of this module: an out-of-bounds read returns TILE_WALL, so
FOV, A* and the flow maps get "blocked" without a bounds branch anywhere.

    .venv/bin/python -m pinkmohawk.grid      # runs demo()
"""

from __future__ import annotations

from collections.abc import Iterable

from .constants import TILE_FLOOR, TILE_WALL


class TileMap:
    """A W x H grid of terrain ids with two independent per-cell bit tracks."""

    __slots__ = ("tiles", "explored", "visible", "w", "h")

    def __init__(self, w: int, h: int) -> None:
        self.w = w
        self.h = h
        self.tiles = bytearray(w * h)       # terrain id; 0 = wall
        self.explored = bytearray(w * h)    # has this cell ever been seen this Run? (Memory)
        self.visible = bytearray(w * h)     # is this cell visible right now? (FOV)

    # -- indexing -------------------------------------------------------------------------
    def idx(self, x: int, y: int) -> int:
        return y * self.w + x

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.w and 0 <= y < self.h

    def at(self, x: int, y: int) -> int:
        """Terrain id, or TILE_WALL when out of bounds."""
        return self.tiles[self.idx(x, y)] if self.in_bounds(x, y) else TILE_WALL

    def is_wall(self, x: int, y: int) -> bool:
        """True for a wall *and* for out of bounds — the border rule."""
        return self.at(x, y) == TILE_WALL

    # -- bulk writes ----------------------------------------------------------------------
    def fill(self, tile: int) -> None:
        self.tiles[:] = bytes([tile]) * (self.w * self.h)

    def clear_visible(self) -> None:
        self.visible[:] = b"\0" * (self.w * self.h)

    def remember(self) -> None:
        """Fold what is currently visible into Memory. Call once per turn, after FOV."""
        for i, v in enumerate(self.visible):
            if v:
                self.explored[i] = 1

    @classmethod
    def load_rows(cls, rows: Iterable[str], wall: str = "#", floor: str = ".") -> TileMap:
        """Build from ASCII art. Used by fixtures and tests; '#' is wall, anything else floor."""
        grid = [list(r) for r in rows]
        h = len(grid)
        w = max(len(r) for r in grid) if h else 0
        m = cls(w, h)
        for y, row in enumerate(grid):
            for x, ch in enumerate(row):
                m.tiles[m.idx(x, y)] = TILE_WALL if ch == wall else TILE_FLOOR
        return m


def demo() -> None:
    m = TileMap(4, 3)
    m.tiles[m.idx(0, 0)] = TILE_FLOOR

    # border: the corner is addressable, its neighbours are not
    assert m.at(0, 0) == TILE_FLOOR
    assert m.at(-1, 0) == TILE_WALL and m.at(4, 0) == TILE_WALL
    assert m.at(0, -1) == TILE_WALL and m.at(0, 3) == TILE_WALL
    assert m.is_wall(-1, -1) is True

    # explored and visible are independent tracks
    m.visible[m.idx(0, 0)] = 1
    assert m.explored[m.idx(0, 0)] == 0
    m.explored[m.idx(0, 0)] = 1
    m.visible[m.idx(0, 0)] = 0
    assert m.explored[m.idx(0, 0)] == 1

    # THE TRAP this module's border rule exists to prevent: idx() does not clamp, so idx(-1, 0) is
    # -1, and Python resolves a negative index from the END of the flat array. The aliased cell is
    # therefore the map's bottom-right cell — not the last column of row 0, which is the
    # intuitive-but-wrong guess. Reads are safe (at() guards); writes are not, which is why fov's
    # _lit() checks in_bounds() before touching `visible`.
    assert m.idx(-1, 0) == -1
    assert m.idx(-1, 0) % len(m.tiles) == m.idx(m.w - 1, m.h - 1), "aliases the bottom-right cell"
    assert m.idx(-1, 0) % len(m.tiles) != m.idx(m.w - 1, 0), "NOT the last column of row 0"

    # load_rows + remember
    g = TileMap.load_rows(["###", "#.#", "###"])
    assert g.w == 3 and g.h == 3
    assert g.is_wall(0, 0) and not g.is_wall(1, 1)
    g.visible[g.idx(1, 1)] = 1
    g.remember()
    assert g.explored[g.idx(1, 1)] == 1 and g.explored[g.idx(0, 0)] == 0

    # clear_visible leaves Memory alone
    g.clear_visible()
    assert g.visible[g.idx(1, 1)] == 0 and g.explored[g.idx(1, 1)] == 1

    # storage budget: 3 bytes per cell
    big = TileMap(60, 60)
    assert len(big.tiles) + len(big.explored) + len(big.visible) == 3 * 3600

    print("OK  TileMap: border rule, 3 tracks independent, 11KB at 60x60")


if __name__ == "__main__":
    demo()

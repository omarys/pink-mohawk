"""The only display module. Nothing else in the project imports `tcod` (ADR-0004, layer law 4).

`docs/art/pipeline.md` §3 is the verified tcod recipe, §8 the three cell states, §9 the draw order.
The renderer's whole job: turn a `RunState` into console cells, once per frame.

Three facts from the renderer that shape everything above it:
- **One Glyph per cell.** tcod cannot overlap, rotate or scale tiles, so an "effect" is a glyph swap or
  a tint, never a sprite on top of a sprite.
- **FOV and Memory decide what a cell may show** (§8): unseen cells are blank, remembered cells show
  terrain dimmed and *never* actors, visible cells show terrain plus whatever is standing there.
- **The UI band is rows 38-44**, reserved at 80x38 by DECISIONS §9. The Site scrolls; the band does not.

v1 note: terrain renders as *font* glyphs (`#` and `.`) rather than tileset cells. The tileset is used
for actors and devices, and the pipeline's per-prop index budget (§5.1) is the thing to align by eye
when someone is looking at a screen — guessing sheet indices here would be worse than text.

    .venv/bin/python -m pinkmohawk.render --check      # headless: tileset, remaps, one frame
"""

from __future__ import annotations

import pathlib
from typing import Final

import numpy as np
import tcod.console
import tcod.tileset

from .constants import SITE_H, SITE_W, TILE_FLOOR, TILE_WALL, UI_ROWS, VIEW_H, VIEW_W
from .entities import Actor
from .run import RunState

ROOT = pathlib.Path(__file__).resolve().parent.parent
SHEET: Final = ROOT / "assets/vendor/kenney-rpg-urban-pack/Tilemap/tilemap_packed.png"
FONT: Final = ROOT / "assets/vendor/fonts/spleen-8x16.bdf"
SHEET_COLS: Final = 27
SHEET_ROWS: Final = 18

#: Our own codepoints. 0xE000..0xE00F is terrain and fixtures, 0xE010..0xE02F actors (§5's budget
#: in spirit; the sheet cells behind them are the part that wants a human eye).
CP_TERRAIN: Final = {TILE_FLOOR: 0xE000, TILE_WALL: 0xE001}
CP_DEVICE: Final = 0xE002
CP_LOOT: Final = 0xE003
CP_PAYDATA: Final = 0xE004
ACTOR_RANGE: Final = (0xE010, 0xE02F)

MUL_MEMORY: Final = (86, 102, 128)  # §8: the Memory tint, from the pipeline
UI_BG: Final = (18, 18, 24)


def load_tileset() -> tcod.tileset.Tileset:
    """Sheet plus bitmap font, merged 1:1. The recipe and its constraints are in pipeline.md §3."""
    if not SHEET.exists():
        raise FileNotFoundError(f"missing tile sheet: {SHEET}")
    if not FONT.exists():
        raise FileNotFoundError(f"missing font: {FONT} (pipeline.md §13 #2)")
    tileset = tcod.tileset.load_tilesheet(SHEET, SHEET_COLS, SHEET_ROWS, None)
    if tileset.tile_shape != (16, 16):
        raise ValueError(f"the whole grid depends on 16x16 tiles, got {tileset.tile_shape}")

    # Our codepoints, bound to sheet cells. The indices are deliberate but cheap to change: they are
    # the pipeline's §5 budget rounded to "something is here" until someone looks at the screen.
    # Cell (0, 0) is deliberately unused: remapping a codepoint to tile index 0 does not bind it in
    # libtcod 21.2.1, verified with a probe (x=0,y=0 reports absent, x=1 and y=1 both bind). One
    # wasted sheet cell is cheaper than a codepoint that silently draws nothing.
    for index, codepoint in enumerate((*CP_TERRAIN.values(), CP_DEVICE, CP_LOOT, CP_PAYDATA)):
        tileset.remap(codepoint, 1 + index, 0)
    for index, codepoint in enumerate(range(ACTOR_RANGE[0], ACTOR_RANGE[1] + 1)):
        tileset.remap(codepoint, 1 + index, 2)

    font = tcod.tileset.load_bdf(FONT)
    if font.tile_shape != (16, 8):
        raise ValueError(f"expected a 16x8 bitmap font, got {font.tile_shape}")
    for codepoint in range(0x20, 0x7F):
        try:
            glyph = font[codepoint]
        except KeyError, IndexError:
            continue
        cell = np.zeros((*tileset.tile_shape, 4), np.uint8)
        cell[:, :8] = glyph
        tileset[codepoint] = cell
    return tileset


def camera(run: RunState, focus: tuple[int, int]) -> tuple[int, int]:
    """Top-left cell of the viewport, centred on `focus` and clamped to the Site."""
    x = min(max(0, focus[0] - VIEW_W // 2), max(0, SITE_W - VIEW_W))
    y = min(max(0, focus[1] - VIEW_H // 2), max(0, SITE_H - VIEW_H))
    return x, y


def draw(
    console: tcod.console.Console, run: RunState, focus: tuple[int, int] | None = None
) -> None:
    """One frame, in pipeline.md §9's order: clear, terrain, items, actors, effects, UI."""
    focus = focus or run.crew[0].pos
    origin_x, origin_y = camera(run, focus)
    tile_map = run.site.map

    console.rgb["ch"][:, :] = 0x20
    console.rgb["fg"][:, :] = (0, 0, 0)
    console.rgb["bg"][:, :] = (0, 0, 0)

    # --- terrain, classified by FOV and Memory (§8) ---------------------------------------
    for view_y in range(VIEW_H):
        y = origin_y + view_y
        for view_x in range(VIEW_W):
            x = origin_x + view_x
            if not tile_map.in_bounds(x, y):
                continue
            index = tile_map.idx(x, y)
            if not tile_map.explored[index] and not tile_map.visible[index]:
                continue  # unseen: stays blank
            glyph = "#" if tile_map.is_wall(x, y) else "."
            console.rgb["ch"][view_y, view_x] = ord(glyph)
            if tile_map.visible[index]:
                console.rgb["fg"][view_y, view_x] = (
                    (150, 150, 160) if glyph == "#" else (90, 90, 100)
                )
            else:
                console.rgb["fg"][view_y, view_x] = MUL_MEMORY

    # --- items and devices: remembered cells show them, dimmed (§8) ------------------------
    for spawn in run.population.spawns:
        if spawn.kind not in ("device", "loot"):
            continue
        view = _to_view(spawn.cell, origin_x, origin_y)
        if view is None:
            continue
        index = tile_map.idx(*spawn.cell)
        if not (tile_map.visible[index] or tile_map.explored[index]):
            continue
        console.rgb["ch"][view[1], view[0]] = CP_PAYDATA if spawn.mission else CP_DEVICE
        console.rgb["fg"][view[1], view[0]] = (
            (255, 255, 255) if tile_map.visible[index] else MUL_MEMORY
        )

    # --- actors: visible cells only, and never in the dark ---------------------------------
    for actor in run.actors:
        if actor.downed:
            continue
        view = _to_view(actor.pos, origin_x, origin_y)
        if view is None:
            continue
        index = tile_map.idx(*actor.pos)
        if not tile_map.visible[index]:
            continue
        console.rgb["ch"][view[1], view[0]] = _actor_codepoint(actor)
        console.rgb["fg"][view[1], view[0]] = actor.tint

    _draw_ui(console, run)


def _actor_codepoint(actor: Actor) -> int:
    """An actor's Glyph, clamped into the range the tileset actually bound."""
    low, high = ACTOR_RANGE
    return min(max(actor.glyph, low), high)


def _to_view(cell: tuple[int, int], origin_x: int, origin_y: int) -> tuple[int, int] | None:
    x, y = cell[0] - origin_x, cell[1] - origin_y
    return (x, y) if 0 <= x < VIEW_W and 0 <= y < VIEW_H else None


def _draw_ui(console: tcod.console.Console, run: RunState) -> None:
    """Rows 38-44: the Clock, the crew, and the last thing that happened."""
    top = VIEW_H
    for row in range(top, top + UI_ROWS):
        console.rgb["bg"][row, :] = UI_BG

    segments = run.clock.segments
    bar = "#" * segments + "-" * (10 - segments)
    console.print(
        1,
        top + 1,
        f"CLOCK [{bar}] {segments}/10  {run.clock.state.value.upper()}",
        fg=(255, 200, 120),
        bg=UI_BG,
    )

    for column, member in enumerate(run.crew):
        x = 1 + column * 20
        state = "DOWN" if member.downed else f"E{member.energy:>2}"
        console.print(
            x,
            top + 3,
            f"{member.name[:7]:<7} P{member.physical.filled:>2} S{member.stun.filled:>2} {state}",
            fg=(150, 200, 150) if not member.downed else (200, 120, 120),
            bg=UI_BG,
        )

    if run.clock.log:
        last = run.clock.log[-1]
        console.print(
            1,
            top + 5,
            f"last: {last.event} +{last.delta} -> {last.total}/10",
            fg=(200, 200, 200),
            bg=UI_BG,
        )
    console.print(
        1,
        top + 6,
        "move: arrows/hjkl  attack: a  wait: .  extract: e  quit: Esc",
        fg=(140, 140, 140),
        bg=UI_BG,
    )


def check() -> None:
    """Headless verification: the recipe loads, the frame has content, and the UI band is drawn."""
    tileset = load_tileset()
    run = __import__("pinkmohawk.run", fromlist=["build_run"]).build_run("extraction", 20260918)
    console = tcod.console.Console(VIEW_W, VIEW_H + UI_ROWS)
    draw(console, run)
    drawn = sum(1 for row in console.rgb["ch"] for cell in row if cell != 0x20)
    assert drawn > 100, f"expected a populated frame, drew {drawn} cells"
    assert tileset[CP_DEVICE].any(), "device codepoint resolves to a tile"
    assert tileset[ord("A")].any(), "the font merged"
    print(
        f"OK  render: {tileset.tile_shape} tiles, sheet {SHEET_COLS}x{SHEET_ROWS}, "
        f"{drawn} cells drawn, UI band {UI_ROWS} rows, memory tint {MUL_MEMORY}"
    )


if __name__ == "__main__":
    import sys

    if "--check" in sys.argv:
        check()
    else:
        print(__doc__)

"""Phase 0 spike: prove tcod opens a window, draws a Tileset Glyph, and takes input.

Throwaway. `docs/roadmap.md` Phase 0: this file exists to characterise the third-party
renderer boundary (ADR-0004) *before* any of our own code sits on it. Delete it when
Phase 1 starts.

    .venv/bin/python spike/tcod_probe.py              # open the window (arrows move, Esc quits)
    .venv/bin/python spike/tcod_probe.py --check      # headless: tileset, remap, font, buffer
    SDL_VIDEODRIVER=dummy .venv/bin/python spike/tcod_probe.py --frames 2   # headless window

Acceptance: a 1280x720 window, the loaded urban Tileset with at least one Remap resolved to a
visible cell, a Glyph moving one cell per arrow press, and a clean exit (0, no traceback) on Esc.

Recipe verified against python-tcod 21.2.1 (docs/art/pipeline.md §3).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import tcod.console
import tcod.context
import tcod.event
import tcod.tileset

ROOT = Path(__file__).resolve().parent.parent

VIEW_W, VIEW_H = 80, 38  # map viewport
UI_ROWS = 7              # rows 38-44
SHEET = ROOT / "assets/vendor/kenney-rpg-urban-pack/Tilemap/tilemap_packed.png"
SHEET_COLS, SHEET_ROWS = 27, 18
FONT = ROOT / "assets/vendor/fonts/spleen-8x16.bdf"

CP_FLOOR, CP_WALL, CP_ACTOR = 0xE000, 0xE001, 0xE002  # private-use area: ours to assign


def build_tileset() -> tcod.tileset.Tileset:
    """Load the sheet, bind codepoints to cells, then paste the bitmap font in 1:1."""
    if not SHEET.exists():
        sys.exit(f"missing sheet: {SHEET}")
    if not FONT.exists():
        sys.exit(f"missing font: {FONT}  (fetch it — docs/art/pipeline.md §13 #2)")

    tileset = tcod.tileset.load_tilesheet(SHEET, SHEET_COLS, SHEET_ROWS, None)
    assert tileset.tile_shape == (16, 16), tileset.tile_shape

    tileset.remap(CP_FLOOR, 0, 0)
    tileset.remap(CP_WALL, 1, 0)
    tileset.remap(CP_ACTOR, 2, 0)

    # The font's tile is 16x8; ours is 16x16. Paste the glyph into the left half and never scale.
    font = tcod.tileset.load_bdf(FONT)
    assert font.tile_shape == (16, 8), font.tile_shape
    merged = 0
    for cp in range(0x20, 0x7F):
        try:
            glyph = font[cp]
        except (KeyError, IndexError):  # codepoint absent from the BDF
            continue
        cell = np.zeros((*tileset.tile_shape, 4), np.uint8)
        cell[:, :8] = glyph
        tileset[cp] = cell
        merged += 1
    assert merged >= 90, f"only merged {merged} font glyphs"

    return tileset


def draw(console: tcod.console.Console, px: int, py: int) -> None:
    """Write the console buffer directly. No print(), which takes a str and cannot address a Glyph."""
    rgb = console.rgb
    rgb["ch"][:, :] = CP_FLOOR
    rgb["ch"][0, :] = CP_WALL          # a border, to prove the merge renders
    rgb["ch"][VIEW_H - 1, :] = CP_WALL
    rgb["bg"][0, :] = (40, 40, 48)
    rgb["bg"][VIEW_H - 1, :] = (40, 40, 48)
    rgb["ch"][py, px] = CP_ACTOR
    rgb["fg"][py, px] = (255, 220, 120)  # tint multiplier, not a paint colour

    console.print(2, VIEW_H + 2, f"glyph at {px:>2},{py:>2}   arrows move  Esc quits",
                  fg=(200, 200, 200), bg=(20, 20, 24))
    console.print(2, VIEW_H + 4, "─│┌┐└┘├┤┬┴┼ █▌▐░▒▓", fg=(120, 200, 160), bg=(20, 20, 24))


def check() -> None:
    """Headless: everything except the window. This is the part CI can run."""
    tileset = build_tileset()
    console = tcod.console.Console(VIEW_W, VIEW_H + UI_ROWS)
    draw(console, 10, 10)

    rgb = console.rgb
    assert rgb["ch"][10, 10] == CP_ACTOR, "actor glyph not in the buffer"
    assert rgb["ch"][0, 0] == CP_WALL, "border glyph not in the buffer"
    assert rgb["fg"][10, 10][0] == 255, "tint not applied"
    assert tileset[CP_ACTOR].any(), "actor codepoint resolves to an empty tile"
    assert tileset[ord("A")].any(), "font glyph 'A' did not merge"
    print(f"OK  tileset {tileset.tile_shape}  cols={SHEET_COLS} rows={SHEET_ROWS}  buffer+remap+font verified")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="headless verification, no window")
    ap.add_argument("--frames", type=int, default=0, help="auto-exit after N frames (for headless runs)")
    args = ap.parse_args()

    if args.check:
        check()
        return 0

    tileset = build_tileset()
    px, py = VIEW_W // 2, VIEW_H // 2
    frames = 0

    with tcod.context.new(columns=VIEW_W, rows=VIEW_H + UI_ROWS, tileset=tileset,
                          title="Pink Mohawk — Phase 0 spike") as context:
        console = tcod.console.Console(VIEW_W, VIEW_H + UI_ROWS)
        while True:
            for event in tcod.event.wait(timeout=0.05):
                if isinstance(event, tcod.event.Quit):
                    return 0
                if isinstance(event, tcod.event.KeyDown):
                    match event.sym:
                        case tcod.event.KeySym.ESCAPE:
                            return 0
                        case tcod.event.KeySym.LEFT:
                            px = max(1, px - 1)
                        case tcod.event.KeySym.RIGHT:
                            px = min(VIEW_W - 2, px + 1)
                        case tcod.event.KeySym.UP:
                            py = max(1, py - 1)
                        case tcod.event.KeySym.DOWN:
                            py = min(VIEW_H - 2, py + 1)
            draw(console, px, py)
            context.present(console, integer_scaling=True, clear_color=(0, 0, 0))
            frames += 1
            if args.frames and frames >= args.frames:
                print(f"OK  presented {frames} frame(s), window path exercised")
                return 0


if __name__ == "__main__":
    raise SystemExit(main())

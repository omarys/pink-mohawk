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
from typing import Any, Final

import numpy as np
import tcod.console
import tcod.tileset

from . import dialogue
from .constants import (
    CLOCK_SEGMENTS,
    HUB_TICKS_PER_DAY,
    SCREEN_H,
    SCREEN_W,
    SITE_H,
    SITE_W,
    TILE_FLOOR,
    TILE_WALL,
    UI_ROWS,
    VIEW_H,
    VIEW_W,
)
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

#: The Hub is authored at 80x38, which is VIEW_H exactly, so it draws 1:1 and never scrolls. That is
#: the reason world.md §1.1 chose the size.
HUB_WALL_FG: Final = (150, 150, 160)
HUB_FLOOR_FG: Final = (86, 86, 96)
HUB_LABEL_FG: Final = (112, 132, 168)
HUB_NPC_FG: Final = (232, 208, 120)
HUB_CREW_FG: Final = (255, 255, 255)
PANEL_BG: Final = (12, 14, 20)
PANEL_TITLE_FG: Final = (240, 220, 160)
PANEL_ROW_FG: Final = (206, 206, 214)
PANEL_PICK_FG: Final = (150, 230, 150)
PANEL_HINT_FG: Final = (140, 140, 140)
PANEL_STATUS_FG: Final = (255, 200, 120)


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
    bar = "#" * segments + "-" * (CLOCK_SEGMENTS - segments)
    console.print(
        1,
        top + 1,
        f"CLOCK [{bar}] {segments}/{CLOCK_SEGMENTS}  {run.clock.state.value.upper()}",
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


def draw_hub(
    console: tcod.console.Console, hub: Any, *, selected: int = 0, status: str = ""
) -> None:
    """The district, one cell per cell, plus the UI band.

    No FOV and no Memory here, and that is a decision rather than an omission: the Hub is authored,
    not generated, so there is nothing to discover by looking. FOV is what a Site needs.
    """
    _clear(console)
    tile_map = hub.map
    for y in range(min(tile_map.h, VIEW_H)):
        for x in range(min(tile_map.w, VIEW_W)):
            wall = tile_map.is_wall(x, y)
            console.rgb["ch"][y, x] = ord("#") if wall else ord(".")
            console.rgb["fg"][y, x] = HUB_WALL_FG if wall else HUB_FLOOR_FG

    # Zone labels are text on the floor fill: world.md §1.1 says a label occupies no special tile.
    for zone in hub.zones:
        x, y, _w, _h = zone.rect
        console.print(x + 1, y, f"[{zone.name}]", fg=HUB_LABEL_FG, bg=(0, 0, 0))

    for npc in hub.npcs:
        console.rgb["ch"][npc.pos[1], npc.pos[0]] = ord(npc.glyph)
        console.rgb["fg"][npc.pos[1], npc.pos[0]] = HUB_NPC_FG

    console.rgb["ch"][hub.pos[1], hub.pos[0]] = ord("@")
    console.rgb["fg"][hub.pos[1], hub.pos[0]] = HUB_CREW_FG

    _draw_hub_ui(console, hub, selected=selected, status=status)


def _draw_hub_ui(console: tcod.console.Console, hub: Any, *, selected: int, status: str) -> None:
    """Rows 38-44: the world clock, the world's numbers, the selected Runner, and where you are."""
    top = VIEW_H
    for row in range(top, top + UI_ROWS):
        console.rgb["bg"][row, :] = UI_BG

    state = hub.campaign
    left = HUB_TICKS_PER_DAY - hub.ticks
    console.print(
        1,
        top,
        f"DAY {state.hub_day}  ({left:>3} ticks left)   {state.nuyen:,}¥   HEAT {state.heat}"
        f"   FIXER {state.rep_fixer:+d}   LEGWORK {hub.legwork_remaining}/3",
        fg=(255, 200, 120),
        bg=UI_BG,
    )

    index = min(max(selected, 0), len(state.runners) - 1)
    sheet = state.runners[index]
    console.print(
        1,
        top + 2,
        f"{sheet.id:<7} P{sheet.physical:>2}/{sheet.physical_max:<2} S{sheet.stun:>2}/{sheet.stun_max:<2}"
        f"  XP {sheet.xp:<3} EDGE {sheet.edge}  gear {len(sheet.loadout)}",
        fg=(150, 200, 150),
        bg=UI_BG,
    )

    zone = hub.zone_at(hub.pos)
    if zone is not None:
        console.print(1, top + 3, f"{zone.name}: {zone.mechanics[0]}", fg=(200, 200, 200), bg=UI_BG)
    here = [npc.name for npc in hub.npcs if npc.pos == hub.pos]
    if here:
        console.print(
            1, top + 4, f"{here[0]} is here - Enter to talk", fg=(232, 208, 120), bg=UI_BG
        )

    if status:
        console.print(1, top + 5, status[:78], fg=PANEL_STATUS_FG, bg=UI_BG)
    console.print(
        1,
        top + 6,
        "move: arrows/hjkl  Enter: talk  o: board  i: shop  c: clinic  r: rest  "
        "v: scout  t: favour  d: depart  Tab: crew  Esc: quit",
        fg=PANEL_HINT_FG,
        bg=UI_BG,
    )


def draw_panel(
    console: tcod.console.Console,
    *,
    title: str,
    entries: list[str],
    hint: str = "",
    cursor: int | None = None,
    status: str = "",
) -> None:
    """A list screen over the map area: the Job board, a shop, the clinic.

    One function because they differ only in their rows and their prompt, and a per-screen renderer
    would be three copies of this one.
    """
    _clear(console, rows=VIEW_H)
    console.print(2, 1, title.upper(), fg=PANEL_TITLE_FG, bg=PANEL_BG)
    for index, entry in enumerate(entries[: VIEW_H - 5], start=1):
        picked = index - 1 == cursor
        console.print(
            2,
            index + 2,
            f"{index}. {entry}"[: VIEW_W - 4],
            fg=PANEL_PICK_FG if picked else PANEL_ROW_FG,
            bg=PANEL_BG,
        )
    if status:
        console.print(2, VIEW_H - 2, status[: VIEW_W - 4], fg=PANEL_STATUS_FG, bg=PANEL_BG)
    console.print(2, VIEW_H - 1, hint[: VIEW_W - 4], fg=PANEL_HINT_FG, bg=PANEL_BG)
    _draw_band_background(console)


def draw_talk(console: tcod.console.Console, presenter: dialogue.RecordingPresenter) -> None:
    """A conversation: the recent lines, then the choices with their numbers."""
    _clear(console, rows=VIEW_H)
    lines = presenter.lines[-6:]
    for index, (speaker, text) in enumerate(lines):
        console.print(2, 1 + index * 2, f"{speaker}: "[:22], fg=PANEL_TITLE_FG, bg=PANEL_BG)
        console.print(
            4 + len(speaker), 1 + index * 2, text[: VIEW_W - 8], fg=PANEL_ROW_FG, bg=PANEL_BG
        )
    choices = presenter.shown[-1] if presenter.shown else []
    base = max(len(lines) * 2 + 2, VIEW_H - 4 - len(choices))
    for index, text in enumerate(choices):
        console.print(
            2, base + index, f"{index + 1}. {text}"[: VIEW_W - 4], fg=PANEL_PICK_FG, bg=PANEL_BG
        )
    if not choices:
        console.print(2, base, "(Enter to continue)", fg=PANEL_HINT_FG, bg=PANEL_BG)
    _draw_band_background(console)


def _clear(console: tcod.console.Console, *, rows: int | None = None) -> None:
    """Blank the map area (or the whole screen) to black, so a frame never inherits the last one."""
    up_to = VIEW_H if rows is None else rows
    console.rgb["ch"][:up_to, :] = 0x20
    console.rgb["fg"][:up_to, :] = (0, 0, 0)
    console.rgb["bg"][:up_to, :] = (0, 0, 0)


def _draw_band_background(console: tcod.console.Console) -> None:
    for row in range(VIEW_H, VIEW_H + UI_ROWS):
        console.rgb["bg"][row, :] = UI_BG


def check_hub() -> None:
    """Headless: the district draws, a panel draws, and a conversation draws."""
    from . import campaign as campaign_mod
    from . import hub as hub_mod

    hub = hub_mod.Hub(campaign_mod.new_campaign(20260918))
    console = tcod.console.Console(SCREEN_W, SCREEN_H)
    draw_hub(console, hub)
    drawn = sum(1 for row in console.rgb["ch"][:VIEW_H] for cell in row if cell != 0x20)
    assert drawn > 2000, f"the district should be mostly drawn, got {drawn} cells"
    assert hub.zones, "the district has zones to label"

    draw_panel(
        console,
        title="Job board",
        entries=["job_001  extraction  12,000¥", "job_002  extraction  12,000¥"],
        hint="1-9 take, Esc back",
        cursor=0,
    )
    panel_cells = sum(1 for row in console.rgb["ch"][:VIEW_H] for cell in row if cell != 0x20)
    band_cells = sum(1 for row in console.rgb["ch"][VIEW_H:] for cell in row if cell != 0x20)
    assert panel_cells > 20, f"the panel should draw its rows, got {panel_cells}"
    assert band_cells > 0, "a panel keeps the Hub band: a shop is where you want to see your money"

    presenter = dialogue.RecordingPresenter(
        lines=[("fixer", "Pay is 12k. In and out.")], shown=[["I'm in.", "Not interested."]]
    )
    draw_talk(console, presenter)
    talked = sum(1 for row in console.rgb["ch"][:VIEW_H] for cell in row if cell != 0x20)
    assert talked > 30, f"a conversation should draw its lines and choices, got {talked}"
    print(
        f"OK  render_hub: {hub.map.w}x{hub.map.h} district, {len(hub.zones)} zones, "
        f"{len(hub.npcs)} NPCs, {drawn} cells drawn, panel and conversation views drawn"
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
        check_hub()
    else:
        print(__doc__)

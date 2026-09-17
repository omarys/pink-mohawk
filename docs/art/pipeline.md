# Art and rendering pipeline

The renderer is the tcod console plus one hand-written file that writes
`(codepoint, foreground, background)` triples into it. Everything the player sees — terrain,
items, actors, effects, UI — is one Glyph in one cell. This document is the contract for
that: the tile grid, the codepoint budget, the tint palette, the animation rule, and what
is physically impossible.

Vocabulary is `CONTEXT.md` (Glyph, Tileset, Remap, FOV, Memory). Numbers are
`docs/design/DECISIONS.md` §12 unless a table below cites another source. Display decision
is ADR-0004. The thing that shapes the whole look is one line of libtcod:

```c
// libtcod src/libtcod/tileset_render.c, render_tile()
struct TCOD_ColorRGBA rgba = tile->bg;
struct TCOD_ColorRGBA fg = { tile->fg.r * graphic[i].r / 255, ... };  // foreground × tile
TCOD_color_alpha_blend(&rgba, &fg);
```

One tile, copied 1:1 into one cell, its pixels multiplied by the foreground colour, then
alpha-blended over the background colour. That is the entire visual vocabulary. No overlap,
no rotation, no scaling, no per-cell zoom, no sub-cell offset.

## 1. Tile size: 16×16

| Fact | Value |
|---|---|
| Cell / tile size | 16×16 px (`DECISIONS.md` §12) |
| Window | 1280×720 px |
| Screen cells | `1280 / 16 = 80` columns × `720 / 16 = 45` rows → 80×45 = 3600 cells |
| Map viewport | rows 0–37 → **80×38 = 3040 cells** |
| UI band | rows 38–44 → **80×7 = 560 cells, reserved** (`DECISIONS.md` §9) |
| Scale factor | 1.0 — every source sheet is natively 16×16, so no tile is ever resampled |
| Hub | 80×38 cells = exactly the map viewport (`DECISIONS.md` §9) |
| Glyph vs screen | a Runner is 16 px tall on a 720 px screen |

The bottom **7 rows are the UI band** and are never part of the map: that is where the Security
Clock, crew status, and the dialogue box are drawn. It is why the Hub is 80×38 and not 80×45 — an
80×45 district fills the whole screen and leaves nowhere to draw them (`DECISIONS.md` §9).

16 divides both dimensions with no remainder, so the console maps to the window exactly: no
letterboxing, no fractional scaling, no blur. It is also the native size of the three
16×16 packs, so the art is shown as authored.

Consoles of other cell sizes are possible but are whole-console swaps, not mixtures: a
32×32 atlas (DCSS) gives `1280/32 = 40` columns and `720/32 = 22.5` → 22 rows (704 px) plus
16 px of letterbox. `Tileset.tile_shape` is a single `(height, width)` for the whole
tileset; there is no per-glyph size.

The window may be presented larger without touching the art: `Context.present(...,
integer_scaling=True)` scales the finished console in integer steps, so 2× on a hidpi
display stays pixel-exact.

### Camera (viewport) maths

```python
VIEW_W, VIEW_H = 80, 38          # the map viewport, console rows 0-37
UI_ROWS = 7                      # rows 38-44, reserved: Clock, crew status, dialogue
SCREEN_W, SCREEN_H = VIEW_W, VIEW_H + UI_ROWS      # the console, 80x45

def camera_origin(cx: int, cy: int, site_w: int, site_h: int) -> tuple[int, int]:
    ox = (site_w - VIEW_W) // 2 if site_w < VIEW_W else min(max(cx - VIEW_W // 2, 0), site_w - VIEW_W)
    oy = (site_h - VIEW_H) // 2 if site_h < VIEW_H else min(max(cy - VIEW_H // 2, 0), site_h - VIEW_H)
    return ox, oy
```

Hub (80×38 = the viewport): origin is always `(0, 0)`. Site (60×60, `DECISIONS.md` §9): 60 < 80 so
the Site is centred with 10 blank columns each side, and 60 > 38 so it **scrolls vertically only**.
Cells outside the Site keep `ch=0x20, fg=(0,0,0), bg=(0,0,0)`. The UI band is never scrolled.

## 2. Vendored assets (on disk now)

`assets/vendor/<pack>/LICENSE.md` records author, source URL, license, attribution
requirement, download date and the primary source used to verify it, per
`create-game-assets/references/provenance.md`.

| Directory | Sheet file(s) | Sheet size | Grid | Tile | Files |
|---|---|---|---|---|---|
| `assets/vendor/kenney-rpg-urban-pack/` | `Tilemap/tilemap_packed.png` | 432×288 | 27 cols × 18 rows = 486 | **16×16**, no spacing | 9 |
| | `Tilemap/tilemap.png` | 458×305 | same 27×18 | 16×16, **1 px spacing** | |
| `assets/vendor/kenney-roguelike-modern-city/` | `Tilemap/tilemap_packed.png` | 592×448 | 37 cols × 28 rows = 1036 | **16×16**, no spacing | 8 |
| | `Tilemap/tilemap.png` | 628×475 | same 37×28 | 16×16, **1 px spacing** | |
| `assets/vendor/future-city-27/` | `future_city_27.png`, `future_city_27_gritty.png` | 256×272 | 16 cols × 17 rows = 272 | **16×16** | 5 |
| | `alley-tiles.png` | 96×96 | 6×6 | 16×16 | |
| | `characters_24.png` | 32×28 | 2×2 | 16×**14** — off-grid, do not load as a sheet | |
| | `cars_3.png` | 74×14 | not on a grid | — | |
| `assets/vendor/dcss-tiles/` | `releases/Nov-2015/**` (one PNG per tile) + 3 docs | 4249 of 4357 PNGs are 32×32 | — | **32×32** | 4360 |

**Load `*_packed.png` only.** `tcod.tileset.load_tilesheet` derives the tile size from
`image_width / columns`, and assumes tiles fill the image; the 1 px-spaced variants
(458 = 27×16 + 26) silently shift every glyph by a pixel per column. The shipped
`Tilemap/tilemap.txt` and `Tilesheet.txt` confirm 16×16 / 0 px margin / 1 px spacing.

The `.zip` archives were deleted after extraction; no archive is committed. The per-tile
`Tiles/` directories (486 and 1036 individual PNGs) were deleted — the packed sheets are the
same data, and the `tile_XXXX` index equals the packed sheet index row-major.

Roles are fixed by `DECISIONS.md` §12: **Kenney RPG Urban Pack** is the Hub and city-Site sheet,
**Kenney Roguelike Modern City** is the interiors and furniture sheet (§5.3), Future City 27 is a
backdrop panel only (§5.4), and DCSS is an alternative whole-console atlas (§5.6).

DCSS outliers a loader must skip or crop: 83 tiles at 32×48 (`mon/unique/*`,
`mon/panlord/*`), 8×14 `misc/numbers/*`, 20×20 `gui/*`, two 416×416 `UNUSED/gui/` title
screens. The `releases/Ancient` tree was not vendored (risk per
`TILES_UNDER_UNKNOWN_LICENSE.md`).

## 3. tcod recipe

Verified against python-tcod 21.2.1 (`tcod/tileset.py`, `tcod/console.py`,
`tcod/context.py`) and libtcod `tileset_render.c`.

```python
# the render seam — the only module that touches tcod's display API
from pathlib import Path
import numpy as np
import tcod.console, tcod.context, tcod.event, tcod.tileset

VIEW_W, VIEW_H = 80, 38                     # map viewport, rows 0-37
UI_ROWS = 7                                 # UI band, rows 38-44
SHEET = Path("assets/vendor/kenney-rpg-urban-pack/Tilemap/tilemap_packed.png")
FONT = Path("assets/vendor/fonts/spleen-8x16.bdf")

# 1. load the tileset: (path, columns, rows, charmap). charmap=None => nothing mapped yet.
tileset = tcod.tileset.load_tilesheet(SHEET, 27, 18, None)

# 2. bind codepoints: remap(codepoint, tile_x, tile_y). One argument = tile index.
tileset.remap(0xE004, 1, 1)                 # tile at sheet cell (1, 1) -> U+E004
tileset.remap(0xE00A, 100)                  # index form; x wraps by the sheet's row width
# remap raises IndexError if the tile index does not exist in the sheet.

# 3. merge a bitmap font into the same tileset (uniform tile size is not negotiable)
font = tcod.tileset.load_bdf(FONT)          # Spleen 8x16 -> tile_shape (16, 8)
assert font.tile_shape == (16, 8)
cell = np.zeros((*tileset.tile_shape, 4), np.uint8)
for cp in range(0x20, 0x7F):
    if cp in font:
        cell[:] = 0
        cell[:, :8] = font[cp]              # paste 1:1 at x=0; never scale
        tileset[cp] = cell                  # __setitem__ requires exactly tile_shape

# 4. open the window with that one tileset
with tcod.context.new(columns=VIEW_W, rows=VIEW_H + UI_ROWS, tileset=tileset,
                      title="Pink Mohawk") as context:
    console = tcod.console.Console(VIEW_W, VIEW_H + UI_ROWS)   # order="C": index [y, x]
    while True:
        for event in tcod.event.wait(timeout=0.05):     # returns early on input
            if isinstance(event, tcod.event.Quit):
                raise SystemExit
        draw(console, world)                            # section 9
        context.present(console, integer_scaling=True, clear_color=(0, 0, 0))
```

Drawing one cell — write the console buffer directly, not `print`:

```python
rgb = console.rgb            # np.dtype([("ch", np.intc), ("fg", "3B"), ("bg", "3B")]), [y, x]
rgb["ch"][cy, cx] = 0xE004
rgb["fg"][cy, cx] = (255, 255, 255)   # tint multiplier, not a paint colour
rgb["bg"][cy, cx] = (0, 0, 0)

# alpha is only reachable through the 4-byte view of the same buffer:
console.rgba["fg"][cy, cx] = (255, 255, 255, 56)      # section 6, invisible / Spirit
```

`Console.print(x, y, text, fg=..., bg=...)` is for strings of font glyphs (HUD, message
log) and takes a `str`, so it cannot address a PUA Glyph codepoint. `put_char` exists but
is deprecated. Vectors are fine too: `rgb["ch"][y0:y1, x0:x1] = cp`.

### API constraints (all verified, ADR-0004's ceiling)

| Constraint | Where it comes from |
|---|---|
| One tileset per context → **every cell is the same pixel size** | `Tileset.tile_shape` is a single `(h, w)`; the render surface is `console.w × tile_w` by `console.h × tile_h` |
| **No overlap** | one codepoint per cell; `ch` is a single int — there is no second layer |
| **No rotation, no flipping, no per-tile scaling** | `render_tile` copies the tile rows straight into the output |
| `load_tilesheet` assumes tiles fill the image | it computes `tile_w = image_w / columns` |
| `remap(cp, x, y)` — codepoint first, tile coordinates second; large `x` wraps by row | `Tileset.remap` |
| fg is a **multiplier** (`tile × fg / 255`), then blended over bg using the tile's alpha | `render_tile` above |
| Transparent tile pixels show `bg`; `bg` alpha 0 shows the context's `clear_color` | same |
| Per-cell cost is skipped when `(ch, fg, bg)` are unchanged since the last present | `TCOD_tileset_render_to_surface` cache |
| Foreground tint can only scale channels toward 0 — it cannot lighten, and it cannot desaturate | multiplication |

Consequence for the palette: a tint is a **multiplier triplet**, `(255,255,255)` = the tile
as authored. Two tints stack by multiplying in Python:

```python
def tint(a, b):                      # matches libtcod's /255 fixed-point
    return (a[0] * b[0] // 255, a[1] * b[1] // 255, a[2] * b[2] // 255)
```

## 4. Codepoint plan

Glyphs live in the Unicode Private Use Area; ASCII is left for text (tcod's own advice for a
`Tileset` cell that is not a letter). One flat table, one spelling:

| Range | Contents | Bound from |
|---|---|---|
| `U+E000–U+E0FF` | terrain: 9 pieces × 20 material slots (0–8 city, 9–19 interior) | pack sheet, §5.1 |
| `U+E100–U+E16F` | ten actors × 4 directions × 3 frames (Crew, five archetypes, Spirit) | pack figures / font glyphs, §5.2 |
| `U+E180–U+E1FF` | devices, items, markers | pack sheet / DCSS items |
| `U+E200–U+E27F` | single-cell props / decor | pack sheet, §5.1 |
| `U+E280–U+E2BF` | effects | font glyphs, or DCSS `effect/*` in DCSS mode |
| `U+E300–U+E31F` | UI | font glyphs (box drawing, blocks) |
| `U+0020–U+007E`, `U+2500…` | text and frames | Spleen, §7 |

Address arithmetic, used verbatim by the renderer:

```python
def terrain_cp(material: int, piece: int) -> int:      # piece 0..8, row-major inside the 3x3 patch
    return 0xE000 + material * 9 + piece

def actor_cp(kind: int, direction: int, frame: int) -> int:   # direction 0=L 1=down 2=up 3=R
    return 0xE100 + kind * 12 + direction * 3 + frame
```

## 5. Glyph budget

### 5.1 Kenney RPG Urban Pack (primary)

The sheet is a **9 × 6 grid of 48×48 patches** (each patch = 3×3 tiles = a rounded
terrain square). Patch column `B` (0–8) and row `R` (0–5) start at tile index
`R*81 + B*3` (row-major, 27 columns). Verified by rendering the sheet at 3× and 8×.

Piece layout inside a patch, verified at 8× on `B0R0` (grass, tl 0):

| | col 0 | col 1 | col 2 |
|---|---|---|---|
| row 0 | 0 top-left corner | 1 top edge | 2 top-right corner |
| row 1 | 3 left edge | 4 **centre** | 5 right edge |
| row 2 | 6 bottom-left | 7 bottom edge | 8 bottom-right |

```python
def patch_piece(n_open, e_open, s_open, w_open) -> int:
    """x/y are 0 at a closed side, 2 at the opposite closed side, 1 when open."""
    x = 0 if not w_open else (2 if not e_open else 1)
    y = 0 if not n_open else (2 if not s_open else 1)
    return y * 3 + x          # north/south win over east/west when both are closed
```

Terrain materials (patch top-left tile index `tl`, which is also the tile the piece offsets
apply to):

| M | `tl` | Patch | Use |
|---|---|---|---|
| 0 | 0 | grass | Hub verges, parkland |
| 1 | 9 | concrete slab | **default Site floor** |
| 2 | 12 | concrete slab + hatch outline | vault floor, service hatch |
| 3 | 81 | pale tile floor | office interior |
| 4 | 84 | pale floor + inset panel | office detail, elevator mat |
| 5 | 87 | interior partition (grey band in pale floor) | interior walls |
| 6 | 18 | red-brick paving with lane dashes | street |
| 7 | 90 | concrete with curb | sidewalk edge |
| 8 | 171 | water | water |

Material → piece codepoint: `0xE000 + M*9 + P`. Slots 9–19 (`U+E051–U+E0B3`) are the **interior
block**, bound from the Roguelike Modern City sheet (§5.3) rather than from this one; 0x72 Dungeon
Tileset II is an optional later upgrade to those same slots (§5.5).

The dark asphalt with lane lines (sheet tiles 411–431) and the red-brick road runs (tiles
15–77) are **not** among these rounded patches — they sit in the props rows and are placed
as individual road cells from the props block.

Single-cell props: use one tile only. Cars (3-tile runs starting at tiles 420, 423 and 426),
fence runs (tl 327, 408), stone wall runs (tl 324, 405) and long canopies are **3-tile
runs** on the sheet: place them as terrain, three Site cells each carrying its own piece,
never as one entity. An entity is exactly one cell.

Verified prop hosts for the `U+E200` block (contents read off the sheet at 3–6×):

| tile region | contents |
|---|---|
| 162–211 | lamp posts, pipes, road-edge pieces |
| 216–251 | benches, tables, road markings, concrete barriers |
| 252–305 | bins, crates, vending/fridge units, shelves, chests |
| 306–347 | lockers, doors, door frames, grey wall segments |
| 333–404 | green trees, pine trees, autumn trees, wooden fencing |
| 405–431 | stone wall runs, grey fencing, windows, cars (3-tile runs) |

### 5.2 Crew and enemies

Figure block on the same sheet: **columns 23–26 × rows 0–17** (it cuts across patch
columns B7/B8, so those two patch columns do not exist for rows 0–17).

| Axis | Meaning (verified at 16× on tiles 23–26 / 50–53 / 77–80) |
|---|---|
| column 23 | facing left |
| column 24 | facing down (front) |
| column 25 | facing up (back) |
| column 26 | facing right |
| row `3k + f` | figure `k` (0–5), walk frame `f` (0–2); frame 0 is the standing pose, frames 1 and 2 are the two contacts |

Tile for a row in this table → `(x = 23 + direction, y = 3*figure + frame)`, where `figure`
is the sheet figure index in the last column.

| `kind` | Codepoint base | Actor | Sheet figure | Tint |
|---|---|---|---|---|
| 0 | U+E100 | Physical Adept | 0 (rows 0–2) | `(255,255,255)` |
| 1 | U+E10C | Mage | 2 (rows 6–8) | `(255,255,255)` |
| 2 | U+E118 | Shaman | 3 (rows 9–11) | `(255,255,255)` |
| 3 | U+E124 | Decker | 5 (rows 15–17) | `(255,255,255)` |
| 4 | U+E130 | Corp Guard | 1 (rows 3–5) | `(160,200,255)` |
| 5 | U+E13C | Security Drone | font `○` U+25CB | `(255,190,60)` |
| 6 | U+E148 | Ganger | 4 (rows 12–14) | `(255,170,110)` |
| 7 | U+E154 | Corp Mage | 1 (rows 3–5) | `(185,120,255)` |
| 8 | U+E160 | Hellhound | font `♦` U+2666 | `(255,90,70)` |
| 9 | U+E16C | Spirit | font `☼` U+263C | `(150,220,255)`, fg alpha 150 |

The pack has six human figures and nothing else — no machine, no beast. The three
non-human actors therefore use font glyphs, pasted into the same 16×16 cell (an 8×16 glyph
in a 16×16 cell reads smaller than one of the 16×16 figures; accepted, and a hand-drawn
16×16 replacement is tracked in §12). The three human enemies reuse two figures
distinguished by multiply tint; the Crew's four figures are never tinted, so "tinted human =
hostile" is a rule the player can read.

### 5.3 Kenney Roguelike Modern City

Same 16×16 grid, 37×28, no patch structure — autotile groups are 2–3 tiles wide with
props interleaved. It is the **interiors and furniture sheet** (`DECISIONS.md` §12), not a mixture
and not a Hub swap: the loader is re-run against this sheet to bind the interior terrain slots
(§5.1) and the interior prop range, while the RPG Urban Pack stays the sheet for the Hub district
and the city Sites.

| Region | Contents |
|---|---|
| 0–142 | building walls: red brick, concrete, pale stone, 2–3 tiles wide per face + corners |
| 148–190 | pavement, kerbs, grass strip, road edges |
| 296–487 | more facades: shopfronts, windows, doors |
| 209–284 | shop awnings and trim |
| 356–511 | striped fencing and canopies |
| 494–648 | crates, bins, dumpsters, pallets, wood piles, industrial units, **hazard-striped tiles 642–648** |
| 660–665, 697–700, 771–776, 808–813, 845–850, 956–961, 993–996 | cars, 3-tile runs |
| 401–443, 475–517 | trees |
| 717–754, 790–791 | road markings |
| 981–1035 | dirt and grass ground |

The hazard stripes and awnings are the closest thing any vendored pack has to a cyberpunk
signal; the interior reader should prefer them over the RPG Urban Pack's plain brick for Site
interiors and industrial rooms.

### 5.4 Future City 27

**Not a top-down tilemap.** Each tile is a slice of a building facade (lit windows, neon
signs reading `BAR`, `SHOP`, `HOTEL`, a vertical street lamp). Use it only for a full-screen Hub
backdrop or a Job-briefing panel, drawn as terrain: 16 columns × 17 rows is exactly
256×272 px, which is a centred panel in the 80×38 map viewport at origin
`((80-16)//2, (38-17)//2) = (32, 10)`. Mixing it into the Site grid would read as noise.

### 5.5 0x72 16×16 Dungeon Tileset II — optional manual step, see §13

`DECISIONS.md` §12 keeps this as the *intended* interiors pack, but itch.io will not serve it
headlessly, so it is a documented manual step rather than a dependency (§13 #1), and its indices are
not invented here. **Interiors and furniture come from Kenney Roguelike Modern City** (§5.3), which
is already vendored and CC0 — nothing in v1 waits on 0x72.

If it is ever added it binds into the interior terrain slots 9–19 (`U+E051–U+E0B3`) and prop slots
`U+E260–U+E27F`. The binding procedure is §3 step 2 — verify the sheet grid first, then `remap`
each piece.

### 5.6 DCSS — whole-console alternative, not a mixture

32×32 tiles cannot share a console with 16×16 ones. DCSS mode means: rebind every codepoint
from an atlas built out of the per-file PNGs, and accept a **40×22** cell screen with 16 px
of letterbox.

Atlas build (a one-off script, output committed as one PNG):

1. Take `releases/Nov-2015/**/*.png` **only** if the image is exactly 32×32 — that is 4249
   of 4357 files and it mechanically drops the 32×48 tiles, the 8×14 numbers and the
   416×416 title screens.
2. Sort paths for determinism, pack row-major into a sheet of `96` columns (96×32 = 3072 px
   wide), record `path -> tile index` in a JSON sidecar next to the atlas.
3. `remap` the chosen indices onto the same codepoint ranges as §4, so every other module
   (Site data, animation, tint) is unchanged — only the view module and the atlas differ.

Which slots DCSS can fill (it is a fantasy set; it has no sprawl, no drones, no guns):

| Codepoint range | DCSS source |
|---|---|
| terrain `U+E000–U+E05F` | `dngn/floor/*` (371), `dngn/wall/*` (424), `dngn/doors/*` — basement/prefab interiors |
| items/devices `U+E180` | `item/weapon/*` (170), `item/misc/*`, `item/gold/*` (Paydata) |
| effects `U+E280` | `effect/*` (198): `bolt*`, `arrow*`, `cloud_fire*`, `cloud_cold*`, rays |
| markers `U+E1F0` | `misc/cursor*.png`, `misc/mdam_*` damage overlays, `gui/*` |
| props `U+E200` | `dngn/traps/*`, `dngn/statues/*`, `misc/*` |

Non-living actors: `mon/nonliving/*` (46 — golems, crystal guardians) is the only vendored
source for a machine-like actor. Humans in the Crew cannot come from here: `player/*` is a
paper-doll system (19 part groups), not whole 32×32 actors.

## 6. Tint palette

`fg` is a multiplier; the values below are what the renderer reads, not paint colours.
Where a cell has both a state tint and a region tint, combine with `tint()` (§3).

| State | `fg` multiplier | Cycle | Read as |
|---|---|---|---|
| Normal, visible | `(255,255,255)` | — | tile as authored |
| Memory (seen, not currently visible) | `(86,102,128)` | — | cool, dark — the only dimming the palette has |
| Unseen | `ch=0x20`, `bg=(0,0,0)` | — | nothing drawn |
| Room darkened (Lights device hacked, `DECISIONS.md` §7) | `(60,70,110)` | — | still FOV-visible, just dark |
| Stunned | `(255,230,110)` ↔ `(170,150,70)` | 2 frames, 150 ms | warm flash |
| Blinded (Optics hacked, −3 dice) | `(110,110,110)` | — | grey-washed |
| Hacked / seized device (3 rounds) | `(0,235,235)` ↔ `(120,120,120)` | 2 frames, 200 ms | cyan blink |
| On fire | `(255,120,40)` ↔ `(140,60,20)` | 2 frames, 120 ms | orange pulse |
| Invisible (spell) | own tint, `fg` alpha 56 | — | ghost of the player's own Runner |
| Spirit | `(150,220,255)`, alpha 150 ↔ 190 | 3 frames, 300 ms | cold shimmer |
| Downed | `(170,30,40)` on glyph `%` | 2 frames, 400 ms, then settle dark | out of the Run |
| Cursor / selected Runner | `bg = (40,40,60)` | — | bg shows through the tile's transparent pixels |
| Zone preview (Ward, Fear, radius markers) | `bg = (30,10,40)` | 2-frame bg pulse | the only sub-cell signal that exists |

`bg` is a real cell fill — the tile is alpha-blended over it, so a bg tint colours the gaps
around a rounded terrain patch and nothing else. It never replaces a glyph.

## 7. Animation by codepoint cycling

An animation is a list of codepoints plus a frame duration. The pack ships **three walk
frames per direction and nothing else**: there are no idle, attack, downed or death frames
in any vendored pack. So two of the four cycles are frame cycles and two are glyph swaps
plus a tint pulse — which is exactly the mechanism `DECISIONS.md` §12 describes.

| Cycle | Codepoints | Frames | Timing rule |
|---|---|---|---|
| Idle | frames `[0, 2]` of the actor's direction | 2 | 600 ms per frame, looping; frame 0 is the standing pose |
| Walk | frames `[0, 1, 2]` | 3 | **event-driven: one frame per Step action taken**, min 110 ms per frame so a 3-tile Sprint does not blur into 30 ms |
| Attack | frames `[1, 2]` | 2 | 90 ms per frame, non-looping, started when the Attack action resolves; the target cell gets the effect glyph/tint in the same frame |
| Downed | `[%, %]` — glyph swap to `%` | 2 | 400 ms alternating `(170,30,40)` and `(110,20,30)`, then settles on the dark frame and stops |

Rules that keep this deterministic and turn-based:

- The wall clock only drives *decoration*. Walk phase comes from Step events, so the player
  and the Behavior Tree actors animate in lockstep with the turn engine, never against it.
- One accumulator per frame: `dt` from `tcod.event.wait(timeout=0.05)` returning. `frame =
  (elapsed_ms + phase) // frame_ms % len(frames)`, `phase = (actor_id * 137) % cycle_ms` so
  a crowd does not pulse in unison.
- Two frames per cycle minimum, four maximum (`DECISIONS.md` §12).
- Facing is data, not animation: the direction changes the glyph column (23–26) and takes
  effect immediately; the walk frame index is preserved across a turn so the feet do not
  reset.
- Attack, Downed and every state in §6 are shown in the actor's own cell. There is no second
  Glyph layer: an effect cannot be drawn *on top of* an actor, only *instead of* the actor's
  glyph (draw order §9) or as a tint on it.

## 8. FOV, Memory and darkness — glyph swap and tint only

`FOV` and `Memory` decide which of three states a cell is in; nothing else in the pipeline
knows they exist. The Site keeps `visible` and `explored` byte arrays (`DECISIONS.md` §13),
filled by our own recursive shadowcasting (ADR-0004 — libtcod's FOV is deliberately unused).

**Sight radius is a contract parameter: 8 cells**, reduced to **2 in darkness** (`DECISIONS.md`
§12). It is the only visibility parameter in v1 — no cone, no facing-dependent FOV, no per-actor
radius. The renderer never computes it; it draws whatever the FOV module classified.

| Cell state | Glyph | `fg` | `bg` | Actors drawn? | Items drawn? |
|---|---|---|---|---|---|
| Unseen | `0x20` | `(0,0,0)` | `(0,0,0)` | no | no |
| Memory | terrain glyph, unchanged | `MUL_MEMORY (86,102,128)` | `(0,0,0)` or region bg | **never** | yes, dimmed |
| Visible | terrain glyph | `(255,255,255)` × state × region | region bg | yes | yes |
| Visible, room darkened | terrain glyph | `× MUL_DARK (60,70,110)` | region bg | yes | yes |

Why this shapes the look: there is no lighting model, no light map, no smooth falloff and no
alpha ramp into the dark. A cell is either drawn, drawn dim and blue, or not drawn. The
Memory tint is the *only* "old light" in the game, so exploration reads as a growing
blue-grey floor plan rather than a lit scene.

Corollaries the implementer must respect:

- Actors are never drawn from Memory: a Runner remembers walls, doors and loot, never a
  guard's last position. (Legwork intel, `DECISIONS.md` §9, is intel data, not a Memory
  glyph — if it needs a marker it gets a cell in `U+E1F0` inside currently-visible territory.)
- Darkness from the Lights hack is a **tint step, not a glyph change**: the room's cells
  keep their terrain glyph and stay visible, while the enemies inside lose sight radius
  (`DECISIONS.md` §7: −2 dice, and §12: sight radius 2 in darkness against 8 in light). The player
  sees the room; the enemies stop seeing the Crew.
- `fg` alpha is the one extra knob available if Memory ever needs two ages. It requires
  `console.rgba`, and the tile then contributes `alpha/255` of the pixel over `bg` — alpha 56
  is 22% tile, 78% background. v1 uses one Memory state.

## 9. Draw order

One console, six passes, each pass writing `(ch, fg, bg)` for whole cell ranges. Later
passes overwrite earlier ones in the same cell, which is why effects are last: an actor
standing on a burning cell shows the fire, not the Runner (`DECISIONS.md` §12 order).

```
1. clear       all 3600 cells: ch=0x20, fg=bg=(0,0,0)
2. terrain     the Site's tile array + autotile pieces + FOV/Memory classification (§8)
3. items       loot, devices, Paydata
4. actors      Crew, enemies, Spirit (visible cells only)
5. effects     muzzle flashes, impacts, fire, zone previews (bg only)
6. UI          rows 38-44 only: Security Clock, crew status, dialogue, log, cursor, menus
```

The Security Clock is ten cells drawn in the UI band, at row 38 (the first UI row), right-aligned at
`x = 80 - 12 .. 80 - 3`: the first `segments` of them are `█` (U+2588) and the rest `░` (U+2591),
both from the font's CP437 block. Ten cells is 160 px, one tenth of the screen width, and the
ten-segment count is `DECISIONS.md` §9's contract.

UI placement is no longer constrained: rows 38–44 are a reserved band (`DECISIONS.md` §9), so the
Clock, crew status, dialogue box, message log and menus draw there and never overwrite the Site.
That reserved band is the whole reason the Hub is 80×38 rather than 80×45.

## 10. Font

| Decision | Value |
|---|---|
| Font | **Spleen 8×16**, bitmap (BDF) |
| File (must exist) | `assets/vendor/fonts/spleen-8x16.bdf` |
| License | BSD-2-Clause (verified at the upstream repo, §13) |
| Coverage | ASCII + full CP437, so box drawing `─│┌┐└┘├┤┬┴┼` and blocks `█▌▐░▒▓` are available for the UI |
| How it is used | pasted 1:1 into the 16×16 cell, left-aligned at `x=0` — **never rasterised, never scaled** |
| Advance | 16 px, so 80 text columns = exactly 1280 px |

A bitmap font is required by the geometry: a TTF renderer (`load_truetype_font`) rasterises
at an arbitrary size, and any non-integer result fights a 16×16 pixel grid. Spleen's native
height is exactly 16 px, so the glyph is a byte-for-byte paste into the cell with 8 empty
columns to its right. That spare half-cell is what makes cell backgrounds work behind text.

`DECISIONS.md` §12 names **Cozette (MIT)** and **Spleen (BSD-2-Clause)** and records that neither is
OFL; that correction is already in the contract, so there is no text left to fix here. What is still
open is `DECISIONS.md` §14 Q2: TTF (Cozette) versus a bitmap font (Spleen). This document recommends
the bitmap route for the geometry above, and §12 #4 keeps that question open. Either way no vendored
tileset pack contains a font, so the file is a manual fetch (§13 #2, §13 #3).

## 11. The pygame-ce escape hatch

ADR-0004: "the documented escape hatch is to keep tcod for FOV and input while rendering
with pygame-ce, which is a contained change to one module." That module is the render seam
— the view module, `src/render/view.py` in this repository's layout; whatever the package
root ends up being, the seam is "the one file that owns the display". Nothing else in the
game holds a `Console`, a `Context` or a `Tileset`; every other module produces
`(codepoint, fg, bg)` triples and cell coordinates.

What changes, in full:

| Stays identical | Changes |
|---|---|
| the sheets and their grid maths (§5) | `Console` → one `pygame.Surface` per frame, or a dirty-rect list |
| the codepoint plan and the atlas (§4) | `context.present` → `screen.blit` + `pygame.display.flip()` |
| the font paste (§10) | `load_bdf` → `sheet.subsurface(Rect(tx*16, ty*16, 16, 16))` slicing |
| the tint palette and its multiply semantics (§6) | `fg` multiply → `tile.copy()` + `copy.fill(fg, special_flags=pygame.BLEND_RGB_MULT)` |
| animation timing and frames (§7) | `bg` fill → `screen.fill(bg, Rect(x*16, y*16, 16, 16))` before the blit |
| FOV/Memory classification (§8) | the loop becomes `clock.tick(60)` + `pygame.event.get()` |
| draw order (§9) | nothing else |

`pygame.Surface.fill(color, special_flags=BLEND_RGB_MULT)` multiplies the destination
channels by the source channels (`>> 8`, per pygame-ce's special-flags reference) where
libtcod divides by 255 — the same operation, differing by at most 1 per channel, so the
palette table does not need revisiting, but the two renderers are not byte-identical. Cache
by `(codepoint, fg, bg)`, the same key libtcod's own render cache uses, or the
copy-per-cell cost will dominate.

Order matters and mirrors `render_tile`: fill the cell with `bg`, then blit the tinted,
alpha-carrying tile over it.

Input: `tcod.event` records are translated from `pygame.event` at the top of the loop, so the
event vocabulary downstream is unchanged. If the tcod context is dropped entirely, the input
adapter is the second and last file that changes.

## 12. Open questions (parameters this document proposes)

None of these exist in `DECISIONS.md`; each is a recommendation, marked as unresolved. Two former
entries are closed and have been removed from this table: **sight radius** is now a contract
parameter, 8 cells and 2 in darkness (`DECISIONS.md` §12, used in §8), and **UI placement** is settled
by the reserved 7-row band (`DECISIONS.md` §9, used in §9).

| # | Question | Recommendation |
|---|---|---|
| 1 | Animation frame durations (§7): 600/110/90/400 ms | ship as written; they are presentation values, tune on feel |
| 2 | Tint values (§6) | ship as written; they are calibration knobs for mood, not mechanics — the two region tints and the six state tints are the only values the art needs |
| 3 | Non-human actor art (§5.2) — three actors are font glyphs because no vendored pack has a drone, a hound or a spirit in 16×16 | accept for v1 and commission three hand-drawn 16×16 glyphs later; they are **not** code, they are additions to `U+E13C`, `U+E160`, `U+E16C` |
| 4 | Font (§10): `DECISIONS.md` §14 Q2 leaves TTF (Cozette) versus a bitmap font open. The license claims are no longer in dispute — §12 now records Cozette as MIT and Spleen as BSD-2-Clause | Spleen 8×16 BDF, BSD-2-Clause, fetched into `assets/vendor/fonts/`; the file is a manual fetch either way (§13 #2) |
| 5 | DCSS mode (§5.6): a 40×22 console is a different game view (fewer cells, different UI geometry) | keep DCSS as a comparison atlas only until a 32×32 pass is actually wanted; if wanted, it is a `--tile-size=32` view module variant, not a mixture |
| 6 | Future City 27 use (§5.4): backdrop or unused? | backdrop panel for the Hub and job briefs |

## 13. Manual steps

Handoffs. Nothing below exists on disk; nothing below was faked.

| # | What | Exact location |
|---|---|---|
| 1 | **0x72 16×16 Dungeon Tileset II** — `DECISIONS.md` §12's *intended* interiors pack, now an optional manual step because interiors are covered by Kenney Roguelike Modern City (§5.3). The download needs an itch.io browser session: `https://0x72.itch.io/dungeontileset-ii/download` returns "We couldn't find your page" for a session-less request, and the item page carries no direct file link. **License is verified** from the item's own info table on `https://0x72.itch.io/dungeontileset-ii`: `license` = *Creative Commons Zero v1.0 Universal*. | Download the ZIP in a browser, extract into `assets/vendor/0x72-dungeon-tileset-ii/`, keep the sheets and any readme, delete the ZIP, then write `assets/vendor/0x72-dungeon-tileset-ii/LICENSE.md` (author 0x72, source URL above, CC0, attribution not required, download date, verified-at: that item page). Verify the sheet grid before binding (§5.5) |
| 2 | **Spleen font** (§10). BSD-2-Clause, not MIT (MIT is Cozette's); grab the release for `8x16`. | `https://github.com/fcambus/spleen/releases` → `assets/vendor/fonts/spleen-8x16.bdf` + `LICENSE` |
| 3 | **Cozette**, only if the bitmap font is ever swapped for a TTF (`DECISIONS.md` §14 Q2). MIT license, and the vector `CozetteVector.ttf` is upstream's own compatibility flag ("doesn't look right at any size") — bitmap `.bdf`/`.otb` only. | `https://github.com/the-moonwitch/Cozette/releases` |
| 4 | **DawnLike** — `DECISIONS.md` §12 lists it as CC-BY 4.0 with attribution required. Not vendored in this phase; if it is ever added it needs a visible credit line, unlike every pack in §2. | OpenGameArt, `DawnLike` |
| 5 | The per-prop codepoint audit (§5.1, `U+E200–U+E27F`) needs a human eye on the shipped `Preview.png` / sheet — 128 slots, roughly ten minutes with the sheet open. | `assets/vendor/kenney-rpg-urban-pack/Preview.png` |

## 14. Licenses and obligations

| Pack | Path | License | Attribution required? | Source of truth |
|---|---|---|---|---|
| Kenney RPG Urban Pack | `assets/vendor/kenney-rpg-urban-pack/` | CC0 1.0 | **No** (credit requested) | in-pack `License.txt` + kenney.nl page; role: Hub and city-Site sheet |
| Kenney Roguelike Modern City | `assets/vendor/kenney-roguelike-modern-city/` | CC0 1.0 | **No** (credit requested) | in-pack `License.txt` + kenney.nl page; role: interiors and furniture sheet (DECISIONS §12) |
| Future City 27 | `assets/vendor/future-city-27/` | CC0 1.0 | **No** | OpenGameArt item page (`license` = CC0), author `knekko` |
| DCSS tiles (Nov-2015 export) | `assets/vendor/dcss-tiles/` | CC0 (with the upstream caveat) | **No** | repo `README.md`/`ARTISTS.md`; caveat list `TILES_UNDER_UNKNOWN_LICENSE.md` |
| 0x72 Dungeon Tileset II | *not vendored — optional manual step* | CC0 1.0 | **No** (credit requested) | itch.io item info table; §13 #1 |
| DawnLike | *not vendored* | **CC-BY 4.0** | **YES — attribution required** | `DECISIONS.md` §12; must be credited visibly if used |
| Spleen 8×16 | *not vendored* | BSD-2-Clause | No (license text must ship) | github.com/fcambus/spleen |
| Cozette | *not vendored* | MIT (not OFL) | No (license text must ship) | github.com/the-moonwitch/Cozette |

CC0 permits commercial use, modification and redistribution with no attribution, so shipping
the game requires nothing from any vendored pack; the project credits Kenney in the README
anyway because the pack asks for it. BSD/MIT fonts require their license text to travel with
the binary — copy `LICENSE` into `assets/vendor/fonts/` when the font is vendored.

The interiors licensing is settled without 0x72: Kenney Roguelike Modern City is vendored, CC0, and
is the interiors and furniture source (`DECISIONS.md` §12), so no interior art in v1 depends on a
manual fetch. 0x72 stays an optional upgrade that inherits the same CC0 terms.

Assets whose licenses are unclear must not be added: the project has no per-file
attribution tracking, only per-pack `LICENSE.md`.

## Sources

Borrowed patterns, in the order used:

- `.agents/skills/roguelike/SKILL.md` — Pattern 3 ("FOV + explored memory") is the source of
  the three-state cell classification in §8, and its "use a proven algorithm, never a naive
  raycast" note is why FOV stays in its own module and the renderer only reads two byte
  arrays (ADR-0004). §3 of `references/generation-fov-loot.md` is the octant/shadowcasting
  reference that module implements.
- `.agents/skills/pygame-core/SKILL.md` and
  `.agents/skills/pygame-core/references/sprites-and-collision.md` — sheet slicing with
  `subsurface`, frame-animation timing, `LayeredUpdates` as the z-order analogue of §9, and
  the escape-hatch table in §11.
- `.agents/skills/create-game-assets/references/provenance.md` — the per-asset record fields
  used in every vendored `LICENSE.md`, and "do not treat free as a license".
- `.agents/skills/create-game-assets/references/art-direction.md` — semantic colour roles
  (§6 is a role table, not a colour cloud) and the "must read at native scale" rule that
  decides the tint-over-glyph choices in §7.

API facts in §3 are from python-tcod 21.2.1 (`tcod/tileset.py`, `tcod/console.py`,
`tcod/context.py`, typed stubs) and libtcod's `src/libtcod/tileset_render.c`.

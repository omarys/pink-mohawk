# Kenney RPG Urban Pack — license record

| Field | Value |
|---|---|
| Pack | RPG Urban Pack 1.0 |
| Author | Kenney (Kenney Vleugels), kenney.nl |
| Source page | https://kenney.nl/assets/rpg-urban-pack |
| Downloaded from | https://kenney.nl/media/pages/assets/rpg-urban-pack/0a097d1dc7-1677578575/kenney_rpg-urban-pack.zip |
| Download date | 2026-09-17 |
| License | CC0 1.0 Universal (Public Domain Dedication) |
| Attribution legally required | **No** |
| License verified at | 1. the archive's own `License.txt` (shipped here, kept); 2. the pack page above (author's own site) |

The in-archive `License.txt` states: *"License: (Creative Commons Zero, CC0)
http://creativecommons.org/publicdomain/zero/1.0/ ... This content is free to use in
personal, educational and commercial projects. Support us by crediting Kenney or
www.kenney.nl (this is not mandatory)"*. Credit is requested, not required; this project
credits Kenney in the README credits block anyway.

## What was kept

Extracted `Tilemap/` (the sheets), the pack docs and previews; the 486 per-tile
`Tiles/tile_XXXX.png` files were deleted after extraction. No `.zip` was committed.

## Verified contents

| File | Size | Grid | Tile |
|---|---|---|---|
| `Tilemap/tilemap_packed.png` | 432×288 | 27 cols × 18 rows = 486 tiles | 16×16, no spacing |
| `Tilemap/tilemap.png` | 458×305 | same 27×18 grid | 16×16, 1px spacing |

`Tilemap/tilemap.txt` (shipped) confirms `Tile width: 16px`, `Tile height: 16px`,
`Margin: 0px`, `Spacing: 1px`. **Load `tilemap_packed.png`, never `tilemap.png`** —
`tcod.tileset.load_tilesheet` assumes the tiles fill the image, so the 1px-spaced
version silently desynchronises from the grid.

# spleen-8x16.bdf

| | |
|---|---|
| Author | Frederic Cambus |
| Source | https://github.com/fcambus/spleen (release 2.2.0) |
| License | BSD-2-Clause — full text in `LICENSE-spleen` |
| Attribution required | No. The license text must be retained, which this file and `LICENSE-spleen` do. |
| Downloaded | 2026-09-17 |
| License verified at | the release tarball's own `LICENSE` file (primary source) |

Chosen over Cozette per `docs/art/pipeline.md` §10: native height is exactly 16px, so a glyph
is a byte-for-byte paste into the left 8 columns of a 16×16 cell with no rasterisation step.
A TTF would rasterise at an arbitrary size and fight the pixel grid. Coverage is ASCII plus
CP437, which supplies the box-drawing and block characters the UI band uses.

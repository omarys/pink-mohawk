# python-tcod for display, hand-written algorithms beneath it

python-tcod owns the window, input, tileset rendering, and event loop. It does *not* own the interesting algorithms: FOV, pathfinding, the turn scheduler, and Site generation are written by hand because practising data structures and algorithms is an explicit goal of this project. libtcod's FOV, `Pathfinder`, and `BSP` exist and are deliberately unused.

**Considered options**: tcod end-to-end with its FOV and pathfinding (rejected: it deletes the practice the project exists to provide); pygame-ce with a hand-built renderer (rejected for now: weeks of surface/blit/camera plumbing before the first playable frame); a renderer interface with both implementations (rejected: an interface with one implementation is a seam for a hypothetical).

**Consequences**: tcod's renderer is a character console, so every visual is one Glyph in one cell — no overlapping, rotated, or multi-cell sprites, and no scaling inside a tileset. That ceiling is accepted and documented rather than worked around; if it ever binds, the documented escape hatch is to keep tcod for FOV and input while rendering with pygame-ce, which is a contained change to one module.

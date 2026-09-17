"""Pink Mohawk — a turn-based tactical roguelite.

Layer law (docs/design/data-model.md §15): `tcod` may appear in exactly three modules —
`render`, `input`, `main`. Nothing in layers 0-3 may import it, which is what keeps every
algorithm in this package testable headless. Enforced by tools/check_layers.py.
"""

__all__: list[str] = []

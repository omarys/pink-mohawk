"""Enforce the layer law from docs/design/data-model.md §15.

`tcod` may appear in exactly three modules: render.py, input.py, main.py. Everything in
layers 0-3 is display-free, which is why every algorithm in this project can be exercised by
its own `__main__` self-check with no window and in CI.

    .venv/bin/python tools/check_layers.py
"""

from __future__ import annotations

import ast
import pathlib
import re

PACKAGE = pathlib.Path(__file__).resolve().parent.parent / "pinkmohawk"
ALLOWED_TCOD_IMPORTERS = {"render.py", "input.py", "main.py"}

# algorithms may not import the domain: they operate on coordinates, arrays and plain data
ALGORITHM_MODULES = {
    "fov.py",
    "pathfinding.py",
    "scheduler.py",
    "mission_graph.py",
    "embed.py",
    "placement.py",
    "bt.py",
    "utility.py",
}
FORBIDDEN_FOR_ALGORITHMS = {"entities.py", "rules.py", "security.py"}


def imported_modules(path: pathlib.Path) -> set[str]:
    """Top-level module names imported by a file, via AST rather than regex."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    return found


def main() -> int:
    if not PACKAGE.exists():
        print(f"no package at {PACKAGE}")
        return 1

    failures: list[str] = []
    for path in sorted(PACKAGE.glob("*.py")):
        imports = imported_modules(path)

        if "tcod" in imports and path.name not in ALLOWED_TCOD_IMPORTERS:
            failures.append(
                f"{path.name}: imports tcod but is not one of {sorted(ALLOWED_TCOD_IMPORTERS)}"
            )

        if path.name in ALGORITHM_MODULES:
            illegal = imports & FORBIDDEN_FOR_ALGORITHMS
            if illegal:
                failures.append(f"{path.name}: algorithm imports the domain ({sorted(illegal)})")

    # the renderer seam should also be discoverable by plain grep, as a second opinion on the AST
    grep_hits = {
        p.name
        for p in PACKAGE.glob("*.py")
        if re.search(r"^\s*(import\s+tcod|from\s+tcod)", p.read_text(encoding="utf-8"), re.M)
    }
    if grep_hits != {n for n in grep_hits if n in ALLOWED_TCOD_IMPORTERS}:
        failures.append(f"grep found tcod in {sorted(grep_hits - ALLOWED_TCOD_IMPORTERS)}")

    if failures:
        print("LAYER LAW VIOLATIONS:")
        for line in failures:
            print("  " + line)
        return 1

    print(
        f"OK  layer law holds across {len(list(PACKAGE.glob('*.py')))} modules "
        f"(tcod importers: {', '.join(sorted(grep_hits)) or 'none'}; allowed: {sorted(ALLOWED_TCOD_IMPORTERS)})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

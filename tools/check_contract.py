"""Check that pinkmohawk/constants.py still matches the tables in docs/design/DECISIONS.md.

`constants.py` claims to hold "every number from DECISIONS.md", and until now nothing enforced it.
The drift this catches is not hypothetical: across this project's review rounds the same figure has
been restated in two documents and diverged repeatedly — gear prices, Clock ticks, energy costs,
save field names, the `objective` key. A number with two homes needs a check, or it has two values.

    .venv/bin/python tools/check_contract.py      # exit 1 on any mismatch

Scope: the numeric tables only. Prose rules are not machine-checkable, and the few tables whose
values are formulas (Drain, Spirit attacks) are checked for their integer columns only.
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "design" / "DECISIONS.md"

problems: list[str] = []
checked = 0


def table_after(md: str, header: str) -> list[list[str]]:
    """Cells of every row in the first markdown table whose header line starts with `header`."""
    i = md.find(header)
    if i < 0:
        raise LookupError(f"table not found in DECISIONS.md: {header!r}")
    rows: list[list[str]] = []
    for line in md[i:].splitlines()[1:]:
        s = line.strip()
        if not s.startswith("|"):
            if rows:
                break
            continue
        if set(s) <= set("|-: "):  # the |---|---| separator
            continue
        rows.append([c.strip() for c in s.strip("|").split("|")])
    return rows


def key(label: str) -> str:
    """'Heavy pistol' -> heavy_pistol; 'Ammunition (per reload)' -> ammunition."""
    label = re.sub(r"\s*\(.*?\)", "", label)
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")


def leading_int(text: str) -> int | None:
    # Strip thousands separators first: "1,200" is 1200, not 1. (This bug was in the checker's
    # own first run, and it looked exactly like a contract drift of eight prices.)
    cleaned = text.replace(",", "").replace("−", "-").replace("+", "")
    m = re.search(r"[-+]?\d+", cleaned)
    return int(m.group()) if m else None


def expect(where: str, label: str, doc_value: object, code_value: object) -> None:
    global checked
    checked += 1
    if doc_value != code_value:
        problems.append(
            f"{where}: {label}: DECISIONS says {doc_value!r}, constants says {code_value!r}"
        )


def check_clock(md: str, C) -> None:
    for cells in table_after(md, "| Event | Segments |"):
        k, v = key(cells[0]), leading_int(cells[1])
        if k in C.CLOCK_TICKS and v is not None:
            expect("clock ticks", k, v, C.CLOCK_TICKS[k])


def check_devices(md: str, C) -> None:
    for cells in table_after(md, "| Device | Rating |"):
        k, v = key(cells[0]), leading_int(cells[1])
        if k in C.DEVICE_RATINGS and v is not None:
            expect("device ratings", k, v, C.DEVICE_RATINGS[k])


def check_armour(md: str, C) -> None:
    for cells in table_after(md, "| Armor | Rating |"):
        k, v = key(cells[0]), leading_int(cells[1])
        if k in C.ARMOUR and v is not None:
            expect("armour", k, v, C.ARMOUR[k])


def check_weapons(md: str, C) -> None:
    for cells in table_after(md, "| Weapon | DV | AP |"):
        k = key(cells[0])
        if k not in C.WEAPONS:
            continue
        dv, code, ap, _range = C.WEAPONS[k]
        expect("weapon AP", k, leading_int(cells[2]), ap)  # AP is always an integer
        m = re.fullmatch(r"(\d+)([PS])", cells[1])
        if m:  # formula DVs are skipped
            expect("weapon DV", k, int(m.group(1)), dv)
            expect("weapon code", k, m.group(2), code)


def check_energy(md: str, C) -> None:
    for cells in table_after(md, "| Action | Cost |"):
        k, v = key(cells[0]), leading_int(cells[1])
        if k == "sprint":
            k = "sprint_per_3_tiles"
        if k in C.ENERGY_COSTS and v is not None:
            expect("energy costs", k, v, C.ENERGY_COSTS[k])


def check_gear(md: str, C) -> None:
    # four columns: | item | price | item | price |
    for cells in table_after(md, "| Item | Price |"):
        for i in range(0, len(cells) - 1, 2):
            k, v = key(cells[i]), leading_int(cells[i + 1])
            if k in C.GEAR_PRICES and v is not None:
                expect("gear prices", k, v, C.GEAR_PRICES[k])


def check_weights(md: str, C) -> None:
    for cells in table_after(md, "| archetype | `w_threat` |"):
        k = key(cells[0])
        if k not in C.ARCHETYPE_WEIGHTS:
            continue
        want = C.ARCHETYPE_WEIGHTS[k]
        for label, cell, field in (
            ("w_threat", cells[1], "w_threat"),
            ("w_visible", cells[2], "w_visible"),
            ("w_objective", cells[3], "w_objective"),
            ("w_ally_risk", cells[4], "w_ally_risk"),
            ("hysteresis", cells[5], "hysteresis"),
        ):
            expect("archetype weights", f"{k}.{label}", float(cell), want[field])
        expect(
            "archetype weights",
            f"{k}.morale_bonus",
            None if cells[6] == "—" else leading_int(cells[6]),
            want["morale_bonus"],
        )
        expect(
            "archetype weights",
            f"{k}.flee_threshold",
            None if cells[7].startswith("never") else leading_int(cells[7]),
            want["flee_threshold"],
        )


def main() -> int:
    if not DOC.exists():
        print(f"missing {DOC}")
        return 1
    md = DOC.read_text()
    sys.path.insert(0, str(ROOT))
    from pinkmohawk import constants as C  # imported late so --help works without the package

    for check in (
        check_clock,
        check_devices,
        check_armour,
        check_weapons,
        check_energy,
        check_gear,
        check_weights,
    ):
        before = len(problems)
        check(md, C)
        name = check.__name__.removeprefix("check_")
        print(f"  {'ok ' if len(problems) == before else 'MISMATCH'} {name}")

    if problems:
        print(f"\n{len(problems)} mismatch(es) between DECISIONS.md and constants.py:")
        for p in problems:
            print("  " + p)
        print("\nDECISIONS.md is the source of truth: fix constants.py, or change the document.")
        return 1

    print(f"\nOK  {checked} values agree between DECISIONS.md and constants.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

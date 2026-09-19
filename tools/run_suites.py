"""Run every module's acceptance test, discovering the modules rather than listing them.

A hand-maintained list of suite names had already started to drift: `render.py` and `main.py` have no
`demo()` because their acceptance test needs a whole frame's worth of setup and lives in `check()`, so
the list had to be kept in the handoff, in the pre-commit hook and in the author's head at once. The
rule here is structural instead, so adding a module adds its suite by existing:

    a module defining `def demo()`   ->  python -m pinkmohawk.<module>
    a module defining `def check()`  ->  python -m pinkmohawk.<module> --check

A module with both runs both, which nothing does today and nothing has to decide about later.

Each suite runs in its own interpreter on purpose. The demos are assert-based and a few of them build
whole Runs and Sites, so sharing one process would let a module's import-time state leak into the next
one's results - and the layer law's whole point is that each module is runnable alone.

    .venv/bin/python tools/run_suites.py           # every suite; exit 1 if any fails
    .venv/bin/python tools/run_suites.py -v        # plus each suite's own one-line summary
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "pinkmohawk"

#: A definition at column 0, so a nested `def demo()` or a mention in prose does not count.
DEMO = re.compile(r"^def demo\(\)", re.M)
CHECK = re.compile(r"^def check\(\)", re.M)


def suites() -> list[tuple[str, list[list[str]]]]:
    """Every module that has an acceptance test, and the argument lists that run it."""
    found: list[tuple[str, list[list[str]]]] = []
    for path in sorted(PACKAGE.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        variants: list[list[str]] = []
        if DEMO.search(source):
            variants.append([])
        if CHECK.search(source):
            variants.append(["--check"])
        if variants:
            found.append((path.stem, variants))
    return found


def run(module: str, args: list[str]) -> tuple[int, str]:
    """One suite, in its own interpreter, from the repository root."""
    result = subprocess.run(
        [sys.executable, "-m", f"pinkmohawk.{module}", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, (result.stdout + result.stderr).strip()


def main(argv: list[str] | None = None) -> int:
    verbose = any(
        flag in (argv if argv is not None else sys.argv[1:]) for flag in ("-v", "--verbose")
    )
    started = time.perf_counter()
    passed = 0
    failures: list[tuple[str, str]] = []

    for module, variants in suites():
        for args in variants:
            label = " ".join([module, *args])
            code, output = run(module, args)
            if code:
                failures.append((label, output))
                print(f"  FAIL {label}")
            else:
                passed += 1
                if verbose:
                    summary = (output.splitlines() or [""])[-1][:72]
                    print(f"  ok   {label:<26} {summary}")

    elapsed = time.perf_counter() - started
    total = passed + len(failures)
    if failures:
        print(f"\n{len(failures)} of {total} suites failed:\n")
        for label, output in failures:
            print(f"--- {label} ---")
            print(output or "(no output)")
            print()
        return 1

    print(f"OK  {passed}/{total} suites pass in {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# Pink Mohawk

A turn-based tactical roguelite about running a four-person shadowrunner crew through corporate jobs in
a cyberpunk sprawl. Named for the loud, flashy style of running — the exact style the Security Clock
exists to punish.

Python 3.14 and [tcod](https://python-tcod.readthedocs.io/), no engine. It is a learning project with
a syllabus: the data structures and algorithms are written by hand, one per subsystem, and
`docs/design/data-model.md` is where each of them is specified, costed and given a runnable self-check.
That document and `docs/design/DECISIONS.md` are the point as much as the game is.

## Status

Phases 0–2 of `docs/roadmap.md` are complete; 3 and 4 are not started. **v1 is not finished.**

What runs today: an authored 80×38 Hub with a Job board, three Legwork actions, shops and a clinic; a
Fixer conversation you can negotiate with through a JSON dialogue graph; a procedurally generated,
union-find-verified Site with FOV, a Security Clock and Behavior Tree enemies; and a schema-versioned
save that carries the crew and the world forward. Phase 3 adds Perks, XP, the other three Job types,
Totems and factions; Phase 4 is polish — making it readable, audible, animated and safe to patch.

## Setup

Requires [mise](https://mise.jdx.dev/). `mise.toml` pins every tool and dependency version.

```bash
mise run setup      # create .venv, install tcod/numpy/mypy at the pinned versions
mise run hooks      # install the pre-commit hook (once per clone)
```

## Play

```bash
.venv/bin/python -m pinkmohawk.main          # continue the save in saves/
.venv/bin/python -m pinkmohawk.main --new    # start a new campaign
```

Arrows or `hjkl` to move. Walk into the safehouse, the Fixer's bar, the shop, the clinic or the
Transit tile; the UI band lists the verbs that work where you are standing, and `input.py` is the only
place the key map lives.

The Hub is turn-based — one Step is one tick, and a day is `HUB_TICKS_PER_DAY` of them. Taking a Job,
spending Legwork and walking all cost time, and time is what the Security Clock is made of.

## Check

```bash
mise run check
```

That is the whole gate, and it is the same six pieces the pre-commit hook runs, in about three
seconds: `ruff format --check`, `ruff check`, `mypy`, `tools/check_contract.py`,
`tools/check_layers.py`, `tools/run_suites.py`. Individually they are `mise run fmt-check`, `lint`,
`types`, `contract`, `layers` and `suites`; `mise tasks` lists them.

**Every module carries its own acceptance test.** There is no test framework — a module's `demo()` is
both its test and its documentation, and it runs standalone:

```bash
.venv/bin/python -m pinkmohawk.fov        # the demo, and its asserts
```

`tools/run_suites.py` finds every module with a `demo()` (run plain) or a `check()` (run with
`--check`) and runs each in its own interpreter, so **adding a module adds its suite by existing**.

## The two rules the code is shaped by

**The layer law.** `tcod` may be imported by exactly three modules — `input.py`, `render.py`,
`main.py` — and the eight algorithm modules may not import the domain (`entities`, `rules`, `security`)
at all. Everything else operates on coordinates, arrays and plain data, which is why every algorithm can
be exercised headlessly and in CI. `tools/check_layers.py` enforces it, including that `dialogue.py`
never imports the campaign it drives.

**One home per number.** `docs/design/DECISIONS.md` is the contract. `pinkmohawk/constants.py` holds
its values and cites the section each came from, and `tools/check_contract.py` fails the build when the
two disagree — 134 values today. A hand-written number in the code is a bug in one of the two files.

## Where the truth lives

| | |
|---|---|
| `CONTEXT.md` | The glossary, and nothing else. Start here for a term you don't know. |
| `docs/roadmap.md` | The phases, what each one builds, and the acceptance test for it. |
| `docs/design/DECISIONS.md` | Every number and resolved question. The contract. |
| `docs/design/data-model.md` | The algorithms: data structure, complexity, pseudocode, self-check. |
| `docs/design/world.md` | The Hub, the Job loop, Site generation, Heat, persistence. |
| `docs/design/dialogue.md` | The dialogue graph format, evaluator, effects and runner. |
| `docs/design/ai.md`, `enemies.md`, `classes.md`, `rules.md` | Brains, stat blocks, the four Runners, the d6 pool rules. |
| `docs/adr/` | Twelve decisions, each with the alternative it beat. |
| `docs/art/pipeline.md` | The tcod recipe, cell states, draw order, and the asset licence table. |
| `docs/HANDOFF.md` | A working note for whoever picks this up next. Transient, not contract. |

## Layout

```
pinkmohawk/     the game: 28 modules, ~15k lines, layered 0 (rng, grid) to 4 (main)
data/           content as data: stat blocks, Behavior Trees, dialogue graphs, the Hub, shops, Jobs
tools/          the two checkers and the suite runner that `mise run check` calls
docs/           the design documents above
assets/vendor/  art and fonts, each with its own licence
spike/          the Phase 0 throwaway probe, excluded from linting
```

## Requirements and licensing

Everything is pinned in `mise.toml`; nothing needs installing globally. The venv holds `tcod 21.2.1`,
`numpy 2.5.3` and `mypy 2.3.1`, while ruff, black, pre-commit and uv come from mise so there is one
copy of each on the machine.

This repository has **no LICENSE file yet**. The vendored art and fonts are third-party and each
carries its own terms — Kenney's packs and Future City 27 are CC0, the Spleen font is BSD-2-Clause —
listed in `docs/art/pipeline.md` and `docs/design/DECISIONS.md` §12. Anything published from here needs
that column read first.

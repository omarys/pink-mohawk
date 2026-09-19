# Handoff — Pink Mohawk

A working note for the next agent, **not** part of the design contract. Phase 2 is complete; Phase 3
("Depth") is next. Written at commit `54f729b`, working tree clean.

Delete or refresh this file once its contents are absorbed — the project's rule is that the design
docs are the source of truth, and a stale handoff would be a second one.

---

## 1. Where this stands

`docs/roadmap.md` owns the phase plan and each phase's acceptance criteria. Phases 0, 1 and 2 are
complete and verified; Phase 3 and 4 are not started.

- **Phase 1** — the Run vertical slice. Its acceptance test is `run.demo()` (roadmap Phase 1, points
  1–7).
- **Phase 2** — Hub, dialogue, legwork, shops, economy, persistence, and the display for them. Its
  acceptance test is `session.demo()` (roadmap Phase 2, points 1–5), and `main --check` drives the
  same loop through real key commands.
- **Where the numbers live** — `docs/design/DECISIONS.md` §16 now fixes every Phase 2 parameter, and
  `tools/check_contract.py` enforces all 134 values between that file and `pinkmohawk/constants.py`.
  A number that appears in code without a contract row is a bug in one of the two.

The full architecture, layer law and algorithm choices are in `docs/design/data-model.md` (§15 is the
layer law), with the rationale in `docs/adr/`. The design docs for the systems Phase 3 extends are
`docs/design/world.md` (§3 Legwork, §4 Job types, §5–7 Sites and devices), `docs/design/classes.md`
(§6 obstacle matrix, §7.3 Spirit attacks), `docs/design/enemies.md` (§7 device placement) and
`docs/design/ai.md`.

## 2. How to verify (the operating ritual)

From the repo root, one command:

```bash
mise run check
```

That is `ruff format --check`, `ruff check`, `mypy`, `tools/check_contract.py`,
`tools/check_layers.py` and `tools/run_suites.py`, in that order — the same six pieces the pre-commit
hook runs, so a clean commit and a clean `mise run check` mean the same thing. Individually they are
`mise run fmt-check`, `mise run lint`, `mise run types`, `mise run contract`, `mise run layers` and
`mise run suites`; `mise tasks` lists them.

The last two are the interesting ones and neither takes a module list:

- `tools/check_layers.py` enforces the layer law — `tcod` may appear only in `input.py`, `render.py`
  and `main.py`, and `dialogue.py` may not import the campaign.
- `tools/run_suites.py` finds every module with a `demo()` (run plain) or a `check()` (run with
  `--check`) and runs each in its own interpreter. **Adding a module adds its suite by existing**, so
  there is no list to keep. `-v` shows each suite's own summary line.

Expected: 25/25 suites, mypy clean on 31 files, 134 contract values, layer law across 28 modules,
about three seconds end to end.

```bash
SDL_VIDEODRIVER=dummy .venv/bin/python -m pinkmohawk.main --frames 5   # real window loop, no display
```

The environment itself is `mise run setup` (venv plus pinned dependencies) and `mise run hooks` (the
pre-commit hook, once per clone); `mise.toml` holds every tool and dependency pin.

**Toolchain placement matters and is easy to get wrong.** `ruff` is on `PATH` via `mise` (pinned in
`mise.toml`); `mypy` and `tcod` exist **only** in `.venv`. So `ruff check` works bare, but everything
that imports the package must run as `.venv/bin/python -m pinkmohawk.<module>`. Running `python -m
pinkmohawk.render` with the system interpreter fails with an import error that looks like a code
failure and is not one.

## 3. Traps worth not re-learning

**Contract discipline.** One home per number. A duplicate that is *not* caught by the checker is the
recurring defect: `content._gear` once clamped every device rating to a literal 3 while
`DEVICE_RATINGS` said otherwise, and the wound modifier has been copied four separate times. It now
lives only in `entities.wound_modifier_from_boxes`, which `Actor.wound_modifier`, `rules.wound_modifier`
and the Hub's `pool_bonus` all call.

**The layer law has a second half.** Beyond tcod, `tools/check_layers.py` now also enforces that
`dialogue.py` never imports `campaign.py`, `save.py` or `hub.py`. That is what keeps the dialogue
engine's demo runnable against a stub host. If you find yourself wanting to import the campaign into
the engine, the seam is wrong, not the check.

**Three modules built from the same doc still disagreed.** Lanes coded against `dialogue.md` §5.2's
protocol asked for `spec(key).type`; `campaign.py` implemented `kind`. When parallel work meets, check
the *protocol surface* first (method names, property vs method, field names) — the demos can all be
green while the seam is broken.

**Property vs method.** `hub.legwork_remaining` and `hub.shop_open` are properties. Both cost a crash
or a mypy error to learn.

**`main.Panel` actions may close or replace their own panel** (taking a Job closes the board; the shop
replaces itself once the Buy Gear action is spent). `hub_command` writes the action's result back to
whichever screen is showing, falling back to the Hub status line.

**Engine rules the display and tests have already tripped over:**

- `job.*` store keys need a *bound* Job, so the board comes before the Fixer's negotiation —
  `take_job` → `campaign.begin_job` is what binds it.
- `hub.take_job` and `hub.legwork` each cost one hub day (§1.3), and a day's rest heals two boxes,
  Stun first. Set up test state *after* them, or you measure the recovery.
- `run.extract` pro-rates on `crew_at_objective()`, which needs a living Runner on the **Paydata cell**
  (`run.paydata_cell()`), not merely in the objective room.
- The gear shop needs §3.2's Buy Gear Legwork action spent before it sells anything, and its stock is
  a seeded draw of `SHOP_STOCK_SIZE` items.

**libtcod.** Remapping a codepoint to sheet cell `(0, 0)` does not bind it (verified by probe:
`x=0,y=0` reports absent, `x=1` and `y=1` bind), which is why terrain starts at column 1.

**Python 3.14 accepts `except A, B:` without parentheses** (PEP 758). It reads exactly like Python 2's
binding syntax, so it survives review and compiles — parenthesise it anyway.

**Editing by script.** `ruff format` moves line numbers and re-wraps long lines, so text anchors go
stale between calls. Validate *every* anchor before writing anything, and if an edit call is rejected,
re-grep the real text rather than re-guessing it.

## 4. What Phase 2 leaves as known gaps

- **The display has never been looked at by a human.** It is verified headless and under
  `SDL_VIDEODRIVER=dummy`. The tile-sheet indices behind actors and devices are still
  `docs/art/pipeline.md` §5's budget "rounded to something is here"; aligning them wants eyes on a
  screen.
- **The Job board draws only `extraction` Jobs**, which is why the economy assertions land on exactly
  12,000¥. The other three types are Phase 3 work (`world.md` §5.3's `JOB_GRAPH` templates,
  `docs/jobs.json` already carries the `paydata` → `extraction` alias).
- **Perks and inverted XP are unimplemented** — but the hook exists: `session.CampaignHost.on_test`
  records every resolved social roll for ADR-0006's payout, and `ActiveJob.ledger` is the persisted
  place for it.
- **No save migration.** `save.py` writes `schema_version` and refuses anything newer; per the
  roadmap that is Phase 4.
- **Faction reputation beyond the Fixer** is stored and clamped, and nothing changes it yet.

## 5. Suggested skills

Call these when the work matches; they are the ones this session actually used.

| Skill | When |
|---|---|
| `python-patterns` | Before writing or reviewing any Python here. It is the standard the codebase's style was reviewed against. |
| `pi-subagents` | Before any delegation. Read it first — the agent roster matters: `scout`, `worker`, `reviewer`, `delegate`, `oracle`, `researcher`, `evidence-auditor` exist; **`explorer` does not**, and an unknown agent name fails the whole workflow. |
| `code-review` | To review a branch or a range since a commit. It runs standards and spec reviews in parallel children. |
| `save-systems` | For Phase 4's schema migration, atomic writes and slot policy (ADR-0012, `world.md` §10). |
| `roguelike` | For Phase 3's Perks, inverted XP (ADR-0006) and run structure. |
| `procedural-gen` | For the remaining Job types, loot tables and seeded placement. |
| `dialogue-systems` | Before authoring or extending any conversation (`dialogue.md` is the spec). |
| `game-ui-ux` | For the Hub screens, focus and key navigation, and any new panel. |
| `diagnosing-bugs` | When something breaks and the cause is not obvious from the traceback. |
| `checkpoint-before-empty` | When context is nearly exhausted mid-task — write a checkpoint rather than abandoning half-finished work. |
| `writing-for-agents` | Before editing `AGENTS.md` or adding a skill. |
| `unslop` | For any prose that goes into a doc. |

## 6. Context the next agent cannot get from the repo

- The design-condensation artifacts this phase was built from live outside the tree, under the
  session's `subagent-artifacts/phase2-spec.md` and `phase2-data.md`. They are convenience summaries
  and may be pruned; **the documents they condensed are in `docs/design/` and are authoritative.**
- Nothing in this session needs redacting: no credentials, tokens or personal data were involved. The
  gameplay save that had been committed was checked and contains only crew sheets, nuyen, Heat,
  reputation and flags — it is now gitignored (`54f729b`).

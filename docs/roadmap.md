# Pink Mohawk — Implementation Roadmap

Risk-first implementation order for the v1 contract in `docs/design/DECISIONS.md`. Ordering rule: build the thing that can kill the project first, then the thing that proves the loop, then breadth, then polish. Every number below is quoted from `DECISIONS.md`; nothing new is invented here (see **Open questions**).

The four learning goals, referenced as ids throughout:

- **G1 — data structures & algorithms.** The syllabus in `DECISIONS.md` §13.
- **G2 — game development.** The loop, the turn engine, content, economy, persistence.
- **G3 — AI behaviour scripting.** Behavior Trees, Blackboards, Utility Scores, Dialogue Graphs.
- **G4 — graphics handling.** python-tcod consoles, Tilesets, Remaps, Glyphs, draw order, animation.

## Why this order

The four highest-risk decisions are the ones worth failing early:

1. **ADR-0004** — tcod renders one Glyph per cell and nothing else. If that ceiling is unacceptable, the whole renderer changes, so prove it in Phase 0.
2. **ADR-0011** — Mission Graph *then* embed is the project's richest algorithm exercise and the one whose failure is invisible (a connected map that is a boring Site is still "working"). Build it in Phase 1 where there is no Hub to blame.
3. **ADR-0003** — Initiative Score as Energy means one number controls both turn frequency and actions-per-turn; the roadmap tracks it as the standing balance risk, not a Phase 4 cleanup.
4. **ADR-0009 / ADR-0010** — AI and dialogue are data we must author, validate, and debug ourselves. They are content pipelines, so they get built before the content that depends on them.

---

## Phase 0 — Spike: tcod renders a Tileset and takes input

**Goal.** In one evening, prove python-tcod opens a window, draws a Tileset Glyph, and reacts to a keypress.

**Systems built.** One file (`spike/tcod_probe.py`): tcod context/console at 1280×720 with 16px tiles, Tileset load plus a Remap binding a codepoint to a cell, one Glyph drawn per cell, keyboard event loop, quit on Esc.

**Algorithms / data structures (DECISIONS §13).** None. This phase deliberately writes no project algorithm — it characterises the third-party renderer boundary (ADR-0004) before any of our own code sits on it.

**Acceptance test.** `python spike/tcod_probe.py` opens a 1280×720 window, renders the loaded urban Tileset with at least one Remap resolved to a visible cell, moves a Glyph one cell per arrow-key press, and exits cleanly (code 0, no traceback) on Esc.

**Non-goals.** No `src/`, no tests directory, no map, no FOV, no game loop structure, no assets beyond the one Tileset. Throw the file away when Phase 1 starts.

**Estimate.** 0.5 day.

---

## Phase 1 — Mission vertical slice

**Goal.** One complete Run of the paydata-extraction Job, played start to finish on a generated Site, with all four learning goals exercised end to end.

**Systems built.**

| System | Detail |
|---|---|
| Map | dense 2D tile array plus `explored` and `visible` byte arrays |
| FOV + Memory | recursive shadowcasting, 8 octants, written by hand (ADR-0004); sight radius 8 cells, 2 in darkness (§12) |
| Initiative–Energy scheduler | Initiative Score = `Reaction + Intuition + 1d6`; Energy = the Score; actions cost per §5; Pass ends when Energy cannot cover the cheapest useful action and `Score −= 10`; tie-break higher Reaction then lower actor id |
| Pathfinding | A\* over `heapq`, **Chebyshev** heuristic `max(dx, dy)`, stable tie-break — a diagonal Step costs 1 Energy (§5), so Chebyshev is exact and an octile heuristic would overestimate and break admissibility (§13) |
| Shared targeting | Dijkstra flow maps ("distance to each Runner"), consumed by the Utility Score |
| Mission Graph generation | typed nodes (entry, security, objective, side, exit), adjacency list, union-find connectivity, cycle detection for side branches |
| Embedding | BSP tree for room partition, L-corridor carving, union-find connectivity verified before the Site is accepted; the Site is 60×60 and camera-scrolled (§9) |
| Behavior Trees | JSON trees over a Blackboard; Selector, Sequence, Condition, Action, Inverter, Succeeder, Cooldown, Repeat; explicit-stack ticker, per-node cooldown counters |
| Utility | weighted candidate scoring (`score = w_threat·(1 / max(1, distance)) + w_visible·visible + w_objective·objective_value − w_ally_risk·allied_fire_risk`, `distance` Chebyshev) with hysteresis so targets do not oscillate |
| Classes | all four Runners from the start (§7), three powers each for this phase only |
| Enemy archetypes | five (§8): Corp Guard, Security Drone, Ganger, Corp Mage, Hellhound |
| Security Clock | 10 segments, Alert at 4, Lockdown at 7, Converge at 10; events tick per §9 |
| Extraction | voluntary extraction pays for objectives completed; forced extraction (Clock full) pays 0 |
| Entry point | placeholder text menu listing a seeded Job, then straight into the Run |

Class powers for this phase: each Runner gets three of its §7 kit (subset listed in **Open questions** 1). Resolution is the §3 Dice Pool; combat uses §4 Condition Monitors, Overflow, Wound Modifier, Downed; Runners spend Edge (3, refresh at Run start), the Physical Adept spends Qi, the three Casters pay Drain.

**Algorithms / data structures.** §13 rows: Map, FOV, Pathfinding, Shared targeting, Scheduler, Mission Graph, Embedding, Behavior Tree, Utility. This is the densest DSA phase in the project.

**Acceptance test.** From the placeholder menu, start a seeded Run (`run_seed = derive(campaign_seed, f"run:{job_id}:{run_counter}")`, derived once and stored on the save, never recomputed). Assert:
1. the generated Mission Graph has every objective reachable from entry and exit reachable from every objective (union-find over the embedded Site), and every side node is optional;
2. the embedded Site holds the Paydata in the vault node and the Crew spawns at entry;
3. each Runner's first Pass Energy equals its Initiative Score and drops by 10 per Pass (§5);
4. moving reveals cells into FOV and retains previously seen cells in Memory;
5. all five enemy archetypes tick a Behavior Tree and pick a target via the Utility Score;
6. firing a shot adds 2 Security Clock segments, a silent takedown adds 0;
7. the Crew reaches the Paydata and voluntarily extracts, ending the Run with a payout of `12,000¥ ± 100 × net Negotiation Hits`, or 0 when the Clock reaches 10.

**Non-goals.** No Hub, no Dialogue Graph, no shops, no faction reputation, no Heat, no Legwork, no Perks, no save between sessions, no sound, no animation, no authored art beyond the two project Tileset packs. The placeholder menu is a keyboard list, not a screen.

**Estimate.** 15–20 days.

---

## Phase 2 — Hub and persistence

**Goal.** Close the between-Jobs loop: take a Job at the Hub, do Legwork, run it, get paid, and carry the crew and world forward.

**Systems built.**

| System | Detail |
|---|---|
| Hub | one authored district, **80×38 cells**, with the bottom 7 rows of the 1280×720 screen reserved for UI (§9); turn-based steps with a world clock (DEC §14 Q1 recommendation) |
| Dialogue Graph runner | JSON node graph, explicit queue runner, whitelisted-`ast` condition evaluator, reachability + `goto` + condition validation in the runner (ADR-0010) |
| Hub NPC dialogue | Fixer and vendors authored as Dialogue Graphs, branching on `rep.fixer`, `heat`, `clock`, flags, skills and attributes (§11). Conversation is **always** the Dialogue Graph, even though ADR-0009 puts every non-player brain on a Behavior Tree: a Hub NPC may carry a trivial tree to walk a route or turn to face the Crew, and the boundary is that the tree owns *movement* while the Dialogue Graph owns *talking*. A stationary Hub NPC needs no tree at all |
| Legwork | three actions per Job: Scout Site (reveals Mission Graph node types), Buy Gear, Call in a Favour (spend Fixer reputation for a Clock head start or a device reveal) |
| Shops | gear from the §4 weapon/armor tables bought with nuyen |
| Job board | Fixer posts Jobs; selecting one starts the Phase 1 Run flow |
| Payout + economy | base payout 12,000¥ ± 100 × net Negotiation Hits; voluntary vs forced extraction split (§9) |
| Heat and reputation | Heat persists and decays by 1 per successful Job, with the −2 valve above Heat 8 and ceiling 20 (§14, resolved item 4); faction and Fixer reputation persist; raises Site difficulty across Jobs |
| Persistence | schema-versioned JSON save (ADR-0012): crew sheets, Perks, gear, nuyen, Heat, faction/Fixer reputation. Site layout, enemy placement, and Clock reset per Run |

**Algorithms / data structures.** §13 rows: Dialogue (graph dict, explicit queue runner, whitelisted-`ast` evaluator, reachability validation) and Save (schema-versioned JSON). Secondary: Mission Graph again for Scout Site's node-type reveal; the Hub's turn-based step loop reuses the Phase 1 scheduler.

**Acceptance test.** Load a save at the Hub, take a Job from the Job board, spend all three Legwork actions (buying gear, scouting the Site so node types show, spending Fixer reputation), then run it. Assert:
1. a dialogue choice gated on `skill.negotiation >= 4` changes the accepted payout and writes to the variable store;
2. a Job judged successful by voluntary extraction adds `12,000¥ ± 100 × net Negotiation Hits` to nuyen and decays Heat by 1 (floor 0);
3. a forced extraction pays 0, adds Heat +2, and drops Fixer reputation by 1;
4. gear bought at the Hub is equipped and visible in a Run;
5. saving and reloading round-trips crew sheets, Perks, gear, nuyen, Heat, and both reputations, while the next Run's Site differs (seed changed by the run counter).

**Non-goals.** No Perks beyond what Phase 1 already grants by failure (the table itself is Phase 3), no Totems, no factions beyond the Fixer, no additional Job types beyond paydata extraction, no save *migration* (schema bump logic is Phase 4), no real-time Hub movement.

**Estimate.** 12–15 days.

---

## Phase 3 — Depth

**Goal.** Make the systems pay off with breadth: growth, varied Jobs, and a device and enemy catalogue the Decker and the casters can play against.

**Systems built.**

| System | Detail |
|---|---|
| Perks + inverted XP | successful test 1 XP, failed test 5 XP; a random Perk rolls on failure; each obstacle pays failure XP exactly once (ADR-0006); Advance spends XP, ratings cap at 6 |
| Job types | sabotage, protection, courier join paydata extraction (four total, §9), each generating a connected Site |
| Devices | the full §7 device table given hack effects: gun, optics, door/lock, lights, commlink, drone, cyberware, at device rating 2–4 |
| Enemy archetypes | beyond the five: variants and additions that reuse the BT node library and differ by parameters |
| Totems | one Shaman Totem passive at creation, +1 die to a skill family (§7) |
| Factions | reputation beyond the Fixer; Heat and faction standing shift Site difficulty and Job availability |

**Algorithms / data structures.** §13 rows exercised: Behavior Tree (new archetypes as data, no new Python), Utility (per-archetype weights), weighted tables for Perk rolls and device placement. Mission Graph and Embedding are re-exercised per Job type (a courier route and a protection Site want different node shapes).

**Acceptance test.** Assert:
1. failing one obstacle pays 5 XP and rolls exactly one Perk, and failing it again pays 0 (§ "one payout per obstacle");
2. a successful test pays 1 XP and Advance raises a rating up to the cap of 6;
3. each of the four Job types generates a connected Site that passes the union-find check;
4. every device row in §7 has a defined hack effect reachable after Scan, and hacking one resolves immediately in the same encounter (ADR-0008);
5. a Shaman Totem grants +1 die to its skill family and is visible on the sheet;
6. a faction reputation change alters at least one Job's difficulty or availability, and Heat has a non-loss path (it decays by 1 per successful Job, and by 2 above Heat 8 — §14, resolved item 4);
7. new enemy archetypes are authored as JSON trees and load without Python changes.

**Non-goals.** No new resource systems, no Marks/Overwatch, no Matrix dive (ADR-0008), no ally AI beyond Spirits (ADR-0009), no campaign narrative arc beyond the Fixer's Jobs.

**Estimate.** 15–20 days.

---

## Phase 4 — Polish

**Goal.** Make it readable, audible, animated, and safe to patch — without new content systems.

**Systems built.**

| System | Detail |
|---|---|
| Sound | event-triggered effects for shot, hit, Downed, Clock segment, hack, spell, objective complete, extraction |
| Animation | codepoint cycling over 2–4 frames per §12; effects are a Glyph swap plus foreground tint (no rotation, no scaling — ADR-0004) |
| UI readability | HUD shows Security Clock segments at all times (ADR-0005), condition tracks, Energy, and the tick source; draw order terrain → items → actors → effects → UI |
| Save migration | one migration function per schema version, plus an explicit test loading a v(n) save under v(n+1) (§13 Save row) |
| Balance passes | Initiative–Energy costs (§5) and Security Clock tick values (§9) tuned against recorded Runs; Clock tunable per Job type |

**Algorithms / data structures.** §13 rows: Save (migration function per version) and Animation's frame table. Everything else is tuning, not structure.

**Acceptance test.** Assert:
1. a save written at schema v1 loads under schema v2 through the migration function, with all §9 persistent fields intact;
2. every animation is 2–4 frames of codepoint cycling, no rotated, overlapping, or multi-cell Glyph;
3. the Security Clock's segment count and its last tick source are visible at all times;
4. the 1280×720 layout holds at 16px tiles with no clipped text: the 80×38 map viewport plus the reserved 7-row UI band (§9);
5. a recorded seeded Run completes within the payout and Clock ranges in §9 (no runaway).

**Non-goals.** No new systems, no new classes, no new Job types, no graphics beyond Glyph/Tileset primitives (ADR-0004 escape hatch to pygame-ce is not taken in v1), no multiplayer, no localisation.

**Estimate.** 10–15 days.

---

## Phase-to-learning-goal table

P = primarily served, S = supportive.

| Phase | G1 data structures & algorithms | G2 game development | G3 AI behaviour scripting | G4 graphics handling | Primarily serves |
|---|---|---|---|---|---|
| 0 Spike | – | S (loop, input) | – | **P** | G4 |
| 1 Mission vertical slice | **P** (shadowcasting, A\*, flow maps, bucket queue, Mission Graph, BSP embed) | **P** (turn engine, combat, Clock, extraction) | **P** (BT ticker, Blackboard, Utility) | S (Remap, draw order, FOV/Memory draw) | G1 + G2 + G3 |
| 2 Hub & persistence | S (dialogue queue, `ast`, save schema) | **P** (economy, Legwork, shop, Job board, save/load) | S (Dialogue Graph, Hub NPC brains) | S (Hub map, dialogue UI) | G2 |
| 3 Depth | **P** (weighted tables, per-Job-type graphs) | S (advancement, faction pressure) | **P** (new trees and utility weights as data) | – | G1 + G3 |
| 4 Polish | S (migration functions) | S (balance) | – | **P** (animation, tint, HUD readability) | G4 |

---

## Definition of done for v1

Testable checklist; a run that satisfies every line is v1.

- [ ] Phase 0 spike deleted; `src/` and a tests directory exist and the test suite runs green.
- [ ] A seeded Run is reproducible: the same stored `run_seed` gives the same Mission Graph, Site, and enemy placement.
- [ ] Every generated Site is connected and every objective is reachable from entry; side nodes are never required.
- [ ] FOV reveals and Memory retains, with explored cells drawn distinct from visible cells.
- [ ] Each Runner's Pass Energy equals its Initiative Score and drops by 10 per Pass.
- [ ] All four Runners, all five enemy archetypes, and Spirits tick Behavior Trees over Blackboards authored as JSON.
- [ ] The Security Clock has 10 segments, is always visible, and reports its last tick source; Alert 4 / Lockdown 7 / Converge 10 behave as §9.
- [ ] Voluntary extraction pays `12,000¥ ± 100 × net Negotiation Hits`; forced extraction pays 0 and applies Heat +2 and Fixer reputation −1.
- [ ] Crew sheets, Perks, gear, nuyen, Heat, and faction/Fixer reputation persist across a save/load round trip; a v(n) save migrates to v(n+1).
- [ ] A failed test pays 5 XP and rolls one Perk; a successful test pays 1 XP; each obstacle pays failure XP once.
- [ ] The Hub has three Legwork actions per Job and a Job board with at least the paydata Job.
- [ ] All four Job types generate a connected Site.
- [ ] Every §7 device has a defined hack effect; the Decker can Scan and hack devices in the physical world.
- [ ] Edge, Qi, and Drain behave as §6, with Glitches and Critical Glitches per §3 (a Critical Glitch adds a Clock segment).
- [ ] No animation uses rotation, overlap, multi-cell Glyphs, or in-tileset scaling.
- [ ] A full Job can be played start to finish from the Hub without a crash or a placeholder string.

---

## Risks to the schedule

Source note: `DECISIONS.md` §13 names `docs/design/data-model.md` as the expansion of this list.
That file now exists, and its §16 *where the difficulty actually lives* ranks the same subsystems by
**coding** risk. It disagrees with this table about the scheduler, and both rankings are stated below
rather than smoothed into one.

| Rank | Subsystem | Why it overruns | Earliest mitigation |
|---|---|---|---|
| 1 | Embedding (BSP + L-corridor) | Graph-to-map quality is subjective; connectivity bugs are intermittent; a boring embed hides behind a connected map (ADR-0011) | Build the union-find acceptance check in Phase 1 before any art or content |
| 2 | Behavior Tree ticker + Utility | Data-driven trees fail silently at runtime and need a validator and a tick trace (ADR-0009) | Ship the JSON validator and a debug trace line in Phase 1, not Phase 3 |
| 3 | FOV shadowcasting (slope arithmetic, octant transforms) | The classic swamp — an off-by-half in `l_slope`/`r_slope` or a wrong `MULT` tuple fails in one octant of eight, and a screenshot that looks right is not evidence | Write the pillar-corner and diagonal-gap asserts before the first octant exists; add this row because `data-model.md` §16 ranks it above the scheduler and this table did not list it at all |
| 4 | Initiative–Energy scheduler | One number controls turn frequency and actions-per-turn and cannot be balanced independently (ADR-0003) | Freeze §5 costs in Phase 1 and treat any change as a balance pass, not a feature |
| 5 | Dialogue runner + validation | We own the format, its ergonomics, and its error messages (ADR-0010) | Prototype the whitelisted-`ast` evaluator and reachability check before authoring any NPC |
| 6 | Save schema + migration for two persistent graphs | Crew and world both persist, so two graph shapes need versioning; Heat's spiral needs a floor and ceiling (ADR-0012) | Build the versioned schema in Phase 2; add migration only in Phase 4 |
| 7 | Content catalogue (devices, archetypes, Job types) | ADR-0008 makes the device layer a content burden, not a systems one | Keep every device/archetype as data so Phase 3 adds files, not Python |

**The scheduler-versus-shadowcasting disagreement, stated, not resolved.** Ranks 3 and 4 are the
disagreement. `data-model.md` §16 ranks the *coding* risks as Embedding, BT ticker, then
**shadowcasting**, and keeps the scheduler off the list as an honourable mention: "it will not eat a
week of *coding*. It will eat a week of *balance*." This roadmap keeps the scheduler in the table at
rank 4 because Phase 1 cannot ship without it and because its mitigation here is also a tuning
mitigation. The two documents therefore disagree about which kind of week the scheduler costs —
implementation or balance — and `data-model.md` §16 asks that one of them "move the FOV row into its
risk table". This document has now done that (rank 3) without demoting the scheduler, so the
scheduler's true rank stays open on purpose until Phase 1 is estimated from real ticks. Note that
`data-model.md` §16 still describes this table as not listing shadowcasting; that sentence is now
stale against this revision, and only its own author should change it.

## Cut order if time runs short

Cut from the end backwards; the spine (Phase 1 + Hub + one Job + payout/Heat) is never cut.

1. **First to go: Phase 4 extras** — sound, animation frames, and balance passes beyond the save migration and HUD readability. Ship v1 silent and static; the loop still reads.
2. **Second: Phase 3 breadth** — factions and Totems drop before Perks and the extra Job types, because Heat and Fixer reputation already give world pressure.
3. **Third: Phase 2 depth** — Legwork collapses from three actions to Scout Site only, and shops drop to a single gear vendor. The Hub, Job board, payout, and Heat stay.

Do **not** cut: Mission Graph + embed, FOV + Memory, the scheduler, the Security Clock, extraction, the four classes, or the save round trip. Those are the learning goals and the loop.

---

## Open questions

New parameters this document needs but `DECISIONS.md` does not fix. Recommendations are the default; each is flagged in the phase report. Four questions that used to be here are closed: FOV radius is 8 cells, 2 in darkness (§12); Site size is 60×60 camera-scrolled (§9); Hub NPC brains are settled by the Dialogue-Graph/trivial-tree boundary in Phase 2; and `data-model.md` now exists, so the risk ranking above cites it directly.

1. **Which three powers per class in Phase 1?** Recommendation: Physical Adept — Improved Reflexes, Killing Hands, Wall Run; Mage — Manabolt, Invisibility, Heal; Shaman — Summon Spirit, Fear, Ward; Decker — Scan, hack Gun, hack Door/lock. Completes §7 in Phase 3.
2. **Objectives per Site in the vertical slice.** Recommendation: three — one objective node holding the Paydata, two side nodes as optional loot. Needs a §10 entry if adopted.
3. **Where the save is built vs migrated.** This roadmap builds the versioned save in Phase 2 and adds migration in Phase 4, because Phase 4 is the parent's stated migration phase. Confirm that split.
4. **Jobs on the Job board at once.** Not specified. Recommendation: three, one per Fixer relationship tier if factions land in Phase 3.

## Sources

Borrowed patterns: `.agents/skills/roguelike/SKILL.md` (run loop, FOV/fog, permadeath-as-Clock), `.agents/skills/procedural-gen/SKILL.md` (one seeded RNG passed everywhere, generate into a plain data grid first), `.agents/skills/game-ai/SKILL.md` (decide / steer / path separation), `.agents/skills/ai-behavior-trees-utility-ai/SKILL.md` (BT + Utility hybrid, decorators, Blackboard), `.agents/skills/dialogue-systems/SKILL.md` (build-a-graph-not-a-language), `.agents/skills/save-systems/SKILL.md` (version field, migrate on load), `.agents/skills/game-ui-ux/SKILL.md` (screen stack, event-driven HUD), `.agents/skills/input-systems/SKILL.md` (actions not keys), `.agents/skills/pygame-core/SKILL.md` (loop order; relevant only to the ADR-0004 escape hatch), `.agents/skills/rpg/SKILL.md` (stats, progression, quest state).

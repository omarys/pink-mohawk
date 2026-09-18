# Decisions and parameters

The single parameter contract for this project. `CONTEXT.md` defines vocabulary; `docs/adr/` records *why*; this file records *what* — the numbers every document and every line of code must agree on.

Everything here is a v1 default and is meant to be tuned. If a document needs a number that is not here, it must add one here in the same change, or raise it in the Open Questions section rather than inventing it locally.

## 1. Attributes

Range 1–6 for an unaugmented human; the Physical Adept starts above it. Pools are `linked attribute + skill + modifiers`.

| Attribute | Use |
|---|---|
| Body | soak, Physical monitor |
| Agility | firearms, close combat, athletics, stealth |
| Reaction | ranged defence, Initiative Score |
| Strength | melee damage |
| Willpower | Drain resistance, Stun monitor |
| Logic | Cybercombat, Electronics, Medicine, Mage and Decker Tradition Attribute |
| Intuition | Perception, defence, Initiative Score |
| Charisma | Conjuring, social skills, Shaman Tradition Attribute |
| Edge | luck pool, 3 points, refreshes at the start of each Run |

## 2. Skills

Thirteen skills, each with one linked attribute.

`Firearms` (AGI) · `Close Combat` (AGI) · `Athletics` (AGI) · `Stealth` (AGI) · `Perception` (INT) · `Sorcery` (Tradition Attribute) · `Conjuring` (CHA) · `Cybercombat` (LOG) · `Electronics` (LOG) · `Medicine` (LOG) · `Negotiation` (CHA) · `Con` (CHA) · `Intimidation` (CHA)

Starting rating 3–5 by class. Ratings cap at 6 in v1.

## 3. Resolution

- **Hit**: a die showing 5 or 6. Pool = attribute + skill + modifiers.
- **Success Test**: Hits ≥ threshold. Thresholds: 1 trivial, 2 average, 3 hard, 4+ extreme.
- **Opposed Test**: net Hits decide; ties go to the defender. In combat, net Hits add to DV.
- **Glitch**: more 1s than half the dice rolled. SR5's printings disagree ("more than half" vs "half or more"); we use **more than half**. A Glitch with zero Hits is a Critical Glitch: the action fails *and* the Security Clock gains a segment.
- **No Limits. No extended tests.** No test in this game rolls more than twice.
- **Area effects use a Chebyshev radius** — a square of cells, corners included, consistent with the movement model and the A\* metric. "Radius 2" means every cell within 2 in both axes.

## 4. Damage

| Mechanic | Rule |
|---|---|
| Physical monitor | `8 + ceil(Body / 2)` boxes |
| Stun monitor | `8 + ceil(Willpower / 2)` boxes |
| Wound Modifier | `-1 die per 3 filled boxes`, counting both tracks together |
| Attack | attacker pool vs defender pool; net Hits add to DV |
| Soak | `Body + (armor − AP)` Hits, each cancelling 1 DV. DV ≤ 0 = no damage |
| Damage type | Nominal for the attack. **S-code attacks are always Stun.** A **P-code** attack becomes Stun when its modified DV is less than the modified armor |
| AP | Stored as a **positive magnitude** and subtracted. AP 3 is better than AP 1. AP is never negative anywhere in the contract |
| Overflow | when the Stun monitor fills, 2 further Stun boxes convert to 1 Physical |
| Downed | zero Physical boxes = out of the Run, recovers at the Hub |

Ranged defence pool: `Reaction + Intuition + cover`. Melee defence pool: `Agility + Close Combat`. Cover gives +2.

**Cover is a cell, not a status.** A cell is in cover when it is adjacent to a blocking tile *and* the line of sight from the attacker to that cell is blocked. Occupying such a cell grants the +2. This sentence is the whole definition: `ai.md` was delegating cover geometry to "the tactical-map document", which does not exist and never did, while `has_cover_available`, `at_cover`, `seek_cover`, `take_cover` and the Security Drone's "cover is no defence" rule all depend on it.

| Weapon | DV | AP |
|---|---|---|
| Heavy pistol | 5P | 1 |
| SMG | 6P | 0 |
| Assault rifle | 8P | 2 |
| Shotgun | 7P | 1 |
| Katana | (Strength + 3)P | 3 |
| Stun baton | 6S | 0 |
| Hellhound bite | (Strength + 2)P | 1 |

**Spirits** attack by type (`classes.md` §7.3 is authoritative): Beast `(Force+3)P` AP 1 melee · Air `(Force+1)P` AP 0, range 8 · Earth `(Force+2)P` AP 2 melee · Water `(Force)S` AP 0, range 6, radius 2. The ability names are `beast_strike`, `air_bolt`, `earth_slam`, and `water_burst` — pinned here because two documents independently invented a name for the Earth attack and disagreed.

**Ranges** (in cells): heavy pistol 8, SMG 10, assault rifle 14, shotgun 6, melee 1 (adjacent). Spells range 12 with line of sight.

| Armor | Rating |
|---|---|
| Armoured vest | 6 |
| Lined coat | 7 |
| Armoured jacket | 8 |
| Helmet (adds) | +2 |

Only the highest armor value applies; accessories add.

## 5. Turns: Initiative Score as Energy

- **Initiative Score** = `Reaction + Intuition + 1d6`, plus `1d6` per Improved Reflexes rating (max +2d6 in v1).
- **The Score is rolled at the start of every Round**, not once per encounter. It persists across Passes within that Round and is re-rolled when the Round ends. A Runner with Score 11 acts in Pass 1, then in Pass 2 with 1 Energy — one Step. Two *substantial* Passes need a Score of 15 or more and three need 25, so at the starting range of 8–16 most Runners get one full Pass and sometimes a short second one. That is the honest shape of ADR-0003's claim that initiative dice buy extra passes: they buy short extra passes until the Score climbs.
- Energy for the turn = the Initiative Score. Actions cost Energy:

| Action | Cost | Notes |
|---|---|---|
| Step | 1 per tile | 8 directions |
| Sprint | 2 per 3 tiles | −2 defence until the next Pass |
| Attack | 10 | |
| Use power | 10 | Qi, spell, or hack |
| Aim | 5 | +1 die, stacks to +2 |
| Reload | 5 | |
| Take cover | 5 | +2 defence |
| Use item | 5 | |
| Stand up | 5 | |

- **Pass end threshold is 1 Energy** (`PASS_END_THRESHOLD = 1`). A Step costs 1, so a Pass runs until the actor cannot afford even one Step; then `Score −= 10` and a new Pass begins while the Score is still positive. An earlier draft said `≥ 5`, which contradicted the worked example in this same section and a two-to-three-Pass pacing target in `world.md`; both documents have since been corrected, and `data-model.md`'s constant now reads 1 as well.
- Tie-break order: higher Reaction, then lower actor id. Deterministic, no re-rolls.

## 6. Resources

**Edge** (all classes, 3 points, refresh at the start of each Run)

| Spend | Effect |
|---|---|
| Push the Limit | +Edge dice to one test, 6s explode |
| Second Chance | reroll the failures of one test |
| Seize the Initiative | +10 Energy immediately |

**Qi** (Physical Adept, pool 4, +1 at the start of each Pass, **capped at 4**). The cap is what makes Qi a resource: costs are 1–2 per power and a fast Adept spends 2–5 per Round, so an unbroken fight drains the pool even with the refresh.

| Power | Cost | Effect |
|---|---|---|
| Improved Reflexes | 2 | +1d6 Initiative Score for the rest of the Run |
| Killing Hands | 1 | unarmed is lethal, +1 DV, 3 rounds |
| Wall Run | 1 | cross one impassable tile |
| Mystic Armor | 1 | +2 soak, 3 rounds |
| Attribute Boost | 1 | +1 die to Agility, Strength, or Reaction, 3 rounds |

**Drain** (Mage, Shaman, Decker). Resisted with `Willpower + Tradition Attribute` (Logic for Mage and Decker, Charisma for Shaman). Unresisted boxes are Stun. Drain is Physical when `Force > the Tradition Attribute value`.

| Ability | Drain |
|---|---|
| Manabolt | `max(2, Force − 3)` |
| Stunball | `max(3, Force − 2)` |
| Heal | `max(3, Force − 1)` |
| Analyze Device | `max(1, Force − 4)` |
| Invisibility | `max(2, Force − 2)` |
| Armor | `max(2, Force − 2)` |
| Summon Spirit | `2 × the spirit's Hits`, minimum 2 |
| Fear | `max(2, Force − 2)` |
| Ward | `max(2, Force − 3)` |
| Hack a device | `ceil(device rating / 2)` Stun, doubled on a Glitch, no resistance roll |

Spell Force is chosen at cast time, range **1–8**. Sustaining a spell costs −2 dice on everything else, and at most **two** spells may be sustained at once.

Force 1–8 against a starting Tradition Attribute of 6 is deliberate: Force 7 and 8 are the only way to make Drain *Physical*, so overcasting is a reachable, self-inflicted risk rather than dead code.

## 7. Classes

All four are in the Crew from the start; the player controls all four. No recruitment, no class selection.

| Class | Role | Key stats | Identity |
|---|---|---|---|
| Physical Adept | physical | AGI 7, BOD 6, REA 6, STR 7 | Qi powers; prodigal attributes; no spells |
| Mage | direct caster | LOG 6, WIL 5 | acts on people and space |
| Shaman | conjurer | CHA 6, WIL 5 | acts through Spirits and zones |
| Decker | fighter-technomancer | LOG 6, AGI 5 | acts on devices |

**Mage** (Sorcery + Logic): Manabolt (Force DV, single target), Stunball (Force Stun, radius 2), Heal (Hits boxes), Analyze Device (reveals devices and ratings in radius), Invisibility (+3 stealth dice), Armor (+2 soak), Counterspell (opposed Sorcery test to cancel an enemy spell, range 12). A Caster may target **itself** with Heal, at the same Drain — a lone Corp Mage behind cover healing itself is the natural play.

**Shaman** (Conjuring + Charisma): Summon Spirit, Fear (radius 2, −2 dice, 3 rounds), Ward (radius 2, −1 die to enemy magic entering it), one Totem passive chosen at creation (+1 die to a skill family). Spirit types: Beast (melee), Air (fast, ranged), Earth (tank, slow), Water (area). A failed Conjuring roll, or a Glitch, lets the Spirit break free and become hostile; a Spirit lasts 3 rounds.

**Decker** (Cybercombat + Logic): Scan (reveals the device list and ratings in radius 12, Drain 1). Hacks are Success Tests vs threshold = device rating.

| Device | Rating | Effect |
|---|---|---|
| Gun | 2 | eject magazine, disabled 3 rounds |
| Optics | 2 | blinded, −3 dice, 3 rounds |
| Door or lock | 2–4 | unlocked |
| Lights | 3 | room dark: enemy FOV radius 2, −2 dice |
| Commlink or phone | 3 | read messages; spoof a distraction |
| Drone | 4 | seized for 3 rounds, or disabled |
| Cyberware | 4 | −2 dice to one enemy for 3 rounds |

Enemy gear uses the same table, so the Decker can hack enemies as well as fixtures.

**Device placement is one contract in two tables, and that is a drift risk.** `enemies.md` §7 is the detailed form (ratings, mandatory cells, Heat tier gating, caps) and **wins**; `world.md` §7 is the population checklist and declares itself the same contract. Every change must land in both or the divergence is a bug. It has already drifted in six cells — entry Lights, security Door and Commlink, side Lights and Optics odds, Sabotage Optics, and Protection's Gun, Optics and Cyberware — plus the Corp Mage gate, which is Heat tier ≥ 2. The **Paydata terminal is a Commlink at rating 3**: rating 4 would breach the rating-4 devices-per-node cap in a node that already spends it on the vault door. The caps: at most 3 devices carried per enemy, at most 2 rating-4 devices per node, and at most 6 total Hack Drain per node. Without caps, generation oscillates between Sites with nothing to hack and Sites where every guard is a device piñata.

## 8. Enemies and brains

Five archetypes in v1: **Corp Guard** (patrol, escalate, call backup), **Security Drone** (hackable, flies, rigid patrol), **Ganger** (opportunist, poor discipline, flees at Wound Modifier −3), **Corp Mage** (counterspells, casts from range, retreats), **Hellhound** (fast melee, tracks by scent, never flees). Their full stat blocks, devices, escalation tiers and encounter budgets live in **`enemies.md`, which is authoritative for enemy numbers** — this file only fixes the archetype list and the blackboard.

**`alert_level` is 0 Calm / 1 Alert / 2 Lockdown.** The site raises every actor's floor to 1 at 4 Security Clock segments and to 2 at 7, and `call_backup` writes 2. Trees branch on this key, so the mapping is part of the contract: an earlier draft of `world.md` set Alert to 2, which collides with Lockdown and makes the two tiers indistinguishable.

Every non-player actor is a Behavior Tree over a Blackboard. Node types: Selector, Sequence, Condition, Action, Inverter, Succeeder, and the Cooldown and Repeat decorators. Blackboard keys in v1 are a fixed typed set, not an open dictionary: `target` (actor id or null), `last_known_pos` (cell), `home_pos` (cell), `cover_pos` (cell), `noise_pos` (cell), `alert_level` (0/1/2), `morale` (int), `objective` (a **Mission Graph node id string**, or `"hostile"` for a freed Spirit — never a cell, never a dict), `pacified` (bool), `command_target` (cell or actor id; written only by a player command to a Spirit or a protectee), `summoner_id` (actor id, Spirits only), `rounds_bound` (int, Spirits only). Twelve keys.

`objective` being a string is load-bearing: the Utility Score resolves it to a room, so a dict or a prose value silently zeroes the objective term — the term that makes Command Spirit and Protection work at all. Spirit commands therefore live in `command_target`, and Spirit lifetime in `summoner_id` and `rounds_bound`, rather than overloading `objective`.

`pacified` is the one channel a conversation has into a brain: a dialogue effect sets it, and a tree checks it before escalating. Without it, a bribed guard has nowhere to store "stop looking" and the dialogue layer's promises are undeliverable.

**Morale** = `wound_modifier + morale_bonus − allies_downed`, recomputed each decision step; `flee_threshold` is per archetype (Ganger −3).

**Cooldown decorators are measured in Passes and are not cleared by `reset_tree` or by an abort.** A guard that flees and comes back must not re-arm `call_backup`, or the Alarm tick fires every few steps and the Clock stops meaning anything.

**Abandoning a RUNNING branch clears that subtree's ephemeral state** — RUNNING markers and repeat counters — so re-entering the branch starts it fresh; cooldowns survive, per the rule above. Without this, a "wait 2 turns" leaf returns SUCCESS instantly the second time it is entered, and a half-finished sequence resumes at its third child.

Target choice is a Utility Score over candidates:

`score = w_threat · (1 / max(1, distance)) + w_visible · visible + w_objective · objective_value − w_ally_risk · allied_fire_risk`

`distance` is Chebyshev. `objective_value` is 1.0 when the candidate is inside the room named by `objective` and 0.0 otherwise, so it needs no separate normalisation scale. `max(1, distance)` keeps the term finite when a target shares the actor's cell, which a player command can produce. Target switching requires beating the incumbent's score by that archetype's `target_hysteresis` (0.05–0.25), never by one global constant.

Weights are per-archetype parameters. Spirits are the only friendly actors with a brain: they follow the summoner and act on their own tree.

**Behavior Tree architecture (settled before the ticker was written).**

- **Trees are immutable shared data; state is per actor.** One parsed tree per archetype, shared by every
  actor of that type. Everything mutable — the RUNNING path, repeat counters, cooldowns — lives in a
  per-actor `BTState` keyed by node path. A shared tree holding state is how two guards come to act in
  lockstep or corrupt each other's branch.
- **Leaves never spend Energy.** A leaf performs its game action and the ticker reports how much the step
  cost; the caller deducts it from `ENERGY_COSTS` (§5). One place owns the accounting, so an assertion can
  require that every leaf which can spend Energy declares a cost — a leaf that spends for itself can forget,
  and a free action is a silent bug.
- **Cooldowns key on the node's `name` when it has one, otherwise on its path.** An author who names two
  nodes `call_backup` shares one timer deliberately; unnamed nodes are independent.
- **Repeat `times: 0` means one repetition per decision step**, not an unbounded loop.
- **A FINITE `repeat` is atomic inside one decision step.** `times: N` resolves all N repetitions
  and returns SUCCESS in a single tick, so a large N is precisely the spin `MAX_TICKS_PER_STEP`
  guards against. Only `times: 0` spans steps, returning RUNNING once per step. The asymmetry is
  not obvious and it is easy to write `times: 500` believing it holds for 500 steps.
- **`MAX_TICKS_PER_STEP = 64`.** A `Repeat` whose condition never changes spins inside one decision step
  while spending no Energy, and the scheduler stalls with nothing to charge. Exceeding the cap raises a
  `BTLivelock` error naming the tree and the path, so a hang becomes a diagnosis.

**Archetype parameters — unplaytested defaults.** Moved here from `ai.md` §6.2 so all brain code reads one
table. Expect these to move in Phase 1's playtest.

| archetype | `w_threat` | `w_visible` | `w_objective` | `w_ally_risk` | `target_hysteresis` | `morale_bonus` | `flee_threshold` |
|---|---|---|---|---|---|---|---|
| Corp Guard | 1.0 | 2.0 | 1.5 | 3.0 | 0.10 | +1 | −4 |
| Security Drone | 1.2 | 3.0 | 1.0 | 2.0 | 0.15 | — | never (machine) |
| Ganger | 1.5 | 1.5 | 0.5 | 2.5 | 0.05 | 0 | −3 |
| Corp Mage | 0.8 | 2.5 | 1.0 | 3.5 | 0.20 | 0 | −4 |
| Hellhound | 2.0 | 2.0 | 1.0 | 0.5 | 0.25 | — | never |
| Spirit | 2.0 | 2.0 | 1.0 | 1.0 | 0.10 | — | never (conjured) |

Two of these carry design intent rather than taste: the Ganger's **lowest** hysteresis is its poor
discipline, so do not "fix" its dithering with a wider margin, and the Corp Guard's ally-risk weight is the
highest in the game because a rifle line through its own squad must hold fire.

## 9. Jobs, the Clock, and the world

**Security Clock**: 10 segments. At 4 the site goes **Alert** (patrols converge); at 7 **Lockdown** (doors lock, guards +2 armor); at 10 security **Converges** and the Run ends.

| Event | Segments |
|---|---|
| Gunfire | +2 |
| Guard killed | +2 |
| Body found | +3 |
| Failed hack | +1 |
| Loud spell (Force ≥ 4) | +2 |
| Alarm tripped | +2 |
| Lock forced | +1 |
| Silent takedown, successful hack | 0 |

**Extraction**: voluntary extraction pays for objectives completed and grants **Fixer reputation +1** — the Favour is the only reputation sink, so without a positive source the reputation economy cannot function; forced extraction (clock full) pays 0, `Heat +2`, Fixer reputation −1.

**Economy**: base payout 12,000¥ ± `100 × net Negotiation Hits`. Heat decays by 1 per successful Job. Job types in v1: paydata extraction (the vertical slice), sabotage, protection, courier.

**Condition Monitors persist as Hub state.** Filled boxes carry across Jobs and clear only by resting or by paying the clinic (250¥ per box, `HUB_RECOVER_BOXES_PER_DAY`). That persistence is what gives the Hub a cost and a day budget; a draft of `rules.md` proposed that every box clears on Extraction, which would remove both.

**A Decker cannot use the device table without a cyberdeck (8,000¥).** Losing it removes the class's core ability, so it is the one piece of gear with a stated consequence.

**Hub**: one authored district, **80×38 cells**, with **7 rows reserved for UI** on a 1280×720 screen (45 rows total at 16px). An 80×45 district leaves nowhere to draw the Clock, crew status, or dialogue. Turn-based steps with a world clock. Three Legwork actions per Job: Scout Site (reveals Mission Graph node types), Buy Gear, Call in a Favour (spend Fixer reputation for a Clock head start or a device reveal).

**Site size**: **60×60 cells**, camera-scrolled. The Hub fits on one screen; a Site does not.

**Gear prices** (nuyen, v1):

| Item | Price | Item | Price |
|---|---|---|---|
| Heavy pistol | 1,200 | Katana | 1,500 |
| SMG | 2,400 | Stun baton | 900 |
| Assault rifle | 4,800 | Armoured vest | 1,000 |
| Shotgun | 3,000 | Lined coat | 2,000 |
| Ammunition (per reload) | 100 | Armoured jacket | 3,500 |
| Medkit | 500 | Helmet | 600 |

**Persistence**: crew sheets, Perks, gear, nuyen, Heat, and faction/Fixer reputation persist. Site layout, enemy placement, and the Clock reset per Run. The `run_seed` is **stored** on the save, not recomputed from the job id — recomputation would silently change a Site the moment generation code changed, which is the one thing a save must never do.

**There is exactly one seeding scheme in this project**: `derive(run_seed, stream_name)`, a sha256-based derivation over named per-subsystem streams — `gen.graph`, `gen.embed`, `gen.place`, `rules.initiative`, `rules.combat`, `loot`, `ai:<actor id>`. Two things are banned. The builtin `hash()` is salted per process via `PYTHONHASHSEED`, so it cannot reproduce a Run — and it was in `ai.md`'s target choice. And every *second* scheme is superseded: `site_seed = f(job id, run counter)`, `seed_graph = site_seed ^ 0x01`, and FNV-1a variants all appeared in drafts. Three schemes existed at once and only one survives. Per-subsystem streams also mean one subsystem's draws cannot perturb another's, which is what makes a seeded Run reproducible in the first place.

**The root is `campaign_seed`.** It is created once when the campaign starts and stored on the save; everything else derives from it. `run_seed = derive(campaign_seed, f"run:{job_id}:{run_counter}")`, derived once at Depart and then stored on the save, and Hub-side draws get their own namespaced streams, `derive(campaign_seed, f"hub:{hub_day}:{name}")`. This closes the last gap in the scheme: `world.md` §3.2 seeds shop stock from `(job id, hub_day)`, which was a second, unnamed scheme until it had a shared root and a stream name.

## 10. Generation

Two stages, always in this order.

1. **Mission Graph.** Typed nodes — entry, security, objective, side, exit — with edges constrained so that every objective is reachable from entry, exit is reachable from every objective, and side nodes hang off the main path without becoming required. Side branches become optional objectives and loot.
2. **Embed.** Each node becomes a room sized by type (vault large, corridor 1-wide); edges become L-shaped corridors; connectivity is verified with union-find before the map is accepted. Devices, enemies, and loot are placed by node type, with the vault holding the paydata.

**`world.md` §5 owns the graph generator**: the per-Job `JOB_GRAPH` templates, the `sec_pre` and `sec_post` security nodes, and the ceilings — entry exactly 1, security 1–3 **in total** (at most 2 `sec_pre` plus 1 `sec_post`), objective 1–2, side 0–3 in chains no longer than 2, exit exactly 1 — which bound the graph at 10 nodes. (Read as "1–3 pre plus 1 post" the ceilings would sum to 11 and contradict their own stated bound; 
security is 1–3 total.) `data-model.md` §6 previously described a simpler builder with no `job_type` argument and no `sec_post` nodes, and claimed `N ≤ 20`; that has since been rewritten to match.

**`world.md` §10.4 owns the save's field names**: a top-level `schema_version`, roots `campaign` / `crew` / `world` / `job`, Runners at `crew.runners[]`, and `nuyen` under `crew`. `data-model.md` §11's `version` key and its persisted `qi` field are both wrong — Qi is per-Run and resets, so it is never persisted. Edge is two different things and both must be named precisely: the **Edge rating** lives on the sheet and persists, while **Edge points** reset every Run.

## 11. Dialogue

JSON node graph. Node contract:

```json
{
  "id": "offer",
  "speaker": "fixer",
  "line": "Pay is 12k. In and out.",
  "choices": [
    {"text": "I want 15k", "cond": "skill.negotiation >= 4", "goto": "haggle", "effects": []},
    {"text": "I'm in", "goto": "accept", "effects": [{"set": "job.accepted", "value": true}]}
  ]
}
```

A node carries a `line` (the spoken text) and/or `choices`, optionally `effects` that fire on entry, and at most one flow terminator (`goto` or an end). It may not be both a choice node and a jump.

Conditions are expressions over the shared variable store (`rep.fixer`, `heat`, `clock`, `flags`, skill and attribute ratings) and are evaluated by a whitelisted `ast` evaluator — never `eval`. Variable names are lowercase dot paths (`attr.logic`, `skill.negotiation`, `rep.fixer`) so a condition can never collide with a Python name. Division is not an allowed operator; comparisons and boolean operators are.

Effects: `set`, `give_item`, `start_job`, `change_rep`, `tick_clock`, and `test`. `test` runs a Dice Pool check mid-conversation and exposes `test.<key>.hits`, `.net`, and `.glitch` to later conditions — this is what makes a haggle or a bribe a real roll rather than a flat skill gate. `tick_clock` exists because a failed social approach has to be able to cost the Clock.

Validation (every `goto` resolves, every condition parses, no unreachable nodes, at most one terminator per node) is part of the runner, not a separate tool.

On disk a conversation is a `nodes` **array**; at load it is indexed into a `dict[str, Node]`. The array is the authoring and diffing form (a duplicate id is visible on the page); the dict is the runtime form.

## 12. Art and rendering

- Tiles are **16×16**. Primary packs: **Kenney RPG Urban Pack** (CC0) for the Hub and city Sites, and **Kenney Roguelike Modern City** (CC0) for interiors and furniture. **0x72 Dungeon Tileset II** (CC0) remains the intended interiors pack but itch.io will not serve it headlessly, so it is a documented manual step rather than a dependency.
- **FOV sight radius is 8** cells, reduced to 2 in darkness. Sight radius is the only visibility parameter in v1.
- Vendored alongside for later comparison: Kenney Roguelike Modern City (CC0), Future City 27 (CC0), DCSS 32×32 (CC0, with the upstream caveat about legacy pieces), DawnLike (CC-BY 4.0 — attribution required if used).
- Fonts: **Cozette (MIT)** or **Spleen (BSD-2-Clause)** — neither is OFL, which an earlier draft of this file got wrong. No vendored tileset pack ships a font, so either way the file is fetched by hand.
- **One Glyph per cell.** No overlapping, rotated, or multi-cell sprites, and no in-tileset scaling — that is the renderer. Animation is codepoint cycling over 2–4 frames; recolouring is foreground tint; state effects (blind, burning, hacked) are a glyph swap plus tint.
- Draw order in one console: terrain → items → actors → effects → UI.

## 13. Algorithms to write

This table is the project's practice syllabus; `docs/design/data-model.md` expands it with complexity, references, and self-checks.

| Subsystem | Data structure or algorithm |
|---|---|
| Map | dense 2D tile array + `explored` and `visible` byte arrays |
| FOV | recursive shadowcasting, 8 octants |
| Pathfinding | A\* over `heapq`, stable tie-break. A diagonal Step costs 1 Energy like an orthogonal one, so the **Chebyshev heuristic `max(dx, dy)`** is exact for this cost model — an octile heuristic would overestimate and break admissibility |
| Shared targeting | Dijkstra flow maps ("distance to each Runner") |
| Scheduler | Energy bucket queue keyed by Energy value, `O(1)` pop; compared against a binary heap |
| Mission Graph | adjacency list, union-find connectivity, cycle detection for side branches |
| Embedding | BSP tree for room partition, L-corridor carving |
| Behavior Tree | explicit-stack ticker, per-node cooldown counters |
| Utility | weighted candidate scoring with hysteresis |
| Dialogue | graph dict, explicit queue runner, whitelisted-`ast` condition evaluator, reachability validation |
| Save | schema-versioned JSON with a migration function per version |

## 14. Open questions

Recommendations are the default; these are documented, not decided.

Resolved since the first draft. Recorded because each resolution was a real choice.

1. **Site size**: 60×60, camera-scrolled.
2. **Save**: a single schema-versioned JSON slot, with a migration function per version.
3. **Spirit control**: a Behavior Tree with a player-issued target.
4. **Heat decay**: −1 per successful Job, a −2 valve above Heat 8, ceiling 20 (`world.md`).
5. **Initiative re-roll**: at the start of every Round.
6. **Gear prices**: priced in section 9 above.
7. **Social outcome channel**: the `pacified` Blackboard key.
8. **Advance cost**: skill = `new rating × 3`, attribute = `new rating × 5`. `world.md`'s `10 × target rating` is superseded.
9. **Magazine sizes**: heavy pistol 15, SMG 30, assault rifle 30, shotgun 8.
10. **Perk exhaustion**: a duplicate Perk re-rolls once, then converts to 3 XP. The table is expected to grow past twelve entries.
11. **`alert_level` mapping**: 1 at Clock 4, 2 at Clock 7, site-wide floor.
12. **`run_seed`**: stored on the save rather than recomputed.
13. **Device placement caps**: 3 carried per enemy, 2 rating-4 devices per node, 6 total Hack Drain per node (`enemies.md` §7).
14. **Placeholder opponents retired**: the `rules.md` worked combat example now uses real tier-0 Corp Guard stat blocks from `enemies.md`.
15. **Pass end threshold**: 1 Energy, not 5 — a Pass runs until a Step is unaffordable.
16. **Blackboard is twelve typed keys**, not nine: `objective` is a Mission Graph node id string, and `command_target`, `summoner_id` and `rounds_bound` carry Spirit and protectee state.
17. **Cooldowns are measured in Passes and survive `reset_tree`.**
18. **Condition Monitors persist as Hub state**; healing costs rest or nuyen.
19. **Save field names are `world.md` §10.4's**; `schema_version`, not `version`; never persist `qi`.
20. **`world.md` §5 owns the Mission Graph generator**, and its 10-node ceiling replaces `data-model.md`'s 20.
21. **Voluntary extraction grants Fixer reputation +1.**
22. **Font**: Spleen 8×16 bitmap (BSD-2-Clause), vendored at `assets/vendor/fonts/spleen-8x16.bdf`.
23. **Behavior Tree state is per actor**; parsed trees are immutable and shared.
24. **Abandoning a RUNNING branch clears its ephemeral state**, never its cooldowns.
25. **Leaves never spend Energy**; the caller deducts `ENERGY_COSTS` from the ticker's reported cost.
26. **Cooldowns key on node `name`, else node path.**
27. **`MAX_TICKS_PER_STEP = 64`**; exceeding it raises `BTLivelock`.
28. **`Repeat times: 0` = one repetition per decision step.**
29. **Archetype weights and morale values adopted as unplaytested defaults** (`ai.md` §12 items 1–2 closed).
30. **Self-targeted Heal is allowed** at the standard Drain. The geometry forces it — a TTF rasterises at an arbitrary size and fights the 16px grid, while Spleen's native height is exactly 16px so its glyph is a byte-for-byte paste into the left 8 columns of the cell. Cozette (MIT) stays the documented TTF alternative if the look ever changes; its vector build is upstream's own compatibility flag and is warned against at any size.

Still open, and genuinely undecided:

1. **Hub movement**: turn-based steps with a world clock (recommended) versus real-time exploration.
2. **Dead skill slots**: nine skill slots have no use outside their owner's domain at the starting stat blocks. Either give them cross-class uses or cut them from the sheet.

## 15. Accepted risks

Carried forward deliberately, with the mitigation recorded, not forgotten.

- Three of four classes drain Stun, so class identity rests entirely on target domain (ADR-0007).
- Inverted XP is farmable across many trivial obstacles; mitigation is content-side, with risk-roll gating as the documented fallback (ADR-0006).
- Random Perks can pull a Runner off their archetype (ADR-0006).
- No permadeath makes this a roguelite; the Security Clock carries all the tension (ADR-0005).
- tcod cannot overlap, rotate, or scale Glyphs (ADR-0004).
- **The Decker carries the Drain burden.** In the obstacle matrix (`classes.md` §6, which is authoritative and has grown since this line was written), the Decker pays Drain on nearly every obstacle type against a handful for the Mage and fewer still for the Shaman. ADR-0007 assumed the three Casters would be separated by domain rather than by cost; they are separated by domain, but they are not equally burdened. Do not quote a count from this file — count the matrix.
- **Advance costs make the campaign short.** `new rating × 3` for a skill means roughly one Job per Advance, and a crew can approach maxed sheets inside the 24-Job v1 campaign. Either the campaign is shorter than assumed, or costs must climb with rating, or Jobs must get harder faster than Heat does.
- **Two classes are interchangeable on some obstacles.** The Adept and the Shaman are the same cell on a forced door and on the paydata vault; the Mage and the Shaman are the same choice against soft targets. The roster is distinct where it matters (matrix devices are Decker-only, hostile Spirits are Mage-only) and undifferentiated where it does not.
- **Gear prices and enemy stats were the thinnest parts of the contract.** Prices are now in section 9; enemy stats are still an open question, and more than one document depends on them.

# Enemies: the five archetypes, their brains, and their devices

`rules.md` and `ai.md` previously ran a placeholder cast because no lane owned enemy numbers;
`rules.md` §3.0 now uses this document's tier-0 blocks, and `DECISIONS.md` §14 records the
placeholder cast as retired (resolved item 14). This document owns them: the stat block, the
behaviour parameters, the carried devices, and the threat each archetype poses.

Vocabulary is `CONTEXT.md`; every number is `DECISIONS.md` (cited as `DEC §n`) or is flagged here as
a proposal in [Open questions](#11-open-questions). Behaviour is **not** re-specified: the trees,
the Utility Score formula, the Weight table, the Morale rule and the action/condition catalogues all
live in `docs/design/ai.md` (cited as `AI §n`); this file fills the parameter values those trees
read and binds each archetype to a tree. Nodes, devices and tiers follow `docs/design/world.md`
(cited as `W §n`).

Conventions used throughout:

- **Attributes** are `DEC §1`'s eight, plus Edge. Enemy Edge ratings are proposed (Open question 4).
- **Skills** are `DEC §2`'s thirteen. `⟨t⟩` means *the Heat-tier skill rating*: **3** at tier 0,
  **4** at tier 2, **5** at tier 3, clamped at 5 (`W §8.3`). `—` means the archetype does not
  possess the skill and never rolls it.
- **Condition Monitors**: Physical `8 + ceil(BOD/2)`, Stun `8 + ceil(WIL/2)` (`DEC §4`).
- **Initiative Score** = `REA + INT + 1d6` (`DEC §5`).
- **AP is a positive magnitude** and is subtracted (`DEC §4`); a stale `rules.md`/`classes.md`
  table writes it signed and is wrong (see [Contradictions](#10-contradictions-found)).
- **Damage type**: S-code is always Stun; a P-code attack becomes Stun when its modified DV is
  less than the modified armour (`DEC §4`). Net Hits add to DV, so a good roll converts a nominal
  Stun into Physical and vice versa.
- **Soak** = `BOD + (armour − AP)` d6, each Hit cancelling one DV (`DEC §4`).
- **Ranged defence** = `REA + INT + cover`; **melee defence** = `AGI + Close Combat`; cover is +2.

---

## 1. Stat-block summary

### 1.1 Attributes

| Archetype | BOD | AGI | REA | STR | WIL | LOG | INT | CHA | EDG |
|---|---|---|---|---|---|---|---|---|---|
| Corp Guard | 4 | 3 | 4 | 3 | 3 | 2 | 3 | 3 | 1 |
| Security Drone | 4 | 4 | 5 | 2 | 3 | 3 | 4 | 1 | 0 |
| Ganger | 4 | 4 | 3 | 4 | 2 | 1 | 2 | 3 | 1 |
| Corp Mage | 3 | 3 | 3 | 3 | 5 | 5 | 4 | 4 | 2 |
| Hellhound | 5 | 5 | 5 | 5 | 3 | 1 | 3 | 1 | 0 |

All five sit inside `DEC §1`'s 1–6 band. The Hellhound is an animal, so its BOD/AGI/REA/STR at 5
is a species rating, not chrome; nothing here exceeds the cap.

### 1.2 Skills

| Skill (linked) | Corp Guard | Security Drone | Ganger | Corp Mage | Hellhound |
|---|---|---|---|---|---|
| Firearms (AGI) | ⟨t⟩ | ⟨t⟩ | ⟨t⟩ | ⟨t⟩ | — |
| Close Combat (AGI) | ⟨t⟩ | 1 | ⟨t⟩ | 1 | ⟨t⟩ |
| Athletics (AGI) | 2 | 3 | 3 | 2 | 4 |
| Stealth (AGI) | 2 | 2 | 2 | 2 | 3 |
| Perception (INT) | ⟨t⟩ | ⟨t⟩ | 2 | 3 | 4 |
| Sorcery (Trad) | — | — | — | ⟨t⟩ | — |
| Conjuring (CHA) | — | — | — | 2 | — |
| Cybercombat (LOG) | — | — | — | — | — |
| Electronics (LOG) | 1 | 2 | — | 2 | — |
| Medicine (LOG) | 1 | — | — | 3 | — |
| Negotiation (CHA) | 2 | — | 1 | 3 | — |
| Con (CHA) | 2 | — | 2 | 2 | — |
| Intimidation (CHA) | 3 | — | 3 | 2 | — |

`DEC §2`'s "starting rating 3–5 by class" is a **Runner** rule; the class sheet does not exist for an
archetype, which is why a Drone has no Negotiation and a Hellhound has no Firearms. The Heat-tier
rating scales the skills the archetype does possess, which is `W §8.3`'s difficulty knob applied to
enemies rather than to fixtures.

### 1.3 Derived numbers (tier 0, no cover)

| Archetype | Physical | Stun | Initiative | Armour | Soak (AP 0) | Weapon (DV) | AP | Range | Attack pool | Ranged def | Melee def |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Corp Guard | 10 | 10 | 7 + 1d6 | 8 (vest 6 + helmet 2) | 12 | Assault rifle (8P) | 2 | 14 | 6 | 7 | 6 |
| Security Drone | 10 | 10 | 9 + 1d6 | 4 (chassis) | 8 | SMG (6P) | 0 | 10 | 7 | 9 | 5 |
| Ganger | 10 | 9 | 5 + 1d6 | 6 (vest) | 10 | Katana (7P) | 3 | 1 | 7 | 5 | 7 |
| Corp Mage | 10 | 11 | 7 + 1d6 | 9 (coat 7 + helmet 2) | 12 | Manabolt (Force 4) | 0 | 12 | 8 | 7 | 4 |
| Hellhound | 11 | 10 | 8 + 1d6 | 2 (hide) | 7 | Bite (7P) | 1 | 1 | 8 | 8 | 8 |

Weapon DV recaps: katana is `(STR + 3)P` = `(4 + 3)P`; bite is `(STR + 2)P` = `(5 + 2)P`; both from
`DEC §4`. The Security Drone's chassis armour 4 and the Hellhound's hide armour 2 have no row in
`DEC §4`'s armour table (Open question 2). Under Lockdown every archetype adds **+2 armour**
(`DEC §9`) — the Drone included, since it is a fixture-grade asset, not a Runner.

### 1.4 Exotic walls

- **The Decker's domain is enemy gear, not enemy bodies.** No archetype is hackable except the
  Security Drone, and it is hackable *because it is a device* (`DEC §7`, `AI §7`: "enemy gear uses
  the same table").
- **No enemy casts, summons, or hacks.** The Corp Mage is the only enemy with a Caster class pool
  (Drain, on its Stun monitor, resisted with `WIL + LOG = 10`). No enemy has Qi. No enemy has a
  cyberdeck, so no enemy scans or hacks (`AI §7`: non-player actors never hack and never summon).
- **The Hellhound is the Decker's designed dead end.** It carries nothing, is nothing, and tracks
  by scent, so a dark room does not hide the crew either.

---

## 2. Corp Guard

**Role:** the gatekeeper. Holds a post, escalates, calls backup. The baseline against which every
other archetype is a variation.

**Stat block** — `§1`; at tier 0 the rifle pool is `AGI 3 + Firearms 3 = 6` and Perception is 3.
Armour 8 (vest 6 + helmet 2), Lockdown 10.

**Behaviour**
- Tree: `corp_guard` (`AI §9.1`) — flee → combat (call_backup → shoot → reload → hold cover →
  close) → investigate noise → pursue last known → return to post → patrol.
- Utility weights: `w_threat 1.0 · w_visible 2.0 · w_objective 1.5 · w_ally_risk 3.0`,
  hysteresis `0.10` (`AI §6.2`). The highest ally-risk weight in the game: it will not shoot
  through its own squad.
- Morale: `morale_bonus +1`, `flee_threshold −4` (`AI §6.2`). With no allies down it breaks at
  Wound Modifier −5.
- Patrol / station: a **patrol ring** inside its node with 2 waypoints and `home_pos` on the
  Blackboard (`W §7.1`). Escalates with `call_backup` (cooldown 4 Passes, `AI §9.1`; a success
  raises `alert_level` to 2 and is `DEC §9`'s "Alarm tripped +2 Clock"). Reloads rather than idles;
  falls back to cover rather than fire through an ally; pulls back to `home_pos` when
  `pursue_last_known` dead-ends.

**Devices**

| Device | Rating | Decker's hack does this | Hack Drain |
|---|---|---|---|
| Assault rifle | Gun 2 | magazine ejected, rifle disabled 3 rounds; guard falls back on the heavy pistol | 1 Stun |
| Helmet optics | Optics 2 | blinded, −3 dice, 3 rounds | 1 Stun |
| Commlink | Commlink 3 | read messages; spoof a distraction (recommended: also blocks `call_backup` for 3 rounds — Open question 5) | 2 Stun |

**Threat budget**
- **Threatens most: the Mage.** The rifle's 14-cell band covers the Mage's 12-cell casting
  position, and the Mage has the crew's worst ranged defence (`REA 3 + INT 4 = 7`) behind the
  crew's fewest Physical boxes (10). Net Hits make most rifle hits Physical (DV 8 ≥ modified
  armour 6–7 against coat 9 or vest 8).
- **Answered best: the Decker** (hack the rifle, 1 Drain, 0 Clock; `classes.md` §6 already scores
  this as ✅) or the **Adept** (Stealth + silent takedown, 0 Clock).
- **A fair fight:** generation places **1 Corp Guard per security node at tier 0**, plus the tier
  extras (`W §7`, `W §8.3`); that placement rule wins, and the node is never just one body because
  it also carries its mandatory devices (§7). This paragraph is a difficulty statement about higher
  tiers, not a placement rule: as the tier table stacks guards, 2 guards is a fight the Crew wins
  with cover, 3 is a real fight, and 4 in the open is an Extraction.

---

## 3. Security Drone

**Role:** the alarm on legs. Flies, patrols rigidly, relays the alarm, and ignores cover. The one
archetype that is both an actor and a device (`data-model.md` §12).

**Stat block** — `§1`; tier 0 SMG pool `AGI 4 + Firearms 3 = 7`. Chassis armour 4; soak 8.

**Behaviour**
- Tree: `security_drone` (`AI §9.2`) — relay alarm → fire → track and aim → patrol. Root
  `"reactive": false`, so it finishes what it started before re-scanning.
- Utility weights: `w_threat 1.2 · w_visible 3.0 · w_objective 1.0 · w_ally_risk 2.0`, hysteresis
  `0.15` (`AI §6.2`). Visibility-dominated: it reacts to what it sees and nothing else.
- Morale: no morale branch at all — a machine (`AI §6.2`, `§9.2`). No flee threshold.
- Patrol / station: a **rigid patrol ring** (2 waypoints; `W §7.1`); on sight it holds and fires,
  and `aim`s (5 Energy, stacks to +2) to convert dead Energy into a better next shot. Its `call_backup`
  is `relay_alarm` on a 3-Pass cooldown.
- **Flight rules.** It never takes cover and cover is no defence against it: it flies over the
  cover predicate. This is the whole reason `AI §9.2` has no cover branch, and it is what makes the
  Drone the answer to a Crew that has settled behind a pillar.

**Devices**

| Device | Rating | Decker's hack does this | Hack Drain |
|---|---|---|---|
| The Drone itself | Drone 4 | seized for 3 rounds, or disabled; a seized Drone stops relaying the alarm | 2 Stun |
| SMG | Gun 2 | magazine ejected, disabled 3 rounds | 1 Stun |
| Sensor optics | Optics 2 | blinded, −3 dice, 3 rounds | 1 Stun |

**Threat budget**
- **Threatens most: the Decker.** The Decker's plan is "take cover, then hack" (`rules.md` §3.2);
  the Drone denies the cover and is itself the highest-value hack target in the room. The tension is
  deliberate: the counter is the thing being threatened.
- **Answered best: the Decker** (seize or disable, rating 4, 2 Drain, 0 Clock; `classes.md` §6).
- **A fair fight:** one Drone per two Runners. A Drone with a Guard is a normal security node; two
  Drones plus a Guard is a node that needs the Light hack or a Stunball. A Drone alone is a nuisance
  that costs the Crew 2 Clock the moment anyone shoots it.

---

## 4. Ganger

**Role:** the opportunist. Poor discipline, no squad, no network, flees at Wound Modifier −3
(`DEC §8`). The archetype that makes the side branch a *choice*.

**Stat block** — `§1`; tier 0 katana pool `AGI 4 + Close Combat 3 = 7`. Armour 6 (vest, no helmet);
soak 10. Stun monitor 9, the lowest in the game.

**Behaviour**
- Tree: `ganger` (`AI §9.3`) — flee → fight (melee → shoot → flank → pursue) → patrol.
- Utility weights: `w_threat 1.5 · w_visible 1.5 · w_objective 0.5 · w_ally_risk 2.5`, hysteresis
  `0.05` (`AI §6.2`). Threat-dominated, objective-blind, and the **lowest hysteresis in the game**:
  it dithers between two near-equal Runners. That dithering is "poor discipline" and is not a bug
  to fix with a bigger margin.
- Morale: `morale_bonus 0`, `flee_threshold −3` (fixed by `DEC §8`: "flees at Wound Modifier −3").
- Patrol / station: patrols its `side` room; **no `call_backup` anywhere** — no commlink, no
  escalation (`AI §9.3`). No investigate branch either: the Ganger does **not** converge on Alert —
  a deliberate archetype trait, not a missing branch (C2, §10). It charges what it sees and runs
  when it hurts.

**Devices**

| Device | Rating | Decker's hack does this | Hack Drain |
|---|---|---|---|
| Heavy pistol | Gun 2 | magazine ejected, pistol disabled 3 rounds; the Ganger draws the katana and closes | 1 Stun |

Nothing else on a Ganger is hackable — no commlink, no optics, no cyberware. A Ganger room is
**Decker-quiet by design**; the node's Door or Lights is what the Decker is there for.

**Threat budget**
- **Threatens most: the Mage.** 10 Physical boxes and melee defence 6 (`AGI 3 + Close Combat 3`);
  a Ganger that gets adjacent with Net Hits makes the katana Physical against coat 9 (DV 7 + Hits ≥
  modified armour 6).
- **Answered best: the Mage's Stunball or the Shaman's Fear.** Gangers cluster in one small room, so
  the area answer is the clean one; the Adept duels them one at a time. The Decker's pistol hack
  is a 1-Drain speed bump, not an answer.
- **A fair fight:** three Gangers in a side room is a fair optional objective; five in the open can
  Down a Runner. Because they flee at 9 filled boxes they rarely fight to the death, which is what
  keeps a side room from being a grinder.

---

## 5. Corp Mage

**Role:** the counter-caster. Counterspells, casts from range, retreats. The archetype that punishes
a Crew leaning on sustained spells.

**Stat block** — `§1`; tier 0 casting pool `LOG 5 + Sorcery 3 = 8`, Drain resistance
`WIL 5 + LOG 5 = 10`. Armour 9 (lined coat 7 + helmet 2); soak 12.

**Class pool:** **Drain**, paid on the Stun monitor (11 boxes). Manabolt at Force 4 is
`max(2, 4 − 3) = 2` Drain (`DEC §6`); a Force 5–6 cast is Drain 2–3. This is the only enemy with a
class-specific pool.

**Behaviour**
- Tree: `corp_mage` (`AI §9.4`) — flee → kite → wounded fall back → counterspell → manabolt →
  reposition. The counterspell branch is legal: Counterspell is in `DEC §7` (opposed Sorcery test to
  cancel an enemy spell, range 12, no Drain by `classes.md` §3.2).
- Utility weights: `w_threat 0.8 · w_visible 2.5 · w_objective 1.0 · w_ally_risk 3.5`, hysteresis
  `0.20` (`AI §6.2`). The highest ally-risk weight and the highest hysteresis: it casts area magic
  from inside its own squad, so it wants a clear line, and once it commits to a counterspell target
  it finishes the job.
- Morale: `morale_bonus 0`, `flee_threshold −4` (`AI §6.2`).
- Patrol / station: **static** — holds the far corner of its node (`W §7.1`), never patrols.
  Withdraws one Step whenever a Runner gets adjacent (`kite`, `dest:"fallback"`); at Wound Modifier
  −2 or worse it takes cover and holds rather than trading.

**Devices**

| Device | Rating | Decker's hack does this | Hack Drain |
|---|---|---|---|
| Datajack / cyberware | Cyberware 4 | −2 dice for 3 rounds; applied to the casting pool, and recommended to the Drain-resistance pool too, so the Mage's own resource degrades | 2 Stun |
| Commlink | Commlink 3 | read messages; spoof a distraction | 2 Stun |

**Threat budget**
- **Threatens most: the Adept.** The Adept's only ranged option is Firearms 4 with a pistol, and the
  Corp Mage kites it; Manabolt outranges a pistol (12 vs 8). The Adept eats Manabolt all the way in.
- **Answered best: the Decker** (hack the datajack, 2 Drain, 0 Clock — no Drain race with an enemy
  Caster) or the **Mage's Counterspell** (`classes.md` §4.2, the domain answer).
- **A fair fight:** 1 Corp Mage + 1 Corp Guard is a security node the whole Crew handles; a lone
  Corp Mage is a two-Runner problem. It is **Stun pressure, not a burst threat**: a default Force 4
  Manabolt (DV 4 + Net Hits) is downgraded to Stun against the Crew's armour 8–10 (`DEC §4`), so it
  bleeds the Casters' Stun resource rather than killing anyone outright. That is the intended shape;
  see Open question 8 for the Force knob.

---

## 6. Hellhound

**Role:** the hunter. Fast melee, tracks by scent, never flees (`DEC §8`). The one archetype that
makes leaving the backline alone a mistake.

**Stat block** — `§1`; tier 0 bite pool `AGI 5 + Close Combat 3 = 8`. Hide armour 2; soak 7.
Physical monitor 11, the largest enemy monitor in the game.

**Behaviour**
- Tree: `hellhound` (`AI §9.5`) — bite → charge → track → patrol. **No flee branch exists in the
  document** (`AI §9.5`): "never flees" is structural, not a condition.
- Utility weights: `w_threat 2.0 · w_visible 2.0 · w_objective 1.0 · w_ally_risk 0.5`, hysteresis
  `0.25` (`AI §6.2`). Highest threat weight, near-zero ally-risk (pure melee, no area attacks), and
  the highest hysteresis: single-minded, never switches mid-run.
- Morale: no morale input; `flee_threshold` is unreachable (`AI §5`, `§6.2`).
- Patrol / station: patrols its node; its `tracks_by_scent` trait puts **every living Runner** into
  its candidate set whether visible or not, so `has_target` stays true through walls and it closes
  without LOS (`AI §5`, `§6.2`). It still has to path around walls — scent is targeting, not
  phasing.

**Devices**

| Device | Rating | Decker's hack does this | Hack Drain |
|---|---|---|---|
| — | — | **nothing to hack.** The Decker's only levers are the node's Door and Lights, and darkness does not stop a scent-tracker | — |

**Threat budget**
- **Threatens most: the Mage.** 10 Physical boxes, melee defence 6 (`AGI 3 + Close Combat 3`), and
  no way to break the scent track once it is hunting.
- **Answered best: the Adept** (katana AP 3 exceeds the hide armour 2, so modified armour is −1 and
  DV 7 + Hits is reliably Physical) or a **Beast / Water Spirit**. The Mage's Manabolt is a Stun pin
  against 11 Physical boxes and is the wrong tool.
- **A fair fight:** 1 Hellhound + 1 Guard (or 1 Ganger) is a `side` or `security` node. **Two
  Hellhounds is an emergency** — together they can Pin a backline Runner inside one Round. Hellhounds
  are released only at Heat tier ≥ 3 (`W §7.1`) because of exactly this.

---

## 7. Device placement by Mission Graph node type

The load-bearing table, and the **detailed authority for device placement** — ratings, mandatory
cells, Heat-tier gates and caps. `W §7` is the population checklist that must match it. The two are
one contract (DEC §7), so every change lands in both or the divergence is a bug. A `—` means the
node type never carries that device. "mandatory" means the embedder must place it.

| Node type | Gun (2) | Optics (2) | Door / lock (2–4) | Lights (3) | Commlink (3) | Drone (4) | Cyberware (4) | Mission device | Enemy-carried devices |
|---|---|---|---|---|---|---|---|---|---|
| `entry` | — | — | **2 mandatory** (the way in) | 3 | **3 mandatory** (guard desk) | — | — | — | Guards only at Heat tier ≥ 2 (gun 2, optics 2, commlink 3) |
| corridor | — | — | 2–4 at 50% | **3 every 15 cells** (`W [P17]`) | — | — | — | — | 1 patrolling Guard at Heat tier ≥ 2 |
| `security` | 2 turret at 50% | **2 mandatory** (camera) | 2–4 (on the through-door) | **3 mandatory** | 3 (desk, 50%) | **4 tier-gated** (`W §8.3`) | — | — | 1 Guard + tier extras; +1 Corp Mage at tier ≥ 2 |
| `objective` — Extraction vault | — | 2 (corner camera) | **4 mandatory** (vault door) | 3 | **3 mandatory** (Paydata terminal) | **4 tier-gated** | — | **Paydata terminal (Commlink 3)** | 1 Guard; +1 Corp Mage at tier ≥ 2 |
| `objective` — Sabotage | — | 2 | 2–4 | 3 | — | — | — | **machine-class device (4)** | 1–2 Guards |
| `objective` — Protection | 2 turret at 50% | 2 | 2–4 | 3 | **3** (the protectee's) | **4 tier-gated** | 4 (the protectee, if augmented) | — | the assault wave: 2 + Heat tier |
| `objective` — Courier drop | — | **2 mandatory** (scanner) | 2–4 | 3 | — | — | — | the package (carried, not a fixture) | 1 Guard |
| `side` | — | 2 (50%) | 2–4 | 3 | — | — | — | loot cache (an item, not a device) | 1–2 Gangers at tier ≤ 1; 1 Guard at tier ≥ 2 |
| `exit` | — | — | **2 mandatory** | 3 | — | — | — | — | 0; 1 Guard while Lockdown is active |

### 7.1 G1 — a Site always has something to hack

Every **main-path** node — `entry`, every `security`, every `objective`, `exit` — carries at least
one hackable device with a `DEC §7` rating. The mandatory cells above are the proof: `entry`'s
Commlink 3 and `exit`'s Door 2 cannot be omitted, so the two nodes most likely to be left empty are
the two that are never empty. If a generation bug still leaves a main-path node bare, the population
pass adds a Lights 3 rather than shipping an empty node (`W §7.1`). The Decker's kit *is* a device
layer (ADR-0008); a main-path node with nothing to hack is a node where one of four Runners has no
class.

### 7.2 G2 — no node is a device piñata

Three caps, now in `DEC §7` (which names `enemies.md` §7 the authoritative table for them):

1. **Carried devices per enemy ≤ 3.** Corp Guard 3, Security Drone 3, Corp Mage 2, Ganger 1,
   Hellhound 0. An archetype that carries nothing (Hellhound) and one that carries a single gun
   (Ganger) exist deliberately so that the Decker's monopoly is *situational*.
2. **Rating-4 devices per node ≤ 2**, excluding the mission device (the vault door, the Paydata
   terminal, both Sabotage targets). Two rating-4 devices is already 4 Stun of Drain.
3. **Hack Drain per node ≤ 6**, excluding the mission device. The Decker's Stun monitor is 10
   (`DEC §4`/`§7`); a node whose fixtures alone cost 8+ Drain is not a puzzle, it is a tax that ends
   the Decker's Run in one room. A `security` node at the cap reads:
   Optics 1 + Gun 1 + Lights 2 + Drone 2 = 6.

The Drain economy is the real brake: `ceil(rating/2)` (`DEC §7`) means a fully-loaded node costs the
Decker roughly half its health, so the *caps above codify a limit the arithmetic already imposes*.

### 7.3 Why the distribution is what it is

- **Doors and Lights are everywhere** because they are the cheap, 0-Clock, every-node hack; they are
  the floor under G1.
- **Guns and Optics scale with enemies**, because they are the Decker's combat contribution
  (`classes.md` §5.3 "Gunmancer").
- **Drones are the prize and are tier-gated**, so tier 0 is not a Drone farm.
- **Cyberware appears only on the Corp Mage and an augmented protectee.** It is the best effect in
  the table (−2 dice for 3 rounds) and should be rare.

---

## 8. Corporate security escalation

`DEC §9` fixes three thresholds: **4 Alert**, **7 Lockdown**, **10 Converge**. `DEC §8` fixes the
Blackboard mapping: `alert_level 0` Calm, `1` Alert, `2` Lockdown, with the site raising every
actor's floor to 1 at Clock 4 and 2 at 7 (`AI §5`, `§8`; `W §8.1` now uses the same values).

**The Clock does not spawn.** The whole garrison is placed at embed time (`W §7`); v1 has no
mid-Run spawner. Crossing a threshold changes what the existing roster *does* and what it *is
wearing*, not who exists. Mid-Run reinforcement waves are a new system and Open question 9.

| State | Clock | `alert_level` | What the roster does | How much worse | What arrives |
|---|---|---|---|---|---|
| **Quiet** | 0–3 | 0 | Guards walk their rings; Drones walk theirs; Corp Mages hold the far corner; Gangers sit in `side` rooms | — | the tier roster (`W §8.3`), fixed at embed |
| **Alert** | 4 | 1 | Corp Guards investigate `noise_pos` / `last_known_pos` and `call_backup` (cooldown 4 Passes, +2 Clock); Drones `relay_alarm` (cooldown 3 Passes); every actor re-scores targets | Patrols are abandoned. The Corp Guards stop guarding and start searching; the `side` rooms keep their Gangers, who move only on sight (§10 C2) | nothing new spawns |
| **Lockdown** | 7 | 2 | Every Door device locks (rating raised to 4 until unlocked, `W §8.1`); every archetype gains **+2 armour** (`DEC §9`); `call_backup` now fails, because `alert_below(level: 2)` is false; Corp Mages stop kiting and hold cover | Doors cost +1 Clock to force or 2 Drain to hack. Guards soak two more dice and a P attack needs two more DV to stay Physical — SMGs and heavy pistols are now Stun-only against the vest 8 | nothing new spawns |
| **Converge** | 10 | — | Security converges; the Run ends | **Forced Extraction**: payout 0, Heat +2, Fixer reputation −1 (`DEC §9`) | the Run is over |

**Who converges.** `rules.md` §7.2 scopes Alert to the trees that carry search branches: the site
raises every actor's floor to 1 and writes `last_known_pos` / `noise_pos`, and only the **Corp
Guard** tree consumes them (`AI §9.1`). The Security Drone, Ganger and Corp Mage trees have no
investigate branch, so Alert is a Corp Guard behaviour and the other three archetypes ignore it
(resolved as C2, §10) — which makes the threshold's bite depend on the garrison's composition
rather than on the Clock.

### 8.1 Escalation by Heat tier (who is even present)

`W §8.3` is authoritative for counts; restated here because escalation reads the roster:

| Heat tier | Heat | Guards / security node | Skill ⟨t⟩ | Archetype roster | Devices added |
|---|---|---|---|---|---|
| 0 | 0–2 | 1 | 3 | Corp Guard, Ganger | baseline |
| 1 | 3–5 | 1 (+1 at 50%) | 3 | + Security Drone | +1 Optics per security node |
| 2 | 6–8 | 2 | 4 | + Corp Mage | +1 Gun turret per security node |
| 3 | 9–11 | 2 (+1 at 50%) | 5 | + Hellhound | main-path locks are rating 4 |
| 4 | 12+ | 3 (frozen) | 5 (frozen) | frozen | frozen |

---

## 9. Threat ratings and encounter budget

Two tables for tuning a difficulty curve later. **Ratings** say what an archetype does; **threat
points** say what a garrison costs. Both are proposals (Open question 12); the per-node *counts* in
`W §8.3` stay authoritative, and points are a check that a garrison sits inside its band.

### 9.1 Threat ratings (1–5)

| Archetype | Offensive | Defensive | Control | Why |
|---|---|---|---|---|
| Corp Guard | 3 | 3 | **4** | The only common *Physical* ranged threat (rifle 8P at 14); armour 8 and 10 boxes behind cover; `call_backup` is the escalation and Lockdown makes it tougher |
| Security Drone | 3 | 3 | **4** | SMG 6P is mostly Stun, but it ignores cover and never misses a sighting; armour 4 is thin, 9 ranged defence and flight are not; `relay_alarm` plus detection |
| Ganger | 2 | 2 | **1** | Katana 7P is real but lands at 7 dice on `5 + 1d6` Initiative; armour 6, no helmet, and it flees at 9 filled boxes; no escalation, no network |
| Corp Mage | **4** | 3 | **5** | Manabolt at 12 cells plus a pistol; armour 9 and it kites; Counterspell (`DEC §7`) switches off the Crew's Casters, which no other archetype can do |
| Hellhound | **5** | 3 | 2 | 8-dice melee at 7P, sprint in, scent through walls, never flees; 11 Physical boxes is the largest monitor in the game; armour 2 is the one soft spot |

### 9.2 Encounter budget per Job difficulty tier

The Job difficulty tier *is* the Heat tier (`W §8.3`): higher Heat means harder Sites and the Job pool
follows. Point values below are the tuning currency; the roster column is `W §8.3`'s and is what
generation actually places.

| Archetype | Threat points |
|---|---|
| Ganger | 2 |
| Corp Guard | 3 |
| Security Drone | 5 |
| Corp Mage | 7 |
| Hellhound | 8 |

| Job / Heat tier | Heat | Point budget | Roster available | Example garrison (Extraction, 9 nodes) |
|---|---|---|---|---|
| 0 | 0–2 | 22–28 | Guard, Ganger | 5 Guards + 5 Gangers = 25 |
| 1 | 3–5 | 28–36 | + Drone | 6 Guards + 4 Gangers + 1 Drone = 18 + 8 + 5 = 31 |
| 2 | 6–8 | 38–48 | + Corp Mage | 8 Guards + 2 Gangers + 1 Drone + 1 Mage = 24 + 4 + 5 + 7 = 40 |
| 3 | 9–11 | 50–62 | + Hellhound, skill 5 | 10 Guards + 1 Drone + 2 Mages + 1 Hellhound = 30 + 5 + 14 + 8 = 57 |
| 4 | 12+ | 50–62 (frozen) | frozen | frozen at tier 3 |

The bands overlap deliberately: an 8-node Courier and a 14-node vault run should not cost the same.
A garrison below its band is a quiet Job; above it is the top of the spiral that ADR-0012 wants
to terminate.

---

## 10. Contradictions found

Recorded here rather than patched around. Each was a real conflict between two documents that
predate this one; the entries marked **Resolved** have since been fixed in the named document.

- **C1 — `alert_level` at Alert. Resolved.** `DEC §8` fixes the mapping at `0 Calm / 1 Alert /
  2 Lockdown`, with the site raising the floor to 1 at Clock 4 and 2 at 7. `W §8.1`'s earlier
  `alert_level = 2` at Alert was the straggler; it is now corrected to 1, matching `AI §5` and
  `rules.md` §7.2.
- **C2 — Alert convergence for three of five trees. Resolved.** `rules.md` §7.2 no longer promises
  site-wide search behaviour; it names only the trees that carry search branches, the Corp Guard's
  `investigate_noise` / `pursue_last_known` (`AI §9.1`). The Drone, Ganger and Corp Mage trees have
  no such branch, so Alert is a Corp Guard behaviour and the Ganger's non-convergence is a
  deliberate archetype trait (§4), not a contradiction.
- **C3 — Security Drones at tier 0. Resolved.** `W §7`'s Drone entries are now gated on Heat
  tier ≥ 1 to match `W §8.3`'s roster, so a Heat 0 Run (the guaranteed-winnable floor) holds Guards
  only; `W §7` cross-references the tier table.
- **C4 — The Corp Mage's commlink and its tree disagree. Resolved.** `AI §7`'s `call_backup`
  prerequisite now requires a commlink *and* a `call_backup` leaf, and names the Corp Mage as one
  that "carries one but never calls backup" (`AI §9.4`). The prerequisite list and the tree agree.
- **C5 — Assault rifle range. Resolved.** **14** cells is the contract (`DEC §4`), and `ai.md`
  states 14; there is no 16-cell recommendation anywhere (§12 is `ai.md`'s open-questions list and
  carries no range). The signed bite AP `−1` is likewise gone: `ai.md` §9.5 writes the bite
  `(Strength + 2)P` **AP 1**, positive as `DEC §4` requires.
- **C6 — Weapon and armour tables sign AP. Resolved.** AP is a positive magnitude everywhere
  (`DEC §4`). `rules.md` states the positive rule, `classes.md` writes AP positive (AP 3, AP 1), and
  `ai.md` §9.5 writes the bite AP 1. No document still writes a signed AP.
- **C7 — The placeholder cast is superseded. Resolved.** `rules.md` §3.0 now uses this document's
  tier-0 Corp Guard (BOD 4 · AGI 3 · REA 4 · STR 3, armour 8 = vest 6 + helmet 2, assault rifle 8P
  AP 2 range 14, Firearms pool 6), so the old AGI 4 / SMG 6P placeholder is gone, and `DEC §14`
  records the placeholder cast as retired (resolved item 14).
- **C8 — "Waves arrive" in Protection has no spawner. Resolved.** `W §4.2`'s unspawned "waves"
  claim is removed: the Protection hold is attacked by its **placed** garrison (2 + Heat tier,
  `W §7`), placed once at embed. No document promises a Mid-Run spawner; if one is ever wanted it is
  Open question 9.

---

## 11. Open questions

Nothing below is settled; each carries a recommendation. Items 1, 5 and 6 are the ones with code
consequences.

1. **Behaviour parameters have no home in `DECISIONS.md`.** `DEC §8` fixes the Utility Score
   *formula*, `morale_bonus` and `flee_threshold` as per-archetype parameters, but supplies values
   only for the Ganger (−3) and the Hellhound (never). This document uses `AI §6.2`'s proposed
   table (`w_threat / w_visible / w_objective / w_ally_risk / hysteresis / morale_bonus /
   flee_threshold`) and `AI §9`'s trees. *Recommendation:* move `AI §6.2` into `DEC §8` verbatim so
   the weights have one home.
2. **Non-humanoid armour has no row.** Chassis 4 (Security Drone) and hide 2 (Hellhound) are not in
   `DEC §4`'s armour table, which only prices wearable armour. *Recommendation:* add two rows to
   `DEC §4` — "Drone chassis 4", "Animal hide 2" — rather than leaving them as enemy-block numbers.
3. **Enemy skill floor.** `DEC §2` gives Runners a 3–5 starting band; an enemy has no class sheet, so
   unpossessed skills are `—` and possessed skills scale with the Heat tier. *Recommendation:* state
   in `DEC §2` that the 3–5 band is a Runner rule and that enemy sheets list only possessed skills.
4. **Enemy Edge.** Edge ratings here are 1 (Guard, Ganger), 2 (Corp Mage), 0 (Drone, Hellhound), but
   no condition or action in `AI §7`/`§8` spends Edge, so an enemy Edge pool is inert in v1.
   *Recommendation:* either add an `Edge` spend leaf to the catalogue (a Guard pushing a shot, a
   Mage pushing a Drain resistance) or declare enemies Edge-less and drop the column.
5. **Does hacking a commlink stop `call_backup`?** `DEC §7` gives the commlink hack two effects
   (read messages, spoof a distraction) and neither interrupts escalation, yet `AI §7` makes the
   commlink the `call_backup` prerequisite. *Recommendation:* a successful Commlink 3 hack disables
   `call_backup` for 3 rounds. Without it the Decker cannot silence a room before the alarm, which
   is the class's most obvious play.
6. **What brain does a seized Drone have?** `DEC §7` says the Drone is "seized for 3 rounds"; `AI`
   does not say what drives it while seized. *Recommendation:* reuse the Spirit model — the Decker
   issues a target and the Drone's own tree under it — and have seizure suppress `relay_alarm`.
7. **Alert convergence for the other three trees.** The rules-text half is resolved (C2); what
   remains open is whether the Security Drone and Corp Mage should gain an Alert-gated
   `move_to_blackboard{key:"noise_pos"}` branch. *Recommendation:* yes for the Drone and Corp Mage;
   leave the Ganger non-converging as a deliberate archetype trait.
8. **Corp Mage Manabolt Force.** The `Force 4` baked into `AI §9.4` is downgraded to Stun against
    the Crew's armour 8–10, making the Corp Mage a Stun/control enemy by default. *Recommendation:*
    make Force scale with the Heat tier (4 / 5 / 6 at tiers 0 / 2 / 3, Drain 2 / 2 / 3), so a
    high-Heat Corp Mage can actually reach Physical DV.
9. **Mid-Run reinforcement waves.** The Clock currently escalates behaviour and armour but spawns
    nothing; no document now promises arrivals (`W §4.2`'s Protection "waves" claim was removed).
    *Recommendation:* no general
    spawner in v1 (ADR-0005 makes the Clock the loss state, and a spawner weakens it); if one is
    wanted, scope it to Protection's hold, seeded by the tier roster, and use the existing flow map
    for pathing.
10. **Manabolt has no AP row.** `DEC §4` prices spells by DV only. *Recommendation:* AP 0 for all
    spells, so armour is the whole counter to a caster (and the P-to-Stun rule is what makes a
    Force 4 Manabolt a Stun pin).
11. **AP can exceed armour.** A katana (AP 3) against the Hellhound's hide 2 gives modified armour
    −1, and `DEC §4` never clamps it, so soak drops below `BOD` and the P-to-Stun comparison runs
    against a negative number. *Recommendation:* clamp modified armour at 0 (`armour − AP`, floor
    0) in `DEC §4`, so an over-penetrating hit simply leaves no soak rather than a negative.
12. **Threat ratings and point budgets.** The 1–5 offensive/defensive/control ratings and the
    threat-point bands in §9 are this document's proposals, keyed to the Heat tiers `W §8.3` already
    defines. *Recommendation:* adopt the points as a generation assertion (warn when a Site's
    garrison falls outside its tier's band), and revisit the numbers once a full difficulty curve is
    tuned — the bands are the hook for tuning it, not the curve itself.

---

## 12. Sources

Patterns borrowed, by file:

- `.agents/skills/roguelike/SKILL.md` — "monsters obey the same rules as the player" is why every
  archetype gets a full Runner-shaped sheet (eight attributes, thirteen skills, both Condition
  Monitors, the same dice); "scale monsters/loot by depth and keep resources scarce" is the Heat-tier
  roster and the min-depth gate on the Hellhound and the Security Drone; "show HP, turn results, and a
  message log" is why the stat blocks are written to be read at the table.
- `.agents/skills/roguelike/references/generation-fov-loot.md` — separate the **monster** spawn table
  from the **item** table, and gate stronger entries behind a minimum depth. §7's device table is a
  spawn table keyed by Mission Graph node type instead of depth, and §8.1 is the same gate applied to
  Heat.
- `.agents/skills/game-ai/SKILL.md` — "separate decision from motion" and "recompute paths sparingly"
  behind the patrol/station split and the flow-map drift at Alert; the guard tree sketch
  (`Selector[Sequence[CanSeePlayer → Chase], Patrol]`) is the shape `AI §9.1` expands; the pitfall
  "behavior tree leaves that never return RUNNING restart the action" is why `patrol` returns
  RUNNING and not SUCCESS.
- `.agents/skills/game-ai/references/behavior-trees.md` — the blackboard keys (`player`, `home`,
  `path`) and the utility-AI brief behind the per-archetype Utility Score; the "Blackboard as typed
  key/value store" rule is `AI §5`'s fixed eight keys.
- `docs/design/ai.md` — the trees, the Utility Score, the weight table and the Morale rule are used
  as written; this document supplies the parameter values and the stat blocks they read.
- `docs/design/world.md` — Heat tiers (`§8.3`), the per-node population table (`§7`), and the Decker
  guarantee (`§7.1`) are the anchors for §7 and §8.1 here.

# Classes, Spirits, and Progression

Everything needed to build and play the four Runners of the Crew, plus the growth loop after a Run.
Numbers come from `docs/design/DECISIONS.md`. Where a number is **not** there it is marked `†` and
repeated in [Open questions](#13-open-questions). Vocabulary is `CONTEXT.md`'s; no synonyms.

Conventions used throughout:

- Every power is a **Use power** action: **10 Energy**.
- A **round** (used for every duration below) is one cycle in which every actor has taken one Pass,
  i.e. until each Initiative Score has dropped below the point where another Pass begins. Initiative
  is **re-rolled at the start of every round** (DECISIONS §5).
- `†` = proposed parameter, listed in Open questions with a recommendation.
- Gear prices are DECISIONS §9; weapon ranges and magazine sizes are DECISIONS §4. This document does
  not restate them.
- Dice pools are `linked attribute + skill + modifiers`.

---

## 0. Element of the Crew

All four Runners exist at Run start. No recruitment, no class selection, no permadeath.
XP and Perks are **per Runner**; Advances are bought per Runner at the Hub between Jobs.
Edge is 3 points for every Runner and refreshes at the start of each Run.

| | Physical Adept | Mage | Shaman | Decker |
|---|---|---|---|---|
| Acts on | bodies and geometry | people and space | bodies it conjures, plus zones | devices |
| Pool | Qi | Stun monitor (Drain) | Stun monitor (Drain) | Stun monitor (Drain) |
| Tradition Attribute | — | Logic | Charisma | Logic |

---

## 1. Starting stat blocks

One table, one column per Runner. This is the whole starting block; each Runner's derived numbers
are repeated in their section.

### 1.1 Attributes

| Attribute | Physical Adept | Mage | Shaman | Decker | Use |
|---|---|---|---|---|---|
| Body | **6** | 3 | 4 | 4 | soak, Physical monitor |
| Agility | **7** | 3 | 4 | **5** | firearms, close combat, athletics, stealth |
| Reaction | **6** | 3 | 4 | 5 | ranged defence, Initiative Score |
| Strength | **7** | 3 | 3 | 3 | melee damage |
| Willpower | 4 | **5** | **5** | 4 | Drain resistance, Stun monitor |
| Logic | 3 | **6** | 3 | **6** | Cybercombat, Electronics, Medicine, Mage/Decker Tradition |
| Intuition | 4 | 4 | 4 | 5 | Perception, defence, Initiative Score |
| Charisma | 3 | 4 | **6** | 3 | Conjuring, social skills, Shaman Tradition |
| Edge | 3 | 3 | 3 | 3 | luck pool |

Attribute cap is 6; the Physical Adept may Advance **Agility and Strength to 7** `†` (its two
prodigal attributes).

### 1.2 Skills (13, each 3–5 at creation)

| Skill | Linked | Physical Adept | Mage | Shaman | Decker |
|---|---|---|---|---|---|
| Firearms | AGI | 4 | 3 | 4 | 4 |
| Close Combat | AGI | **5** | 3 | 3 | 3 |
| Athletics | AGI | **5** | 3 | 3 | 4 |
| Stealth | AGI | 4 | 3 | 3 | 4 |
| Perception | INT | 4 | 4 | 4 | 4 |
| Sorcery | Trad | 3 | **5** | 4 | 3 |
| Conjuring | CHA | 3 | 4 | **5** | 3 |
| Cybercombat | LOG | 3 | 3 | 3 | **5** |
| Electronics | LOG | 3 | 3 | 3 | **5** |
| Medicine | LOG | 3 | 4 | 3 | 3 |
| Negotiation | CHA | 3 | 3 | **5** | 3 |
| Con | CHA | 3 | 3 | 4 | 4 |
| Intimidation | CHA | 4 | 3 | 3 | 3 |

Skill cap is 6. Nine of the thirteen skills sit at the floor of 3 for at least one Runner; §6 shows
which of those are dead weight outside their owner's domain.

### 1.3 Derived numbers

| | Physical Adept | Mage | Shaman | Decker |
|---|---|---|---|---|
| Physical monitor | 8 + ceil(6/2) = **11** | 10 | 10 | 10 |
| Stun monitor | 8 + ceil(4/2) = **10** | 11 | 11 | 10 |
| Initiative Score | 10 + 1d6 | 7 + 1d6 | 8 + 1d6 | 10 + 1d6 |
| Armor worn | 8 + 2 = **10** | 7 + 2 = **9** | 7 + 2 = **9** | 6 + 2 = **8** |
| Primary pool | unarmed/katana | `LOG 6 + Sorcery 5` = **11** | `CHA 6 + Conjuring 5` = **11** | `LOG 6 + Cybercombat 5` = **11** |
| Drain pool | — | `WIL 5 + LOG 6` = **11** | `WIL 5 + CHA 6` = **11** | `WIL 4 + LOG 6` = **10** |

---

## 2. Physical Adept

**BOD 6 · AGI 7 · REA 6 · STR 7 · WIL 4 · LOG 3 · INT 4 · CHA 3** — Edge 3, **Qi pool 4**.

### 2.1 Gear

| Item | Effect |
|---|---|
| Katana | `(STR + 3)P` = **10P**, AP 3 |
| Heavy pistol | 5P, AP 1 |
| Armoured jacket | armor 8 |
| Helmet | armor +2 |
| Commlink | device rating 3 — hackable by an enemy Decker |
| Medkit | enables `LOG + Medicine` first aid |

Soak pool `BOD 6 + (10 − AP)`. A heavy pistol (AP 1) rolls `6 + 9 = 15` dice against it; an
assault rifle (AP 2) `6 + 8 = 14`.

### 2.2 Qi powers (all 10 Energy)

Qi starts at 4 and gains **+1 at the start of each Pass**, **capped at 4** (DECISIONS §6) — the cap
is what keeps it a resource rather than a ramp. Powers last 3 rounds unless stated.

| Power | Qi | Effect |
|---|---|---|
| Improved Reflexes | 2 | +1d6 Initiative Score for the rest of the Run (max +2d6 in v1) |
| Killing Hands | 1 | unarmed becomes lethal, +1 DV, 3 rounds |
| Wall Run | 1 | cross one impassable tile |
| Mystic Armor | 1 | +2 soak, 3 rounds |
| Attribute Boost | 1 | +1 die to Agility, Strength, or Reaction, 3 rounds |

Unarmed DV is `Strength` (Stun), AP 0 `†`; with Killing Hands it is `(Strength + 1)P`.

### 2.3 Builds

| Build | Maximises | Signature | Gives up |
|---|---|---|---|
| **Razorgirl** — Close Combat 5, katana, Killing Hands, Improved Reflexes | single-target DV in melee. 10P at AP 3, unarmed 8P after Killing Hands, +1d6 Initiative for extra Passes | Charge a guard, silent takedown, 0 Clock | any ranged answer; Firearms 4 is a placeholder. Useless against a Spirit (Stun only) and against a Matrix device |
| **Ghost** — Stealth 5, Athletics 5, Wall Run + Attribute Boost (Agility) | not being tested at all. Stealth pool 7+5 = 12 `†` (Silent takedown pays 0 Clock) | Wall Run past a locked door or a drone line instead of engaging | damage; the least useful Adept in a fight, and the build that fails most, so it out-levels the crew (see §12) |
| **Gunslinger** — Firearms 5, Attribute Boost (Reaction) | ranged skirmishing and Pass count. Pool 7+5 = 12 `†`, +1 die Reaction, +1d6 Initiative | Two Passes of pistol fire at DV 5 before anyone closes | soak; WIL 4 means a 10-box Stun monitor, the first Runner to be drained by a Corp Mage |

### 2.4 Strengths and weaknesses

| Strengths | Weaknesses |
|---|---|
| Highest soak and the only 11-box Physical monitor | Zero ranged-domination tools: no spells, no hacks, no Spirit |
| Killing Hands makes a weaponless Adept lethal | Every Qi power is self-only; it buffs nobody else |
| Athletics 5 + Wall Run bypasses geometry without ticking the Clock | Damage from non-magical attacks is Stun against a Spirit — the Adept's worst row in §6 |
| Fastest sustained Initiative in the crew | CHA 3: the worst social Runner, and no answer to a social gate except Intimidation |

---

## 3. Mage

**BOD 3 · AGI 3 · REA 3 · STR 3 · WIL 5 · LOG 6 · INT 4 · CHA 4** — Edge 3, no pool.

### 3.1 Gear

| Item | Effect |
|---|---|
| Heavy pistol | 5P, AP 1 |
| Lined coat | armor 7 |
| Helmet | armor +2 |
| Commlink | device rating 3 |
| Medkit | enables first aid |

### 3.2 Spells (all 10 Energy, Force chosen at cast time 1–8)

Casting pool is `LOG + Sorcery` = 11. Sustained spells cost **−2 dice on everything else each**,
last until dropped (free) or the Mage is Downed, and **at most two may be sustained at once**
(DECISIONS §6).

| Spell | Range | Effect | Drain |
|---|---|---|---|
| Manabolt | 12 tiles, LOS | Opposed `LOG + Sorcery` vs `REA + INT + cover`; DV = Force, net Hits add; damage type by the normal rule | `max(2, Force − 3)` |
| Stunball | 12 tiles, LOS | Success Test vs threshold 2; DV = Force **Stun** + Hits to every actor within radius 2 of the target cell | `max(3, Force − 2)` |
| Heal | 12 tiles, LOS | Restores `Hits` boxes on a target's **Physical** monitor. Cannot target a Downed Runner (ADR-0005) | `max(3, Force − 1)` |
| Analyze Device | 12 tiles, LOS | Reveals every device in radius and its rating (the §6 device table) | `max(1, Force − 4)` |
| Invisibility | 12 tiles, LOS | Target gains **+3 Stealth dice**; sustained | `max(2, Force − 2)` |
| Armor | 12 tiles, LOS | Target gains **+2 soak**; sustained | `max(2, Force − 2)` |
| Counterspell | 12 tiles, LOS | Opposed `LOG + Sorcery` test against an enemy caster's Hits; each net Hit cancels one of the caster's Hits. No Drain | — |

Spell range is DECISIONS §4's **12 cells with line of sight**. Radius is Chebyshev (radius 2 = the
5×5 cell block) `†`. Drain is resisted with `WIL + LOG` = 11, unresisted boxes are Stun. **Note the
Force rule:** Drain is Physical only when `Force > the Tradition Attribute`. Force runs 1–8 against
Logic 6, so **Force 7 and 8 take Physical Drain** — overcasting is the Mage's one way to convert a
cast into real risk, and it also costs **+2 Clock** (loud spell at Force ≥ 4). Force ≤ 3 is the clean
band: no Clock, Stun Drain.

Casting at Force ≥ 4 adds **+2 Clock** (loud spell). Force 2–3 is free of Clock.

### 3.3 Builds

| Build | Maximises | Signature | Gives up |
|---|---|---|---|
| **Blaster** — Sorcery 6 eventually, Manabolt at Force 5–6 | damage. DV 6 + net Hits, Physical, no Clock at Force ≤ 3 | One-shot a Guard from 10 tiles | Sustains nothing for the crew; Drain 3 per cast means three casts empty the Stun monitor's useful margin |
| **Support** — Heal, Armor, Invisibility | keeping the crew on their feet and unseeable | Armor on the Adept (+2 soak) + Heal the tank + Invisibility on the face | near-zero damage; wholly dependent on the other three Runners doing the work |
| **Recon** — Analyze Device + Invisibility, never casts past Force 3 | intel and Clock discipline. Zero Clock from magic, device list revealed before contact | Pre-map the Site, Invisibility the face through a social gate | one sustained spell's worth of actions per Pass; a Corps Mage counterspells it and it has nothing left |

### 3.4 Strengths and weaknesses

| Strengths | Weaknesses |
|---|---|
| The only in-Run healer and the only clean answer to a hostile Spirit (magic is Physical to them) | Stun monitor is both the resource and the health track (ADR-0007) |
| Armor and Invisibility are the only buffs in the crew | BOD 3, REA 3: 10 Physical boxes, the worst defence pool in the crew |
| Manabolt is Physical damage at range with no device or Spirit required | Sustained spells tax every other action by 2 dice |
| Analyze Device exposes the Decker's target list without Drain on the Decker | No answer to any device row except "reveal it" |

---

## 4. Shaman

**BOD 4 · AGI 4 · REA 4 · STR 3 · WIL 5 · LOG 3 · INT 4 · CHA 6** — Edge 3, no pool.

One bound Spirit at a time `†`. Summoning while a Spirit is bound dismisses the first with no
break-free roll.

### 4.1 Gear

| Item | Effect |
|---|---|
| SMG | 6P, AP 0 |
| Lined coat | armor 7 |
| Helmet | armor +2 |
| Commlink | device rating 3 |
| Medkit | enables first aid |
| Totem focus | flavour; carries the §8 Totem |

### 4.2 Powers (all 10 Energy)

| Power | Range `†` | Effect | Drain |
|---|---|---|---|
| Summon Spirit | 6 tiles | See §7. Force 1–6 | `2 × the Spirit's Hits`, minimum 2 |
| Fear | 8 tiles | Success Test `CHA + Conjuring` vs threshold 2; every enemy within radius 2 takes **−2 dice for 3 rounds**. Mindless actors are immune: Drones and Spirits | `max(2, Force − 2)` |
| Ward | centred on the Shaman | Radius 2 zone for 3 rounds: **−1 die** to any enemy magic cast into the zone or from inside it | `max(2, Force − 3)` |
| Totem passive | — | Always on; see §8 | — |

Drain is resisted with `WIL + CHA` = 11. Summon Drain is the Shaman's big spend; Fear and Ward now
carry the two smallest Drain values on the table (`max(2, Force − 2)` and `max(2, Force − 3)`), so
the Shaman's Stun monitor still degrades slower per effect than the Mage's or the Decker's.

Counterspell is the **Mage's** ability (DECISIONS §7, §3.2), not a cross-class one; the Shaman's
answer to enemy casting is Ward. That leaves the Shaman's Sorcery 4 with no in-domain use — an open
skill-slot question, see Open question 5.

### 4.3 Builds

| Build | Maximises | Signature | Gives up |
|---|---|---|---|
| **Spirit-Slinger** — Conjuring 5, a Beast or Air Spirit standing every round | a fifth body on the map. A Force 3 Beast is 5 BOD / 5 STR, 6-dice attack at 6P | Send the Spirit into the heavy weapons team while the crew does the objective | Drain 4-ish per summon; two summons and the Stun monitor is half full. Own damage is an SMG at 6P |
| **Face** — Negotiation 5, Con 4, Intimidation 3, Fear | solving the Job without a Clock tick. Pool `CHA 6 + Negotiation 5` = 11 for the social gate and the payout formula | Talk a guard off his post, then Fear whoever is left | contributes almost nothing in a firefight; every fight is the other three's problem |
| **War-Shaman** — Fear + Water Spirit + Ward | area control. Fear −2 dice on everything in a 5×5, a Water Spirit's area Stun, Ward denying the Corp Mage | Stack Fear and Water on a choke point, Ward the Decker while he works | summons a slow, low-DV Spirit; leans on Drain for three separate effects in one fight |

### 4.4 Strengths and weaknesses

| Strengths | Weaknesses |
|---|---|
| The only Runner with a second body; the Spirit absorbs fire the crew would take | Every Spirit costs Drain, and a failed summoning creates a hostile instead |
| Fear is the cheapest area debuff in the game (the smallest Drain value on the table, 3 rounds) | LOG 3: the worst Decker-adjacent Runner and Medicine 3 |
| The face: best social pool in the crew, and the social gate is often the only 0-Clock route | No answer to any Matrix device, ever |
| Ward is the Shaman's counter to a Corp Mage's area casting (the Mage counterspells instead) | The Spirit's break-free check is a second failure surface on every command |

---

## 5. Decker

**BOD 4 · AGI 5 · REA 5 · STR 3 · WIL 4 · LOG 6 · INT 5 · CHA 3** — Edge 3, no pool.

The Decker requires a **cyberdeck** (**8,000 ¥**, DECISIONS §9; item id `cyberdeck`). Without it,
none of the device table is available to anyone, and losing it removes the class's core ability —
the one piece of gear with a stated consequence.

### 5.1 Gear

| Item | Effect |
|---|---|
| Cyberdeck | item id `cyberdeck`; the hacking implement, required for Scan and Hack |
| Heavy pistol | 5P, AP 1 |
| Armoured vest | armor 6 |
| Helmet | armor +2 |
| Commlink | device rating 3 |
| Medkit | enables first aid |

### 5.2 Powers (all 10 Energy)

| Power | Range `†` | Effect | Drain |
|---|---|---|---|
| Scan | radius 12 | Reveals the device list and every rating in radius. No test | **1** |
| Hack | line of sight, 12 tiles | Success Test `LOG + Cybercombat` vs **threshold = device rating** | `ceil(rating / 2)`, **doubled on a Glitch**, no resistance roll |

Costs are fixed by the table below; a failed hack is **+1 Clock**, a successful one is 0.

| Device | Rating | Effect |
|---|---|---|
| Gun | 2 | eject magazine, disabled 3 rounds |
| Optics | 2 | blinded, −3 dice, 3 rounds |
| Door or lock | 2–4 | unlocked |
| Lights | 3 | toggles the room's lighting. Off: **enemies** inside have FOV radius 2 and −2 dice (DEC §7 Lights); the Crew is unaffected |
| Commlink or phone | 3 | read messages; spoof a distraction |
| Drone | 4 | seized for 3 rounds, or disabled |
| Cyberware | 4 | −2 dice to one enemy for 3 rounds |

Enemy gear uses the same table, so the Decker can hack a guard's gun as easily as a door.

### 5.3 Builds

| Build | Maximises | Signature | Gives up |
|---|---|---|---|
| **Ghost-hack** — Cybercombat 5, Electronics 5, hacks only locks, cameras, lights | 0-Clock entry. Every hack is rated 2–4, so Drain 1–2 and no gunfire | Open the perimeter door, blind the camera cluster, walk in | damage; against an unnetworked Site (no devices) the build is a Heavy pistol with 4 dice behind it |
| **Gunmancer** — Cybercombat 6 eventually, targets enemy guns and cyberware | disarming a fight. Rating 2 guns at Drain 1, four enemies neutered for 3 rounds | Turn a heavy weapons team into four men holding paperweights | Drain 4–8 per Pass of heavy work; both Condition Monitors take it |
| **Recon Decker** — Electronics 5, Scan every room, Analyze Device synergy | knowing the Site. The device list is revealed before the crew commits | Feed the crew the guard's optics rating and let the Mage choose Force | only 1 Drain per Scan but no effect on the map; contributes no damage, no healing, no Spirit |

### 5.4 Strengths and weaknesses

| Strengths | Weaknesses |
|---|---|
| The only Runner who can solve a Matrix device row — a hard domain wall, not a preference | Drain 2 for a Drone or Cyberware hack (4 on a Glitch), paid on more obstacle rows than any other Caster's effect |
| Hacks resolve immediately in the physical world, at any range up to 12 tiles | Every hack is a Glitch risk, and a Glitch doubles Drain *and* ticks the Clock |
| REA 5 + INT 5 = 10 + 1d6 Initiative, tied with the Adept for the most Passes | Requires a cyberdeck; losing it removes the class |
| Neutralises enemy *gear* rather than enemy bodies, which sidesteps armour entirely | No answer to Spirits, Fear, or a social gate |

---

## 6. Domain overlap matrix

Every cell is a way to solve the obstacle and its cost. ✅ clean solve · ◐ partial or expensive ·
— no answer. `E` = Energy on top of the standard 10 for a power.

Costs shorthand: **⚙** Clock segments, **🩸** Drain (Stun), **Qi** the Adept's pool, **¥** nuyen.

| Obstacle | Physical Adept | Mage | Shaman | Decker |
|---|---|---|---|---|
| **Locked door** (rating 2–4) | ◐ Force it `STR + Close Combat` vs rating; ⚙1 | — | ◐ Spirit forces it; ⚙1 | ✅ Hack lock; 🩸1–2, ⚙0 |
| **Patrolling guard** | ✅ Stealth + silent takedown; ⚙0 on success, ⚙3 if the body is found | ✅ Manabolt; ⚙0 at Force ≤ 3, ⚙2 at Force ≥ 4 | ✅ Fear −2 dice for 3 rounds, or Con/`CHA` | ✅ Hack optics; −3 dice 3 rounds, 🩸1, ⚙0 |
| **Security drone** (rating 4) | ◐ Shoot it; ⚙2 gunfire | ◐ Manabolt; ⚙2 if loud | ◐ Beast Spirit tanks it; 🩸4 + Spirit risk | ✅ Seize 3 rounds or disable; 🩸2, ⚙0 |
| **Camera** | ◐ Shoot it; ⚙2 | ◐ Manabolt; ⚙2 if loud | — (no mind to Fear, nothing to smash cheaply) | ✅ Blind it, −3 dice 3 rounds; 🩸1, ⚙0 |
| **Dark room** | ✅ Fight normally; darkness only blinds enemies (FOV 2, −2 dice), never the Crew | ✅ Fight normally | ✅ Fight normally | ✅ Toggle the lights: off blinds the garrison, on restores the room; 🩸2, ⚙0 |
| **Hostile spirit** | ◐ Katana deals **Stun only**; slow, expensive grind | ✅ Manabolt is Physical to a Spirit | ✅ Banish it `CHA + Conjuring` vs Force, or fight it with your own | — |
| **Enemy caster (Corp Mage)** | — | ✅ Counterspell: opposed `LOG + Sorcery`, range 12; ⚙0, no 🩸 | ◐ Ward −1 die to enemy magic entering the zone; 🩸`max(2, Force − 3)` | — |
| **Wounded ally** | ◐ `LOG + Medicine` vs 2 = 1 Stun box or stop Overflow `†` | ✅ Heal, `Hits` boxes of Physical | ◐ Same first aid as the Adept | ◐ Same first aid as the Adept |
| **Social gate** | ◐ Intimidation `CHA 3 + Intimidation 4` = 7 dice; works, raises Heat `†` | ◐ `CHA 4 + 3` = 7 dice | ✅ `CHA 6 + Negotiation 5` = 11 dice, and sets the payout | ◐ Con `CHA 3 + 4` = 7 dice |
| **Matrix device / paydata host** | — (can only smash the terminal, losing Paydata) | — (Analyze Device locates it; Manabolt destroys it) | — | ✅ `LOG + Cybercombat` vs rating 3; 🩸2, ⚙0 |
| **Heavy weapons team** (2+ assault rifles) | ✅ Katana 10P at AP 3; the fastest kill | ✅ Stunball radius 2; DV Force Stun | ✅ Beast Spirit + Fear | ✅ Hack both guns; 🩸2 total, ⚙0 |
| **Trapped corridor** | ✅ Perception to spot, Athletics 5 + Wall Run (1 Qi) to cross | ◐ Analyze Device reveals the trigger | ◐ Send the Spirit ahead to soak it | ◐ Hack the trigger **only if it is a rated device**; a pressure plate has no device row, so nothing to hack |
| **Paydata vault** | ◐ Force it; ⚙1 | — | ◐ Spirit forces it; ⚙1 | ✅ Hack rating 4; 🩸2, ⚙0 |

Ranges: weapons per DECISIONS §4 (melee 1; pistol 8, SMG 10, rifle 14, shotgun 6); spells,
Counterspell, Scan and Hack all reach **12 cells with line of sight**. Spell Force is 1–8, so
overcasting (Force 7–8) is where a Caster meets Physical Drain.

### 6.1 Verdict on the accepted risk (ADR-0007)

**Where classes are genuinely interchangeable — say so out loud:**

- **Adept ↔ Shaman on brute force.** Locked door and paydata vault are the same cell twice: both
  force it for the same ⚙1. The spirit is a reskinned crowbar. Nothing distinguishes them.
- **Mage ↔ Shaman on soft targets.** Stunball (radius 2, Stun, `max(3, Force−2)` Drain) and Fear
  (radius 2, −2 dice for 3 rounds, `max(2, Force−2)` Drain) occupy the same design space — an area
  answer to a cluster of minds. Fear is cheaper and does no damage; Stunball does damage. They are
  the same row twice.
- **Mage ↔ Shaman on hostile magic.** The Counterspell row is a defensive slot both casters cover:
  Counterspell cancels the cast outright, Ward taxes it by −1 die. Same slot, different mechanism —
  the Mage's is the harder stop, the Shaman's is the cheaper one.
- **Decker ↔ Adept on doors and cameras.** Same obstacle, opposite cost: ⚙0 + 🩸1–2 versus ⚙2 +
  gunfire. Interchangeable in outcome, not in price — which is the honest shape of it.
- **Adept ↔ Shaman ↔ Decker on wounded allies.** All three share the identical weak first-aid test.
  Only the Mage's Heal differs. This is ADR-0007's homogenisation risk made visible: three Runners
  are the same Runner on this row.

**Where the roster actually diverges (hard walls, not preferences):**

- **Matrix device: Decker only.** Not one other Runner can extract Paydata. The Decker's monopoly is
  total and is where the class earns its slot (ADR-0008).
- **Hostile spirit: Decker useless, Mage clean, Shaman fine, Adept slow.** The inverse wall.
- **Enemy caster: Mage only.** Counterspell is the one ability in the game that stops a spell
  outright; the Shaman can only tax it with Ward, and nobody else can answer it at all.
- **Camera and Dark room: Decker-favoured.** The Decker is the only Runner whose answer costs zero
  Clock and zero gunfire.
- **Wounded ally: Mage only, for anything that matters.**

**Drain concentration.** Count the rows where each Caster must pay Stun on the matrix above; it is
the authority and this text quotes no tally (DECISIONS §15 says count the matrix, do not quote a
count). The Decker pays Drain on nearly every obstacle type, the Mage on a handful, and the Shaman
on fewer still — and the amendment that gave **Fear** and **Ward** real Drain values
(`max(2, Force−2)`, `max(2, Force−3)`) removes the old reading that the Shaman's rows were Drain-free:
the Shaman now also pays on the Patrolling-guard (Fear) and Enemy-caster (Ward) rows, so "the
Shaman's cheap rows keep its monitor intact" no longer holds exactly. The Decker remains the most
Drain-dependent Runner in the crew, and the risk in ADR-0007 falls hardest on it.

---

## 7. Spirits

A Spirit is a real actor: it has attributes, an Initiative Score, Energy, two Condition Monitors,
and a Behavior Tree. It is the only friendly actor with a brain (ADR-0009).

### 7.1 Summoning roll

| Step | Rule |
|---|---|
| Action | **Summon Spirit**, 10 Energy, range 6 tiles `†`, Force 1–6 chosen at summon |
| Test | **Opposed:** `CHA + Conjuring` vs the Spirit's `Force` dice. The Spirit is the defender, so ties go to the Spirit — the summoner needs **net Hits ≥ 1** |
| Success | The Spirit manifests at the target cell and is bound for **3 rounds** |
| Failure (summoner Hits ≤ Spirit Hits) | The Spirit manifests **immediately hostile** and attacks the nearest Runner for the rest of the Run |
| Glitch | Same as failure, regardless of Hits |
| Drain | `2 × the Spirit's Hits`, minimum 2. Resisted with `WIL + CHA`; unresisted boxes are Stun. Physical only if `Force > CHA`; Summon Force caps at 6 and the Shaman's CHA is 6, so summoning never takes Physical Drain — spells at Force 7–8 are the reachable path |
| One at a time | A second summon dismisses the first `†` |

### 7.2 The Spirit stat block (all values are functions of Force, F)

| Stat | Value |
|---|---|
| Attributes | All equal F, plus the type modifiers below |
| Initiative Score | `Reaction + Intuition + 1d6` = `2F + 1d6` |
| Attack pool | `2F` (its implicit skill is F) |
| Ranged defence | `2F` |
| Melee defence | `2F` |
| Armor | F |
| Physical monitor | `8 + ceil(BOD / 2)` |
| Stun monitor | `8 + ceil(WIL / 2)` |
| **Immunity** | Damage from non-magical sources is **Stun**. Magic (Manabolt, Stunball) is Physical `†` |
| Energy | Initiative Score, spent on the §5 action table; Attack 10 |

### 7.3 The four types

| Type | Role | Attribute mods | Ability (attack) | Range | Movement | Behaviour hook |
|---|---|---|---|---|---|---|
| **Beast** | melee bruiser | BOD +2, STR +2, AGI +1 | `beast_strike`: `(F + 3)P`, AP 1 | 1 tile | normal | Charges. `morale` is pinned at 10 — it never flees. Closes on whatever `command_target` names and stays on it |
| **Air** | fast skirmisher | REA +2, AGI +2, BOD −1 | `air_bolt`: `(F + 1)P`, AP 0 | 8 tiles | Sprint costs 1 Energy per 3 tiles `†`; ignores all terrain cost | Kites: attacks from range, then repositions to a cell outside the target's FOV. Refuses melee |
| **Earth** | tank | BOD +3, STR +2, REA −2 | `earth_slam`: `(F + 2)P`, AP 2 | 1 tile | Step costs 2 Energy per tile `†` | Bodyguard: stays beside its summoner via the `follow_summoner` action and `summoner_id` (`ai.md` §9.6). It does not leave the summoner's side unless ordered. NB `objective_value` is room membership, not proximity — proximity is `follow_summoner`, not the objective term |
| **Water** | area | none | `water_burst`: `(F)S`, AP 0 | 6 tiles, **radius 2** | normal | Clusters: picks the cell covering the most enemies, attacks when 2+ targets are covered, otherwise repositions |

The four attacks are named here — `beast_strike`, `air_bolt`, `earth_slam`, `water_burst` — and `DEC §4` defers to this table for their DV, AP and range (`ai.md` calls the melee strike and the ranged bolt by these names).

Worked example, Force 3 Beast: BOD 5, STR 5, AGI 4, Init 7 + 1d6, attack pool 6 at **6P AP 1**,
soak `5 + 3` = 8, 11 Physical boxes. It is roughly a Corp Guard with more hit points and no gun.

### 7.4 Issuing a target to a Behavior Tree Spirit

The player never drives the Spirit move-by-move (DECISIONS §14's resolved spirit-control item is the
BT-with-issued-target model). The Shaman issues a target; the Spirit's tree decides how to act on it.

**Command Spirit** — a Use power action, 10 Energy. The player-issued target goes into the
Blackboard key `command_target`, which holds a cell or an actor id (DECISIONS §8):

```json
{"kind": "cell",  "x": 12, "y": 7}
{"kind": "actor", "id": 42}
```

The Spirit obeys that pin until the Shaman issues another command or it breaks free. Then a
break-free check: roll `CHA + Conjuring` vs the Spirit's `Force` again. On failure or a Glitch the
Spirit breaks free **instead of obeying** and becomes hostile (§7.5).

`objective` is *not* where a command goes. It stays a Mission Graph node id string — or `"hostile"`
for a freed Spirit — because the Utility Score resolves it to a room and a cell or dict value
silently zeroes the objective term (DECISIONS §8). Spirit lifetime is `summoner_id` plus
`rounds_bound`; a bound Spirit lasts 3 rounds (§7.1).

**The tree is `ai.md` §9.6, and that JSON is the only definition of a Spirit's behaviour.** This
document does not restate it and carries no tree or weights of its own: `ai.md` §6.2 owns the Utility
Score weights, §9.6 owns the per-type attack branches (`beast_strike`, `earth_slam`, `air_bolt`,
`water_burst`, whose DV/AP/range are §7.3 above), and §6.1 owns the `command_target` resolution.
From outside, what the Shaman sees is: the Spirit fights the target it was commanded to, follows the
summoner when it has no target, and uses its type's ability (§7.3).

### 7.5 Escape, duration, and the break-free loop

| Event | Result |
|---|---|
| Failed summoning roll | Manifest hostile immediately |
| Any Glitch on the summoning roll | Manifest hostile immediately |
| Issuing a new target (Command Spirit) and failing the opposed check | Breaks free instead of obeying |
| Summoner Downed | Breaks free immediately `†` |
| 3 rounds elapse | Departs quietly; no check |
| Summoner summons a second Spirit | The first departs quietly; no check |

A hostile Spirit is a normal actor from then on: it attacks the nearest Runner, never leaves the
Site, and is killed like anything else. It does not tick the Security Clock when it dies.

---

## 8. Totems

Chosen once at Shaman creation, always on, never changed. Each gives **+1 die to a named skill
family** (two skills) and one concrete drawback. Drawbacks are `†` — DECISIONS gives the bonus only.

| Totem | +1 die to | Drawback | Favoured Spirit |
|---|---|---|---|
| **Bear** | Close Combat, Athletics | **−2 dice to Stealth.** You are loud and enormous; every infiltration is the crew's problem | Earth |
| **Cat** | Stealth, Athletics | **−1 die to Negotiation and Intimidation.** Aloof; nobody takes a cat-shaman seriously at a gate | Air |
| **Eagle** | Perception, Firearms | **−2 dice to Close Combat.** Keeps its distance or it panics | Air |
| **Owl** | Sorcery, Medicine | **−1d6 Initiative Score, minimum 1d6.** Nocturnal: slower to act than the crew it supports | Beast |
| **Rat** | Electronics, Stealth | **−1 die to Negotiation.** Vermin, socially. Also the only totem that helps a Shaman touch devices | Water |
| **Wolf** | Perception, Intimidation | **−1 die to every Drain resistance test.** The pack drinks deep | Beast |

Owl at creation: `8 + 1d6` Initiative becomes `8 + 1d6 − 1d6` = a straight 8. That is one fewer Pass
on an average roll and is a genuine, playable cost.

---

## 9. Progression: XP

XP is paid per test, to the Runner who made the test. The failure payout is the only part that is
capped, and it is capped **per scored obstacle** (ADR-0006).

| Outcome | XP | Perk roll? |
|---|---|---|
| Success (Hits ≥ threshold) | **1** | no |
| Failure (Hits < threshold) | **5** | yes |
| Opposed Test with net Hits ≤ 0 (defender wins the tie) | **5** | yes |
| Critical Glitch (a Glitch with zero Hits) | **5** | yes — and the action fails *and* the Clock gains a segment |
| A failure on a scored obstacle that has **already** paid a failure payout this Run | **0** | no |
| Hub actions (Legwork, shopping, healing) | **0** | no |
| Job completion | **0** — the Job pays nuyen and Heat, not XP | no |

**A scored obstacle** is one discrete, scene-significant problem with a named stake: one Mission
Graph node resolution, one placed device, one firefight, one dialogue gate, one Legwork action, one
discovered trap. A firefight is **one** obstacle no matter how many attacks and misses happen
inside it. This is ADR-0006's own content-side mitigation, written down as a rule so a Site full of
trivial locks cannot pay.

Consequence, settled in DECISIONS §14: a Runner who fails an obstacle first pays 5 and owns it;
retrying and succeeding pays 1 more; retrying and failing again pays 0. A Runner who succeeds first
time gets 1. Failing first is therefore worth 5× a clean success on the same obstacle — the design
intent — and the retry loop is dead.

**Duplicate Perks.** Perks are unique per Runner. On a roll the Runner already owns, re-roll once
ignoring owned entries; if the re-roll is also a duplicate (or every entry is owned), that roll
converts to **3 XP** instead of a Perk (DECISIONS §14). The table is expected to grow past twelve
entries.

---

## 10. Progression: Advance costs

Advances are bought at the Hub between Jobs, never mid-Run. Cost is the **new** rating: skill
`new rating × 3`, attribute `new rating × 5` (DECISIONS §14). No XP is refunded; ratings never fall.

| Advance | Cost | From → To | Total |
|---|---|---|---|
| Skill | `new rating × 3` | 3 → 4 | 12 |
| | | 4 → 5 | 15 |
| | | 5 → 6 | 18 |
| Attribute | `new rating × 5` | 4 → 5 | 25 |
| | | 5 → 6 | 30 |
| | | 6 → 7 (Adept Agility/Strength only) | 35 |

Total XP to max one Runner from these starting blocks: **~960 XP** (525 into skills, 435 into
attributes for the Mage). At the §12 income that is roughly 30–60 Jobs of grinding, so the cap is
never the constraint inside a v1 campaign.

---

## 11. Perk table

Rolled **d20** on every failure payout. Twelve entries spread over twenty faces, so the common ones repeat. Marked
**↷** where the Perk pulls a Runner off its archetype — ADR-0006's accepted risk, made visible.

| Perk | d20 | Effect | Pulls toward |
|---|---|---|---|
| Thick Skin | 1–2 | +1 box on your Physical Condition Monitor | — |
| Steady Nerves | 3–4 | +1 box on your Stun Condition Monitor | — |
| Iron Will | 5–6 | +1 die to Drain resistance tests | — |
| Sure Grip | 7–8 | +1 die to Firearms | — |
| Brawler | 9 | +1 die to Close Combat | ↷ Physical Adept |
| Silver Tongue | 10 | +1 die to Negotiation and Con | ↷ Shaman |
| Ghost | 11 | +1 die to Stealth | ↷ Physical Adept |
| Code Slinger | 12–13 | +1 die to Cybercombat and Electronics | ↷ Decker |
| Ward Weaver | 14 | +1 die to Sorcery and Conjuring | ↷ Mage / Shaman |
| Pack Leader | 15 | +1 die to every attack made by a Spirit you summoned | ↷ Shaman |
| Field Medic | 16–17 | +1 die to Medicine; your first aid removes 1 extra box | ↷ Mage |
| Sixth Sense | 18–20 | +1 die to Perception; you are told when a device or trap is in a room you enter | ↷ Decker |

Eight of twelve bend the archetype. The non-benders (Thick Skin, Steady Nerves, Iron Will, Sure
Grip) are the boring ones and the d20 makes them the most common by face count — a deliberate
softening of ADR-0006's risk, not an accident.

---

## 12. Worked levelling: ten Jobs, three Runners

**Model** `†`. A v1 paydata Job presents **10 scored obstacles** to the Crew. A Runner personally
attempts **~12 tests per Job**. Successes pay 1; failures pay 5 once per scored obstacle. A Runner's
own Job payout and Heat are tracked separately, because that is the counterweight to inverted XP.

### 12.1 Sable — the planner (mostly succeeds)

Failed first on 1.2 obstacles per Job, got everything else the quiet way.

| | 10 Jobs |
|---|---|
| Tests attempted | 120 |
| Successes → XP | 90 → 90 XP |
| Distinct obstacles failed first | 12 → 60 XP |
| **Total XP** | **150** |
| Perks earned | 12 (table exhausted exactly at Job 10) |
| Jobs paid out | 10 |
| Nuyen | ~135,000¥ |
| Heat | 0 (decays 1 per successful Job) |

What 150 XP buys: Sorcery 5→6 (18), Conjuring 4→5 and 5→6 (33), Perception 4→5 (15), Medicine 4→5
(15), Willpower 5→6 (30), Intuition 4→5 (25) = **136**, 14 unspent.
Sable is now a Mage casting at 12 dice with 11 Physical boxes of soak behind Armor. Marginal change:
the crew's work looks the same, done slightly better.

### 12.2 Kessler — the hammer (mostly fails)

Fails loudly, survives on 11 Physical boxes, and pays for it in Heat.

| | 10 Jobs |
|---|---|
| Tests attempted | 140 |
| Successes → XP | 35 → 35 XP |
| Distinct obstacles failed first | 55 → 275 XP |
| **Total XP** | **310** |
| Perks earned | all 12, by Job 3 |
| Jobs paid out | 3 of 10 — seven forced extractions pay **0¥** and give **Heat +2** each |
| Nuyen | ~40,500¥ |
| Heat | 7 × 2 − 3 (decay) = **11** |

What 310 XP buys: nine skills from 3 to 5 at 27 each = 243, two of those to 6 = 36, Willpower 5→6
= 30 → **309**, 1 unspent.
Kessler is the strongest Runner in the crew on paper — most skills at 5–6, all twelve Perks — and
the poorest. Heat 11 is the counterweight: Sites generated under high Heat field more guards, more
devices, and a Clock that starts hotter, so Kessler's next ten Jobs pay even less.

### 12.3 Vex — the mixed Shaman (half and half)

| | 10 Jobs |
|---|---|
| Tests attempted | 130 |
| Successes → XP | 65 → 65 XP |
| Distinct obstacles failed first | 30 → 150 XP |
| **Total XP** | **215** |
| Perks earned | all 12, by Job 5 |
| Jobs paid out | 7 |
| Nuyen | ~91,000¥ |
| Heat | 3 |

What 215 XP buys: Sorcery 5→6 (18), Conjuring 4→5 (15), Perception 4→5 (15), Medicine 4→5 (15),
Willpower 5→6 (30), Intuition 4→5 (25), Charisma 4→5 (25), Cybercombat 3→5 (27), Electronics 3→5
(27), Stealth 3→4 (12) = **209**, 6 unspent.
Vex's Rat totem has already pulled its Electronics to 5, which is one point of the Decker's domain
bought with failure. That is the archetype bleed ADR-0006 describes, arriving on schedule.

### 12.4 Is inverted XP degenerate?

| | Sable | Vex | Kessler |
|---|---|---|---|
| XP | 150 | 215 | 310 |
| XP advantage over Sable | — | 1.43× | **2.07×** |
| Nuyen | 135,000¥ | 91,000¥ | 40,500¥ |
| Heat | 0 | 3 | 11 |
| Jobs failed | 0 | 3 | 7 |

**Not degenerate, by three checks.** Failing pays ~2× planning, exactly as designed, and the ceilings
are far away: 310 XP is under a third of a Runner's lifetime sink. The failure payout is per
obstacle, so the retry farm pays nothing — ADR-0006's core hole is closed by the definition of a
scored obstacle rather than by a special case. And Kessler's advantage is bought with 94,500¥ less
nuyen and Heat 11, which ADR-0012 turns into harder Sites; the growth is real, the world pushes
back.

**Bounded, not degenerate.** The current twelve-entry table is exhausted by Job 3 for a
mostly-failing Runner and by Job 5 for a mixed one. DECISIONS §14 settles the tail: the table is
expected to grow past twelve entries, and a duplicate past exhaustion converts to **3 XP**. The
ADR-0006 story still weakens for the failure-heavy Runner once the table runs dry — the XP keeps
flowing, the identity change stops — but it is now a recorded, bounded limit rather than an open
hole.

---

## 13. Open questions

1. **Blackboard keys — answered.** DECISIONS §8 now fixes the twelve-key typed set, including
   `summoner_id`, `rounds_bound` and `command_target`; nothing about a Spirit needs smuggled state.
   `spirit_type` is *not* added — the type is fixed at summon and read from the sheet, and a
   thirteenth key would break the fixed-set contract.
2. **Unarmed DV is undefined.** Killing Hands says "unarmed is lethal, +1 DV" but the weapon table
   has no unarmed line. Recommendation: `DV = Strength` (Stun), AP 0; Killing Hands makes it
   `(Strength + 1)P`. Adept 8P, Mage 3S.
3. **Shaman power and Decker hack ranges are undefined.** DECISIONS §4 fixes spell range at 12
   cells with LOS, but the non-spell powers still have only draft values: Summon 6, Fear 8, Ward
   centred on the Shaman, Hack 12. Recommendation: adopt these, or move them into DECISIONS so
   range is one contract.
4. **Radius is unspecified.** I have used Chebyshev (radius 2 = 5×5). Recommendation: adopt
   Chebyshev everywhere — movement is 8-direction and a diagonal Step costs 1 Energy like an
   orthogonal one (DECISIONS §5), so `max(dx, dy)` is the exact distance metric (DECISIONS §13);
   the grid is not octile.
5. **Cross-class skill use.** Nine skill slots are dead outside their owner (Adept Sorcery,
   Mage Conjuring, Adept Cybercombat, Mage Intimidation). Recommendation: give them a floor cost
   of one line each somewhere, rather than leaving three dead skills on a sheet the player stares
   at. The Shaman's Sorcery 4 is now one of them: Counterspell moved into the Mage's kit.
6. **Non-Decker device access.** I have ruled that the §6 device table is Decker-only (the
   cyberdeck is the gate). If non-Deckers should be able to hotwire a door, that needs a stated
   modifier and it changes the §6.1 monopoly.

---

Sources: stat-block base/derived/advance layering and the XP-curve framing from
`.agents/skills/rpg/SKILL.md` and `references/stats-combat-quests.md`; the three-value tick
status, Blackboard-as-shared-memory, and utility scoring with per-archetype weights from
`.agents/skills/ai-behavior-trees-utility-ai/SKILL.md`; selector/sequence tree assembly and the
"recompute paths sparingly, verify by observation" tuning loop from
`.agents/skills/game-ai/SKILL.md`; the single-run RNG and message-log discipline from
`.agents/skills/roguelike/SKILL.md`.

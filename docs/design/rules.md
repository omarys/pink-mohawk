# Pink Mohawk — Rules Reference

The complete table-ready rules for one Job. Every number here is copied from `docs/design/DECISIONS.md`; every term is from `CONTEXT.md`. Where a needed parameter was missing, it is marked **[proposed]** and listed in *Open questions* — never silently invented.

**One-page loop.** Roll Initiative once per combat round → each actor's Pass spends its Energy on Actions → the Pass ends when the actor cannot afford a Step (threshold 1 Energy), subtract 10, take another Pass while the Score is still positive → when every actor's Score is spent the round ends and Initiative is re-rolled. Every action is a Dice Pool of d6s, a Hit is a 5 or a 6, net Hits become damage, soaked damage fills boxes, filled boxes penalise the next pool. Loud actions tick the Security Clock; the Clock, not death, ends the Run.

---

## 1. The dice

| Term | Rule |
|---|---|
| Dice Pool | `linked attribute + skill + modifiers` |
| Hit | one die showing **5** or **6** |
| Success Test | Hits ≥ threshold: 1 trivial, 2 average, 3 hard, 4+ extreme |
| Opposed Test | both sides roll a pool; **net Hits** decide; a tie goes to the defender |
| Glitch | **more 1s than half the dice rolled** |
| Critical Glitch | a Glitch with **zero Hits** — the action fails *and* the Security Clock gains **+1 segment** |
| Limits / extended tests | none. No test rolls more than **twice** |

Modifiers are always **dice added to or removed from the pool**, never a change to the Hit number. Keep them in a modifier layer and recompute; never edit a base attribute for a buff.

---

## 2. The turn loop

### 2.1 Roll Initiative (once per combat round)

`Initiative Score = Reaction + Intuition + 1d6` (+`1d6` per Improved Reflexes rating, max **+2d6** in v1).

- **Energy for the round's first Pass = the Initiative Score.**
- The Score is **re-rolled at the start of every combat round** (DECISIONS §5). It persists across the Passes *within* that round and only goes down; the re-roll at the round boundary is what gives each round a fresh order.
- An actor joining mid-round (a new patrol, a conjured Spirit, a freed Spirit) rolls its own Score and is inserted into the order at that value. A Spirit lasts 3 rounds.

### 2.2 Order

Highest Score acts first. Ties break by:

1. **higher Reaction**, then
2. **lower actor id** (stable, deterministic, no re-rolls).

### 2.3 Spend Energy — the Pass

A Pass is one actor spending Energy until it is exhausted. **Actions:**

| Action | Energy | Notes |
|---|---|---|
| Step | 1 per tile | 8 directions |
| Sprint | 2 per 3 tiles | −2 defence until the next Pass |
| Attack | 10 | ranged or melee |
| Use power | 10 | Qi, spell, hack, Scan, Summon |
| Aim | 5 | +1 die, stacks to +2 |
| Reload | 5 | |
| Take cover | 5 | +2 defence |
| Use item | 5 | |
| Stand up | 5 | |

### 2.4 How a Pass ends and the −10

1. Actions are bought **atomically**: you may not start an action you cannot pay for. You can never go below 0 Energy.
2. **Step is tile-granular**, so you can always spend down to exactly 0. **Sprint is bought in 3-tile blocks** for 2 Energy; with 1 Energy left you cannot Sprint, but you may Step instead.
3. When Energy is below 1 (`PASS_END_THRESHOLD = 1`) — it can no longer cover a Step, the cheapest Action — the Pass ends.
4. On Pass end: **`Score −= 10`**.
5. If the new Score is still **positive**, the actor takes another Pass this round with **Energy = the new Score** (at 1, exactly one Step). If it is 0 or less, the actor is done for the round.

A player may also end a Pass voluntarily with Energy remaining; the leftover is lost **[proposed]** (Open questions Q15).

**Running out of Energy mid-action:**

- Mid-move: the move stops in the tile reached at 0 Energy, the Pass ends, Score −= 10.
- Too poor to act usefully (e.g. 4 Energy, Attack costs 10): the leftover may only buy a Step or a 5-cost Action. If neither is worth it, the Pass ends and the Energy is lost.
- You cannot "borrow" against the next Pass, and you cannot carry Energy into the next round.
- **Edge → Seize the Initiative** (+10 Energy immediately) is the only way to extend a Pass.

### 2.5 End of round

When **every** actor's Score is spent (0 or less), the round is over. Re-roll Initiative (§2.1) and start a new round. Fights are read as: *Round N → Pass 1 (everyone), Pass 2 (whoever still has a positive Score), … → re-roll*.

---

## 3. Worked example: one combat round

### 3.0 The example cast

Used for every worked example in this document. The Runners' attribute rows are copied from `classes.md` §1.1, the class authority — do not invent a different spread here; their skill ratings sit inside DECISIONS' 3–5 starting band. The Adept's AGI 7 / STR 7 / BOD 6 / REA 6 are from DECISIONS §7. The two Corp Guards use the tier-0 stat block of `docs/design/enemies.md` §1: BOD 4 · AGI 3 · REA 4 · STR 3 · WIL 3 · LOG 2 · INT 3 · CHA 3, armour 8 (vest 6 + helmet 2), assault rifle 8P AP 2 range 14, Firearms pool `AGI 3 + Firearms 3 = 6`, Close Combat 3.

| Actor | BOD | AGI | REA | STR | WIL | LOG | INT | CHA | Skills | Armour | Weapon |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Sable — Physical Adept | 6 | 7 | 6 | 7 | 4 | 3 | 4 | 3 | Close Combat 5, Firearms 4 | Armoured jacket 8 | Katana (10P, AP 3), heavy pistol (5P, AP 1) |
| Kestrel — Mage | 3 | 3 | 3 | 3 | 5 | 6 | 4 | 4 | Sorcery 5 | Lined coat 7 | heavy pistol |
| Voss — Shaman | 4 | 4 | 4 | 3 | 5 | 3 | 4 | 6 | Conjuring 5 | Lined coat 7 | SMG |
| Nine — Decker | 4 | 5 | 5 | 3 | 4 | 6 | 5 | 3 | Cybercombat 5, Electronics 4 | Armoured vest 6 | SMG |
| Guard A — Corp Guard | 4 | 3 | 4 | 3 | 3 | 2 | 3 | 3 | Firearms 3, Close Combat 3, Perception 3 | Vest 6 + helmet 2 = 8 | Assault rifle (8P, AP 2) |
| Guard B — Corp Guard | 4 | 3 | 4 | 3 | 3 | 2 | 3 | 3 | Firearms 3, Close Combat 3, Perception 3 | Vest 6 + helmet 2 = 8 | Assault rifle (8P, AP 2) |

Condition Monitors from §4:

| Actor | Physical = `8 + ceil(BOD/2)` | Stun = `8 + ceil(WIL/2)` |
|---|---|---|
| Sable | 8 + 3 = **11** | 8 + 2 = **10** |
| Kestrel | 8 + 2 = **10** | 8 + 3 = **11** |
| Voss | 8 + 2 = **10** | 8 + 3 = **11** |
| Nine | 8 + 2 = **10** | 8 + 2 = **10** |
| Guard A / B | 8 + 2 = **10** | 8 + 2 = **10** |

### 3.1 Roll Initiative (Round 1)

`Score = REA + INT + 1d6`:

| Actor | REA | INT | d6 | Score |
|---|---|---|---|---|
| Sable | 6 | 4 | 5 | **15** |
| Nine | 5 | 5 | 6 | **16** |
| Voss | 4 | 4 | 4 | **12** |
| Kestrel | 3 | 4 | 3 | **10** |
| Guard B | 4 | 3 | 4 | **11** |
| Guard A | 4 | 3 | 2 | **9** |

Order: Nine(16) → Sable(15) → Voss(12) → Guard B(11) → Kestrel(10) → Guard A(9).
No two Scores are equal this round, so §2.2's tie-break (higher Reaction, then lower actor id) has nothing to settle here.

### 3.2 Pass 1

**Nine — Energy 16.** Take cover, then hack Guard A's assault rifle.

| Action | Cost | Energy after |
|---|---|---|
| Take cover | 5 | 11 |
| Use power: Hack Guard A's gun (rating 2) | 10 | 1 |
| Step ×1 | 1 | **0** |

- Hack is a Success Test, threshold = device rating = 2. Pool = `Cybercombat 5 + Logic 6 = 11` d6; roll `5,6,3,2,4,1,6,5,2,3,4` → Hits 4 ≥ 2 → **success**: the magazine ejects, the gun is **disabled 3 rounds**.
- Hack Drain = `ceil(2 / 2)` = **1 box Stun, no resistance roll**. Nine Stun 1/10. Successful hack → **Clock +0**.

**Sable — Energy 15.** Aims, fires a heavy pistol at Guard A in the open.

| Action | Cost | Energy after |
|---|---|---|
| Aim | 5 | 10 |
| Attack (heavy pistol), 10 | 10 | **0** |

- Attack pool = `AGI 7 + Firearms 4 + Aim 1 = 12` d6.
  Roll `6,5,5,4,2,6,1,5,3,2,4,6` → Hits (5/6) = **6**. 1s = 1; glitch needs > 6 ones → **no Glitch**.
- Guard A defence (ranged) = `Reaction 4 + Intuition 3 + cover 0 = 7` d6.
  Roll `5,3,2,6,1,4,2` → Hits = **2**.
- **Net Hits = 6 − 2 = 4.**
- **DV** = weapon 5P + net Hits 4 = **9P**.
- **Modified armour** = vest+helmet 8 − AP 1 = **7**.
- **Damage type**: modified DV 9 ≥ modified armour 7 → **Physical**.
- **Soak** = `Body 4 + (armour 8 − AP 1) = 11` d6. Roll `6,5,2,4,1,3,5,2,6,4,2` → Hits = **4**, each cancelling 1 DV.
- **Damage dealt = 9 − 4 = 5 boxes Physical.**

Guard A: **Physical 5/10**. Wound Modifier = `floor(5 / 3)` = **−1 die** on every pool it rolls from now on. That is also the first **gunfire → Clock +2**.

**Voss — Energy 12.** Summon a Spirit, then step twice.

| Action | Cost | Energy after |
|---|---|---|
| Use power: Summon Spirit | 10 | 2 |
| Step ×2 | 2 | **0** |

- Conjuring pool = `Charisma 6 + Conjuring 5 = 11` d6, 4 Hits → Summon Drain = `2 × 4 = 8` **[the "spirit's Hits" reading is [proposed] — Open questions Q24]**.
- Resist with `Willpower 5 + Charisma 6 (Shaman Tradition Attribute) = 11` d6 → 3 Hits → **8 − 3 = 5 boxes Stun**. Voss Stun **5/11**, Wound Modifier `floor(5/3)` = **−1**.

**Guard B — Energy 11.** Fires its assault rifle at Sable, then steps.

| Action | Cost | Energy after |
|---|---|---|
| Attack (assault rifle) | 10 | 1 |
| Step ×1 | 1 | **0** |

- Attack pool = `AGI 3 + Firearms 3 = 6` d6. Roll `6,5,5,2,3,4` → Hits = **3**.
- Sable defence (ranged) = `Reaction 6 + Intuition 4 + cover 0 = 10` d6. Roll `5,3,2,4,1,6,3,2,4,4` → Hits = **2**.
- Net Hits = 3 − 2 = **1**. DV = assault rifle 8P + 1 = **9P**.
- Modified armour = jacket 8 − AP 2 = **6**. `9 ≥ 6` → the P attack **stays Physical**.
- Soak = `BOD 6 + (8 − 2) = 12` d6. Roll `6,5,4,3,2,1,6,2,4,5,3,2` → Hits = **4**.
- Damage = 9 − 4 = **5 boxes Physical**. Sable **Physical 5/11**. Wound Modifier = `floor(5 / 3)` = **−1**.

**Kestrel — Energy 10.** Casts Stunball at Force 6; the cast is the whole Pass.

| Action | Cost | Energy after |
|---|---|---|
| Use power: Stunball, Force 6 | 10 | **0** |

- DV = Force = **6S**, radius 2. Stunball is an S-typed attack, so it **stays Stun** even though 6 < a guard's armour.
- Placed on the corridor mouth: the radius 2 catches no actor this Pass, so it resolves **no damage** — the point of the cast here is the Drain and the Clock.
- Drain = `max(3, Force − 2) = max(3, 4) = 4`. Resist `WIL 5 + LOG 6 = 11` d6 → 3 Hits → **1 box Stun**. Kestrel Stun 1/11.
- Force 6 ≥ 4 → **loud spell, Clock +2**.

**Guard A — Energy 9, Wound Modifier −1, gun disabled.** Cannot afford an Attack (10 > 9). Takes cover and repositions.

| Action | Cost | Energy after |
|---|---|---|
| Take cover | 5 | 4 |
| Step ×4 | 4 | **0** |

Guard A now has **+2 defence**, and its next Firearms pool would be `AGI 3 + Firearms 3 − 1 = 5` (Wound Modifier). Its gun comes back online in 3 rounds.

### 3.3 Subtract 10 → Pass 2

| Actor | Score after −10 | Acts in Pass 2? |
|---|---|---|
| Sable | 5 | yes |
| Nine | 6 | yes |
| Voss | 2 | yes |
| Kestrel | 0 | no |
| Guard B | 1 | yes |
| Guard A | −1 | no |

**Sable — Energy 5.** Take cover (5) → +2 defence → Energy 0 → Score 5 − 10 = −5, done for the round.
**Nine — Energy 6.** Step ×6 → repositions behind a pillar → Energy 0 → Score 6 − 10 = −4, done.
**Voss — Energy 2.** Step ×2 → Score 2 − 10 = −8, done.
**Guard B — Energy 1.** Step ×1 → Score 1 − 10 = −9, done (a Score of 11 buys a second Pass worth exactly one Step).

Every actor's Score is now spent (0 or less) → **Round 1 ends**. Re-roll Initiative for Round 2 (§2.1): the new rolls give a fresh order and fresh Energy, and none of the Round-1 −10s carry over. (The example stops here; §5.4 picks up a Mage's two-round Drain in isolation.)

### 3.4 State after Round 1

| Actor | Physical | Stun | Wound Modifier | Status |
|---|---|---|---|---|
| Sable | 5/11 | 0/10 | −1 | in cover (+2 def) |
| Nine | 0/10 | 1/10 | 0 | in cover (+2 def) |
| Kestrel | 0/10 | 1/11 | 0 | |
| Voss | 0/10 | 5/11 | −1 | Spirit up (3 rounds) |
| Guard A | 5/10 | 0/10 | −1 | in cover, gun disabled 3 rounds |
| Guard B | 0/10 | 0/10 | 0 | |

Security Clock: **4** (first gunfire +2, loud spell Force 6 +2).

---

## 4. Damage and the Condition Monitors

### 4.1 The two monitors

| Monitor | Boxes |
|---|---|
| Physical | `8 + ceil(Body / 2)` |
| Stun | `8 + ceil(Willpower / 2)` |

Both tracks are ticked separately. A Runner whose **filled Physical boxes reach the monitor maximum** is **Downed** — removed from the Run, recovered at the Hub. Enemies whose filled Physical boxes reach the monitor maximum are removed from the encounter.

### 4.2 Wound Modifier

**−1 die per 3 filled boxes, counting both tracks together.** `penalty = floor((Physical filled + Stun filled) / 3)`. The penalty applies to *every* Dice Pool the actor rolls, including defence, soak, and Drain resistance.

| Filled boxes (both tracks) | Modifier |
|---|---|
| 0–2 | 0 |
| 3–5 | −1 |
| 6–8 | −2 |
| 9–11 | −3 |
| 12–14 | −4 |
| 15–17 | −5 |
| 18–20 | −6 |

A Drain-heavy Caster reaches −3 to −5 off Stun alone, which is intended: Stun is both the resource and the liability.

### 4.3 Attack, soak, and damage type — the sequence

1. **Attack pool** vs **defence pool**:
   - Ranged defence = `Reaction + Intuition + cover (+2 if in cover)`.
   - Melee defence = `Agility + Close Combat`.
2. **Net Hits = attacker Hits − defender Hits**, floor 0. A tie means the defender wins, net 0.
3. **DV = weapon DV + net Hits.**
4. **Modified armour = `armour − AP`.** AP is stored as a **positive magnitude** and subtracted (DECISIONS §4): AP 3 is better than AP 1, and the magnitude always shrinks the armour it meets.
5. **Damage type** (see §4.4).
6. **Soak pool = `Body + (armour − AP)`** d6; each Hit cancels 1 DV.
7. **Boxes dealt = DV − soak Hits**, minimum 0. `DV ≤ 0` = no damage.

### 4.4 Physical vs Stun — the damage-type rule

- Every attack has a **nominal type**: **P** (Physical) or **S** (Stun). Firearms and blades are P; a stun baton and Stunball are S.
- A **P** attack whose **modified DV** (step 3: weapon DV + net Hits) is **less than** the target's modified armour (step 4) is **downgraded to Stun**. If modified DV ≥ modified armour it stays Physical.
- An **S** attack stays Stun regardless of DV vs armour.
- Manabolt and other Force-DV spells are P-nominal and therefore can be downgraded to Stun.

Worked, from §3: Sable's pistol DV 9 vs modified armour `8 − AP 1 = 7` → **9 ≥ 7 → Physical**. A nominal P hit that does not clear the armour is downgraded: an SMG's DV 7 against a jacket 8 → **7 < 8 → Stun**.

### 4.5 Overflow — Stun bleeding into Physical

When the Stun monitor **fills**, further Stun converts at **2 Stun boxes → 1 Physical box**.

**Worked overflow.** Guard A sits at **Stun 8/10, Physical 5/10** and takes **4 more Stun** (a stun baton tap at DV 4, fully unsoaked):

- Stun monitor has room for 2 → Stun goes **8 → 10** (full).
- Remaining 2 Stun → `2 ÷ 2` = **1 Physical box**. Physical **5 → 6**.
- Result: **Stun 10/10, Physical 6/10**.
- Wound Modifier = `floor((10 + 6) / 3)` = `floor(5.33)` = **−5** on everything.

Once the Stun monitor is full, all incoming Stun goes straight to the 2:1 conversion.

### 4.6 Downed and recovery

- **A Runner whose filled Physical boxes reach the monitor maximum is Downed.** A Runner is removed from the Run; the rest of the Crew finishes shorthanded.
- **Condition Monitors persist as Hub state.** Filled Physical and Stun boxes carry across Jobs and clear only by resting or by paying the clinic — **250¥ per box**, limited by `HUB_RECOVER_BOXES_PER_DAY` (DECISIONS §9); a Downed Runner returns to the Crew once healed.
- Stun does not kill: a full Stun monitor has **no effect of its own** in v1 (it only enables overflow and soaks the Wound Modifier). **[proposed — Q6 suggests full Stun should mean unconsciousness; DECISIONS does not say.]**

---

## 5. Drain

Every primary Caster ability costs **Stun** as well as 10 Energy. Mage, Shaman, and Decker all pay Drain; they differ only by *what they act on* (ADR-0007).

### 5.1 Resistance and Physical Drain

- **Drain resistance pool = `Willpower + Tradition Attribute`.** One Hit cancels one Drain box.
- **Tradition Attribute**: **Logic** for the Mage and the Decker, **Charisma** for the Shaman.
- **Unresisted boxes are Stun.**
- **Drain is Physical when `Force > the Tradition Attribute value`.** Force is chosen at cast time, range **1–8**. Against a starting Tradition Attribute of 6, Force 7 and 8 are the only settings that make Drain Physical, so **overcasting** is a reachable, self-inflicted risk rather than a dead branch — and it also ticks the Clock at Force ≥ 4.
- **No resistance roll** for Hack a device (the drain is flat) and none for a Glitch doubling.
- **A Glitch on a hack doubles its Drain.**

### 5.2 The Drain table

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
| Scan | 1 |
| Hack a device | `ceil(device rating / 2)` Stun, doubled on a Glitch, **no resistance roll** |

Drain by Force, for the combat-relevant spells plus the two Shaman debuffs:

| Force | Manabolt | Stunball | Heal | Analyze Device | Invisibility | Armor | Fear | Ward |
|---|---|---|---|---|---|---|---|---|
| 1 | 2 | 3 | 3 | 1 | 2 | 2 | 2 | 2 |
| 2 | 2 | 3 | 3 | 1 | 2 | 2 | 2 | 2 |
| 3 | 2 | 3 | 3 | 1 | 2 | 2 | 2 | 2 |
| 4 | 2 | 3 | 3 | 1 | 2 | 2 | 2 | 2 |
| 5 | 2 | 3 | 4 | 1 | 3 | 3 | 3 | 2 |
| 6 | 3 | 4 | 5 | 2 | 4 | 4 | 4 | 3 |
| 7 | 4 | 5 | 6 | 3 | 5 | 5 | 5 | 4 |
| 8 | 5 | 6 | 7 | 4 | 6 | 6 | 6 | 5 |

Derived Hack Drain from the device table:

| Device | Rating | Drain | Effect |
|---|---|---|---|
| Gun | 2 | 1 Stun | eject magazine, disabled 3 rounds |
| Optics | 2 | 1 Stun | blinded, −3 dice, 3 rounds |
| Door or lock | 2–4 | 1–2 Stun | unlocked |
| Lights | 3 | 2 Stun | room dark: enemy FOV radius 2, −2 dice |
| Commlink or phone | 3 | 2 Stun | read messages; spoof a distraction |
| Drone | 4 | 2 Stun | seized for 3 rounds, or disabled |
| Cyberware | 4 | 2 Stun | −2 dice to one enemy for 3 rounds |

Hacks are **Success Tests with threshold = device rating**. Enemy gear uses the same table.

### 5.3 Sustain

**Sustaining a spell costs −2 dice on everything else.**

- It stacks with the Wound Modifier, cover, Aim, and Edge (all pool modifiers are additive).
- It applies to the sustained spell's own effect? No — it applies to every *other* roll.
- **At most two spells may be sustained at once** (DECISIONS §6), so the penalty tops out at **−4**.

### 5.4 Worked example — a Mage casting twice and paying for it

Kestrel: `WIL 5 + LOG 6 = 11` Drain-resistance dice. Stun monitor **11**. Each **Use power** costs 10 Energy, so with an Initiative Score of `REA 3 + INT 4 + 1d6 = 8–13` she casts **at most once per round** — a Score of 8 or 9 cannot even afford the 10-Energy cast.

**Round 1 — Stunball, Force 6.** Drain = `max(3, 6 − 2) = 4`.
Resist 11 d6: `5,2,3,1,4,6,2,3,4,1,5` → Hits = 3.
**Drain taken = 4 − 3 = 1 box Stun.** Kestrel **Stun 1/11**, Wound Modifier 0.
Loud (Force ≥ 4) → **Clock +2**.

**Round 2 — Manabolt, Force 6, while sustaining Armor.** Drain = `max(2, 6 − 3) = 3`.
Resist 11 − 2 (sustain Armor) = **9 d6**: `2,3,4,1,2,3,5,2,4` → Hits = 1.
**Drain taken = 3 − 1 = 2 boxes Stun.** Kestrel **Stun 3/11**.

**Consequences:** total filled = 3 → **Wound Modifier −1** on every pool, *and* the sustained Armor adds −2 → the Mage's next Manabolt pool is `Sorcery 5 + LOG 6 − 1 (wounds) − 2 (sustain) = 8` d6 instead of 11. Two casts have cost her a third of her Stun track, a −3 die swing, and she gains nothing back until the Run ends. Force is the dial: dropping to Force 3 would have made both casts `max(3,…)` Drain but left the pools clean.

---

## 6. Edge and Qi

### 6.1 Edge

**Pool:** 3 points, all classes, **refreshes at the start of each Run**. Edge is an attribute (rating 3).

| Spend | Cost | Effect |
|---|---|---|
| Push the Limit | 1 Edge | **+Edge rating dice (3)** to one test; **6s explode** (reroll each 6 and add the new die) |
| Second Chance | 1 Edge | reroll the failures of one test |
| Seize the Initiative | 1 Edge | **+10 Energy immediately** |

**When it can be spent:**

- **Push the Limit / Second Chance**: on any test the Runner rolls — attack, defence, soak, Drain resistance, Perception, hack, Stealth. Declare after seeing the dice.
- **Seize the Initiative**: at any point in the Runner's own Pass, or immediately before spending, to unlock an action the Energy cannot cover.

**Stacks with:** everything that touches a Dice Pool — Aim (+1/+2), cover (+2 defence), Sprint's −2, Mystic Armor, Attribute Boost, Killing Hands. Push the Limit is extra dice in the same pool; exploding 6s is a property of those dice only.

**Does not stack with:**

- itself on the same test: **one Edge spend per test [proposed]** (Open questions Q10) — not Push *and* Second Chance on one roll.
- more than 3 points per Run; the pool does not refill mid-Run.
- Seize the Initiative does **not** change the Initiative Score, does **not** create a Pass, and the +10 is lost at Pass end **[proposed]** (Open questions Q14).

### 6.2 Qi (Physical Adept only)

**Pool: 4 points**, **+1 at the start of each Pass**, and **capped at 4** (DECISIONS §6). Every power also costs the **Use power → 10 Energy** Action. The cap is what makes Qi a resource rather than a ramp: powers cost 1–2 Qi, a fast Adept spends 2–5 per Round, and a fixed 4-point pool refills no faster than a heavy spend drains it.

| Power | Qi | Energy | Effect |
|---|---|---|---|
| Improved Reflexes | 2 | 10 | +1d6 Initiative Score for the rest of the Run (max **+2d6** in v1) |
| Killing Hands | 1 | 10 | unarmed is lethal, **+1 DV**, 3 rounds |
| Wall Run | 1 | 10 | cross one impassable tile |
| Mystic Armor | 1 | 10 | **+2 soak**, 3 rounds |
| Attribute Boost | 1 | 10 | **+1 die** to Agility, Strength, or Reaction, 3 rounds |

**When it can be spent:** only in the Adept's own Pass, on the Use power Action. The Qi pool starts full at 4 **[proposed]** (Open questions Q12) and refills +1 per Pass, so a 10-Energy power plus a 2-Qi power is not affordable every Pass.

**Stacks with:**

- **Attribute Boost (Reaction)** adds +1 die to Reaction pools **and +1 to the Initiative Score** (Score = Reaction + Intuition + dice) next round. **[proposed — Open questions Q16]**
- **Attribute Boost (Agility)** stacks with Aim, cover, and Edge on the katana pool.
- **Mystic Armor +2 soak** stacks with worn armour; it does not replace it.
- **Improved Reflexes** stacks with Attribute Boost (Reaction) and with the base 1d6, up to the +2d6 cap.

**Does not stack with:**

- another copy of itself: Improved Reflexes caps at **+2d6** (two purchases of 2 Qi each), so the third purchase does nothing.
- a weapon: **Killing Hands only affects unarmed attacks.** With a katana it has no effect.
- any other Qi power on the *same* Action: each power is its own Use power Action and its own 10 Energy.
- two Attribute Boosts on the same attribute (pick one attribute per purchase).

---

## 7. The Security Clock

**Ten segments.** Loud actions and failed tests tick it. It is visible at all times and must say *what ticked it* (ADR-0005). At 10 the Run ends.

### 7.1 Tick table

| Event | Segments |
|---|---|
| Gunfire | **+2** |
| Guard killed | **+2** |
| Body found | **+3** |
| Failed hack | **+1** |
| Loud spell (Force ≥ 4) | **+2** |
| Alarm tripped | **+2** |
| Lock forced | **+1** |
| Critical Glitch | **+1** |
| Silent takedown, successful hack | **0** |

Gunfire is currently ambiguous between per-shot, per-round, and once-per-fight; **[proposed]** once per fight (Open questions Q5) — otherwise five shots end the Run.

### 7.2 Thresholds and their mechanical effects

| Segments | Threshold | Effect |
|---|---|---|
| ≥ 4 | **Alert** | Patrols converge. The site sets **`alert_level = 1`** — raising *every* actor's Blackboard floor to 1 — and writes `last_known_pos` / `noise_pos`; the trees that carry search branches consume it (in v1 the Corp Guard's `investigate_noise` / `pursue_last_known`, `ai.md` §9.1). Guards stop patrolling and start hunting. The mapping is fixed: **0 Calm / 1 Alert / 2 Lockdown** (DECISIONS §8) — an earlier `world.md` draft set Alert to `alert_level = 2`, which collides with Lockdown and makes the two tiers indistinguishable. |
| ≥ 7 | **Lockdown** | **`alert_level = 2`** on every actor's Blackboard. Every door on the Site **locks**. A locked door must be **forced (Lock forced, +1 Clock)** or **hacked (door rating 2–4)**. **All guards gain +2 armour** — this raises their soak pool *and* raises the DV needed to keep a P attack Physical instead of Stun. |
| 10 | **Converge** | Security converges. **The Run ends immediately**: forced Extraction, payout **0**, **Heat +2**, **Fixer reputation −1**. |

### 7.3 Extraction

| Extraction | Payout | Heat | Reputation |
|---|---|---|---|
| Voluntary | pays for objectives completed | unchanged | **+1** |
| Forced (Clock full) | **0** | **+2** | **−1** |

Clock, Site layout, and enemy placement **reset per Run**. Heat decays by 1 per successful Job; a voluntary Extraction that completes objectives is a successful Job. The Clock resets to 0 for the next Run regardless of extraction type.

### 7.4 Worked example — a fight goes loud, the crew extracts early

Run on a corporate floor. Paydata in the vault.

| # | Event | Clock | Threshold reached |
|---|---|---|---|
| — | Entry: silent takedown of the door guard | 0 | |
| — | Successful hack of the internal door | 0 | |
| — | Successful hack of the vault; **Paydata secured** | 0 | |
| 1 | Exiting, a patrol rounds the corner; Sable fires — **Gunfire +2** (first shot of the fight) | **2** | |
| 2 | Round 2: Sable kills the patrol leader — **Guard killed +2** | **4** | **ALERT** — every patrol stops and converges on the crew's last position |
| 3 | Round 2: Nine's hack of the alarm panel fails — **Failed hack +1** | **5** | |
| 4 | Round 3: Kestrel's Stunball at Force 6 — **Loud spell +2** | **7** | **LOCKDOWN** — doors seal behind them, guards +2 armour |

**Branch B — extract early (recommended).** At Clock **7** the paydata is already secure. The crew voluntarily Extracts. Payout covers the paydata objective and one completed side objective; **Heat unchanged**, **Fixer reputation +1**, and the job counts as successful, so **Heat −1**. The Clock resets to 0 for the next Run. They leave a body and a live guard behind — content consequences, not Clock consequences.

**Branch A — press on.** The crew tries for the side vault anyway. A second patrol finds the first guard's body — **Body found +3** → Clock **10** → **CONVERGE**. Forced Extraction: **payout 0**, **Heat +2**, **reputation −1**. Nine segments of work paid out and the last three cost everything.

---

## 8. Gear and armour

### 8.1 Weapons

| Weapon | DV | AP | Range (cells) | Magazine | Nominal type |
|---|---|---|---|---|---|
| Heavy pistol | 5P | 1 | 8 | 15 | P |
| SMG | 6P | 0 | 10 | 30 | P |
| Assault rifle | 8P | 2 | 14 | 30 | P |
| Shotgun | 7P | 1 | 6 | 8 | P |
| Katana | `(Strength + 3)P` | 3 | 1 (adjacent) | — | P |
| Stun baton | 6S | 0 | 1 (adjacent) | — | S |
| Hellhound bite | `(Strength + 2)P` | 1 | 1 (adjacent) | — | P |
| Beast strike (`beast_strike`) | `(Force+3)P` | 1 | 1 (adjacent) | — | P |
| Air bolt (`air_bolt`) | `(Force+1)P` | 0 | 8 | — | P |
| Earth slam (`earth_slam`) | `(Force+2)P` | 2 | 1 (adjacent) | — | P |
| Water burst (`water_burst`) | `(Force)S` | 0 | 6 (radius 2) | — | S |
| Unarmed | `Strength S` **[proposed]** | 0 | 1 (adjacent) | — | S (P with Killing Hands, +1 DV) |

Ranges are DECISIONS §4: melee 1 (adjacent), spells **12 cells with line of sight**. AP is a positive magnitude (DECISIONS §4).

Katana with Sable's STR 7 → **10P, AP 3**. Close combat uses `Strength` for damage (DECISIONS §1).

### 8.2 Armour

| Armour | Rating |
|---|---|
| Armoured vest | 6 |
| Lined coat | 7 |
| Armoured jacket | 8 |
| Helmet (adds) | +2 |

**Only the highest armour value applies; accessories add.** Jacket 8 + helmet = **10**. Under Lockdown, guards are **+2 armour** (vest 6 → 8, jacket 8 → 10).

### 8.3 How AP meets soak

- **Modified armour = `armour − AP`**, with AP a positive magnitude, so AP only ever shrinks the armour it meets. A katana (AP 3) against a vest 6 → modified armour **3**.
- **Soak pool = `Body + modified armour`** d6; each Hit cancels 1 DV.
- AP therefore does two things at once: it **shrinks the soak pool** and it **lowers the threshold for Physical damage** (P stays Physical when DV ≥ modified armour).
- Worked: katana 10P + 4 net Hits = DV 14 vs vest 6: modified armour = 6 − 3 = **3**; `14 ≥ 3` → **Physical**; soak = `BOD 4 + 3 = 7`; 3 soak Hits → **11 boxes** — more than the 10-box monitor, so the guard is removed from the encounter.
- Armour is the reason a low-DV hit is only Stun: an SMG's DV 7 against a jacket 8 never leaves a scratch in Physical terms, it just fills Stun.

### 8.4 Gear and the Hub

- Gear is bought through the **Buy Gear** Legwork action (three Legwork actions per Job).
- Payout is `12,000¥ ± 100 × net Negotiation Hits`; Heat decays by 1 per successful Job.
- Devices the Decker can target are the device table in §5.2 — they are all "gear" on the Site, and enemy gear uses the same ratings.
- **Gear prices are in DECISIONS §9**; this document does not restate them.
- Reload costs 5 Energy and refills one magazine. Magazine sizes are in the weapon table in §8.1.

---

## 9. Perception, FOV, darkness, and Memory

### 9.1 Perception

- Skill: **Perception (Intuition)**. Static tests use the standard thresholds: 1 trivial, 2 average, 3 hard, 4+ extreme (spotting a concealed device off a scrawled note = 2; a hidden floor plate = 3).
- Spotting a **hiding actor** is an **Opposed Test**: `Perception + Intuition` vs the hider's `Stealth + Agility` **[proposed]**. Ties go to the defender — the hider stays hidden.
- Perception is rolled when the actor has line of sight (see §9.2), and it is the skill that lets a Runner read the Site before the Clock reads them.

### 9.2 FOV — what "visible" means

- **FOV** is the set of cells currently visible from the viewer's position by line of sight, computed once per move with recursive shadowcasting (8 octants). Cell visibility uses a circular radius, not a square.
- Runners see in all directions within their FOV radius; enemies see with their own FOV, and FOV is **mutual** — if a Runner can see a guard, that guard can see the Runner.
- **FOV radius** is **8** cells in lit conditions, **2** in darkness (DECISIONS §12). Sight radius is the only visibility parameter in v1.

### 9.3 Darkness

- **Darkness** is a Site state, set by hacking a room's **Lights** (device rating 3, Drain 2 Stun).
- While a room is dark: **enemy FOV radius becomes 2** and enemies take **−2 dice**. It lasts 3 rounds unless the Decker re-hacks or a guard fixes the room **[duration is [proposed]; DECISIONS gives the FOV/dice effect only]**.
- Player-facing: the Decker's `Lights` hack is a room-wide debuff. It is the cheapest way to make a firefight quiet, because enemies that cannot see cannot shoot.
- **[proposed]** the −2 dice applies to the enemies' Perception and ranged attack pools (Open questions Q19).

### 9.4 Memory — visible vs remembered, in player terms

Three render states, straight off the `visible` and `explored` byte arrays:

| State | Player sees | Rule |
|---|---|---|
| **Visible** | full terrain, items, actors, colour | inside the current FOV |
| **Memory** | terrain and known fixtures, drawn dim | seen earlier in the Run, not currently visible |
| **Unknown** | black, nothing | never seen |

- **Terrain and fixtures (doors, devices, loot) are remembered** at the moment they are first seen. A vault door you hacked stays on your Memory map.
- **Actors are not remembered.** A guard in Memory is not drawn, and its position is unknown — you know the room, not who is in it now. **[proposed]** (Open questions Q18).
- Memory is per-Run and is wiped at Extraction.
- **Hiding** works off the same split: an actor in a Memory cell is not auto-detected; it must be re-spotted by Perception (§9.1) the moment the cell re-enters FOV.

---

## Appendix A — Playtest on paper

### A.1 Minimum components

| Component | Detail |
|---|---|
| **16 × d6** | enough for the largest single pool in one throw (Sable's soak is 14). One shared cup is fine — no test rolls more than twice. |
| **4 Runner sheets** | the §3.0 cast; write attributes, the 13 skill ratings, Edge 3, Qi 4, and both Condition Monitors as box rows. |
| **2 enemy sheets** | Corp Guard and Security Drone (the two simplest archetypes), with Initiative, Wound Modifier, and both monitors. |
| **One Site sketch** | hand-draw ~20×20 cells on graph paper (the DECISIONS 60×60 recommendation is for the generator, not the paper test). Mark a wall out front, a corridor, a locked door, and one vault cell. |
| **A Mission Graph on one line** | `entry → security → vault(objective) → side(s) → exit`, with the vault holding the Paydata. |
| **A Clock track** | ten boxes, ticked out loud with the event name each time. |
| **Energy scratch pad** | one row per actor per round: Score, Energy spent per Action, remaining Energy, done/not done. |
| **Token per actor** | coins or dice for positions, plus two counters for cover and the aimed bonus. |
| **A 3-round event strip** | who acts in Pass 1 and Pass 2, in the tie-broken order from §2.2. |

### A.2 The five questions paper playtest must answer

1. **Does the Energy budget create a real choice, or does the arithmetic decide for you?** Watch a Score of 11–15 compared with a Score of 9. Does "Aim + Attack = 15, so no movement" feel like a decision, or like the Score playing itself? Specifically: is one Attack per Pass (10 of ~11–15 Energy) too coarse to make cover and Aim matter? *(If yes, ADR-0003's deferred global time-cost queue is the documented successor.)*
2. **Does damage land in the middle, or only at 0 and one-shot?** Across a full Job, how often is a hit fully soaked (0 boxes) versus removing the target outright? The pools are attack ~8–12 vs defence ~7–10 vs soak ~7–14; log every hit and see whether the typical result is a meaningful 2–5 boxes or a coin flip.
3. **Does Drain actually bite?** An 11-dice Drain-resistance pool against Drain 3–4 means the Mage may shrug off a whole Job. Count the Stun boxes the Mage, Shaman, and Decker take across one Job, and whether the sustain −2 ever changed a decision. If Drain never lands, it is a formality, not a resource.
4. **Does the Security Clock create an extract-early decision before Converge?** Did the crew ever choose to leave at 7 (Lockdown) with the paydata secure? Did the player correctly predict which action would tick it, and by how much? If the fight reached 10 without a "we should go" moment, the tick values are wrong.
5. **Does the Wound Modifier spiral end fights decisively, or grind them?** At −3 to −5, everything an actor rolls is crippled (see §4.5, where one Stun overflow takes a guard to −5). Does that shorten fights, or does it make one side helpless too early and the other side tediously finish them?

---

## Open questions

Every entry is a rule that is underspecified in `DECISIONS.md`, with the recommendation this document used. **[proposed]** markers above point here. The contradictions the first draft found (the AP sign, the S codes swallowed by the damage-type rule, unreachable Physical Drain) were fixed by the amended `DECISIONS.md` and are no longer listed here.

**Underspecified — recommendation used in this document:**

- **Q5 — Gunfire tick frequency.** Per shot, per round with shooting, or once per fight? *Recommendation:* **+2 for the first gunfire of an encounter**, once per fight. Per-shot ends a Run in five shots.
- **Q6 — What does a full Stun monitor do?** `DECISIONS.md` describes only the 2:1 overflow on further Stun, and never says a full Stun monitor has an effect of its own. *Recommendation:* **full Stun = unconscious** — removed from the encounter, revives after the Run (not Downed, not out of the Run). Without this, a Runner can carry a full Stun track and a −3 Wound Modifier indefinitely.
- **Q8 — Unarmed DV is missing** from the weapon table, so the Adept's Killing Hands has no base to modify. *Recommendation:* unarmed = `Strength S`, AP 0; Killing Hands makes it `Strength + 1 P` for 3 rounds.
- **Q9 — Push the Limit's dice count.** "+Edge dice" could mean +3 (the Edge rating) or +1 die per point spent. *Recommendation:* **+3 dice** (the Edge rating) for 1 point, matching Edge-as-attribute and SR's Push the Limit.
- **Q10 — Can Edge be spent twice on one test?** *Recommendation:* **no** — one Edge spend per test, so Push the Limit and Second Chance cannot both apply.
- **Q12 — Qi pool starting value.** Pool 4 with +1 per Pass could mean it starts at 0 or starts full. *Recommendation:* **starts full at 4** at the start of a Run, refills +1 per Pass, capped at 4.
- **Q14 — Does Seize the Initiative (+10 Energy) interact with Passes?** *Recommendation:* it adds +10 to the **current Pass's** Energy only; it does not raise the Score, does not grant a Pass, and leftover Energy is lost at Pass end.
- **Q15 — Voluntary Pass end.** *Recommendation:* allowed; leftover Energy is lost. Needed so a player can keep 5 Energy in reserve rather than be forced into a bad Step.
- **Q16 — Attribute Boost (Reaction) and the Initiative Score.** Reaction is both a pool attribute and a Score component. *Recommendation:* **+1 to the Initiative Score** next round, in addition to +1 die on Reaction pools; it stacks with Improved Reflexes but not with another Attribute Boost.
- **Q17 — Improved Reflexes timing.** Does the extra +1d6 Initiative Score apply to the Pass in which it was bought? *Recommendation:* **from the next Pass onward**; it does not retroactively raise the current Pass's Energy.
- **Q18 — Memory and actors.** Are the last-known positions of enemies remembered? *Recommendation:* **no** — Memory holds terrain and fixtures only; actors exist only while visible. This makes the Decker's Scan and the Mage's Analyze Device the tools for "what is on the other side".
- **Q19 — What does the darkness −2 apply to?** *Recommendation:* **enemy Perception and ranged attack pools**, plus the FOV radius 2. The Crew's own pools are unaffected while they have the device feed.
- **Q20 — Darkness/light duration.** *Recommendation:* the hacked Lights state lasts **3 rounds** unless re-hacked or repaired, matching every other 3-round device effect.
- **Q24 — Summon resolution.** "`2 × the spirit's Hits`, minimum 2" leaves open what the spirit rolls and what threshold the Conjuring test needs. *Recommendation:* Summon is a Success Test vs **threshold 3**; the test's **net Hits are "the spirit's Hits"** and set the spirit's power; Drain is `2 × those Hits`. Failing the test, or any Glitch, lets the Spirit break free and become hostile.

---

## Sources

- `.agents/skills/roguelike/SKILL.md` — energy-based turn scheduler, FOV + explored memory, run-vs-profile state.
- `.agents/skills/roguelike/references/generation-fov-loot.md` — symmetric shadowcasting and the visible/explored render split.
- `.agents/skills/rpg/references/stats-combat-quests.md` — base vs derived stats and the modifier-layer discipline behind the Wound Modifier.
- `.agents/skills/ai-behavior-trees-utility-ai/SKILL.md` and `.agents/skills/game-ai/SKILL.md` — Blackboard keys and the utility-score/hysteresis pattern behind the Alert behaviour in §7.2.

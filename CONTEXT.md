# Pink Mohawk

A turn-based tactical roguelite about running a four-person shadowrunner crew through corporate jobs in a cyberpunk sprawl. Named for the loud, flashy style of running — the exact style the Security Clock exists to punish.

This file is a glossary and nothing else. Decisions live in `docs/adr/`. Numbers and parameters live in `docs/design/DECISIONS.md`.

## Language

### The run

**Runner**:
One member of the Crew; a person who takes shadowrun Jobs.
_Avoid_: character, unit, agent

**Crew**:
The four Runners the player controls: Physical Adept, Mage, Shaman, Decker.
_Avoid_: party, team, squad

**Job**:
A contract posted by a Fixer, with an objective and a payout.
_Avoid_: quest, mission, contract

**Run**:
One attempt at a Job, played on a generated Site.
_Avoid_: level, dungeon, raid

**Site**:
The generated map a Run takes place on.
_Avoid_: map, level, dungeon

**Hub**:
The authored city district the Crew occupies between Jobs, where they heal, shop, and take work.
_Avoid_: overworld, town, base

**Legwork**:
The optional pre-Run actions at the Hub that change a Site or the intel available about it.
_Avoid_: preparation phase, downtime

**Extraction**:
Ending a Run, whether on completion or under pressure, and returning the Crew to the Hub.

**Paydata**:
The data objective worth the largest share of a Job's payout.

**Mission Graph**:
The generated objective graph — entry, security, objective, side, and exit nodes — that a Site is embedded from.
_Avoid_: layout, level graph

### Pressure

**Security Clock**:
The ten-segment timer that forces Extraction when it fills.
_Avoid_: alarm, alert level

**Heat**:
Persistent world pressure from loud or failed Runs; raises Site difficulty across Jobs.
_Avoid_: notoriety, wanted level

**Fixer**:
The NPC who posts Jobs and pays out.

**Glitch**:
Too many 1s in a Dice Pool; a failure that carries an extra cost.

### Dice

**Dice Pool**:
The set of d6 rolled for a test: attribute + skill + modifiers.
_Avoid_: roll, check

**Hit**:
One die in a Dice Pool showing a 5 or a 6.

**Opposed Test**:
A test where the defender rolls a Dice Pool and net Hits decide the outcome.

**Edge**:
The small per-Run luck pool any Runner can spend to push a test.

**Qi**:
The Physical Adept's per-fight power pool.

**Drain**:
The Stun cost a Caster pays for its primary abilities.

**Caster**:
A class whose primary abilities cost Drain: Mage, Shaman, or Decker.

**Tradition Attribute**:
The attribute a Caster resists Drain with — Logic for the Mage and the Decker, Charisma for the Shaman.

**Spirit**:
An actor the Shaman conjures; driven by a Behavior Tree, with a risk of breaking free.

### Damage

**Condition Monitor**:
A track of damage boxes; each actor has one for Stun and one for Physical.

**Overflow**:
Stun damage converting to Physical at two boxes to one when the Stun monitor fills.

**Wound Modifier**:
The Dice Pool penalty for filled boxes.

**Downed**:
A Runner removed from the Run at zero Physical boxes; recovers at the Hub.

### Turns

**Initiative Score**:
Reaction + Intuition + dice; sets the actor's Energy for the turn.

**Energy**:
The points an actor spends on actions; running out ends the Pass.

**Pass**:
One turn taken by spending Energy until it is exhausted; the Initiative Score drops by ten each Pass.

### Brains

**Behavior Tree**:
The data-defined decision tree driving every actor the player does not control.
_Avoid_: AI script, state machine

**Blackboard**:
The per-actor dictionary a Behavior Tree reads and writes.

**Utility Score**:
The number used to rank candidate targets or actions against each other.

**Dialogue Graph**:
The JSON node graph that drives an NPC conversation.
_Avoid_: conversation tree, script

### Rendering

**Glyph**:
The single Tileset cell drawn in one map cell; the only sprite primitive the renderer has.
_Avoid_: sprite, image, texture

**Tileset**:
The image the renderer maps Glyphs into.

**Remap**:
Binding a codepoint to a cell of a Tileset.

**FOV**:
The cells currently visible from the viewer's position by line of sight.

**Memory**:
Cells seen earlier in the Run but not currently visible.

### Growth

**XP**:
The currency spent to raise ratings; one per successful test, five per failed test.

**Perk**:
A random improvement granted by failure, sometimes bending the Runner away from their archetype.

**Advance**:
Spending XP to raise a skill or attribute rating.

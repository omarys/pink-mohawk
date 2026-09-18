"""Resolution: dice pools, damage, Drain, and what things cost.

DECISIONS §3 (pools, hits, glitches), §4 (damage, monitors, the Stun→Physical conversion), §5 (Energy
costs) and §6 (Edge, Qi, Drain). Every number comes from `constants.py`, which
`tools/check_contract.py` holds in step with the document.

Layer 2: imports `entities` (same layer, as `data-model.md` §15's import line states), `constants`,
and `random` for the seeded streams.

TWO IDEAS WORTH KNOWING BEFORE READING ON
----------------------------------------
**`classify` is pure; `roll` adds randomness.** Everything a rule says about a set of dice — hits,
glitches, critical glitches — is a function of the dice alone, so it is tested exhaustively with
hand-written dice and no RNG at all. Only `roll` touches a `random.Random`, and it is the project's
seeded stream (`rng.make_static_rngs`), never the global one.

**The box counter does not know about damage types.** `entities.Monitor.mark` returns the boxes that
did not fit; this module decides what that overflow *means* — 2 Stun boxes become 1 Physical (§4) —
and records it. That is why `apply_damage` exists rather than a fatter `Monitor`.

    .venv/bin/python -m pinkmohawk.rules      # runs demo()
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass

from .constants import (
    AIM_MAX_BONUS,
    DAMAGE_PHYSICAL,
    DAMAGE_STUN,
    DRAIN_FORMULAS,
    ENERGY_COSTS,
    HIT_MIN,
    OVERFLOW_STUN_PER_PHYSICAL,
    QI_POWERS,
    SPIRIT_ATTACKS,
    SPIRIT_FORCE_DEFAULT,
    SUMMON_DRAIN_FLOOR,
    SUSTAIN_MAX,
    SUSTAIN_PENALTY,
    THRESHOLDS,
    TRADITION_ATTRIBUTE,
    WEAPONS,
)
from .entities import Actor, RunnerRole
from .errors import ValidationError

type Dice = Sequence[int]

#: Indices into a WEAPONS row: `(dv, code, ap, range)`.
DV, CODE, AP, RANGE = 0, 1, 2, 3


@dataclass(frozen=True, slots=True)
class Roll:
    """The result of one Dice Pool. Pure data: no state, no verdicts beyond what §3 defines."""

    dice: tuple[int, ...]
    hits: int
    ones: int
    glitch: bool
    critical: bool

    def __str__(self) -> str:
        marks = " CRITICAL GLITCH" if self.critical else (" GLITCH" if self.glitch else "")
        return f"{list(self.dice)} -> {self.hits} hits{marks}"


def classify(dice: Dice) -> Roll:
    """Apply §3's rules to a set of dice. No randomness, no I/O: the whole rule set, testable.

    A Glitch is **more 1s than half the dice**, which is the stricter reading — SR5's printings
    disagree, and the contract picked this one (DECISIONS §3). So two dice with one 1 is *not* a
    glitch, and three dice with two 1s is.
    """
    values = tuple(dice)
    for value in values:
        if not 1 <= value <= 6:
            raise ValidationError([f"a d6 cannot show {value}"])
    hits = sum(1 for v in values if v >= HIT_MIN)
    ones = sum(1 for v in values if v == 1)
    glitch = ones * 2 > len(values)
    return Roll(values, hits, ones, glitch, glitch and hits == 0)


def roll(pool: int, rng: random.Random, *, edge_dice: int = 0, explode: bool = False) -> Roll:
    """Roll a pool of d6 from a seeded stream.

    `edge_dice` is Push the Limit's extra dice (§6), and `explode` is its Rule of Six: every 6 adds
    another die, which itself may explode. The loop is bounded so a hostile RNG cannot hang a turn.
    """
    if pool < 0 or edge_dice < 0:
        raise ValidationError([f"pool and edge dice must be non-negative, got {pool}, {edge_dice}"])
    values = [rng.randint(1, 6) for _ in range(pool + edge_dice)]
    if explode:
        frontier = [v for v in values if v == 6]
        for _ in range(64):  # bounded: 6s cannot be chased forever
            if not frontier:
                break
            frontier = [rng.randint(1, 6) for _ in frontier]
            values.extend(frontier)
            frontier = [v for v in frontier if v == 6]
    return classify(values)


def success(result: Roll, threshold: str | int = "average") -> bool:
    """§3: Hits ≥ threshold. Thresholds are named in the contract; an int works too."""
    if isinstance(threshold, str):
        if threshold not in THRESHOLDS:
            raise ValidationError([f"unknown threshold {threshold!r}; known: {list(THRESHOLDS)}"])
        need = THRESHOLDS[threshold]
    else:
        need = threshold
    return result.hits >= need


@dataclass(frozen=True, slots=True)
class Opposed:
    """§3: net Hits decide, and ties go to the defender."""

    attacker: Roll
    defender: Roll

    @property
    def net(self) -> int:
        """Net hits for the attacker. Zero when the defender ties or wins."""
        return max(0, self.attacker.hits - self.defender.hits)

    @property
    def defender_wins(self) -> bool:
        return self.net == 0


def opposed(attacker: Roll, defender: Roll) -> Opposed:
    return Opposed(attacker, defender)


# ----------------------------------------------------------------------------------------------
# Damage
# ----------------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Damage:
    """A weapon's profile with any character-derived DV already resolved."""

    power: int
    code: str  # "P" or "S"
    ap: int  # positive magnitude, subtracted from armour (§4)

    def __post_init__(self) -> None:
        if self.code not in (DAMAGE_PHYSICAL, DAMAGE_STUN):
            raise ValidationError([f"damage code must be P or S, got {self.code!r}"])


def weapon_damage(weapon: str, strength: int) -> Damage:
    """Resolve a WEAPONS row, including the `strength+N` rows (katana, hellhound bite)."""
    row = WEAPONS.get(weapon)
    if row is not None:
        dv, code, ap, _range = row
        power = strength + int(dv.split("+")[1]) if isinstance(dv, str) else int(dv)
        return Damage(power, code, ap)
    # A Spirit's attacks are not in WEAPONS: they scale with Force, not Strength (classes.md §7.3).
    for _spirit_type, (ability, (offset, _b), ap, _r, is_stun) in SPIRIT_ATTACKS.items():
        if ability == weapon:
            return Damage(
                SPIRIT_FORCE_DEFAULT + offset, DAMAGE_STUN if is_stun else DAMAGE_PHYSICAL, ap
            )
    raise ValidationError([f"unknown weapon {weapon!r}"])


def soak_pool(actor: Actor, damage: Damage, armour: int) -> int:
    """§4: Body + (armour − AP). AP is a positive magnitude, so it always reduces."""
    return actor.attrs["body"] + max(0, armour - damage.ap)


def damage_type(damage: Damage, modified_armour: int) -> str:
    """§4: nominal, plus one downgrade. S-code is always Stun; P becomes Stun below the armour."""
    if damage.code == DAMAGE_STUN:
        return DAMAGE_STUN
    return DAMAGE_PHYSICAL if damage.power >= modified_armour else DAMAGE_STUN


@dataclass(frozen=True, slots=True)
class DamageResult:
    """What one application of damage did, for the log and for the caller's checks."""

    code: str
    on_stun: int = 0
    on_physical: int = 0
    overflow_discarded: int = 0
    downed: bool = False
    filled_stun: int = 0
    filled_physical: int = 0


def apply_damage(actor: Actor, code: str, power: int, *, round_no: int = 0) -> DamageResult:
    """Mark boxes on the right monitor, converting Stun overflow 2:1 into Physical (§4).

    The odd Stun box is discarded, not carried: the contract states the conversion as 2 boxes to 1,
    and carrying a remainder would be a rule the document does not have. A Runner at a full Physical
    monitor is **Downed** — out of the Run, recovered at the Hub (ADR-0005, no permadeath in v1).
    """
    del round_no  # reserved: effects are applied by the caller
    if power <= 0:
        return DamageResult(
            code, filled_stun=actor.stun.filled, filled_physical=actor.physical.filled
        )
    if code == DAMAGE_STUN:
        overflow = actor.stun.mark(power, actor.attrs["willpower"])
        physical = overflow // OVERFLOW_STUN_PER_PHYSICAL
        spilled = actor.physical.mark(physical, actor.attrs["body"]) if physical else 0
        return DamageResult(
            code,
            on_stun=power - overflow,
            on_physical=physical - spilled,
            overflow_discarded=overflow % OVERFLOW_STUN_PER_PHYSICAL + spilled,
            downed=actor.downed,
        )
    spill = actor.physical.mark(power, actor.attrs["body"])
    return DamageResult(
        code, on_physical=power - spill, overflow_discarded=spill, downed=actor.downed
    )


@dataclass(frozen=True, slots=True)
class AttackOutcome:
    """The whole exchange, in the order §4 resolves it: net hits, DV, soak, boxes."""

    attack: Roll
    defence: Roll
    net: int
    base_dv: int
    modified_dv: int
    soaked: int
    final_dv: int
    code: str
    applied: DamageResult | None


def attack_pool(
    actor: Actor, weapon: str, *, skill: str = "firearms", aim: int = 0, modifiers: int = 0
) -> int:
    """`attribute + skill + aim + modifiers`; the wound modifier is the caller's to include."""
    attribute = "agility"
    return actor.attrs[attribute] + actor.skills[skill] + min(aim, AIM_MAX_BONUS) + modifiers


def defence_pool(actor: Actor, *, cover: bool = False) -> int:
    """§4: ranged defence is Reaction + Intuition, +2 in cover."""
    base = actor.attrs["reaction"] + actor.attrs["intuition"]
    return base + (2 if cover else 0)


def resolve_attack(
    attacker: Actor,
    defender: Actor,
    weapon: str,
    rng: random.Random,
    *,
    skill: str = "firearms",
    aim: int = 0,
    attack_modifiers: int = 0,
    cover: bool = False,
    armour: int = 0,
    soak_dice: int | None = None,
) -> AttackOutcome:
    """Roll the exchange and apply the damage, in §4's order.

    `armour` is the defender's armour *rating*; AP is subtracted here, not by the caller. `soak_dice`
    overrides the derived pool, for a caller that has already accounted for something unusual.
    """
    damage = weapon_damage(weapon, attacker.attrs["strength"])
    atk = roll(attack_pool(attacker, weapon, skill=skill, aim=aim, modifiers=attack_modifiers), rng)
    dfn = roll(defence_pool(defender, cover=cover), rng)
    result = opposed(atk, dfn)
    modified_dv = damage.power + result.net
    modified_armour = max(0, armour - damage.ap)
    # The damage TYPE is decided by the DV before soak against the armour (§4); soak then cancels
    # boxes of that type. Using the post-soak DV here would let a good soak roll turn a physical hit
    # into a stun one, which the contract does not say.
    code = damage_type(Damage(modified_dv, damage.code, damage.ap), modified_armour)
    soak = soak_dice if soak_dice is not None else defender.attrs["body"] + modified_armour
    soaked = roll(soak, rng).hits
    final = max(0, modified_dv - soaked)
    applied = apply_damage(defender, code, final) if final > 0 else None
    return AttackOutcome(
        atk, dfn, result.net, damage.power, modified_dv, soaked, final, code, applied
    )


# ----------------------------------------------------------------------------------------------
# Drain, Edge, Qi, Energy
# ----------------------------------------------------------------------------------------------
def drain_value(ability: str, force: int) -> int:
    """§6: `max(floor, Force − offset)` from the contract's Drain table."""
    row = DRAIN_FORMULAS.get(ability)
    if row is None:
        raise ValidationError(
            [f"no Drain formula for {ability!r}; known: {sorted(DRAIN_FORMULAS)}"]
        )
    floor, offset = row
    return max(floor, force - offset)


def drain_is_physical(actor: Actor, tradition: str, force: int) -> bool:
    """§6: overcasting — Drain is Physical when Force exceeds the Tradition Attribute's value."""
    attribute = TRADITION_ATTRIBUTE.get(tradition)
    if attribute is None:
        raise ValidationError([f"unknown tradition {tradition!r}"])
    return force > actor.attrs[attribute]


def summon_drain(spirit_hits: int) -> int:
    """§6: 2 × the Spirit's Hits, minimum 2."""
    return max(SUMMON_DRAIN_FLOOR, 2 * spirit_hits)


def hack_drain(device_rating: int, *, glitched: bool = False) -> int:
    """§6/§7: `ceil(rating / 2)`, doubled on a Glitch, with no resistance roll."""
    base = -(-device_rating // 2)
    return base * 2 if glitched else base


@dataclass(frozen=True, slots=True)
class DrainResult:
    value: int
    resisted: int
    taken: int
    code: str
    applied: DamageResult | None


def resist_drain(
    actor: Actor, value: int, rng: random.Random, *, tradition: str, force: int = 0
) -> DrainResult:
    """Willpower + the Tradition Attribute (§6). Unresisted boxes are Stun unless overcasting."""
    attribute = TRADITION_ATTRIBUTE.get(tradition)
    if attribute is None:
        raise ValidationError([f"unknown tradition {tradition!r}"])
    pool = actor.attrs["willpower"] + actor.attrs[attribute]
    resisted = roll(pool, rng).hits
    taken = max(0, value - resisted)
    code = DAMAGE_PHYSICAL if force and drain_is_physical(actor, tradition, force) else DAMAGE_STUN
    applied = apply_damage(actor, code, taken) if taken else None
    return DrainResult(value, resisted, taken, code, applied)


def sustain_penalty(sustaining: int) -> int:
    """§6: −2 dice per sustained spell, and at most two may be sustained at once."""
    if sustaining > SUSTAIN_MAX:
        raise ValidationError([f"at most {SUSTAIN_MAX} spells may be sustained"])
    return SUSTAIN_PENALTY * sustaining


def wound_modifier(actor: Actor) -> int:
    """§4: −1 die per 3 filled boxes, counting both tracks together.

    Delegates: `Actor.wound_modifier` is the one implementation, because four copies of one
    formula is how a contract drifts.
    """
    return actor.wound_modifier


def charge(actor: Actor, action_key: str, times: int = 1) -> int:
    """Deduct `ENERGY_COSTS[action_key]` from the actor and return what was charged (§5).

    This is the one place Energy leaves an actor: decision 25 keeps the behavior-tree leaves out of it
    entirely, so a leaf that forgets to declare a cost cannot hand out a free action.
    """
    if action_key not in ENERGY_COSTS:
        raise ValidationError([f"unknown energy action {action_key!r}; see DECISIONS §5"])
    amount = ENERGY_COSTS[action_key] * times
    actor.energy -= amount
    return amount


def spend_edge(actor: Actor, spend: str, rng: random.Random, pool: int = 0) -> int:
    """§6's three Edge spends. Returns extra dice, or the Energy granted by Seize the Initiative.

    Edge refreshes at the start of a Run, not per Pass, so it is spent deliberately or not at all.
    """
    role = actor.role
    if not isinstance(role, RunnerRole):
        raise ValidationError(["only a Runner has Edge"])
    if role.edge <= 0:
        return 0
    if spend not in ("push_the_limit", "second_chance", "seize_the_initiative"):
        raise ValidationError([f"unknown Edge spend {spend!r}"])
    role.edge -= 1
    if spend == "push_the_limit":
        return pool  # extra dice equal to the pool size
    if spend == "second_chance":
        return 0  # the caller rerolls failures
    actor.energy += 10
    return 10


def spend_qi(actor: Actor, power: str) -> int:
    """§6: deduct a Qi power's cost, or refuse. Qi refreshes 1 per Pass, capped at QI_MAX."""
    role = actor.role
    if not isinstance(role, RunnerRole) or role.klass != "adept":
        raise ValidationError(["only the Physical Adept has Qi"])
    cost = QI_POWERS.get(power)
    if cost is None:
        raise ValidationError([f"unknown Qi power {power!r}; known: {sorted(QI_POWERS)}"])
    if role.qi < cost:
        return 0
    role.qi -= cost
    return cost


# ==============================================================================================
# Acceptance test
# ==============================================================================================
def demo() -> None:
    from .constants import ATTRIBUTES, SKILLS
    from .entities import Monitor, RunnerRole

    def someone(
        actor_id: int = 1,
        body: int = 4,
        willpower: int = 4,
        reaction: int = 4,
        intuition: int = 4,
        agility: int = 4,
        logic: int = 3,
        klass: str = "adept",
    ) -> Actor:
        attrs = dict.fromkeys(ATTRIBUTES, 3)
        attrs.update(
            body=body,
            willpower=willpower,
            reaction=reaction,
            intuition=intuition,
            agility=agility,
            logic=logic,
        )
        return Actor(
            id=actor_id,
            name="x",
            faction="crew",
            pos=(0, 0),
            facing=0,
            glyph=0,
            tint=(0, 0, 0),
            attrs=attrs,
            skills=dict.fromkeys(SKILLS, 0),
            physical=Monitor(),
            stun=Monitor(),
            role=RunnerRole(klass=klass, qi=4, edge=3),
        )

    # ---- 1. classify: pure, exhaustively testable, and the glitch boundary ---------------
    assert classify([6, 6, 5]).hits == 3 and not classify([6, 6, 5]).glitch
    assert classify([4, 3, 2]).hits == 0 and not classify([4, 3, 2]).glitch
    assert classify([1, 1, 5]).glitch and not classify([1, 1, 5]).critical, "1 hit, so not critical"
    assert classify([1, 1, 2]).critical, "glitch with no hits is critical"
    assert classify([1]).glitch, "one die showing 1: more than half the dice are 1s, so glitch"
    assert not classify([1, 2]).glitch, "exactly half the dice as 1s is NOT a glitch (our reading)"
    assert classify([1, 1]).glitch and classify([1, 1]).critical
    assert not classify([]).glitch and classify([]).hits == 0, "an empty pool is not a glitch"
    try:
        classify([7])
        raise AssertionError("a d6 cannot show 7")
    except ValidationError:
        pass

    # ---- 2. roll: seeded, deterministic, exploding bounded ------------------------------
    a, b = random.Random(7), random.Random(7)
    assert roll(9, a).dice == roll(9, b).dice, "the same seed gives the same dice"
    assert len(roll(9, random.Random(1), edge_dice=3).dice) == 12, "Push the Limit adds its dice"
    exploded = roll(60, random.Random(3), explode=True)
    assert len(exploded.dice) >= 60, "exploding 6s only ever add dice"
    assert all(1 <= v <= 6 for v in exploded.dice)

    # ---- 3. thresholds and opposed tests -------------------------------------------------
    assert success(classify([5, 5]), "average") and not success(classify([5]), "average")
    assert success(classify([5, 5, 5]), "hard") and not success(classify([5, 5]), "hard")
    tie = opposed(classify([5, 5, 3]), classify([6, 5, 1]))
    assert tie.net == 0 and tie.defender_wins, "ties go to the defender"
    won = opposed(classify([6, 6, 5]), classify([5, 3, 3]))
    assert won.net == 2 and not won.defender_wins

    # ---- 4. weapons, armour, AP, damage type --------------------------------------------
    assert weapon_damage("heavy_pistol", 4).power == 5
    assert weapon_damage("katana", 7).power == 10, "(Strength + 3)P with Strength 7"
    assert weapon_damage("stun_baton", 3).code == DAMAGE_STUN
    target = someone(body=4, klass="adept")
    pistol = weapon_damage("heavy_pistol", 4)  # 5P, AP 1
    assert soak_pool(target, pistol, armour=6) == 4 + (6 - 1)
    assert damage_type(pistol, modified_armour=5) == DAMAGE_PHYSICAL, "DV 5 vs armour 5: Physical"
    assert damage_type(pistol, modified_armour=7) == DAMAGE_STUN, "below the armour: downgrades"
    baton = weapon_damage("stun_baton", 3)
    assert damage_type(baton, modified_armour=0) == DAMAGE_STUN, "S-code never becomes Physical"

    # ---- 5. applying damage: monitors, the 2:1 overflow, and Downed ----------------------
    victim = someone(body=4, willpower=4)  # Physical 10, Stun 10
    first = apply_damage(victim, DAMAGE_STUN, 6)
    assert first.on_stun == 6 and first.on_physical == 0 and victim.stun.filled == 6
    spill = apply_damage(victim, DAMAGE_STUN, 7)  # 4 fit, 3 overflow -> 1 Physical, 1 discarded
    assert spill.on_stun == 4 and spill.on_physical == 1 and spill.overflow_discarded == 1
    assert victim.physical.filled == 1
    downed = apply_damage(victim, DAMAGE_PHYSICAL, 99)
    assert downed.downed and victim.downed, "a full Physical monitor is Downed (no permadeath)"

    # ---- 6. Drain: the table, resistance, and overcasting -------------------------------
    assert drain_value("manabolt", 4) == 2, "max(2, 4-3)"
    assert drain_value("manabolt", 6) == 3
    assert drain_value("heal", 3) == 3, "the floor wins"
    mage = someone(logic=6, willpower=5, klass="mage")
    assert not drain_is_physical(mage, "mage", 6), "Force 6 against Logic 6 is still Stun"
    assert drain_is_physical(mage, "mage", 7), "Force 7 > Logic 6: overcasting hurts for real"
    assert drain_is_physical(mage, "mage", 8)
    assert summon_drain(4) == 8 and summon_drain(0) == 2
    assert hack_drain(4) == 2 and hack_drain(4, glitched=True) == 4
    cast = resist_drain(mage, 4, random.Random(11), tradition="mage", force=3)
    assert cast.code == DAMAGE_STUN and cast.taken <= 4 and cast.resisted >= 0
    overcast = resist_drain(mage, 4, random.Random(11), tradition="mage", force=8)
    assert overcast.code == DAMAGE_PHYSICAL, "Force 8 marks the physical monitor"

    # ---- 7. Energy, Edge and Qi ----------------------------------------------------------
    worker = someone()
    before = worker.energy = 12
    assert charge(worker, "attack") == 10 and worker.energy == before - 10
    assert charge(worker, "step", times=3) == 3 and worker.energy == before - 13
    try:
        charge(worker, "teleport")
        raise AssertionError("an unknown action has no cost")
    except ValidationError:
        pass
    role = worker.role
    assert isinstance(role, RunnerRole), "a Runner always carries a RunnerRole"
    assert role.edge == 3 and spend_edge(worker, "push_the_limit", random.Random(1), pool=9) == 9
    assert role.edge == 2
    worker.energy = 0
    assert (
        spend_edge(worker, "seize_the_initiative", random.Random(1)) == 10 and worker.energy == 10
    )
    assert role.qi == 4 and spend_qi(worker, "improved_reflexes") == 2 and role.qi == 2
    assert spend_qi(worker, "improved_reflexes") == 2 and role.qi == 0
    assert spend_qi(worker, "improved_reflexes") == 0, "Qi runs out"
    assert sustain_penalty(2) == -4
    try:
        sustain_penalty(3)
        raise AssertionError("at most two spells may be sustained")
    except ValidationError:
        pass

    # ---- 8. a full exchange, resolved in the order §4 says ------------------------------
    attacker = someone(actor_id=1, agility=5)
    attacker.skills["firearms"] = 4
    defender = someone(actor_id=2, body=4, reaction=4, intuition=3)
    outcome = resolve_attack(attacker, defender, "heavy_pistol", random.Random(5), armour=6)
    assert outcome.base_dv == 5 and outcome.modified_dv == 5 + outcome.net
    assert outcome.final_dv == max(0, outcome.modified_dv - outcome.soaked)
    assert outcome.applied is not None or outcome.final_dv == 0
    assert outcome.code in ("P", "S")
    assert str(outcome.attack) and len(outcome.attack.dice) == 9, "AGI 5 + Firearms 4"
    # armour 6 with AP 1 means 9 soak dice: Body 4 + (6 - 1)
    assert soak_pool(defender, weapon_damage("heavy_pistol", 4), 6) == 9

    # ---- 9. the wound modifier closes the loop with entities ----------------------------
    hurt = someone(body=6, willpower=2)
    assert wound_modifier(hurt) == 0
    hurt.physical.filled = 2
    hurt.stun.filled = 1
    assert wound_modifier(hurt) == -1, "3 boxes across both tracks"
    hurt.physical.filled = 6
    assert wound_modifier(hurt) == -2

    print(
        f"OK  rules: classify (glitch boundary, critical), seeded rolls, opposed ties to the "
        f"defender, {len(WEAPONS)} weapons, armour {soak_pool(target, pistol, 6)} soak dice, "
        f"2:1 Stun overflow, Drain table + overcasting, Edge/Energy/Qi spends"
    )


if __name__ == "__main__":
    demo()

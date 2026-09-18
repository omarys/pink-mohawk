"""The actor and entity model: what takes turns, and what only gets acted upon.

`docs/design/data-model.md` §12 is the specification; `CONTEXT.md` names the five kinds of thing in
the world (Runner, enemy, Spirit, device, item) and §12 says how they relate.

**Only things that take turns are Actors.** That one rule decides every case: a Runner, an enemy, a
Spirit and a Security Drone are Actors (they have Energy and a place in the scheduler); a device, an
item and a corpse are `WorldObject`s — acted upon, never acting. A Drone is the interesting case and
it is *not* a subclass: it is an Actor whose `gear` happens to list its own chassis as a device, so
the Decker's hack is the same code path for a door and for a drone (ADR-0008).

What differs between a Runner, an enemy and a Spirit is a **role component** attached to `role`,
present only on the kinds that need it. Subclassing `Actor` four ways would duplicate the whole
combat/monitor/Energy model and put Spirit-only state on Runners; one `Entity` base holding
everything would force doors to carry a blackboard.

Layer 2: this module may import layers 0-1 (`constants`, `bt`, `utility`) and never the display.

    .venv/bin/python -m pinkmohawk.entities      # runs demo()
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any, Final

from .bt import BTState
from .constants import ATTRIBUTES, SKILLS, WOUND_PENALTY_PER_BOXES
from .errors import ValidationError
from .utility import Weights

type Coord = tuple[int, int]


def wound_modifier_from_boxes(physical: int, stun: int) -> int:
    """§4's wound modifier from filled boxes alone.

    Here rather than on `Actor` because two things need it and one of them has no Actor: a Runner at
    the Hub is a persisted sheet, and the Dialogue Graph's `pool_bonus` asks for this while nobody is
    spawned. It was a literal `// 3` in four places before the review, then one in `ai.py`, then here -
    so the number now has exactly one home and the reviewer's finding cannot come back as prose.
    """
    return -((physical + stun) // WOUND_PENALTY_PER_BOXES)


FACTIONS: Final = ("crew", "security", "spirit", "neutral")
CLASSES: Final = ("adept", "mage", "shaman", "decker")
SPIRIT_TYPES: Final = ("beast", "air", "earth", "water")
DEVICE_KINDS: Final = (
    "gun",
    "optics",
    "door",
    "lock",
    "lights",
    "commlink",
    "drone",
    "cyberware",
    "cyberdeck",
)  # the Decker carries one; DECISIONS §7 has no
# rating row for it because it is gear, not
# a fixture the Decker hacks
OBJECT_KINDS: Final = ("device", "item", "corpse")


def monitor_max(attribute: int) -> int:
    """§4: 8 + ceil(attribute / 2) boxes, for either monitor."""
    return 8 + -(-attribute // 2)


@dataclass(slots=True)
class Monitor:
    """One Condition Monitor (§4). `filled` counts boxes; the maximum comes from an attribute.

    The maximum is *not* stored here: it is a function of the owner's Body (Physical) or Willpower
    (Stun), and storing it would be a second copy of a number `attrs` already holds. Callers pass the
    attribute, or use `Actor.physical_max` / `Actor.stun_max`.
    """

    filled: int = 0

    def maximum(self, attribute: int) -> int:
        return monitor_max(attribute)

    def mark(self, boxes: int, attribute: int) -> int:
        """Add boxes, clamp at the maximum, and return the boxes that did not fit.

        Overflow is returned rather than applied: the Stun→Physical conversion is 2:1 (§4), which is
        a *resolution* rule and lives in `rules.py`, not in the box counter.
        """
        if boxes < 0:
            raise ValidationError([f"cannot mark {boxes} boxes"])
        headroom = self.maximum(attribute) - self.filled
        self.filled += min(boxes, headroom)
        return max(0, boxes - headroom)

    def is_full(self, attribute: int) -> bool:
        return self.filled >= self.maximum(attribute)

    def heal(self, boxes: int) -> None:
        self.filled = max(0, self.filled - boxes)


@dataclass(slots=True)
class Effect:
    """A timed condition (§6/§7): blinded, burning, hacked, sustaining, invisible, warded…"""

    kind: str
    until_round: int  # absolute Round number; §6 durations are "3 rounds"
    magnitude: int = 0


@dataclass(slots=True)
class ItemRef:
    """A carried item, by slug. Ids rather than objects so saves stay flat."""

    slug: str
    qty: int = 1


@dataclass(slots=True)
class DeviceRef:
    """A device the Decker can hack: an enemy's gun, a door, or a Drone's own chassis (§7)."""

    kind: str
    rating: int
    hacked_until: int = 0  # absolute Round
    disabled_until: int = 0  # absolute Round

    def __post_init__(self) -> None:
        if self.kind not in DEVICE_KINDS:
            raise ValidationError(
                [f"unknown device kind {self.kind!r}; known: {list(DEVICE_KINDS)}"]
            )


@dataclass(slots=True)
class RunnerRole:
    klass: str
    edge: int = 3  # §6
    qi: int = 0  # Physical Adept only, max 4
    tradition: str | None = None  # "logic" (Mage, Decker) or "charisma" (Shaman)
    inventory: list[ItemRef] = field(default_factory=list)
    xp: int = 0
    perks: list[str] = field(default_factory=list)
    sustaining: list[str] = field(default_factory=list)  # §6: −2 dice each, max 2

    def __post_init__(self) -> None:
        if self.klass not in CLASSES:
            raise ValidationError([f"unknown class {self.klass!r}; known: {list(CLASSES)}"])


@dataclass(slots=True)
class EnemyRole:
    archetype: str
    weights: Weights
    target_hysteresis: float
    home_pos: Coord
    flees_at_wound: int | None = None  # §8: Ganger −3; Hellhound and Drone never flee
    # Added while writing content: §12's EnemyRole had no tradition, but the Corp Mage pays Drain with
    # Logic (DECISIONS §6), so the caster archetypes need one.
    tradition: str | None = None


@dataclass(slots=True)
class SpiritRole:
    summoner_id: int
    spirit_type: str
    rounds_left: int = 3  # §7
    hostile: bool = False  # §7: a failed Conjuring or a Glitch sets this

    def __post_init__(self) -> None:
        if self.spirit_type not in SPIRIT_TYPES:
            raise ValidationError([f"unknown spirit type {self.spirit_type!r}"])


@dataclass(slots=True)
class Blackboard:
    """The twelve typed keys of `ai.md` §5, and nothing else.

    A fixed struct rather than an open dictionary, for the reason the doc gives: a misspelled key
    should be an `AttributeError` while it is being written, not a silently absent value at runtime.
    `objective` is a Mission Graph node id (or `"hostile"` for a freed Spirit) — never a cell and
    never a dict, because the Utility Score resolves it to a room, and a non-string silently zeroes
    that term. Spirit commands live in `command_target` instead.

    It lives here rather than in `ai.py` because `Actor` carries one and `entities` is layer 2: the
    layer law forbids layer 2 importing layer 3, so the type has to sit at or below its owner.
    """

    target: int | None = None  # actor id
    last_known_pos: Coord | None = None
    home_pos: Coord | None = None
    cover_pos: Coord | None = None
    noise_pos: Coord | None = None
    alert_level: int = 0  # 0 Calm / 1 Alert / 2 Lockdown
    morale: int = 0
    objective: str | None = None  # Mission Graph node id, or "hostile"
    pacified: bool = False  # written only by dialogue
    command_target: Coord | int | None = None  # written only by a player command
    summoner_id: int | None = None  # Spirits only
    rounds_bound: int | None = None  # Spirits only


@dataclass(slots=True)
class Actor:
    """Something that takes turns (§5, §8). Composition, not inheritance."""

    id: int
    name: str
    faction: str
    pos: Coord
    facing: int  # 0..7, one of the eight directions
    glyph: int  # the ONE codepoint drawn in this cell (ADR-0004)
    tint: tuple[int, int, int]
    attrs: dict[str, int]
    skills: dict[str, int]
    physical: Monitor
    stun: Monitor
    cover: int = 0  # §4: +2 while in cover
    effects: list[Effect] = field(default_factory=list)
    score: int = 0  # §5: Initiative Score for the current Round
    energy: int = 0  # §5: Energy left in the current Pass
    pass_no: int = 0
    improved_reflexes_dice: int = 0
    gear: list[DeviceRef] = field(default_factory=list)
    role: RunnerRole | EnemyRole | SpiritRole | None = None
    bt: BTState | None = None  # None <=> player-controlled (the four Runners)
    bb: Blackboard | None = None  # the twelve typed keys of ai.md §5
    visible: bytearray | None = None  # per-actor FOV (DECISIONS §8, resolved item 33)

    def __post_init__(self) -> None:
        if self.faction not in FACTIONS:
            raise ValidationError([f"unknown faction {self.faction!r}; known: {list(FACTIONS)}"])
        if not 0 <= self.facing <= 7:
            raise ValidationError([f"facing must be 0..7, got {self.facing}"])

    # -- derived values, so callers never re-derive the monitor maxima -------------------
    @property
    def physical_max(self) -> int:
        return monitor_max(self.attrs["body"])

    @property
    def stun_max(self) -> int:
        return monitor_max(self.attrs["willpower"])

    @property
    def downed(self) -> bool:
        """§4: filled Physical boxes reach the monitor maximum."""
        return self.physical.is_full(self.attrs["body"])

    @property
    def wound_modifier(self) -> int:
        """§4: −1 die per 3 filled boxes, counting both tracks together."""
        return wound_modifier_from_boxes(self.physical.filled, self.stun.filled)

    @property
    def is_player_controlled(self) -> bool:
        return self.bt is None

    def allocate_visibility(self, cells: int) -> bytearray:
        """Give this actor its own FOV buffer. The map's own array belongs to the renderer."""
        self.visible = bytearray(cells)
        return self.visible

    def has_effect(self, kind: str, round_no: int) -> bool:
        return any(e.kind == kind and e.until_round > round_no for e in self.effects)

    def expire_effects(self, round_no: int) -> list[Effect]:
        """Drop everything that has run out; return what was dropped, for the log."""
        done = [e for e in self.effects if e.until_round <= round_no]
        self.effects = [e for e in self.effects if e.until_round > round_no]
        return done


@dataclass(slots=True)
class WorldObject:
    """Never ticks: a hackable device, an item on the floor, or a corpse (a landmark, §9)."""

    id: int
    kind: str
    pos: Coord
    glyph: int
    tint: tuple[int, int, int]
    state: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in OBJECT_KINDS:
            raise ValidationError(
                [f"unknown object kind {self.kind!r}; known: {list(OBJECT_KINDS)}"]
            )


class Occupancy:
    """`dict[cell, actor_id]`, maintained beside the actor list (§12).

    Makes "who is in this cell?" O(1) instead of a scan over 48 actors — bump-to-attack, Spirit
    conjuring and hacking range all ask that question. A derived cache: rebuilt on move, never saved.
    """

    __slots__ = ("_cells",)

    def __init__(self) -> None:
        self._cells: dict[Coord, int] = {}

    def put(self, actor: Actor) -> None:
        occupant = self._cells.get(actor.pos)
        if occupant is not None and occupant != actor.id:
            raise ValidationError([f"cell {actor.pos} already holds actor {occupant}"])
        self._cells[actor.pos] = actor.id

    def move(self, actor: Actor, to: Coord) -> None:
        self._cells.pop(actor.pos, None)
        self._cells[to] = actor.id
        actor.pos = to

    def remove(self, actor: Actor) -> None:
        self._cells.pop(actor.pos, None)

    def at(self, cell: Coord) -> int | None:
        return self._cells.get(cell)

    def __contains__(self, cell: object) -> bool:
        return cell in self._cells

    def __len__(self) -> int:
        return len(self._cells)


# ==============================================================================================
# Acceptance test
# ==============================================================================================
def demo() -> None:
    from .fov import compute_fov_into
    from .grid import TileMap

    def runner(aid: int = 1, klass: str = "adept", **kw: Any) -> Actor:
        base: dict[str, Any] = dict(
            id=aid,
            name=klass,
            faction="crew",
            pos=(2, 2),
            facing=0,
            glyph=0xE000,
            tint=(255, 255, 255),
            attrs=dict.fromkeys(ATTRIBUTES, 3),
            skills=dict.fromkeys(SKILLS, 3),
            physical=Monitor(),
            stun=Monitor(),
            role=RunnerRole(klass=klass, qi=4 if klass == "adept" else 0),
        )
        base.update(kw)  # a test can override any field, faction included
        return Actor(**base)

    # ---- 1. monitor arithmetic: 8 + ceil(attr/2), and overflow is returned not applied ----
    for attribute, want in ((1, 9), (2, 9), (3, 10), (4, 10), (6, 11), (7, 12)):
        assert monitor_max(attribute) == want, (attribute, monitor_max(attribute), want)
    m = Monitor()
    assert m.mark(4, 6) == 0 and m.filled == 4
    assert m.mark(99, 6) == 99 - (11 - 4), "the boxes past the maximum are the overflow"
    assert m.filled == 11 and m.is_full(6)
    assert m.mark(3, 6) == 3, "a full monitor overflows everything further"
    m.heal(4)
    assert m.filled == 7 and not m.is_full(6)
    try:
        m.mark(-1, 6)
        raise AssertionError("negative boxes must be refused")
    except ValidationError:
        pass

    # ---- 2. composition: the same class serves a Runner, an enemy and a Spirit ----------
    adept = runner()
    assert adept.bt is None and adept.is_player_controlled, "the player drives the Runners"
    assert isinstance(adept.role, RunnerRole) and adept.role.klass == "adept" and adept.role.qi == 4
    assert adept.role.tradition is None
    assert adept.physical_max == monitor_max(3) == 10 and adept.stun_max == 10
    assert adept.wound_modifier == 0
    adept.physical.filled = 3
    assert adept.wound_modifier == -1, "−1 die per 3 boxes across both tracks"
    adept.physical.filled = 10
    assert adept.downed, "filled Physical boxes reaching the maximum is Downed"

    guard = Actor(
        id=20,
        name="guard",
        faction="security",
        pos=(9, 9),
        facing=4,
        glyph=0xE010,
        tint=(200, 60, 60),
        attrs=dict.fromkeys(ATTRIBUTES, 4),
        skills=dict.fromkeys(SKILLS, 3),
        physical=Monitor(),
        stun=Monitor(),
        role=EnemyRole(
            archetype="corp_guard",
            weights=Weights.for_archetype("corp_guard"),
            target_hysteresis=0.10,
            home_pos=(9, 9),
            flees_at_wound=-4,
        ),
        bt=BTState(),
    )
    assert guard.bt is not None and not guard.is_player_controlled
    assert isinstance(guard.role, EnemyRole) and guard.role.archetype == "corp_guard"

    spirit = Actor(
        id=30,
        name="beast",
        faction="spirit",
        pos=(3, 3),
        facing=0,
        glyph=0xE020,
        tint=(120, 220, 160),
        attrs=dict.fromkeys(ATTRIBUTES, 3),
        skills=dict.fromkeys(SKILLS, 3),
        physical=Monitor(),
        stun=Monitor(),
        role=SpiritRole(summoner_id=adept.id, spirit_type="beast", rounds_left=3),
        bt=BTState(),
    )
    assert isinstance(spirit.role, SpiritRole)
    assert spirit.role.summoner_id == adept.id and spirit.role.rounds_left == 3
    assert spirit.role.hostile is False, "a summoned Spirit starts friendly"
    spirit.role.hostile = True
    assert spirit.role.hostile, "a failed Conjuring flips it (rules set this)"

    # ---- 3. the Drone: an Actor AND hackable, with no special class ---------------------
    drone = Actor(
        id=40,
        name="drone",
        faction="security",
        pos=(7, 7),
        facing=0,
        glyph=0xE030,
        tint=(180, 180, 200),
        attrs=dict.fromkeys(ATTRIBUTES, 4),
        skills=dict.fromkeys(SKILLS, 3),
        physical=Monitor(),
        stun=Monitor(),
        gear=[DeviceRef("drone", 4), DeviceRef("gun", 2)],
        role=EnemyRole(
            archetype="security_drone",
            weights=Weights.for_archetype("security_drone"),
            target_hysteresis=0.15,
            home_pos=(7, 7),
            flees_at_wound=None,
        ),
        bt=BTState(),
    )
    assert isinstance(drone, Actor) and len(drone.gear) == 2
    assert drone.gear[0].rating == 4, "its own chassis is just another device in gear"
    assert isinstance(drone.role, EnemyRole), "a drone is driven by an enemy brain"
    assert drone.role.flees_at_wound is None, "a machine has no morale branch"

    # ---- 4. the Blackboard is twelve typed keys, not a dictionary ------------------------
    bb = Blackboard()
    typed = {f.name for f in fields(Blackboard)}
    assert typed == {
        "target",
        "last_known_pos",
        "home_pos",
        "cover_pos",
        "noise_pos",
        "alert_level",
        "morale",
        "objective",
        "pacified",
        "command_target",
        "summoner_id",
        "rounds_bound",
    }, sorted(typed)
    assert len(typed) == 12
    bb.objective = "vault"
    assert bb.objective == "vault"
    try:
        bb.objctive = "typo"  # type: ignore[attr-defined]
        raise AssertionError("a misspelled key must not silently succeed")
    except AttributeError:
        pass
    guard.bb = bb
    assert guard.bb.alert_level == 0 and guard.bb.pacified is False

    # ---- 5. WorldObjects never tick ------------------------------------------------------
    door = WorldObject(
        id=50,
        kind="device",
        pos=(5, 5),
        glyph=0xE040,
        tint=(160, 160, 120),
        state={"rating": 3, "hacked_until": 0, "disabled_until": 0},
    )
    assert not isinstance(door, Actor)
    assert door.state["rating"] == 3
    try:
        WorldObject(id=51, kind="portal", pos=(0, 0), glyph=0, tint=(0, 0, 0))
        raise AssertionError("an unknown object kind must be refused")
    except ValidationError:
        pass

    # ---- 5. validation at construction ---------------------------------------------------
    for bad in ({"faction": "goblins"}, {"facing": 9}):
        try:
            runner(**bad)
            raise AssertionError(f"expected refusal for {bad}")
        except ValidationError:
            pass
    try:
        RunnerRole(klass="street_samurai")
        raise AssertionError("the Street Samurai is not a class (ADR-0002)")
    except ValidationError:
        pass
    try:
        DeviceRef("portal", 5)
        raise AssertionError("unknown device kind must be refused")
    except ValidationError:
        pass

    # ---- 6. per-actor visibility: its own buffer, the map's array untouched -------------
    m60 = TileMap(60, 60)
    m60.fill(1)
    guard_buf = guard.allocate_visibility(m60.w * m60.h)
    spirit_buf = spirit.allocate_visibility(m60.w * m60.h)
    for actor in (adept, drone):
        actor.allocate_visibility(m60.w * m60.h)
    # Two actors, two buffers, same answer - from interior cells. A corner sees LESS: the border
    # rule clips the disc, which is why this compares origins rather than actors' positions.
    interior_guard = compute_fov_into(m60, guard_buf, 20, 20, 8)
    interior_spirit = compute_fov_into(m60, spirit_buf, 30, 30, 8)
    assert interior_guard == interior_spirit == 197, "an interior cell sees the whole disc"
    assert compute_fov_into(m60, spirit_buf, *spirit.pos, 8) < 197, (
        "the Spirit stands at (3, 3), so its disc is clipped by the map edge"
    )
    assert guard_buf is not spirit_buf, "each actor owns its own buffer"
    assert not any(m60.visible), "the map's own array belongs to the renderer"

    # ---- 7. the occupancy index ---------------------------------------------------------
    occ = Occupancy()
    for actor in (adept, guard, spirit, drone):
        occ.put(actor)
    assert len(occ) == 4 and (2, 2) in occ and occ.at((2, 2)) == adept.id
    occ.move(adept, (2, 3))
    assert occ.at((2, 2)) is None, "the old cell must no longer resolve"
    assert occ.at((2, 3)) == adept.id and adept.pos == (2, 3), "move updates the actor's pos too"
    occ.remove(guard)
    assert occ.at((9, 9)) is None and len(occ) == 3
    clash = runner(aid=99)
    clash.pos = (2, 3)
    try:
        occ.put(clash)
        raise AssertionError("two actors in one cell must be refused")
    except ValidationError:
        pass

    # ---- 8. effects expire by Round, and the query is honest about the Round ------------
    adept.effects.append(Effect("invisible", until_round=5, magnitude=3))
    assert adept.has_effect("invisible", 4) and not adept.has_effect("invisible", 5)
    assert adept.expire_effects(5)[0].kind == "invisible" and adept.effects == []

    print(
        f"OK  entities: Monitor 8+ceil(attr/2), {len(CLASSES)} classes, role composition "
        f"({type(guard.role).__name__}, {type(spirit.role).__name__}), Drone as Actor+gear, "
        f"occupancy O(1), per-actor visibility separate from the map"
    )


if __name__ == "__main__":
    demo()

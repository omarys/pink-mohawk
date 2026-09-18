"""Brains: perception, the Blackboard, the condition and action catalogues, and leaf dispatch.

`docs/design/ai.md` is the specification — §3.1's Pass loop, §5's twelve Blackboard keys and their
writers, §6's Utility Score, §7's action catalogue with its prerequisites, §8's condition catalogue.
`bt.py` owns the tree *shape* and the tick; this module owns what the leaves mean.

Layer 3: imports `bt` and `utility` (layer 1), `rules` and `entities` (layer 2). Nothing here imports
the display, and nothing here is imported by them.

THE THREE IDEAS THAT SHAPED THIS FILE
------------------------------------
**Perception writes, conditions only read.** `refresh()` is the single writer of `target`,
`last_known_pos`, `noise_pos`, `morale`, the alert floor and `cover_pos`. Every condition is a pure
predicate over the Blackboard and the world (ai.md §8), so a tree cannot change the world merely by
asking about it.

**An actor sees through its own eyes.** `refresh` fills the actor's own `visible` buffer with
`fov.compute_fov_into` (DECISIONS §8.33) — the map's array stays the renderer's — and `can_see_target`
asks that buffer *and* a line of sight, because §8 requires both.

**A leaf either declares a cost or is free, never in between.** Actions go through `rules.charge`, so
the Energy accounting has exactly one owner (decision 25); a prerequisite that is not met returns
FAILURE at zero cost, which is what keeps a Sequence falling through cleanly.

    .venv/bin/python -m pinkmohawk.ai      # runs demo()
"""

from __future__ import annotations

import random
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from .bt import BTState, Status, TickContext, Tree, load, tick
from .constants import (
    ARCHETYPE_WEIGHTS,
    ENERGY_COSTS,
    FOV_RADIUS,
    FOV_RADIUS_DARK,
    MAGAZINES,
    NOISE_RADIUS,
    SPELL_RANGE,
    SPIRIT_ATTACKS,
    WEAPONS,
)
from .entities import Actor, Effect, EnemyRole, RunnerRole, SpiritRole
from .errors import ValidationError
from .fov import compute_fov_into, has_los, line_cells
from .grid import TileMap
from .pathfinding import a_star, chebyshev, step_toward
from .rules import (
    Damage,
    apply_damage,
    damage_type,
    drain_value,
    opposed,
    resist_drain,
    roll,
    weapon_damage,
)
from .security import Clock
from .utility import CandidateFacts, Weights, choose

type Cell = tuple[int, int]


@dataclass(slots=True)
class World:
    """Everything a brain may look at. A plain struct, so a test can build one in three lines.

    `armour`, `ammo` and `patrols` are keyed by actor id because the loadout and spawn data that
    produce them (enemies.md stat blocks, world.md §7 placement) arrive with content, not with the
    brain. A missing key is a legitimate absence — no armour, an empty magazine, no patrol ring.
    """

    map: TileMap
    actors: list[Actor]
    clock: Clock
    rng: random.Random  # the rules.combat stream
    round_no: int = 0
    objective_rooms: dict[str, Cell] = field(default_factory=dict)  # node id -> room centre
    armour: dict[int, int] = field(default_factory=dict)
    ammo: dict[tuple[int, str], int] = field(default_factory=dict)
    patrols: dict[int, list[Cell]] = field(default_factory=dict)
    patrol_index: dict[int, int] = field(default_factory=dict)
    dark_cells: set[Cell] = field(default_factory=set)  # lights hacked off
    exit_cell: Cell | None = None

    # -- small queries the catalogues keep asking ------------------------------------------
    def by_id(self, actor_id: int | None) -> Actor | None:
        if actor_id is None:
            return None
        return next((a for a in self.actors if a.id == actor_id), None)

    def living(self, *, faction: str | None = None) -> list[Actor]:
        return [
            a for a in self.actors if not a.downed and (faction is None or a.faction == faction)
        ]

    def occupants(self) -> dict[Cell, Actor]:
        return {a.pos: a for a in self.actors if not a.downed}


# ----------------------------------------------------------------------------------------------
# Perception: the single writer of the Blackboard
# ----------------------------------------------------------------------------------------------
def sight_radius(actor: Actor, world: World) -> int:
    """§7: hacked-off lights drop an *enemy's* sight to 2 cells. The Crew is unaffected."""
    return FOV_RADIUS_DARK if actor.pos in world.dark_cells else FOV_RADIUS


def sees(actor: Actor, other: Actor, world: World) -> bool:
    """§8's definition, both halves: in the actor's FOV **and** a clear line of sight."""
    if actor.visible is None or not actor.visible[world.map.idx(*other.pos)]:
        return False
    return has_los(world.map, actor.pos, other.pos)


def objective_value(actor: Actor, cell: Cell, world: World) -> float:
    """1.0 when the cell is inside the room named by the actor's `objective` node, else 0.0.

    The Blackboard key is a Mission Graph node id string (§5); a non-string there would silently
    zero this term, which is exactly why the key is typed.
    """
    if actor.bb is None or not isinstance(actor.bb.objective, str):
        return 0.0
    centre = world.objective_rooms.get(actor.bb.objective)
    if centre is None:
        return 0.0
    return 1.0 if chebyshev(cell, centre) <= 2 else 0.0


def ally_in_the_way(actor: Actor, target: Actor, world: World) -> bool:
    """DECISIONS §8.35: a living ally on the Bresenham firing line blocks the shot."""
    line = set(line_cells(actor.pos, target.pos)[1:-1])
    return any(
        a.faction == actor.faction and a.id != actor.id and a.pos in line for a in world.living()
    )


def candidate_facts(actor: Actor, other: Actor, world: World) -> CandidateFacts:
    """Measure one candidate. `utility.py` does the arithmetic; this does the looking."""
    return CandidateFacts(
        distance=chebyshev(actor.pos, other.pos),
        visible=sees(actor, other, world),
        objective_value=objective_value(actor, other.pos, world),
        allied_fire_risk=1.0 if ally_in_the_way(actor, other, world) else 0.0,
        reaction=other.attrs["reaction"],
    )


def weights_for(actor: Actor) -> Weights:
    """An enemy reads its own block; a Spirit uses the `spirit` block, having no EnemyRole."""
    if isinstance(actor.role, EnemyRole):
        return actor.role.weights
    if isinstance(actor.role, SpiritRole):
        return Weights.for_archetype("spirit")
    raise ValidationError([f"actor {actor.id} has no brain and no weight block"])


def morale(actor: Actor, world: World) -> int:
    """§8: `wound_modifier + morale_bonus − allies_downed`, recomputed every decision step."""
    bonus = 0
    if isinstance(actor.role, EnemyRole):
        bonus = ARCHETYPE_WEIGHTS[actor.role.archetype]["morale_bonus"] or 0
    allies_down = sum(
        1 for a in world.actors if a.faction == actor.faction and a.id != actor.id and a.downed
    )
    wounds = -((actor.physical.filled + actor.stun.filled) // 3)
    return wounds + bonus - allies_down


def effect_magnitude(actor: Actor, kind: str, round_no: int) -> int:
    return max(
        (e.magnitude for e in actor.effects if e.kind == kind and e.until_round > round_no),
        default=0,
    )


def refresh(actor: Actor, world: World) -> None:
    """Look, then decide. The only function that writes the soft half of the Blackboard.

    Order matters: the buffer is filled first (everything else reads it), then the target is chosen,
    then the facts that depend on the target are derived. Cover is cleared *after* the target is
    known, because whether a cell gives cover is measured against that target.
    """
    bb = _bb(actor)

    # senses
    if actor.visible is None:
        actor.allocate_visibility(world.map.w * world.map.h)
    assert actor.visible is not None
    compute_fov_into(world.map, actor.visible, *actor.pos, sight_radius(actor, world))

    # morale and the site's alert floor (§5: the floor is raised for every actor, never lowered)
    bb.morale = morale(actor, world)
    bb.alert_level = max(bb.alert_level, world.clock.alert_level)

    # the pin wins outright (§9.6); otherwise the Utility Score decides
    if bb.command_target is not None and isinstance(bb.command_target, int):
        bb.target = bb.command_target
    else:
        candidates = [
            (other.id, candidate_facts(actor, other, world))
            for other in world.living()
            if other.faction != actor.faction and other.pos
        ]
        incumbent = bb.target
        bb.target = choose(weights_for(actor), candidates, incumbent=incumbent)

    # what the target implies
    target = world.by_id(bb.target)
    if target is not None and sees(actor, target, world):
        bb.last_known_pos = target.pos
        if bb.alert_level < 1 and target.faction == "crew":
            bb.alert_level = 1  # §5: raised on the first sighting of a Runner
    if bb.cover_pos is not None and (
        target is None or has_los(world.map, bb.cover_pos, target.pos)
    ):
        bb.cover_pos = None  # §5: cover only counts against the current target


def broadcast(world: World, cell: Cell, event: str) -> int:
    """A loud event tells everyone in earshot where it happened (§5, DECISIONS §8.34).

    Returns how many actors heard it, which is the number worth logging: "nobody came" and
    "everybody came" are different bugs.
    """
    heard = 0
    for actor in world.living():
        if actor.bb is not None and chebyshev(actor.pos, cell) <= NOISE_RADIUS:
            actor.bb.noise_pos = cell
            heard += 1
    return heard


# ----------------------------------------------------------------------------------------------
# §7 actions. Each returns a Status and declares its cost through the context.
# ----------------------------------------------------------------------------------------------
def step_on_map(
    world: World, actor: Actor, toward: Cell, ctx: TickContext, *, sprint: bool = False
) -> Status:
    """One Step toward `toward`, or SUCCESS when already there, or FAILURE when unreachable."""
    if actor.pos == toward:
        return Status.SUCCESS
    if world.map.is_wall(*toward):
        return Status.FAILURE
    nxt = step_toward(world.map, actor.pos, toward)
    if nxt is None:
        return Status.FAILURE
    facing = _facing(actor.pos, nxt)
    ctx.charge("sprint_per_3_tiles" if sprint else "step")
    actor.pos = nxt
    actor.facing = facing
    return Status.SUCCESS if nxt == toward else Status.RUNNING


def _facing(old: Cell, new: Cell) -> int:
    """One of the eight directions, as an index into pathfinding.DIRECTIONS' first eight entries."""
    from .pathfinding import DIRECTIONS

    delta = (new[0] - old[0], new[1] - old[1])
    return DIRECTIONS.index(delta) if delta in DIRECTIONS else 0


def _nearest_cover(actor: Actor, world: World) -> Cell | None:
    """DECISIONS §8.36: nearest reachable cell that breaks LOS from the target, ties by (y, x)."""
    target = world.by_id(actor.bb.target if actor.bb else None)
    if target is None:
        return None
    best: Cell | None = None
    best_key: tuple[int, int, int] | None = None
    for y in range(world.map.h):
        for x in range(world.map.w):
            cell = (x, y)
            if world.map.is_wall(x, y) or has_los(world.map, cell, target.pos):
                continue
            distance = chebyshev(actor.pos, cell)
            if best_key is not None and (distance, y, x) >= best_key:
                continue
            if a_star(world.map, actor.pos, cell) is None:
                continue
            best, best_key = cell, (distance, y, x)
    return best


# ----------------------------------------------------------------------------------------------
# The catalogues: declared args (for the loader) and handlers
# ----------------------------------------------------------------------------------------------
CONDITION_ARGS: Final[dict[str, frozenset[str]]] = {
    "has_target": frozenset(),
    "can_see_target": frozenset(),
    "in_weapon_range": frozenset({"weapon"}),
    "in_melee_range": frozenset(),
    "not_blocked_by_ally": frozenset(),
    "has_cover_available": frozenset(),
    "at_cover": frozenset(),
    "has_last_known_pos": frozenset(),
    "low_morale": frozenset(),
    "wound_modifier_at_most": frozenset({"value"}),
    "noise_heard": frozenset(),
    "at_home": frozenset(),
    "alert_below": frozenset({"level"}),
    "ammo_empty": frozenset(),
    "is_prone": frozenset(),
    "spirit_type_is": frozenset({"type"}),
    "objective_is": frozenset({"value"}),
    "enemy_spell_active": frozenset(),
    "pacified": frozenset(),
}

ACTION_ARGS: Final[dict[str, frozenset[str]]] = {
    "patrol": frozenset(),
    "move_to_blackboard": frozenset({"key"}),
    "move_to_adjacent": frozenset({"key"}),
    "flank_target": frozenset(),
    "track_by_scent": frozenset(),
    "retreat": frozenset({"dest"}),
    "follow_summoner": frozenset(),
    "seek_cover": frozenset(),
    "take_cover": frozenset(),
    "attack_target": frozenset({"weapon"}),
    "use_power": frozenset({"power", "force"}),
    "aim": frozenset(),
    "reload": frozenset(),
    "call_backup": frozenset(),
    "use_item": frozenset({"item"}),
    "stand_up": frozenset(),
}


def check_has_target(actor: Actor, args: Mapping[str, Any], world: World) -> bool:
    return _bb(actor).target is not None


def check_can_see_target(actor: Actor, args: Mapping[str, Any], world: World) -> bool:
    target = world.by_id(_bb(actor).target)
    return target is not None and sees(actor, target, world)


def check_in_weapon_range(actor: Actor, args: Mapping[str, Any], world: World) -> bool:
    from .constants import WEAPONS

    target = world.by_id(_bb(actor).target)
    weapon = args.get("weapon")
    if target is None or weapon not in WEAPONS:
        return False
    return chebyshev(actor.pos, target.pos) <= WEAPONS[weapon][3]


def check_in_melee_range(actor: Actor, args: Mapping[str, Any], world: World) -> bool:
    target = world.by_id(_bb(actor).target)
    return target is not None and chebyshev(actor.pos, target.pos) == 1


def check_not_blocked_by_ally(actor: Actor, args: Mapping[str, Any], world: World) -> bool:
    target = world.by_id(_bb(actor).target)
    return target is not None and not ally_in_the_way(actor, target, world)


def check_has_cover_available(actor: Actor, args: Mapping[str, Any], world: World) -> bool:
    return _nearest_cover(actor, world) is not None


def check_at_cover(actor: Actor, args: Mapping[str, Any], world: World) -> bool:
    return _bb(actor).cover_pos == actor.pos


def check_has_last_known_pos(actor: Actor, args: Mapping[str, Any], world: World) -> bool:
    return _bb(actor).last_known_pos is not None


def check_low_morale(actor: Actor, args: Mapping[str, Any], world: World) -> bool:
    if not isinstance(actor.role, EnemyRole) or actor.role.flees_at_wound is None:
        return False  # a machine has no morale branch at all
    return _bb(actor).morale <= actor.role.flees_at_wound


def check_wound_modifier_at_most(actor: Actor, args: Mapping[str, Any], world: World) -> bool:
    wounds = -((actor.physical.filled + actor.stun.filled) // 3)
    return wounds <= int(args["value"])


def check_noise_heard(actor: Actor, args: Mapping[str, Any], world: World) -> bool:
    return _bb(actor).noise_pos is not None


def check_at_home(actor: Actor, args: Mapping[str, Any], world: World) -> bool:
    home = _bb(actor).home_pos
    return home is not None and actor.pos == home


def check_alert_below(actor: Actor, args: Mapping[str, Any], world: World) -> bool:
    return _bb(actor).alert_level < int(args["level"])


def check_ammo_empty(actor: Actor, args: Mapping[str, Any], world: World) -> bool:
    return any(v == 0 for (aid, _w), v in world.ammo.items() if aid == actor.id)


def check_is_prone(actor: Actor, args: Mapping[str, Any], world: World) -> bool:
    return actor.has_effect("prone", world.round_no)


def check_spirit_type_is(actor: Actor, args: Mapping[str, Any], world: World) -> bool:
    return isinstance(actor.role, SpiritRole) and actor.role.spirit_type == args["type"]


def check_objective_is(actor: Actor, args: Mapping[str, Any], world: World) -> bool:
    return _bb(actor).objective == args["value"]


def check_enemy_spell_active(actor: Actor, args: Mapping[str, Any], world: World) -> bool:
    return any(
        isinstance(a.role, RunnerRole) and a.role.sustaining and sees(actor, a, world)
        for a in world.living(faction="crew")
    )


def check_pacified(actor: Actor, args: Mapping[str, Any], world: World) -> bool:
    return bool(_bb(actor).pacified)


CONDITION_HANDLERS: Final[dict[str, Callable[[Actor, Mapping[str, Any], World], bool]]] = {
    "has_target": check_has_target,
    "can_see_target": check_can_see_target,
    "in_weapon_range": check_in_weapon_range,
    "in_melee_range": check_in_melee_range,
    "not_blocked_by_ally": check_not_blocked_by_ally,
    "has_cover_available": check_has_cover_available,
    "at_cover": check_at_cover,
    "has_last_known_pos": check_has_last_known_pos,
    "low_morale": check_low_morale,
    "wound_modifier_at_most": check_wound_modifier_at_most,
    "noise_heard": check_noise_heard,
    "at_home": check_at_home,
    "alert_below": check_alert_below,
    "ammo_empty": check_ammo_empty,
    "is_prone": check_is_prone,
    "spirit_type_is": check_spirit_type_is,
    "objective_is": check_objective_is,
    "enemy_spell_active": check_enemy_spell_active,
    "pacified": check_pacified,
}


def _bb(actor: Actor) -> Any:
    """The Blackboard, created on first use. A brain without one is a bug, not a state."""
    if actor.bb is None:
        from .entities import Blackboard

        actor.bb = Blackboard()
    return actor.bb


# ----------------------------------------------------------------------------------------------
# §7 action handlers
# ----------------------------------------------------------------------------------------------
def act_patrol(actor: Actor, args: Mapping[str, Any], ctx: TickContext, world: World) -> Status:
    ring = world.patrols.get(actor.id)
    if not ring:
        return Status.FAILURE
    index = world.patrol_index.get(actor.id, 0) % len(ring)
    status = step_on_map(world, actor, ring[index], ctx)
    if status is Status.SUCCESS:
        world.patrol_index[actor.id] = (index + 1) % len(ring)
    return Status.RUNNING if status is Status.SUCCESS else status


def act_move_to_blackboard(
    actor: Actor, args: Mapping[str, Any], ctx: TickContext, world: World
) -> Status:
    cell = getattr(_bb(actor), args["key"], None)
    if not isinstance(cell, tuple):
        return Status.FAILURE
    status = step_on_map(world, actor, cell, ctx, sprint=bool(args.get("sprint")))
    if status is Status.SUCCESS and actor.pos == cell and args["key"] == "noise_pos":
        _bb(actor).noise_pos = None  # §5: cleared when the actor reaches it
    return status


def act_move_to_adjacent(
    actor: Actor, args: Mapping[str, Any], ctx: TickContext, world: World
) -> Status:
    cell = getattr(_bb(actor), args["key"], None)
    if not isinstance(cell, tuple):
        return Status.FAILURE
    if chebyshev(actor.pos, cell) == 1:
        return Status.SUCCESS
    return step_on_map(world, actor, cell, ctx, sprint=bool(args.get("sprint")))


def act_flank_target(
    actor: Actor, args: Mapping[str, Any], ctx: TickContext, world: World
) -> Status:
    target = world.by_id(_bb(actor).target)
    if target is None:
        return Status.FAILURE
    occupied = world.occupants()
    options = [
        cell
        for cell in _neighbours(target.pos)
        if not world.map.is_wall(*cell) and cell not in occupied
    ]
    if not options:
        return Status.FAILURE
    options.sort(key=lambda c: (chebyshev(actor.pos, c), c[1], c[0]))
    return step_on_map(world, actor, options[0], ctx)


def act_track_by_scent(
    actor: Actor, args: Mapping[str, Any], ctx: TickContext, world: World
) -> Status:
    target = world.by_id(_bb(actor).target)
    if target is None:
        return Status.FAILURE
    _bb(actor).last_known_pos = target.pos  # walls do not break the trail
    return step_on_map(world, actor, target.pos, ctx)


def act_retreat(actor: Actor, args: Mapping[str, Any], ctx: TickContext, world: World) -> Status:
    dest = args.get("dest")
    if dest == "home" and _bb(actor).home_pos:
        return step_on_map(world, actor, _bb(actor).home_pos, ctx)
    if dest == "exit" and world.exit_cell:
        return step_on_map(world, actor, world.exit_cell, ctx)
    target = world.by_id(_bb(actor).target)
    if target is None:
        return Status.FAILURE
    options = [c for c in _neighbours(actor.pos) if not world.map.is_wall(*c)]
    if not options:
        return Status.FAILURE
    options.sort(key=lambda c: (-chebyshev(c, target.pos), c[1], c[0]))
    return step_on_map(world, actor, options[0], ctx)


def act_follow_summoner(
    actor: Actor, args: Mapping[str, Any], ctx: TickContext, world: World
) -> Status:
    summoner = world.by_id(_bb(actor).summoner_id)
    if summoner is None:
        return Status.FAILURE
    if chebyshev(actor.pos, summoner.pos) == 1:
        return Status.SUCCESS
    return step_on_map(world, actor, summoner.pos, ctx)


def act_seek_cover(actor: Actor, args: Mapping[str, Any], ctx: TickContext, world: World) -> Status:
    if _bb(actor).target is None:
        return Status.FAILURE
    cell = _nearest_cover(actor, world)
    if cell is None:
        return Status.FAILURE
    _bb(actor).cover_pos = cell
    return step_on_map(world, actor, cell, ctx)


def act_take_cover(actor: Actor, args: Mapping[str, Any], ctx: TickContext, world: World) -> Status:
    target = world.by_id(_bb(actor).target)
    if target is None or has_los(world.map, actor.pos, target.pos):
        return Status.FAILURE  # this cell is not cover against anyone here
    ctx.charge("take_cover")
    _bb(actor).cover_pos = actor.pos
    actor.cover = 2
    return Status.SUCCESS


def act_attack_target(
    actor: Actor, args: Mapping[str, Any], ctx: TickContext, world: World
) -> Status:
    from .rules import attack_pool, defence_pool, opposed

    target = world.by_id(_bb(actor).target)
    weapon = args.get("weapon")
    if (
        target is None
        or not isinstance(weapon, str)
        or (weapon not in WEAPONS and not any(a[0] == weapon for a in SPIRIT_ATTACKS.values()))
    ):
        return Status.FAILURE
    if _ammo_key(actor, weapon) in world.ammo and world.ammo[_ammo_key(actor, weapon)] <= 0:
        return Status.FAILURE  # prerequisites before Energy (ai.md §7)
    if not check_in_weapon_range(actor, {"weapon": weapon}, world):
        return Status.FAILURE
    if not check_not_blocked_by_ally(actor, {}, world):
        return Status.FAILURE
    ctx.charge("attack")
    damage = weapon_damage(weapon, actor.attrs["strength"])
    aim = effect_magnitude(actor, "aim", world.round_no)
    atk = roll(attack_pool(actor, weapon, aim=aim), world.rng)
    dfn = roll(defence_pool(target, cover=target.cover > 0), world.rng)
    net = opposed(atk, dfn).net
    armour = world.armour.get(target.id, 0)
    modified_armour = max(0, armour - damage.ap)
    # rules.damage_type, not a second copy of the P/S rule: one source for §4
    code = damage_type(Damage(damage.power + net, damage.code, damage.ap), modified_armour)
    soak = roll(target.attrs["body"] + modified_armour, world.rng).hits
    final = max(0, damage.power + net - soak)
    if final > 0:
        apply_damage(target, code, final)
    if _ammo_key(actor, weapon) in world.ammo:
        world.ammo[_ammo_key(actor, weapon)] -= 1
    world.clock.tick("gunfire")  # §9: gunfire is loud
    broadcast(world, actor.pos, "gunfire")
    for effect in [e for e in actor.effects if e.kind == "aim"]:
        actor.effects.remove(effect)  # aiming is spent on the shot
    return Status.SUCCESS


def power_manabolt(actor: Actor, args: Mapping[str, Any], ctx: TickContext, world: World) -> Status:
    """The Corp Mage's attack: direct combat magic (classes.md §4).

    Spell defence is Intuition + Willpower, and net hits add to the Force-scaled DV like any other
    attack. Drain is the caller's business (`act_use_power`): Drain is what casting *costs*, not what
    the spell does.
    """
    target = world.by_id(_bb(actor).target)
    force = int(args.get("force") or 0)
    if target is None or not 1 <= force <= 8:
        return Status.FAILURE
    if chebyshev(actor.pos, target.pos) > SPELL_RANGE or not has_los(
        world.map, actor.pos, target.pos
    ):
        return Status.FAILURE
    atk = roll(actor.attrs["logic"] + actor.skills["sorcery"], world.rng)
    dfn = roll(target.attrs["willpower"] + target.attrs["intuition"], world.rng)
    net = opposed(atk, dfn).net
    if net > 0:
        apply_damage(target, "P", force + net)
    if force >= 4:
        world.clock.tick("loud_spell")  # §9: a loud spell is worth 2 segments
        broadcast(world, actor.pos, "loud_spell")
    return Status.SUCCESS


#: The powers a brain may use in v1. The rest of the classes.md kits land with the Shaman and Decker
#: content passes; `act_use_power` refuses an unknown power rather than half-casting it.
POWER_HANDLERS: Final[
    dict[str, Callable[[Actor, Mapping[str, Any], TickContext, World], Status]]
] = {"manabolt": power_manabolt}


def act_use_power(actor: Actor, args: Mapping[str, Any], ctx: TickContext, world: World) -> Status:
    power = args.get("power")
    force = args.get("force")
    if not isinstance(power, str) or not isinstance(force, int):
        return Status.FAILURE
    tradition = getattr(actor.role, "tradition", None) or _tradition_of(actor)
    if tradition is None:
        return Status.FAILURE
    if not 1 <= force <= 8:
        return Status.FAILURE
    handler = POWER_HANDLERS.get(power)
    if handler is None:
        return Status.FAILURE  # unknown power: refuse, never half-cast
    ctx.charge("cast")
    drain = drain_value(power, force)
    resist_drain(actor, drain, world.rng, tradition=tradition, force=force)
    return handler(actor, args, ctx, world)


def act_aim(actor: Actor, args: Mapping[str, Any], ctx: TickContext, world: World) -> Status:
    stacks = effect_magnitude(actor, "aim", world.round_no)
    if stacks >= 2:
        return Status.FAILURE
    ctx.charge("aim")
    actor.effects.append(Effect("aim", world.round_no + 1, stacks + 1))
    return Status.SUCCESS


def act_reload(actor: Actor, args: Mapping[str, Any], ctx: TickContext, world: World) -> Status:
    for key, rounds in list(world.ammo.items()):
        if key[0] == actor.id and rounds < MAGAZINES.get(key[1], 0):
            ctx.charge("reload")
            world.ammo[key] = MAGAZINES[key[1]]
            return Status.SUCCESS
    return Status.FAILURE


def act_call_backup(
    actor: Actor, args: Mapping[str, Any], ctx: TickContext, world: World
) -> Status:
    bb = _bb(actor)
    if bb.alert_level < 1 or bb.alert_level >= 2:
        return Status.FAILURE
    if not any(d.kind == "commlink" for d in actor.gear):
        return Status.FAILURE
    ctx.charge("use_item")  # §7: call_backup costs Use item 5
    bb.alert_level = 2
    world.clock.tick("alarm_tripped")  # §9: the alarm is worth 2 segments
    return Status.SUCCESS


ITEM_EFFECTS: Final[dict[str, tuple[str, int]]] = {
    "medkit": ("heal", 3),
    "trauma_patch": ("heal", 5),
}


def act_use_item(actor: Actor, args: Mapping[str, Any], ctx: TickContext, world: World) -> Status:
    item = args.get("item")
    if not isinstance(item, str) or item not in ITEM_EFFECTS:
        return Status.FAILURE
    in_inventory = isinstance(actor.role, RunnerRole) and any(
        ref.slug == item for ref in actor.role.inventory
    )
    if not in_inventory:
        return Status.FAILURE
    ctx.charge("use_item")
    kind, amount = ITEM_EFFECTS[item]
    if kind == "heal":
        actor.physical.heal(amount)
        actor.stun.heal(amount)
    return Status.SUCCESS


def act_stand_up(actor: Actor, args: Mapping[str, Any], ctx: TickContext, world: World) -> Status:
    if not actor.has_effect("prone", world.round_no):
        return Status.FAILURE
    ctx.charge("stand_up")
    actor.effects = [e for e in actor.effects if e.kind != "prone"]
    return Status.SUCCESS


ACTION_HANDLERS: Final[
    dict[str, Callable[[Actor, Mapping[str, Any], TickContext, World], Status]]
] = {
    "patrol": act_patrol,
    "move_to_blackboard": act_move_to_blackboard,
    "move_to_adjacent": act_move_to_adjacent,
    "flank_target": act_flank_target,
    "track_by_scent": act_track_by_scent,
    "retreat": act_retreat,
    "follow_summoner": act_follow_summoner,
    "seek_cover": act_seek_cover,
    "take_cover": act_take_cover,
    "attack_target": act_attack_target,
    "use_power": act_use_power,
    "aim": act_aim,
    "reload": act_reload,
    "call_backup": act_call_backup,
    "use_item": act_use_item,
    "stand_up": act_stand_up,
}


def _ammo_key(actor: Actor, weapon: str) -> tuple[int, str]:
    """A magazine belongs to one actor and one weapon: the key the World's ammo table uses."""
    return (actor.id, weapon)


def _neighbours(cell: Cell) -> list[Cell]:
    from .pathfinding import DIRECTIONS

    return [(cell[0] + dx, cell[1] + dy) for dx, dy in DIRECTIONS]


def _tradition_of(actor: Actor) -> str | None:
    """A caster's tradition decides which attribute resists Drain (§6)."""
    if isinstance(actor.role, RunnerRole):
        return actor.role.tradition
    if isinstance(actor.role, EnemyRole):
        return "mage" if actor.role.archetype == "corp_mage" else None
    if isinstance(actor.role, SpiritRole):
        return None
    return None


def make_eval_leaf(
    actor: Actor, world: World
) -> Callable[[str, Mapping[str, Any], TickContext], Status]:
    """The callback `bt.tick` calls. One namespace, two catalogues: a name is a condition or an action.

    A name in neither is a load error (`bt.load` is given both catalogues), so reaching this point with
    an unknown name means the tree was never validated — hence the raised error rather than a FAILURE.
    """

    def eval_leaf(name: str, args: Mapping[str, Any], ctx: TickContext) -> Status:
        check = CONDITION_HANDLERS.get(name)
        if check is not None:
            return Status.SUCCESS if check(actor, args, world) else Status.FAILURE
        handler = ACTION_HANDLERS.get(name)
        if handler is None:
            raise ValidationError([f"leaf {name!r} is in neither catalogue"])
        return handler(actor, args, ctx, world)

    return eval_leaf


def load_trees(documents: list[Mapping[str, Any]]) -> dict[str, Tree]:
    """Validate every tree document against both catalogues, keyed by tree id (ai.md §2)."""
    trees: dict[str, Tree] = {}
    for document in documents:
        tree = load(document, known_actions=ACTION_ARGS, known_checks=CONDITION_ARGS)
        if tree.id in trees:
            raise ValidationError([f"duplicate tree id {tree.id!r}"])
        trees[tree.id] = tree
    return trees


# ==============================================================================================
# Acceptance test
# ==============================================================================================
def demo() -> None:
    from .constants import ATTRIBUTES, SKILLS
    from .entities import Blackboard, DeviceRef, Monitor
    from .grid import TileMap

    def make(
        actor_id: int,
        faction: str,
        pos: Cell,
        archetype: str | None = None,
        klass: str | None = None,
    ) -> Actor:
        attrs = dict.fromkeys(ATTRIBUTES, 4)
        attrs["reaction"], attrs["intuition"], attrs["agility"] = 4, 4, 4
        role: Any = None
        if archetype:
            role = EnemyRole(
                archetype=archetype,
                weights=Weights.for_archetype(archetype),
                target_hysteresis=0.10,
                home_pos=pos,
                flees_at_wound=-4,
            )
        elif klass:
            role = RunnerRole(klass=klass, edge=3)
        return Actor(
            id=actor_id,
            name=f"{faction}{actor_id}",
            faction=faction,
            pos=pos,
            facing=0,
            glyph=0,
            tint=(0, 0, 0),
            attrs=attrs,
            skills=dict.fromkeys(SKILLS, 3),
            physical=Monitor(),
            stun=Monitor(),
            role=role,
            bt=BTState(),
            bb=Blackboard(),
            gear=[DeviceRef("commlink", 3), DeviceRef("gun", 2)],
        )

    def bb_of(actor: Actor) -> Blackboard:
        """Narrow once here, rather than asserting `actor.bb is not None` at a dozen call sites."""
        assert actor.bb is not None
        return actor.bb

    room = TileMap(30, 30)
    room.fill(1)
    guard = make(1, "security", (5, 5), archetype="corp_guard")
    runner = make(2, "crew", (9, 5), klass="adept")
    runner.bt = None  # player-controlled: no brain
    world = World(
        map=room,
        actors=[guard, runner],
        clock=Clock(),
        rng=random.Random(4),
        objective_rooms={"vault": (20, 20)},
        armour={2: 6},
        ammo={(1, "heavy_pistol"): 15},
    )
    for a in world.actors:
        a.allocate_visibility(room.w * room.h)

    # ---- 1. the catalogues match the document's lists ------------------------------------
    assert len(CONDITION_ARGS) == 19, len(CONDITION_ARGS)
    assert len(ACTION_ARGS) == 16, len(ACTION_ARGS)
    assert set(CONDITION_HANDLERS) == set(CONDITION_ARGS)
    assert set(ACTION_HANDLERS) == set(ACTION_ARGS)

    # ---- 2. refresh writes the Blackboard; conditions only read it ------------------------
    refresh(guard, world)
    assert bb_of(guard).alert_level == 1, "the first sighting of a Runner raises the alert"
    assert bb_of(guard).target == runner.id, "the only enemy in sight becomes the target"
    assert bb_of(guard).last_known_pos == runner.pos
    assert bb_of(guard).morale == 1, "the Corp Guard's morale_bonus is +1 in §8"
    assert sees(guard, runner, world) and check_can_see_target(guard, {}, world)
    assert check_has_target(guard, {}, world) and not check_low_morale(guard, {}, world)

    # a wall between them ends the sighting, and the alert floor stays up
    room.tiles[room.idx(7, 5)] = 0
    refresh(guard, world)
    assert not check_can_see_target(guard, {}, world), "LOS is required, not just FOV"
    assert bb_of(guard).alert_level == 1, "the site's floor never comes back down"

    # ---- 3. the Utility Score reaches through: the ally-shielded Runner loses ------------
    room.tiles[room.idx(7, 5)] = 1
    ally = make(3, "security", (7, 5), archetype="ganger")  # squarely in the firing line
    world.actors.append(ally)
    ally.allocate_visibility(room.w * room.h)
    assert ally_in_the_way(guard, runner, world), "the Ganger is on the Bresenham line"
    assert check_not_blocked_by_ally(guard, {}, world) is False
    assert candidate_facts(guard, runner, world).allied_fire_risk == 1.0
    assert candidate_facts(guard, ally, world).allied_fire_risk == 0.0, "no ally behind the ally"

    # ---- 4. an action: attack_target checks prerequisites, charges, and is loud -----------
    before_energy = guard.energy = 12
    clock_before = world.clock.segments
    assert (
        act_attack_target(guard, {"weapon": "heavy_pistol"}, TickContext(), world) is Status.FAILURE
    )
    assert guard.energy == before_energy, "an unmet prerequisite costs no Energy (ai.md §7)"
    world.actors.remove(ally)
    bb_of(guard).target = runner.id
    attack_ctx = TickContext()
    status = act_attack_target(guard, {"weapon": "heavy_pistol"}, attack_ctx, world)
    assert status is Status.SUCCESS
    assert attack_ctx.cost == ENERGY_COSTS["attack"], "the handler declares the cost"
    assert guard.energy == before_energy, (
        "and never touches Energy: the caller charges (decision 5)"
    )
    guard.energy -= attack_ctx.cost
    assert world.clock.segments == clock_before + 2, "gunfire ticks the Clock"
    assert world.ammo[(1, "heavy_pistol")] == 14, "a round leaves the magazine"
    assert runner.physical.filled + runner.stun.filled >= 0  # damage may or may not land

    # ---- 5. actions that move: one Step per decision step, RUNNING until arrival ---------
    guard.pos = (5, 5)
    bb_of(guard).noise_pos = (8, 5)
    ctx = TickContext()
    first = act_move_to_blackboard(guard, {"key": "noise_pos"}, ctx, world)
    assert first is Status.RUNNING and guard.pos == (6, 5), "one Step, not the whole path"
    assert ctx.cost == 1, "a Step costs 1 Energy"
    for _ in range(3):
        act_move_to_blackboard(guard, {"key": "noise_pos"}, TickContext(), world)
    assert guard.pos == (8, 5) and bb_of(guard).noise_pos is None, "arrival clears the noise"

    # ---- 6. patrol advances its ring only on arrival -------------------------------------
    world.patrols[guard.id] = [(5, 5), (5, 7)]
    assert act_patrol(guard, {}, TickContext(), world) is Status.RUNNING
    assert world.patrol_index.get(guard.id, 0) == 0, "not there yet, so the ring has not advanced"

    # ---- 7. cover: seek_cover writes a cell, take_cover arms it --------------------------
    room.tiles[room.idx(15, 5)] = 0  # a pillar to hide behind
    guard.pos, bb_of(guard).target, bb_of(guard).cover_pos = (14, 5), runner.id, None
    # §7: seek_cover writes cover_pos when it picks one, then RUNNINGs until it is standing there
    assert act_seek_cover(guard, {}, TickContext(), world) is Status.RUNNING, "it walks there"
    assert bb_of(guard).cover_pos is not None, "seek_cover records where it is going"
    cover = bb_of(guard).cover_pos
    assert cover is not None
    assert not has_los(room, cover, runner.pos), "the cell must break LOS"
    guard.pos = cover  # step behind the pillar first, then claim it
    bb_of(guard).cover_pos = guard.pos
    assert act_take_cover(guard, {}, TickContext(), world) is Status.SUCCESS and guard.cover == 2

    # ---- 8. call_backup: the commlink, the alert gate, and the alarm ---------------------
    bb_of(guard).alert_level = 1
    guard.energy = 12
    clock_before = world.clock.segments
    backup_ctx = TickContext()
    assert act_call_backup(guard, {}, backup_ctx, world) is Status.SUCCESS
    assert bb_of(guard).alert_level == 2
    assert backup_ctx.cost == ENERGY_COSTS["use_item"] and guard.energy == 12
    assert world.clock.segments == clock_before + 2, "the alarm is worth 2 segments"
    assert act_call_backup(guard, {}, TickContext(), world) is Status.FAILURE, "already at 2"

    # ---- 9. noise broadcast: everyone in earshot, nobody further -------------------------
    far = make(4, "security", (5, 28), archetype="corp_guard")
    world.actors.append(far)
    far.allocate_visibility(room.w * room.h)
    heard = broadcast(world, (14, 5), "gunfire")
    assert bb_of(far).noise_pos is None, "28 cells away is out of earshot"
    assert heard == 2, "the guard and the Runner are in earshot; the far guard is not"
    assert bb_of(guard).noise_pos == (14, 5)

    # ---- 10. a real tree, ticked end to end ----------------------------------------------
    tree = load_trees(
        [
            {
                "id": "test_guard",
                "root": {
                    "type": "selector",
                    "children": [
                        {
                            "type": "sequence",
                            "children": [
                                {"type": "condition", "check": "can_see_target"},
                                {"type": "condition", "check": "alert_below", "args": {"level": 2}},
                                {"type": "action", "action": "call_backup"},
                            ],
                        },
                        {
                            "type": "sequence",
                            "children": [
                                {"type": "condition", "check": "noise_heard"},
                                {
                                    "type": "action",
                                    "action": "move_to_blackboard",
                                    "args": {"key": "noise_pos"},
                                },
                            ],
                        },
                        {"type": "action", "action": "patrol"},
                    ],
                },
            }
        ]
    )["test_guard"]
    bb_of(guard).alert_level, bb_of(guard).noise_pos, bb_of(guard).pacified = 1, None, False
    guard.pos, guard.energy = (5, 5), 12
    world.patrols[guard.id] = [(5, 5), (5, 7)]
    refresh(guard, world)
    assert guard.bt is not None, "an enemy always has tree state"
    status, cost = tick(tree, guard.bt, make_eval_leaf(guard, world), TickContext())
    assert status is Status.SUCCESS
    assert cost == ENERGY_COSTS["use_item"], "call_backup costs Use item (5), not nothing"
    assert guard.energy == 12, "the ticker reports the cost; the caller charges it (decision 5)"
    guard.energy -= cost
    assert bb_of(guard).alert_level == 2, "the tree called backup, so the site is at Lockdown"

    # the pacified channel: dialogue stands the guard down, and the tree can see it
    bb_of(guard).pacified = True
    assert check_pacified(guard, {}, world) is True

    print(
        f"OK  ai: {len(CONDITION_ARGS)} conditions, {len(ACTION_ARGS)} actions, refresh writes "
        f"target/last_known_pos/alert, allies block the firing line, one Step per decision step, "
        f"a tree called backup and tripped the alarm"
    )


if __name__ == "__main__":
    demo()

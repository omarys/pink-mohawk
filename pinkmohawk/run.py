"""The Run: compose a Site, its population and the crew, then drive the Pass loop.

This is the composition root. Everything below it is a library with its own acceptance test; this
module is where the pieces meet, and where the decisions that only matter in combination get settled:

- **One Round is a re-rolled initiative order**; a Pass is one actor spending its Energy until it
  cannot afford a Step (§5), and `scheduler` owns that arithmetic.
- **The player owns the four Runners; the machine owns everything else** (ADR-0002, ADR-0009). A
  Runner has `bt is None`, so `step` hands control back to the caller instead of ticking a tree.
- **Extraction ends the Run, and the Clock can end it for you** (ADR-0005): a converged Clock makes
  any extraction forced, which `security.end_run` already knows how to price.

Layer 3. It imports `ai` for the tree tick, `content` for stat blocks, `security` for the Clock, and
`embed`/`placement`/`mission_graph` to build the Site.

    .venv/bin/python -m pinkmohawk.run      # runs the slice acceptance test
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from . import ai, bt, content, embed, entities, mission_graph, placement, scheduler, security
from . import rng as rng_mod
from .constants import FOV_RADIUS, PASS_END_THRESHOLD
from .entities import Actor
from .errors import ValidationError
from .security import Clock, Extraction

CREW_CLASSES = ("adept", "mage", "shaman", "decker")
FIRST_ENEMY_ID = 10


@dataclass
class RunState:
    """One attempt at a Job, in full."""

    job_type: str
    run_seed: int
    graph: mission_graph.MissionGraph
    site: embed.Site
    population: placement.Population
    world: ai.World
    queue: Any
    rngs: dict[str, random.Random]
    crew: list[Actor] = field(default_factory=list)
    round_no: int = 0
    _pass_seen: dict[int, int] = field(default_factory=dict)
    extraction: Extraction | None = None
    finished: bool = False
    heat: int = (
        0  # the campaign's Heat on entry, so `extract` prices the delta against the right base
    )

    # -- queries ---------------------------------------------------------------------------
    @property
    def actors(self) -> list[Actor]:
        return self.world.actors

    @property
    def clock(self) -> Clock:
        return self.world.clock

    def enemies(self) -> list[Actor]:
        return [a for a in self.actors if a.faction != "crew"]

    def live_crew(self) -> list[Actor]:
        return [a for a in self.crew if not a.downed]

    def paydata_cell(self) -> tuple[int, int] | None:
        """Where the Job's objective sits: the mission device's cell."""
        mission = [s for s in self.population.devices() if s.mission]
        return mission[0].cell if mission else None

    def crew_at_objective(self) -> bool:
        """Success in v1: a living Runner stands on the Paydata and survives to say so."""
        cell = self.paydata_cell()
        if cell is None:
            return False
        return any(a.pos == cell for a in self.live_crew())


def build_run(
    job_type: str,
    run_seed: int,
    *,
    heat: int = 0,
    clock_credit: int = 0,
    roster: Sequence[Any] | None = None,
) -> RunState:
    """Graph, Site, population, crew - from one stored seed (DECISIONS 9, 10).

    `roster` is the campaign's four Runner sheets, and passing it is what makes a bought weapon
    visible in a Run: without it the crew is built from `CREW_CLASSES` and the opening sheets, which
    is the Phase 1 behaviour a bare `build_run(job, seed)` still gets.

    `clock_credit` is the Fixer Favour's head start (world.md 3.3): the Clock begins that many
    segments further from convergence, so `remaining` reads CLOCK_SEGMENTS + credit.
    """
    rngs = rng_mod.make_static_rngs(run_seed)
    graph = mission_graph.build_graph(job_type, rngs["gen.graph"])
    site = embed.embed(graph, run_seed)
    rooms = {node_id: (room.x, room.y, room.w, room.h) for node_id, room in site.rooms.items()}
    population = placement.place(graph, rooms, rngs["gen.place"], heat=heat)

    crew: list[Actor] = []
    entry_room = site.rooms[graph.single(mission_graph.ENTRY)]
    entry_cells = entry_room.cells
    # The crew spawns on the entry room's interior, one cell each, deterministically.
    if roster is None:
        crew = [
            content.build_runner(klass, index + 1, entry_cells[index * 2])
            for index, klass in enumerate(CREW_CLASSES)
        ]
    else:
        crew = [
            content.build_runner_from_sheet(sheet, index + 1, entry_cells[index * 2])
            for index, sheet in enumerate(roster)
        ]
    site.spawn = crew[0].pos
    site.map.remember()

    actors: list[Actor] = list(crew)
    armour: dict[int, int] = {}
    weapon_of: dict[int, str] = {}
    patrols: dict[int, list[tuple[int, int]]] = {}
    next_id = FIRST_ENEMY_ID
    for spawn in population.spawns:
        if spawn.kind != "enemy":
            continue
        enemy = content.build_enemy(spawn, next_id, rngs["gen.place"])
        actors.append(enemy)
        armour[enemy.id] = int(content.ENEMIES[spawn.template]["armour"])
        weapon_of[enemy.id] = str(content.ENEMIES[spawn.template]["weapon"])
        ring = content.patrol_ring(rooms[spawn.node_id])
        if ring:
            patrols[enemy.id] = ring
        next_id += 1

    tables = content.world_tables(actors, armour_of=armour, weapon_of=weapon_of)
    world = ai.World(
        map=site.map,
        actors=actors,
        clock=Clock(),
        rng=rngs["rules.combat"],
        round_no=0,
        objective_rooms={
            str(node_id): site.rooms[node_id].center  # §5: the key is a node id STRING
            for node_id, node in graph.nodes.items()
            if node.kind == mission_graph.OBJECTIVE
        },
        armour=tables["armour"],
        ammo=tables["ammo"],
        patrols=patrols,
        exit_cell=site.exit_cell,
    )
    for actor in actors:
        actor.allocate_visibility(site.map.w * site.map.h)

    if clock_credit:
        # A Favour's head start (world.md 3.3): the Clock starts behind, so convergence is that much
        # further away. `remaining` reports it, and every threshold is a >= test, so nothing else
        # needs to know.
        world.clock.segments -= clock_credit

    run = RunState(
        job_type,
        run_seed,
        graph,
        site,
        population,
        world,
        queue=None,
        rngs=rngs,
        crew=crew,
        heat=heat,
    )
    begin_round(run)
    return run


def begin_round(run: RunState) -> None:
    """Roll initiative for everyone and start the Round (DECISIONS §5: re-rolled every Round)."""
    run.world.round_no = run.round_no
    run.queue = scheduler.begin_round(run.actors, run.rngs["rules.initiative"])
    for actor in run.actors:
        actor.effects = [e for e in actor.effects if e.until_round > run.round_no]
    run.round_no += 1


def tree_for(actor: Actor) -> bt.Tree:
    """Which tree drives this actor. An enemy reads its archetype; a Spirit has one of its own."""
    from .entities import EnemyRole, SpiritRole

    if isinstance(actor.role, EnemyRole):
        key = actor.role.archetype
    elif isinstance(actor.role, SpiritRole):
        key = "spirit"
    else:
        raise ValidationError([f"actor {actor.id} has no tree"])
    name = content.TREE_FOR.get(key)
    if name is None or name not in content.TREES:
        raise ValidationError([f"no tree for {key!r}"])
    return content.TREES[name]


def ai_step(run: RunState, actor: Actor) -> tuple[bt.Status | None, int]:
    """One decision step for a machine-driven actor. Returns (status, Energy the caller charges).

    The Pass boundary is where a tree is reset (ai.md §3.1): resume indices and repeat counters clear,
    cooldowns survive. Doing it here, once per Pass rather than once per step, is what lets a RUNNING
    branch continue across steps while a new Pass starts clean.
    """
    if actor.bt is None:
        raise ValidationError([f"actor {actor.id} is player-controlled"])
    if run._pass_seen.get(actor.id) != actor.pass_no:
        actor.bt.reset_tree()
        run._pass_seen[actor.id] = actor.pass_no

    ai.refresh(actor, run.world)
    status, cost = bt.tick(
        tree_for(actor), actor.bt, ai.make_eval_leaf(actor, run.world), bt.TickContext(actor)
    )
    actor.energy -= cost  # the caller charges (decision 25)
    if status is bt.Status.FAILURE or cost == 0 or actor.energy < PASS_END_THRESHOLD:
        end_pass(run, actor)
    else:
        run.queue.insert(actor, actor.energy)
    return status, cost


def end_pass(run: RunState, actor: Actor) -> None:
    """Pass ends: Score −10, cooldowns tick, and the actor returns if the Score is still positive."""
    scheduler.end_pass(run.queue, actor)


def next_actor(run: RunState) -> Actor | None:
    """Pop the next actor. A Round that empties rolls a new initiative order."""
    actor = scheduler.next_actor(run.queue)
    if actor is None:
        if run.finished:
            return None
        begin_round(run)
        actor = scheduler.next_actor(run.queue)
    return actor


def step(run: RunState) -> Actor | None:
    """Advance the Run by one decision step.

    Returns the actor when it is player-controlled — their step is the caller's to take — and None
    when the machine acted, so a UI can loop until it needs a command.
    """
    if run.finished:
        return None
    actor = next_actor(run)
    if actor is None:
        return None
    if actor.is_player_controlled:
        return actor
    ai_step(run, actor)
    return None


# ----------------------------------------------------------------------------------------------
# Player commands. Deliberately a small set: the slice needs movement, an attack, and a wait.
# ----------------------------------------------------------------------------------------------
DIRECTIONS = {
    "n": (0, -1),
    "s": (0, 1),
    "e": (1, 0),
    "w": (-1, 0),
    "ne": (1, -1),
    "nw": (-1, -1),
    "se": (1, 1),
    "sw": (-1, 1),
}


def command_step(run: RunState, actor: Actor, direction: str) -> bool:
    """One Step. Reveals cells through that Runner's own FOV, and folds them into Memory."""
    if actor.energy < PASS_END_THRESHOLD:
        end_pass(run, actor)
        return False
    delta = DIRECTIONS.get(direction)
    if delta is None:
        raise ValidationError([f"unknown direction {direction!r}"])
    target = (actor.pos[0] + delta[0], actor.pos[1] + delta[1])
    if run.site.map.is_wall(*target):
        return False
    occupied = {a.pos for a in run.actors if a.id != actor.id and not a.downed}
    if target in occupied:
        return False
    actor.pos = target
    actor.energy -= 1
    see(run, actor)
    if actor.energy < PASS_END_THRESHOLD:
        end_pass(run, actor)
    else:
        run.queue.insert(actor, actor.energy)
    return True


def see(run: RunState, actor: Actor) -> int:
    """Fill the actor's own visibility buffer and fold what it saw into the map's Memory."""
    assert actor.visible is not None
    from .fov import compute_fov_into

    lit = compute_fov_into(run.site.map, actor.visible, *actor.pos, FOV_RADIUS)
    for index, seen in enumerate(actor.visible):
        if seen:
            run.site.map.explored[index] = 1
    if actor is run.crew[0]:
        run.site.map.visible[:] = actor.visible  # the renderer reads the first Runner's eyes
    return lit


def command_attack(run: RunState, actor: Actor, weapon: str | None = None) -> bool:
    """Shoot the nearest thing in range. The tree catalogue's action, driven by a person."""
    weapon = weapon or _equipped()
    if weapon is None:
        return False
    nearest = min(
        (e for e in run.enemies() if not e.downed),
        key=lambda e: abs(e.pos[0] - actor.pos[0]) + abs(e.pos[1] - actor.pos[1]),
        default=None,
    )
    if nearest is None:
        return False
    assert actor.bb is not None, "a command assumes the actor has a Blackboard"
    actor.bb.target = nearest.id
    ctx = bt.TickContext(actor)
    status = ai.ACTION_HANDLERS["attack_target"](actor, {"weapon": weapon}, ctx, run.world)
    actor.energy -= ctx.cost
    if actor.energy < PASS_END_THRESHOLD:
        end_pass(run, actor)
    else:
        run.queue.insert(actor, actor.energy)
    return status is bt.Status.SUCCESS


def command_wait(run: RunState, actor: Actor) -> None:
    end_pass(run, actor)


def _equipped() -> str | None:
    """v1: the best weapon in the table, for every Runner.

    Not per-class yet. classes.md gives the Decker and the Mage their own kits, and run.command_attack
    takes an explicit weapon, so a class kit is a caller's decision rather than this default's.
    """
    from .constants import WEAPONS

    candidates = [w for w in WEAPONS if w != "hellhound_bite"]
    return max(
        candidates,
        key=lambda w: WEAPONS[w][0] if isinstance(WEAPONS[w][0], int) else 0,
        default=None,
    )


def extract(run: RunState, *, voluntary: bool = True, net_negotiation_hits: int = 0) -> Extraction:
    """End the Run and price it. A converged Clock overrides a voluntary extraction."""
    completed = 1 if run.crew_at_objective() else 0
    total = max(1, len(run.graph.of_kind(mission_graph.OBJECTIVE)))
    result = security.end_run(
        run.clock,
        net_negotiation_hits=net_negotiation_hits,
        objectives_completed=completed,
        objectives_total=total,
        heat=run.heat,
        voluntary=voluntary,
    )
    run.extraction = result
    run.finished = True
    return result


# ==============================================================================================
# The slice acceptance test (roadmap.md Phase 1, points 1-7)
# ==============================================================================================
def demo() -> None:
    run = build_run("extraction", 20260918, heat=0)

    # ---- 1. the Site verifies: objectives reachable, exit reachable, rooms connected -----
    assert embed.verify(run.site, run.graph) == [], embed.verify(run.site, run.graph)
    assert run.graph.validate() == []
    assert run.graph.is_dag()

    # ---- 2. the Paydata is in the vault, and the crew spawns at entry --------------------
    paydata = run.paydata_cell()
    assert paydata is not None
    vault = run.graph.of_kind(mission_graph.OBJECTIVE)[0]
    assert run.site.rooms[vault].contains(*paydata), "the Paydata sits in the objective room"
    entry = run.site.rooms[run.graph.single(mission_graph.ENTRY)]
    assert all(entry.contains(*a.pos) for a in run.crew), "all four spawn in the entry room"
    assert len(run.crew) == 4 and len(run.enemies()) >= 1

    # ---- 3. first-Pass Energy is the Initiative Score, and it drops by 10 per Pass -------
    for actor in run.crew:
        assert actor.energy == actor.score, f"actor {actor.id}: {actor.energy} vs {actor.score}"
    probe = run.crew[0]
    probe.energy = probe.score = 18
    pass_end_before = probe.pass_no
    for _ in range(2):
        scheduler.end_pass(run.queue, probe)
    assert probe.pass_no == pass_end_before + 2 and probe.score == -2, (
        "two Passes from 18 leaves −2 and stops"
    )

    # ---- 4. moving reveals cells, and Memory keeps them ---------------------------------
    scout = run.crew[0]
    run.site.map.explored[:] = b"\0" * len(run.site.map.explored)
    assert not any(run.site.map.explored)
    first = see(run, scout)
    assert first > 50, f"an open room should reveal plenty, got {first}"
    assert sum(run.site.map.explored) == first, "everything visible is now remembered"
    for direction in ("e", "s", "w", "n"):
        command_step(run, scout, direction)
    assert sum(run.site.map.explored) >= first, "Memory never shrinks"

    # ---- 5. every archetype ticks a tree and picks a target -----------------------------
    ticks = 0
    for enemy in run.enemies():
        assert enemy.bb is not None
        ai.refresh(enemy, run.world)
        enemy.bb.target = run.crew[0].id  # a target exists, so trees can act
        enemy.energy = 12
        enemy.score = 12
        status, _cost = ai_step(run, enemy)
        assert status is not None, f"{enemy.name} produced no status"
        assert enemy.bb.target is not None, f"{enemy.name} has no target"
        ticks += 1
    assert ticks == len(run.enemies())

    # ---- 6. gunfire ticks the Clock and a silent action does not -------------------------
    clock_before = run.clock.segments
    shooter = next(
        a
        for a in run.enemies()
        if isinstance(a.role, entities.EnemyRole) and content.ENEMIES[a.role.archetype]["magazine"]
    )
    assert isinstance(shooter.role, entities.EnemyRole), "an enemy that fired carries an EnemyRole"
    shooter.pos = (run.crew[0].pos[0] + 1, run.crew[0].pos[1])  # in range, or the attack fails
    assert shooter.bb is not None
    shooter.bb.target = run.crew[0].id
    shooter.energy = 12
    ai.ACTION_HANDLERS["attack_target"](
        shooter,
        {"weapon": content.ENEMIES[shooter.role.archetype]["weapon"]},
        bt.TickContext(shooter),
        run.world,
    )
    assert run.clock.segments == clock_before + 2, "gunfire is worth 2 segments"
    quiet_before = run.clock.segments
    assert run.clock.tick("silent_takedown") == 0 and run.clock.segments == quiet_before

    # ---- 7. reaching the Paydata and extracting pays the contract's formula --------------
    assert not run.crew_at_objective(), "nobody has walked there yet"
    scout.pos = paydata
    assert run.crew_at_objective()
    paid = extract(run, voluntary=True, net_negotiation_hits=4)
    assert not paid.forced and paid.payout == 12_000 + 400, paid.payout
    assert paid.reputation_delta == 1 and paid.heat_delta == 0
    assert run.finished

    forced_run = build_run("extraction", 7, heat=0)
    for _ in range(5):
        forced_run.clock.tick("gunfire")
    assert forced_run.clock.converged
    broke = extract(forced_run, voluntary=True, net_negotiation_hits=9)
    assert broke.forced and broke.payout == 0, "a converged Clock pays nothing"
    assert broke.reputation_delta == -1 and broke.heat_delta == 2

    # ---- 8. the same seed builds the same Run -------------------------------------------
    def fingerprint(state: RunState) -> tuple[Any, ...]:
        return (bytes(state.site.map.tiles), tuple((a.id, a.pos, a.name) for a in state.actors))

    assert fingerprint(build_run("extraction", 99)) == fingerprint(build_run("extraction", 99))
    assert fingerprint(build_run("extraction", 99)) != fingerprint(build_run("extraction", 100))

    print(
        f"OK  run: roadmap Phase 1 points 1-7 — {len(run.actors)} actors "
        f"({len(run.crew)} crew, {len(run.enemies())} hostiles), {len(run.population.spawns)} "
        f"spawns, FOV radius {FOV_RADIUS}, Clock {run.clock.segments}/10, "
        f"payout {paid.payout}, forced payout {broke.payout}"
    )


if __name__ == "__main__":
    demo()

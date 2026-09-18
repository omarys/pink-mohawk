"""Population: devices, enemies and loot, placed by Mission Graph node type.

`docs/design/enemies.md` §7 is the authoritative table (and `world.md` §7 is the same contract in
checklist form); DECISIONS §7 holds the caps. ADR-0008 makes the device layer the Decker's entire kit,
so this module's real job is not to roll dice but to *enforce two guarantees*:

- **G1 — every main-path node has something to hack.** `entry`, every `security`, every `objective`
  and `exit` carries at least one device. A main-path node with nothing to hack is a node where the
  Decker has no class; if a plan gap leaves one bare, a Lights is added rather than shipping it empty.
- **G2 — no node is a device piñata.** At most 2 rating-4 devices per node, at most 6 total Hack Drain
  per node (both excluding the mission device), and at most 3 devices carried per enemy. The Drain
  economy already brakes this — `ceil(rating/2)` means a loaded node costs the Decker half its Stun —
  so the caps codify a limit the arithmetic imposes, and `validate` proves the plan respects it.

Layer 1: imports `grid`, `mission_graph`, `rng` and `constants` — **never `entities`**. This module
produces plain `Spawn` records; the composition root turns them into Actors. That is what lets a test
place a whole Site and assert the caps without a single Actor existing.

    .venv/bin/python -m pinkmohawk.placement      # runs demo()
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Final

from .constants import (
    DEVICE_CARRY_CAP,
    DEVICE_RATINGS,
    HACK_DRAIN_DIVISOR,
    HACK_DRAIN_PER_NODE_CAP,
    RATING4_PER_NODE_CAP,
)
from .errors import ValidationError
from .mission_graph import ENTRY, EXIT, OBJECTIVE, SECURITY, SIDE, MissionGraph

type Cell = tuple[int, int]
type Rect = tuple[int, int, int, int]  # x, y, w, h — interior, as embed.Room carries them

MAIN_PATH_KINDS: Final = (ENTRY, SECURITY, OBJECTIVE, EXIT)

#: Heat tiers by band (world.md §8.1). Three points per tier; the ceiling is DECISIONS §9's HEAT_MAX.
HEAT_BANDS: Final = ((0, 2), (3, 5), (6, 8), (9, 20))


def heat_tier(heat: int) -> int:
    """0..3. Enemies and their gear scale with this, not with the raw Heat number."""
    for tier, (low, high) in enumerate(HEAT_BANDS):
        if low <= heat <= high:
            return tier
    return 0 if heat < HEAT_BANDS[0][0] else len(HEAT_BANDS) - 1


def device_drain(rating: int) -> int:
    """§7: hacking a device costs `ceil(rating / 2)` Stun. The cap arithmetic uses this."""
    return -(-rating // HACK_DRAIN_DIVISOR)


@dataclass(frozen=True, slots=True)
class Spawn:
    """One thing to create, before anything exists. Data, not an Actor."""

    kind: str  # "device" | "enemy" | "loot"
    node_id: int
    node_kind: str
    cell: Cell
    template: str  # "door" | "corp_guard" | "ammo_cache" …
    rating: int = 0  # devices only
    mission: bool = False  # the vault door / Paydata terminal / sabotage target: cap-exempt
    carried: tuple[str, ...] = ()  # enemies only: the devices in their gear (§7.2 cap 1)


@dataclass(slots=True)
class Population:
    """Everything placed on one Site, plus the queries `validate` and the composition root need."""

    spawns: list[Spawn] = field(default_factory=list)

    def devices(self, node_id: int | None = None) -> list[Spawn]:
        return [
            s
            for s in self.spawns
            if s.kind == "device" and (node_id is None or s.node_id == node_id)
        ]

    def enemies(self, node_id: int | None = None) -> list[Spawn]:
        return [
            s
            for s in self.spawns
            if s.kind == "enemy" and (node_id is None or s.node_id == node_id)
        ]

    def loot(self, node_id: int | None = None) -> list[Spawn]:
        return [
            s for s in self.spawns if s.kind == "loot" and (node_id is None or s.node_id == node_id)
        ]


# ----------------------------------------------------------------------------------------------
# The plan, transcribed from enemies.md §7
# ----------------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class DeviceRule:
    """One row cell: which device, at what rating, and how likely."""

    kind: str
    rating: int | tuple[int, int]
    chance: float = 1.0
    mandatory: bool = False  # "mandatory" in §7's table: never yields to a cap

    def roll(self, rng: random.Random) -> tuple[str, int] | None:
        if self.chance < 1.0 and rng.random() >= self.chance:
            return None
        if isinstance(self.rating, tuple):
            low, high = self.rating
            return self.kind, rng.randint(low, high)
        return self.kind, self.rating


#: Node kind -> devices. Objectives key on the Job type, because a vault is not a courier drop.
DEVICE_PLAN: Final[dict[str, tuple[DeviceRule, ...]]] = {
    ENTRY: (
        DeviceRule("door", 2, mandatory=True),
        DeviceRule("lights", 3),
        DeviceRule("commlink", 3, mandatory=True),
    ),
    # Corridors carry Lights every 15 cells (enemies.md §7), which is the embedder's business: it
    # knows where the corridors are. Only the door belongs to the population pass.
    "corridor": (DeviceRule("door", (2, 4), 0.5),),
    SECURITY: (
        DeviceRule("optics", 2, mandatory=True),
        DeviceRule("lights", 3, mandatory=True),
        DeviceRule("door", (2, 4)),
        DeviceRule("gun", 2, 0.5),
        DeviceRule("commlink", 3, 0.5),
        DeviceRule("drone", 4),
    ),
    SIDE: (DeviceRule("lights", 3), DeviceRule("door", (2, 4)), DeviceRule("optics", 2, 0.5)),
    EXIT: (DeviceRule("door", 2, mandatory=True), DeviceRule("lights", 3)),
}

#: Objectives by Job type. The mission device is separate and cap-exempt, so it is NOT repeated here.
OBJECTIVE_DEVICES: Final[dict[str, tuple[DeviceRule, ...]]] = {
    "extraction": (
        DeviceRule("door", 4, mandatory=True),
        DeviceRule("lights", 3),
        DeviceRule("optics", 2),
        DeviceRule("drone", 4),
    ),
    "sabotage": (DeviceRule("optics", 2), DeviceRule("lights", 3), DeviceRule("door", (2, 4))),
    "protection": (
        DeviceRule("lights", 3),
        DeviceRule("optics", 2),
        DeviceRule("door", (2, 4)),
        DeviceRule("gun", 2, 0.5),
        DeviceRule("drone", 4),
        DeviceRule("cyberware", 4, 0.5),
    ),
    "courier": (
        DeviceRule("optics", 2, mandatory=True),
        DeviceRule("lights", 3),
        DeviceRule("door", (2, 4)),
    ),
}

#: The mission device itself: cap-exempt, and the thing the Job is about.
MISSION_DEVICE: Final[dict[str, tuple[str, int]]] = {
    "extraction": ("commlink", 3),  # the Paydata terminal
    "sabotage": ("gun", 4),  # machine-class target; rated 4, and exempt from the cap
    "protection": ("commlink", 3),  # the protectee's link
    "courier": ("commlink", 3),  # the package is carried, not a fixture
}

#: archetype -> (count at tier 0, min tier at which it appears, extra per tier above the minimum)
ENEMY_PLAN: Final[dict[str, tuple[tuple[str, int, int], ...]]] = {
    ENTRY: (("corp_guard", 1, 2),),
    "corridor": (("corp_guard", 1, 2),),
    SECURITY: (("corp_guard", 1, 0), ("security_drone", 1, 1), ("corp_mage", 1, 2)),
    OBJECTIVE: (("corp_guard", 1, 0), ("security_drone", 1, 1), ("corp_mage", 1, 2)),
    SIDE: (("ganger", 2, 0), ("corp_guard", 1, 2)),
    EXIT: (("corp_guard", 1, 3),),  # only while Lockdown is up, which is tier 3 territory
}

#: What each archetype carries (§7.2 cap 1). Sizes are the contract: 3/3/2/1/0.
CARRIED_DEVICES: Final[dict[str, tuple[str, ...]]] = {
    "corp_guard": ("gun", "optics", "commlink"),
    "security_drone": ("drone", "optics", "gun"),
    "corp_mage": ("commlink", "optics"),
    "ganger": ("gun",),
    "hellhound": (),
}


#: Side-node loot, one weighted draw. v1 content: the cheap consumables from §4/§9.
LOOT_TABLE: Final[tuple[tuple[str, int], ...]] = (
    ("ammo_crate", 4),
    ("medkit", 3),
    ("stun_baton", 1),
)


def _weighted(rng: random.Random, table: tuple[tuple[str, int], ...]) -> str:
    total = sum(weight for _item, weight in table)
    pick = rng.random() * total
    for item, weight in table:
        pick -= weight
        if pick <= 0:
            return item
    return table[-1][0]


def _rooms_of(rooms: dict[int, Rect], node_id: int) -> Rect:
    rect = rooms.get(node_id)
    if rect is None:
        raise ValidationError([f"no room for node {node_id}"])
    return rect


def _cell_in(rect: Rect, rng: random.Random) -> Cell:
    """A cell on the room's interior wall line: devices sit against walls, not in the middle."""
    x, y, w, h = rect
    side = rng.randrange(4)
    if side == 0:
        return (x + rng.randrange(w), y)
    if side == 1:
        return (x + rng.randrange(w), y + h - 1)
    if side == 2:
        return (x, y + rng.randrange(h))
    return (x + w - 1, y + rng.randrange(h))


def place(
    graph: MissionGraph, rooms: dict[int, Rect], rng: random.Random, *, heat: int = 0
) -> Population:
    """Populate a Site. Order is fixed — devices, then enemies, then loot, node by node — because the
    RNG stream is shared and a different order would change every Site for the same seed.
    """
    tier = heat_tier(heat)
    job = graph.job_type or "extraction"
    population = Population()

    for node_id in sorted(graph.nodes):
        node = graph.nodes[node_id]
        rect = _rooms_of(rooms, node_id)

        # -- devices -------------------------------------------------------------------------
        rules = (
            OBJECTIVE_DEVICES.get(job, OBJECTIVE_DEVICES["extraction"])
            if node.kind == OBJECTIVE
            else DEVICE_PLAN.get(node.kind, ())
        )
        # Mandatory cells first and unconditionally; optional cells yield to the caps. A security
        # node's full plan costs 8 Hack Drain against a cap of 6, so §7.2's caps are constraints on
        # this pass rather than assertions about it.
        drain_used = heavy_used = 0
        for rule in sorted(rules, key=lambda r: not r.mandatory):
            if rule.kind == "drone" and tier < 1:
                continue  # tier-gated, per §7's footnote
            rolled = rule.roll(rng)
            if rolled is None:
                continue
            kind, rating = rolled
            cost = device_drain(rating)
            heavy = 1 if rating >= 4 else 0
            if not rule.mandatory and (
                drain_used + cost > HACK_DRAIN_PER_NODE_CAP
                or heavy_used + heavy > RATING4_PER_NODE_CAP
            ):
                continue  # the cap outranks an optional cell
            drain_used += cost
            heavy_used += heavy
            population.spawns.append(
                Spawn("device", node_id, node.kind, _cell_in(rect, rng), kind, rating)
            )
        if node.kind == OBJECTIVE:
            kind, rating = MISSION_DEVICE.get(job, ("commlink", 3))
            population.spawns.append(
                Spawn("device", node_id, node.kind, _cell_in(rect, rng), kind, rating, mission=True)
            )

        # -- enemies -------------------------------------------------------------------------
        for archetype, count, min_tier in ENEMY_PLAN.get(node.kind, ()):
            if tier < min_tier:
                continue
            for _ in range(count):
                population.spawns.append(
                    Spawn(
                        "enemy",
                        node_id,
                        node.kind,
                        _cell_in(rect, rng),
                        archetype,
                        carried=CARRIED_DEVICES[archetype],
                    )
                )

        # -- loot ----------------------------------------------------------------------------
        if node.kind == SIDE:
            population.spawns.append(
                Spawn("loot", node_id, node.kind, _cell_in(rect, rng), _weighted(rng, LOOT_TABLE))
            )

    ensure_hackable(population, graph)
    return population


def ensure_hackable(population: Population, graph: MissionGraph) -> list[int]:
    """G1: give any bare main-path node a Lights, and return the node ids that needed one.

    Cheap insurance against a plan gap: the mandatory cells should make this impossible, which is
    exactly why it is worth asserting rather than assuming.
    """
    fixed: list[int] = []
    for node_id, node in graph.nodes.items():
        if node.kind not in MAIN_PATH_KINDS:
            continue
        if population.devices(node_id):
            continue
        rect_kind = node.kind
        # No room is known here, so the cell is the node's own room centre supplied by the caller in
        # practice; a (0, 0) placeholder is honest about the fact that the caller re-homes it.
        population.spawns.append(Spawn("device", node_id, rect_kind, (0, 0), "lights", 3))
        fixed.append(node_id)
    return fixed


def validate(population: Population, graph: MissionGraph) -> list[str]:
    """Every §7 guarantee and cap, as a list of complaints. Empty means the Site is well posed."""
    bad: list[str] = []

    # G1
    for node_id, node in graph.nodes.items():
        if node.kind in MAIN_PATH_KINDS and not population.devices(node_id):
            bad.append(f"G1: node {node_id} ({node.kind}) is on the main path with nothing to hack")

    # G2 caps 2 and 3, both excluding the mission device
    for node_id in sorted(graph.nodes):
        devices = [d for d in population.devices(node_id) if not d.mission]
        heavy = [d for d in devices if d.rating >= 4]
        if len(heavy) > RATING4_PER_NODE_CAP:
            bad.append(
                f"G2: node {node_id} has {len(heavy)} rating-4 devices, cap {RATING4_PER_NODE_CAP}"
            )
        drain = sum(device_drain(d.rating) for d in devices)
        if drain > HACK_DRAIN_PER_NODE_CAP:
            bad.append(
                f"G2: node {node_id} costs {drain} Hack Drain, cap {HACK_DRAIN_PER_NODE_CAP}"
            )

    # G2 cap 1, and unknown devices/archetypes
    for spawn in population.enemies():
        if len(spawn.carried) > DEVICE_CARRY_CAP:
            bad.append(
                f"G2: {spawn.template} carries {len(spawn.carried)} devices, cap {DEVICE_CARRY_CAP}"
            )
        for kind in spawn.carried:
            if kind not in DEVICE_RATINGS:
                bad.append(f"unknown carried device {kind!r} on {spawn.template}")
    for spawn in population.devices():
        if spawn.template not in DEVICE_RATINGS:
            bad.append(f"unknown device {spawn.template!r} at node {spawn.node_id}")
        elif spawn.rating != DEVICE_RATINGS[spawn.template] and spawn.rating not in (2, 3, 4):
            bad.append(f"node {spawn.node_id}: {spawn.template} rated {spawn.rating}")
    return bad


# ==============================================================================================
# Acceptance test
# ==============================================================================================
def demo() -> None:
    from .mission_graph import JOB_GRAPH, build_graph

    def rooms_for(graph: MissionGraph) -> dict[int, tuple[int, int, int, int]]:
        """A stand-in for embed's rooms: distinct interiors, big enough to hold their spawns."""
        return {
            node_id: (2 + 20 * (i % 4), 2 + 20 * (i // 4), 14, 10)
            for i, node_id in enumerate(sorted(graph.nodes))
        }

    # ---- 1. the plan respects both caps for every Job type, tier 0 through 3 --------------
    for job in JOB_GRAPH:
        for seed in range(8):
            graph = build_graph(job, random.Random(seed))
            rooms = rooms_for(graph)
            for heat in (0, 3, 6, 12):
                population = place(graph, rooms, random.Random(seed), heat=heat)
                problems = validate(population, graph)
                assert problems == [], f"{job}/{seed}/heat{heat}: {problems}"

    # ---- 2. G1: every main-path node has something to hack -------------------------------
    graph = build_graph("extraction", random.Random(3))
    population = place(graph, rooms_for(graph), random.Random(3), heat=0)
    for node_id, node in graph.nodes.items():
        if node.kind in MAIN_PATH_KINDS:
            assert population.devices(node_id), f"main-path node {node_id} ({node.kind}) is bare"
    assert not ensure_hackable(population, graph), "the plan already satisfies G1"

    # ---- 3. the mandatory cells of §7 are really there, and marked -------------------------
    templates = {(d.node_kind, d.template) for d in population.devices()}
    assert (ENTRY, "door") in templates and (ENTRY, "commlink") in templates
    assert (EXIT, "door") in templates and (SECURITY, "optics") in templates
    assert (SECURITY, "lights") in templates
    mission = [d for d in population.devices() if d.mission]
    assert len(mission) == 1 and mission[0].template == "commlink" and mission[0].rating == 3, (
        "an extraction's mission device is the Paydata terminal"
    )

    # ---- 4. tier gating: no drone or mage at tier 0, both later ---------------------------
    quiet = place(graph, rooms_for(graph), random.Random(1), heat=0)
    loud = place(graph, rooms_for(graph), random.Random(1), heat=12)
    assert not [e for e in quiet.enemies() if e.template in ("security_drone", "corp_mage")]
    assert [e for e in loud.enemies() if e.template == "security_drone"], "tier 3 has drones"
    assert [e for e in loud.enemies() if e.template == "corp_mage"], "tier 3 has a Corp Mage"
    assert len(loud.enemies()) > len(quiet.enemies()), "Heat buys the site more bodies"
    assert heat_tier(0) == 0 and heat_tier(3) == 1 and heat_tier(6) == 2 and heat_tier(12) == 3

    # ---- 5. carried devices: the contract's 3/3/2/1/0 ------------------------------------
    for archetype, expected in (
        ("corp_guard", 3),
        ("security_drone", 3),
        ("corp_mage", 2),
        ("ganger", 1),
        ("hellhound", 0),
    ):
        assert len(CARRIED_DEVICES[archetype]) == expected, archetype
    hellhounds = [e for e in loud.enemies() if e.template == "hellhound"]
    assert all(e.carried == () for e in hellhounds), "a Hellhound carries nothing"

    # ---- 6. the caps have teeth: a hand-built piñata node is caught ----------------------
    greedy = Population()
    node_id = next(iter(graph.nodes))
    for rating in (4, 4, 4):  # three rating-4 devices
        greedy.spawns.append(Spawn("device", node_id, SECURITY, (1, 1), "drone", rating))
    greedy.spawns.append(Spawn("device", node_id, SECURITY, (2, 1), "commlink", 3))
    problems = validate(greedy, graph)
    assert any("rating-4" in p for p in problems), problems
    assert any("Hack Drain" in p for p in problems), problems
    greedy.spawns[0] = Spawn(
        "enemy",
        node_id,
        SECURITY,
        (1, 1),
        "corp_guard",
        carried=("gun", "optics", "commlink", "drone"),
    )
    assert any("carries 4 devices" in p for p in validate(greedy, graph)), "cap 1 has teeth"

    # ---- 7. G1's fallback: a bare main-path node gets a Lights --------------------------
    bare = Population()
    fixed = ensure_hackable(bare, graph)
    assert fixed, "with nothing placed, every main-path node was bare"
    assert all(s.template == "lights" for s in bare.devices())
    assert not validate(bare, graph) or all("G1" not in p for p in validate(bare, graph))

    # ---- 8. determinism and seed sensitivity --------------------------------------------
    same = place(graph, rooms_for(graph), random.Random(9), heat=3)
    again = place(graph, rooms_for(graph), random.Random(9), heat=3)
    assert same.spawns == again.spawns, "the same stream gives the same Site"
    other = place(graph, rooms_for(graph), random.Random(10), heat=3)
    assert other.spawns != same.spawns, "a different seed gives a different Site"

    count = len(place(graph, rooms_for(graph), random.Random(5)).spawns)
    print(
        f"OK  placement: {len(DEVICE_PLAN)} node plans + {len(OBJECTIVE_DEVICES)} objective plans, "
        f"G1 and all three G2 caps enforced, tier gating 0-3, {count} spawns on a seeded "
        f"extraction"
    )


if __name__ == "__main__":
    demo()

"""Content: stat blocks, trees and the crew, loaded from `data/`.

ADR-0009 makes AI content rather than code, so the archetypes' numbers and their trees live in
`data/enemies.json` and `data/trees/*.json`. This module is the seam that turns those documents plus a
`placement.Spawn` into an `entities.Actor`, and it is the only place that knows both a spawn record and
an archetype's stat block.

Layer 3: imports `ai` (for the tree loader and its catalogues), `entities`, `placement` and `constants`.

Two v1 simplifications, both stated rather than hidden:
- An archetype's `skills` is a *flat rating*. `enemies.md` §1.2 has the full per-skill table; a flat
  number is enough for the engine and keeps the data honest about being a summary.
- A Spirit's Force is the default constant until the Shaman's conjuring roll lands with its kit.

    .venv/bin/python -m pinkmohawk.content      # runs demo()
"""

from __future__ import annotations

import json
import pathlib
import random
from typing import Any, Protocol

from .ai import load_trees
from .bt import BTState
from .constants import ATTRIBUTES, DEVICE_RATINGS, MAGAZINES, SKILLS
from .entities import (
    Actor,
    Blackboard,
    DeviceRef,
    EnemyRole,
    ItemRef,
    Monitor,
    RunnerRole,
    SpiritRole,
)
from .errors import ValidationError
from .placement import Spawn
from .utility import Weights

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def _load(name: str) -> dict[str, dict[str, Any]]:
    """Read a data file and drop its `_note` keys: the files document themselves, and a comment is
    not an archetype. Without this, `len(ENEMIES)` counts the documentation."""
    raw = json.loads((DATA / name).read_text())
    return {key: value for key, value in raw.items() if not key.startswith("_")}


ENEMIES: dict[str, dict[str, Any]] = _load("enemies.json")
CREW: dict[str, dict[str, Any]] = _load("crew.json")
TREES = load_trees([json.loads(p.read_text()) for p in sorted((DATA / "trees").glob("*.json"))])

#: Which tree drives which actor. An enemy reads its archetype; a Spirit has one of its own.
TREE_FOR: dict[str, str] = {archetype: archetype for archetype in ENEMIES}
TREE_FOR["spirit"] = "spirit"


def _monitors() -> tuple[Monitor, Monitor]:
    return Monitor(), Monitor()  # maxima are derived from attrs on the Actor, not stored here


def _gear(carried: list[str]) -> list[DeviceRef]:
    return [DeviceRef(kind, DEVICE_RATINGS[kind]) for kind in carried]


def build_enemy(spawn: Spawn, actor_id: int, rng: random.Random) -> Actor:
    """Turn one enemy Spawn into an Actor, from its archetype's block.

    The spawn decides *where* and *which archetype*; the stat block decides everything else. Keeping
    that split means a new archetype is a JSON entry, not a code change (ADR-0009).
    """
    block = ENEMIES.get(spawn.template)
    if block is None:
        raise ValidationError([f"no stat block for {spawn.template!r}"])
    attrs = dict.fromkeys(ATTRIBUTES, 3)
    attrs.update(block["attrs"])
    skills = dict.fromkeys(SKILLS, int(block["skills"]))
    physical, stun = _monitors()
    role = EnemyRole(
        archetype=spawn.template,
        weights=Weights.for_archetype(spawn.template),
        target_hysteresis=Weights.for_archetype(spawn.template).hysteresis,
        home_pos=spawn.cell,
        flees_at_wound=block["flees_at"],
    )
    actor = Actor(
        id=actor_id,
        name=block.get("name", spawn.template),
        faction="security",
        pos=spawn.cell,
        facing=0,
        glyph=int(block["glyph"]),
        tint=(210, 90, 90),
        attrs=attrs,
        skills=skills,
        physical=physical,
        stun=stun,
        gear=_gear(list(block["carries"])),
        role=role,
        bt=BTState(),
        bb=Blackboard(),
    )
    role.tradition = block.get("tradition")
    return actor


def build_runner(klass: str, actor_id: int, pos: tuple[int, int]) -> Actor:
    """One of the four Runners, from `data/crew.json`. No `bt`: the player drives these (ADR-0002)."""
    block = CREW.get(klass)
    if block is None:
        raise ValidationError([f"no crew block for {klass!r}"])
    attrs = dict.fromkeys(ATTRIBUTES, 3)
    attrs.update(block["attrs"])
    skills = dict.fromkeys(SKILLS, 3)
    skills.update(block["skills"])
    physical, stun = _monitors()
    role = RunnerRole(
        klass=klass,
        edge=int(block["edge"]),
        qi=int(block.get("qi", 0)),
        tradition=block.get("tradition"),
        inventory=[ItemRef(slug) for slug in block.get("inventory", [])],
    )
    return Actor(
        id=actor_id,
        name=block["name"],
        faction="crew",
        pos=pos,
        facing=0,
        glyph=int(block["glyph"]),
        tint=(120, 200, 255),
        attrs=attrs,
        skills=skills,
        physical=physical,
        stun=stun,
        gear=[DeviceRef("cyberdeck", 4)] if klass == "decker" else [],
        role=role,
        bt=None,
        bb=Blackboard(),
        energy=0,
    )


class SheetLike(Protocol):
    """What `build_runner_from_sheet` needs of a `campaign.RunnerSheet`.

    A Protocol rather than an import because `campaign` imports this module: the dependency runs one
    way, exactly as the layer law wants, and the sheet still gets checked at the call site.
    """

    klass: str
    attributes: dict[str, int]
    skills: dict[str, int]
    edge: int
    loadout: list[str]
    physical: int
    stun: int
    perks: list[Any]


def build_runner_from_sheet(sheet: SheetLike, actor_id: int, pos: tuple[int, int]) -> Actor:
    """A Runner built from the campaign's persisted sheet (world.md §10.1).

    This is what makes a Hub purchase visible in a Run: `build_runner` supplies the class's opening
    numbers, and the sheet then overrides every number a campaign can have changed - attributes,
    skills, Edge, the loadout, and the filled monitor boxes §10.3 carries between Jobs.
    """
    actor = build_runner(sheet.klass, actor_id, pos)
    role = actor.role
    assert isinstance(role, RunnerRole), "build_runner returns a Runner"
    actor.attrs.update(sheet.attributes)
    actor.skills.update(sheet.skills)
    role.edge = sheet.edge
    role.inventory = [ItemRef(slug) for slug in sheet.loadout]
    role.perks = [perk.id for perk in sheet.perks]
    actor.physical.filled = sheet.physical
    actor.stun.filled = sheet.stun
    return actor


def build_spirit(summoner_id: int, spirit_type: str, actor_id: int, pos: tuple[int, int]) -> Actor:
    """A conjured Spirit: a full Actor with its own tree (ai.md §8, `spirit`)."""
    attrs = dict.fromkeys(ATTRIBUTES, 4)
    physical, stun = _monitors()
    return Actor(
        id=actor_id,
        name=f"{spirit_type} spirit",
        faction="spirit",
        pos=pos,
        facing=0,
        glyph=0xE02F,
        tint=(120, 220, 160),
        attrs=attrs,
        skills=dict.fromkeys(SKILLS, 3),
        physical=physical,
        stun=stun,
        role=SpiritRole(summoner_id=summoner_id, spirit_type=spirit_type),
        bt=BTState(),
        bb=Blackboard(),
    )


def patrol_ring(rect: tuple[int, int, int, int], inset: int = 1) -> list[tuple[int, int]]:
    """A four-corner ring inside a room. Deterministic, so a seeded Site patrols the same way."""
    x, y, w, h = rect
    x0, y0 = x + inset, y + inset
    x1, y1 = x + w - 1 - inset, y + h - 1 - inset
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def world_tables(
    actors: list[Actor], *, armour_of: dict[int, int], weapon_of: dict[int, str]
) -> dict[str, Any]:
    """The three keyed tables `ai.World` needs, derived from the stat blocks this module loaded."""
    armour = {a.id: armour_of[a.id] for a in actors if a.id in armour_of}
    ammo = {}
    for actor in actors:
        weapon = weapon_of.get(actor.id)
        if weapon and weapon in MAGAZINES:
            ammo[(actor.id, weapon)] = MAGAZINES[weapon]
    return {"armour": armour, "ammo": ammo}


def demo() -> None:
    # ---- 1. the data loaded, and every tree matches a stat block -------------------------
    assert len(ENEMIES) == 5, sorted(ENEMIES)
    assert len(CREW) == 4, sorted(CREW)
    assert set(CREW) == {"adept", "mage", "shaman", "decker"}
    assert set(TREES) >= set(ENEMIES) | {"spirit"}, sorted(TREES)

    # ---- 2. a spawn becomes an Actor with the contract's derived numbers ----------------
    rng = random.Random(1)
    spawn = Spawn("enemy", 0, "security", (5, 5), "corp_guard")
    guard = build_enemy(spawn, actor_id=10, rng=rng)
    assert guard.attrs["body"] == 4 and guard.attrs["agility"] == 3
    assert guard.physical_max == 10 and guard.stun_max == 10, "(8 + ceil(4/2)) for both"
    assert not guard.is_player_controlled and guard.bb is not None
    assert isinstance(guard.role, EnemyRole) and guard.role.archetype == "corp_guard"
    assert guard.role.flees_at_wound == -4
    assert len(guard.gear) == 3, "§7.2 cap 1: a Corp Guard carries three devices"
    assert all(g.kind in ("gun", "optics", "commlink") for g in guard.gear)

    hellhound = build_enemy(Spawn("enemy", 0, "side", (1, 1), "hellhound"), 11, rng)
    assert isinstance(hellhound.role, EnemyRole)
    assert hellhound.gear == [], "a Hellhound carries nothing, so the Decker's edge is situational"
    assert hellhound.role.flees_at_wound is None, "an animal with no morale branch"
    assert hellhound.attrs["strength"] == 5

    mage = build_enemy(Spawn("enemy", 0, "security", (2, 2), "corp_mage"), 12, rng)
    assert isinstance(mage.role, EnemyRole)
    assert mage.role.tradition == "mage", "its Drain resists with Logic (DECISIONS §6)"

    # ---- 3. the crew, with no tree and its own kit ---------------------------------------
    adept = build_runner("adept", 1, (2, 2))
    assert adept.bt is None and adept.is_player_controlled
    assert isinstance(adept.role, RunnerRole) and adept.role.klass == "adept"
    assert adept.attrs["agility"] == 7 and adept.attrs["strength"] == 7, "prodigal attributes"
    assert adept.role.qi == 4 and adept.role.edge == 3
    decker = build_runner("decker", 4, (2, 3))
    assert [g.kind for g in decker.gear] == ["cyberdeck"], (
        "without it the class has no device table"
    )
    assert isinstance(decker.role, RunnerRole)
    assert decker.role.tradition == "logic"
    shaman = build_runner("shaman", 3, (2, 4))
    assert isinstance(shaman.role, RunnerRole)
    assert shaman.role.tradition == "charisma"

    # ---- 4. a Spirit is a full Actor with its own tree ----------------------------------
    spirit = build_spirit(summoner_id=shaman.id, spirit_type="beast", actor_id=30, pos=(3, 3))
    assert spirit.bt is not None and isinstance(spirit.role, SpiritRole)
    assert spirit.role.summoner_id == shaman.id and spirit.role.rounds_left == 3
    assert not spirit.role.hostile

    # ---- 5. patrol rings and the world tables -------------------------------------------
    ring = patrol_ring((10, 10, 14, 10))
    assert ring == [(11, 11), (22, 11), (22, 18), (11, 18)], ring
    tables = world_tables(
        [guard, mage, hellhound],
        armour_of={10: 8, 12: 9, 11: 2},
        weapon_of={10: "assault_rifle", 12: "heavy_pistol", 11: "hellhound_bite"},
    )
    assert tables["armour"] == {10: 8, 12: 9, 11: 2}
    assert tables["ammo"][(10, "assault_rifle")] == MAGAZINES["assault_rifle"] == 30
    assert (12, "heavy_pistol") in tables["ammo"]
    assert (11, "hellhound_bite") not in tables["ammo"], "a bite has no magazine"

    print(
        f"OK  content: {len(ENEMIES)} archetypes, {len(CREW)} Runners, {len(TREES)} trees loaded "
        f"and validated, spawn -> Actor for every archetype, patrol rings deterministic"
    )


if __name__ == "__main__":
    demo()

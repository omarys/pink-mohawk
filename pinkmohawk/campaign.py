"""Persistent campaign state: the half of ADR-0012's two state graphs that carries forward.

ADR-0012 keeps two state graphs and one save file, and the split is the whole design: a Run is
generated and thrown away, while the crew and the world move on. This module is the half that moves
on — crew sheets with their condition monitors, loadout and stash, nuyen, Heat and both reputations,
the Hub day, the Job board and the active Job — plus the JSON document world.md §10.4 fixes for it.

It is also the Dialogue Graph's shared variable store (dialogue.md §5). That document fixes the
accessor names and section 5.2 fixes which keys persist and where; the mapping lives here, in one
place, because a variable with two homes is how a save and a live game come to disagree.

Three things are deliberately *not* owned here, and a subsystem that holds them declares and sets
them here like any other key:

- `clock` and `npc.*` are Run-scoped facts — the Security Clock and an actor's Blackboard. Nothing in
  this module invents them, and nothing here could: this module has no Site.
- The dice behind `test.<key>.hits/.net/.glitch`. Dialogue rolls them; this stores the result so a
  later condition can read it.
- `tick_clock`. A Clock tick is a Site event, and `security.Clock` owns it.

Job-scoped *results* (`test.*`) are held in memory rather than saved. world.md §10.5 saves at the
safehouse and after payout only, so a conversation can never straddle a save and those values never
need to survive one. The Job facts the Fixer's board reads back after a load — `state`, `accepted`,
the negotiated figure, the authoring flags and the effect ledger — do persist, on `job.active`.

Two spellings of a class meet here. DECISIONS §7 names them ("Physical Adept"), `entities.CLASSES`
keys them ("adept"), and world.md §10.4's example writes `"id": "adept", "class": "physical_adept"`.
`SAVE_CLASS` below is the one mapping between the two, and the save speaks §7's slugs.

Layer 3: imports `content`, `entities`, `rng`, `security` and `constants`. No tcod.

    .venv/bin/python -m pinkmohawk.campaign      # the acceptance test
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final

from . import content, security
from . import rng as rng_mod
from .constants import (
    ATTRIBUTES,
    BASE_PAYOUT,
    FAVOUR_CLOCK_CREDIT,
    FAVOUR_REP_COST,
    GEAR_PRICES,
    HEAT_MAX,
    HEAT_START,
    HUB_DAY_START,
    HUB_RECOVER_BOXES_PER_DAY,
    JOB_OFFER_ROTATION_DAYS,
    JOB_OFFERS,
    JOB_TYPE_MULT,
    PAYOUT_PER_NET_NEGOTIATION_HIT,
    REP_DELTA_MAX,
    REP_MAX,
    REP_MIN,
    SKILLS,
    STARTING_NUYEN,
)
from .entities import CLASSES, RunnerRole, monitor_max
from .errors import RuntimeFailure, ValidationError

#: world.md §10.4 owns this string, and `save.load` refuses a file written under a different one:
#: the note exists so a platform RNG change is detectable rather than silent.
RNG_NOTE: Final = "random.Random/CPython"

#: DECISIONS §7's class names, spelled as world.md §10.4's example spells them.
SAVE_CLASS: Final = {
    "adept": "physical_adept",
    "mage": "mage",
    "shaman": "shaman",
    "decker": "decker",
}
ENGINE_CLASS: Final = {save: engine for engine, save in SAVE_CLASS.items()}

#: dialogue.md §5's `job.state` vocabulary.
JOB_STATES: Final = ("offered", "accepted", "active", "complete", "failed")

#: roadmap Phase 2 non-goal: "no additional Job types beyond paydata extraction". The other three
#: multipliers are in the contract so Phase 3 only has to extend this tuple.
OFFER_TYPES: Final = ("extraction",)

SCOPE_WORLD: Final = "world"
SCOPE_JOB: Final = "job"
SCOPE_RUN: Final = "run"

_REP_FACTION: Final = "rep.faction."


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clamp_rep(value: int) -> int:
    """dialogue.md Open question 3: `rep.*` is clamped, so a conversation cannot run away with it."""
    return max(REP_MIN, min(REP_MAX, value))


def _type_ok(value: Any, kind: Any) -> bool:
    """`bool` is an `int` subclass, so an int field must reject it explicitly: `True` is not a rating."""
    if kind is int:
        return type(value) is int
    return isinstance(value, kind)


@dataclass(slots=True)
class Perk:
    """A Perk and the obstacle that paid it (ADR-0006 pays each obstacle exactly once)."""

    id: str
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "source": self.source}

    @classmethod
    def from_dict(cls, doc: Mapping[str, Any]) -> Perk:
        return cls(str(doc["id"]), str(doc["source"]))


@dataclass(slots=True)
class RunnerSheet:
    """One Runner's persistent sheet (§10.1): what the Run is built from, not the Run itself.

    `attributes` holds the eight engine attributes and `edge` is separate, because the Edge *rating*
    is the sheet's and the Edge *points* reset every Run (§14 item 19). world.md §10.4's example
    writes edge inside `attributes`; `to_dict` merges it there and `from_dict` takes it back out, so
    both spellings agree about which number is the rating.
    """

    id: str
    klass: str
    attributes: dict[str, int]
    skills: dict[str, int]
    edge: int
    xp: int
    perks: list[Perk]
    stun: int
    physical: int
    loadout: list[str]
    totem: str | None = None

    @classmethod
    def opening(cls, slug: str) -> RunnerSheet:
        """The opening sheet for one Runner, read off the Actor Phase 1 spawns.

        `content.build_runner` is the single source for a Runner's starting numbers, so the Hub and a
        Run cannot disagree about them; the defaults it fills (`dict.fromkeys(ATTRIBUTES, 3)`) arrive
        with it rather than being restated here.
        """
        if slug not in CLASSES:
            raise ValidationError([f"unknown class {slug!r}; known: {list(CLASSES)}"])
        actor = content.build_runner(slug, 0, (0, 0))
        role = actor.role
        if not isinstance(role, RunnerRole):
            raise RuntimeFailure([f"crew.json built {slug} without a RunnerRole"])
        return cls(
            id=slug,
            klass=slug,
            attributes={name: int(actor.attrs[name]) for name in ATTRIBUTES},
            skills={name: int(rating) for name, rating in actor.skills.items()},
            edge=role.edge,
            xp=role.xp,
            perks=[],
            stun=actor.stun.filled,
            physical=actor.physical.filled,
            loadout=[item.slug for item in role.inventory],
            totem=None,
        )

    @property
    def physical_max(self) -> int:
        return monitor_max(self.attributes["body"])

    @property
    def stun_max(self) -> int:
        return monitor_max(self.attributes["willpower"])

    def to_dict(self) -> dict[str, Any]:
        attributes = {name: self.attributes[name] for name in ATTRIBUTES}
        attributes["edge"] = self.edge
        return {
            "id": self.id,
            "class": SAVE_CLASS[self.klass],
            "attributes": attributes,
            "skills": dict(self.skills),
            "xp": self.xp,
            "perks": [perk.to_dict() for perk in self.perks],
            "condition": {"stun": self.stun, "physical": self.physical},
            "loadout": list(self.loadout),
            "totem": self.totem,
        }

    @classmethod
    def from_dict(cls, doc: Mapping[str, Any], *, complaints: list[str]) -> RunnerSheet:
        """Build one sheet, appending anything wrong to `complaints` rather than raising per field."""
        where = f"crew.runners[{doc.get('id', '?')}]"
        save_class = doc.get("class")
        if save_class not in ENGINE_CLASS:
            complaints.append(
                f"{where}: class {save_class!r} is not one of {sorted(SAVE_CLASS.values())} "
                f"(DECISIONS §7's names)"
            )
            raise ValidationError(complaints)
        raw_attrs = dict(doc.get("attributes") or {})
        attributes = {}
        for name in ATTRIBUTES:
            if name not in raw_attrs:
                complaints.append(f"{where}: attribute {name!r} is missing")
            attributes[name] = int(raw_attrs.get(name, 0))
        condition = dict(doc.get("condition") or {})
        perks = [Perk.from_dict(entry) for entry in doc.get("perks") or []]
        sheet = cls(
            id=str(doc.get("id", save_class)),
            klass=ENGINE_CLASS[save_class],
            attributes=attributes,
            skills={name: int(rating) for name, rating in (doc.get("skills") or {}).items()},
            edge=int(raw_attrs.get("edge", 0)),
            xp=int(doc.get("xp", 0)),
            perks=perks,
            stun=int(condition.get("stun", 0)),
            physical=int(condition.get("physical", 0)),
            loadout=[str(item) for item in doc.get("loadout") or []],
            totem=doc.get("totem"),
        )
        if sheet.physical > sheet.physical_max or sheet.stun > sheet.stun_max:
            complaints.append(
                f"{where}: monitors {sheet.physical}/{sheet.physical_max} and "
                f"{sheet.stun}/{sheet.stun_max} are past their maximum (DECISIONS §4)"
            )
        return sheet


@dataclass(slots=True)
class StashEntry:
    """The shared stash keeps counts, where a loadout is a plain list (§10.1)."""

    item: str
    count: int

    def to_dict(self) -> dict[str, Any]:
        return {"item": self.item, "count": self.count}


@dataclass(slots=True)
class JobOffer:
    """One Job on the board (§10.4). `attempts` counts Runs started against it, for the seed."""

    id: str
    job_type: str
    payout_base: int
    attempts: int = 0

    def to_dict(self) -> dict[str, Any]:
        # `attempts` is this module's addition to §10.4's example: without it a retry after a load
        # would re-derive the first attempt's seed and walk the same Site twice.
        return {
            "id": self.id,
            "type": self.job_type,
            "payout_base": self.payout_base,
            "attempts": self.attempts,
        }


@dataclass(slots=True)
class ActiveJob:
    """The Job being worked (§10.4's `job.active`), including what the Fixer's board reads back."""

    id: str
    job_type: str
    run_counter: int
    run_seed: int
    scout: int = 0
    buy_gear: int = 0
    favour: int = 0
    clock_credit: int = 0
    state: str = "offered"
    accepted: bool = False
    payout_base: int = 0
    payout_agreed: int = 0
    intel_scouted: bool = False
    flags: dict[str, bool] = field(default_factory=dict)
    ledger: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.job_type,
            "run_counter": self.run_counter,
            "run_seed": self.run_seed,
            "legwork": {"scout": self.scout, "buy_gear": self.buy_gear, "favour": self.favour},
            "clock_credit": self.clock_credit,
            "state": self.state,
            "accepted": self.accepted,
            "payout_base": self.payout_base,
            "payout_agreed": self.payout_agreed,
            "intel_scouted": self.intel_scouted,
            "flags": dict(self.flags),
            "ledger": list(self.ledger),
        }

    @classmethod
    def from_dict(cls, doc: Mapping[str, Any], *, complaints: list[str]) -> ActiveJob:
        legwork = dict(doc.get("legwork") or {})
        state = str(doc.get("state", "offered"))
        if state not in JOB_STATES:
            complaints.append(f"job.active.state {state!r} is not one of {list(JOB_STATES)}")
        payout_base = int(doc.get("payout_base", 0))
        active = cls(
            id=str(doc["id"]),
            job_type=str(doc["type"]),
            run_counter=int(doc.get("run_counter", 0)),
            run_seed=int(doc["run_seed"]),
            scout=int(legwork.get("scout", 0)),
            buy_gear=int(legwork.get("buy_gear", 0)),
            favour=int(legwork.get("favour", 0)),
            clock_credit=int(doc.get("clock_credit", 0)),
            state=state,
            accepted=bool(doc.get("accepted", False)),
            payout_base=payout_base,
            payout_agreed=int(doc.get("payout_agreed", payout_base)),
            intel_scouted=bool(doc.get("intel_scouted", False)),
            flags={str(k): bool(v) for k, v in (doc.get("flags") or {}).items()},
            ledger=[str(entry) for entry in doc.get("ledger") or []],
        )
        return active


@dataclass(slots=True)
class Variable:
    """One declared store key (dialogue.md §5.2): its default, type, scope and write rule."""

    key: str
    default: Any
    kind: Any
    scope: str
    writable: bool
    raise_only: bool = False
    value: Any = None


@dataclass(frozen=True, slots=True)
class Snapshot:
    """The store as it was when an effects array began (dialogue.md §3.3 step 3).

    Frozen on purpose: `{"set": "a", "expr": "b"}` then `{"set": "b", "expr": "a"}` is a swap rather
    than a chained assignment, so every right-hand side reads this and never the live store.
    """

    values: Mapping[str, Any]
    items: frozenset[str]

    def get(self, key: str) -> Any:
        if key not in self.values:
            raise ValidationError(
                [f"{key!r} is not declared in this conversation (dialogue.md §5)"]
            )
        return self.values[key]

    def has_item(self, item_id: str) -> bool:
        return item_id in self.items

    def set(self, key: str, value: Any) -> None:
        raise RuntimeFailure([f"a snapshot is read-only; {key!r} must be written to the store"])


@dataclass(slots=True)
class CampaignState:
    """Crew, world and Job state that outlives a Run, and the store dialogue reads (ADR-0012)."""

    seed: int
    runners: list[RunnerSheet]
    job_count: int = 0
    hub_day: int = HUB_DAY_START
    advance_log: list[dict[str, Any]] = field(default_factory=list)
    nuyen: int = STARTING_NUYEN
    stash: list[StashEntry] = field(default_factory=list)
    heat: int = HEAT_START
    rep_fixer: int = 0
    rep_factions: dict[str, int] = field(default_factory=dict)
    flags: dict[str, bool] = field(default_factory=dict)
    active: ActiveJob | None = None
    offers: list[JobOffer] = field(default_factory=list)
    _vars: dict[str, Variable] = field(default_factory=dict, repr=False)
    _pc: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self._declare_owned()

    # -- the variable store (dialogue.md §5) ------------------------------------------------------
    def declare(
        self,
        key: str,
        default: Any,
        scope: str = SCOPE_JOB,
        *,
        writable: bool = False,
        raise_only: bool = False,
        kind: Any = None,
    ) -> None:
        """Seed a key, and never overwrite one: the loader declares every key in §5's table, and the
        state has already declared the ones it owns."""
        if key in self._vars:
            return
        self._vars[key] = Variable(
            key=key,
            default=default,
            kind=kind if kind is not None else type(default),
            scope=scope,
            writable=writable,
            raise_only=raise_only,
            value=default,
        )

    def get(self, key: str) -> Any:
        """§5.2: an undeclared key is an error, never a quiet default."""
        if key.startswith("skill."):
            return self._skill(key[len("skill.") :])
        if key.startswith("attr."):
            return self._attribute(key[len("attr.") :])
        if key.startswith(_REP_FACTION):
            return self.rep_factions.get(key[len(_REP_FACTION) :], 0)  # unknown faction is neutral
        if key.startswith("flags."):
            return self._flag_read(key)
        if key.startswith("job."):
            return self._job_read(key)
        if key == "heat":
            return self.heat
        if key == "rep.fixer":
            return self.rep_fixer
        if key == "crew.nuyen":
            return self.nuyen
        if key in self._vars:
            return self._vars[key].value
        raise ValidationError([f"{key!r} is not declared; dialogue.md §5 owns the key list"])

    def set(self, key: str, value: Any) -> None:
        """§5.2: unknown, read-only or wrongly typed raises rather than writing."""
        if key.startswith(_REP_FACTION):
            # A wildcard namespace (dialogue.md §5.2): any id is legal, and an unknown one is neutral.
            if not _type_ok(value, int):
                raise ValidationError([f"{key!r} is an integer reputation, got {value!r}"])
            faction = key[len(_REP_FACTION) :]
            if not faction:
                raise ValidationError(["a faction id may not be empty"])
            self.rep_factions[faction] = _clamp_rep(int(value))
            return
        if key.startswith("flags."):
            var = self._var(key)
            self._check(var, value)
            self._require_active(f"set({key!r})").flags[key[len("flags.") :]] = bool(value)
            return
        if key.startswith("job."):
            var = self._var(key)
            self._check(var, value)
            self._job_write(key, value)
            return
        if key in ("heat", "rep.fixer", "crew.nuyen"):
            var = self._var(key)
            self._check(var, value)
            if key == "heat":
                raise ValidationError(["'heat' is read-only to dialogue (dialogue.md §5)"])
            if key == "rep.fixer":
                self.rep_fixer = _clamp_rep(int(value))
            else:
                if int(value) < 0:
                    raise ValidationError([f"crew.nuyen cannot go below zero, got {value!r}"])
                self.nuyen = int(value)
            return
        var = self._var(key)
        self._check(var, value)
        if var.raise_only:
            value = max(int(var.value), int(value))
        var.value = value

    def snapshot(self) -> Snapshot:
        """Every declared key's value, frozen, for the duration of one effects array."""
        values: dict[str, Any] = {}
        for key, var in self._vars.items():
            values[key] = var.value
        for key in ("heat", "rep.fixer", "crew.nuyen"):
            values[key] = self.get(key)
        if self.active is not None:
            for key in (
                "job.id",
                "job.type",
                "job.payout_base",
                "job.payout_agreed",
                "job.accepted",
                "job.state",
                "job.intel_scouted",
            ):
                values[key] = self._job_read(key)
        for sheet in self.runners:
            values.update({f"skill.{name}": rating for name, rating in sheet.skills.items()})
            values.update({f"attr.{name}": rating for name, rating in sheet.attributes.items()})
            values["attr.edge"] = sheet.edge
        return Snapshot(values=values, items=self._owned_items())

    def has_item(self, item_id: str) -> bool:
        """§5.2: a loadout item or anything in the shared stash. The evaluator's one function call."""
        return item_id in self._owned_items()

    def bind_pc(self, runner_id: str) -> None:
        """Bind the acting Runner, whose sheet `skill.*` and `attr.*` read."""
        if not any(sheet.id == runner_id for sheet in self.runners):
            raise ValidationError([f"no Runner {runner_id!r} in the crew"])
        self._pc = runner_id

    def reset_scope(self, scope: str) -> None:
        """§10.2 resets Run-scoped keys between Runs; §5.1 clears Job-scoped ones at Extraction."""
        if scope not in (SCOPE_WORLD, SCOPE_JOB, SCOPE_RUN):
            raise ValidationError([f"unknown scope {scope!r}"])
        for var in self._vars.values():
            if var.scope == scope:
                var.value = var.default

    # -- the six effects that touch campaign state (dialogue.md §3.1) ------------------------------
    def give_item(self, item_id: str, qty: int = 1) -> None:
        """§3.1: appends to the Crew's inventory. The shared stash is that inventory (§10.1)."""
        if not item_id:
            raise ValidationError(["give_item needs an item id"])
        self.add_to_stash(item_id, qty)

    def add_to_stash(self, item_id: str, qty: int = 1) -> None:
        """The other half of a shop purchase, and where `give_item` lands."""
        if type(qty) is not int or qty < 1:
            raise ValidationError([f"quantity must be a positive integer, got {qty!r}"])
        for entry in self.stash:
            if entry.item == item_id:
                entry.count += qty
                return
        self.stash.append(StashEntry(item=item_id, count=qty))

    def start_job(self) -> None:
        """§3.1's `start_job`: the Job stops being an offer and the Fixer's board shows it taken."""
        active = self._require_active("start_job")
        active.accepted = True
        active.state = "accepted"

    def change_rep(self, who: str, delta: int) -> None:
        """§3.1: `fixer` or `faction:<id>`, a non-zero integer with `abs(delta) <= REP_DELTA_MAX`."""
        if type(delta) is not int or delta == 0 or abs(delta) > REP_DELTA_MAX:
            raise ValidationError(
                [
                    f"change_rep delta {delta!r}: must be a non-zero integer, abs at most {REP_DELTA_MAX}"
                ]
            )
        if who == "fixer":
            self.rep_fixer = _clamp_rep(self.rep_fixer + delta)
        elif who.startswith("faction:") and who.split(":", 1)[1]:
            faction = who.split(":", 1)[1]
            self.rep_factions[faction] = _clamp_rep(self.rep_factions.get(faction, 0) + delta)
        else:
            raise ValidationError([f"change_rep who {who!r} must be 'fixer' or 'faction:<id>'"])

    # -- the Job board and the Job lifecycle -------------------------------------------------------
    def roll_offers(self) -> list[JobOffer]:
        """§10.4's `job.offers`: JOB_OFFERS offers from the Hub's own derived stream (§5.5).

        Ids are numbered from `job_count`, so a re-posted Job keeps its id and its Site while an
        already-completed id is never issued again.
        """
        stream = random.Random(rng_mod.derive(self.seed, f"hub:{self.hub_day}:jobs"))
        attempts = {entry.id: entry.attempts for entry in self.offers}
        offers = []
        for index in range(JOB_OFFERS):
            job_type = stream.choice(OFFER_TYPES)
            job_id = f"job_{self.job_count + index + 1:03d}"
            offers.append(
                JobOffer(
                    id=job_id,
                    job_type=job_type,
                    payout_base=round(BASE_PAYOUT * JOB_TYPE_MULT[job_type]),
                    attempts=attempts.get(job_id, 0),  # a re-posted Job keeps its attempt count
                )
            )
        self.offers = offers
        return self.offers

    def begin_job(self, offer_id: str) -> ActiveJob:
        """Depart. The seed is derived once from `(job id, attempt)` and then stored (§10.4, §14.12).

        `run_counter` counts attempts at this Job, so a retry walks a different Site and the counter
        is what changes it (roadmap Phase 2, acceptance point 5).
        """
        if self.active is not None:
            raise ValidationError([f"Job {self.active.id} is already active"])
        offer = next((entry for entry in self.offers if entry.id == offer_id), None)
        if offer is None:
            raise ValidationError([f"no Job {offer_id!r} on the board"])
        offer.attempts += 1
        self.active = ActiveJob(
            id=offer.id,
            job_type=offer.job_type,
            run_counter=offer.attempts,
            run_seed=rng_mod.run_seed(self.seed, offer.id, offer.attempts),
            payout_base=offer.payout_base,
            payout_agreed=offer.payout_base,
        )
        self.reset_scope(SCOPE_JOB)
        return self.active

    def apply_extraction(self, extraction: security.Extraction) -> None:
        """The one place a Run's consequences touch the campaign.

        `security.py` computes all three; this applies them, so no caller can apply two of the three
        or apply one twice. A forced extraction fails the Job and leaves the offer on the board for a
        retry; a voluntary one completes it and takes it off (§16: Extraction writes `job.state`).
        """
        active = self._require_active("apply_extraction")
        self.nuyen += extraction.payout
        self.heat += extraction.heat_delta  # security.heat_after already clamps to [0, HEAT_MAX]
        self.rep_fixer = _clamp_rep(self.rep_fixer + extraction.reputation_delta)
        active.state = "failed" if extraction.forced else "complete"
        self.job_count += 1
        if not extraction.forced:
            self.offers = [entry for entry in self.offers if entry.id != active.id]
        self.active = None
        self.reset_scope(SCOPE_JOB)

    # -- Legwork (world.md §3): the three actions' state transitions -------------------------------
    def legwork_scout(self) -> None:
        """§3.1: node types on the Mission Graph become visible to the player."""
        active = self._require_active("legwork_scout")
        active.scout += 1
        active.intel_scouted = True

    def legwork_buy_gear(self, item_id: str, price: int, qty: int = 1) -> None:
        """§3.2: a shop purchase made before Depart."""
        active = self._require_active("legwork_buy_gear")
        self.spend_nuyen(price * qty)
        self.add_to_stash(item_id, qty)
        active.buy_gear += 1

    def legwork_favour(self) -> None:
        """§3.3: `FAVOUR_REP_COST` of Fixer standing buys `FAVOUR_CLOCK_CREDIT` Clock segments."""
        active = self._require_active("legwork_favour")
        if self.rep_fixer < FAVOUR_REP_COST:
            raise ValidationError(
                [
                    f"a Favour costs {FAVOUR_REP_COST} Fixer reputation; the crew has {self.rep_fixer}"
                ]
            )
        self.rep_fixer -= FAVOUR_REP_COST
        active.favour += 1
        active.clock_credit += FAVOUR_CLOCK_CREDIT

    # -- Hub time: money, rest and the day ---------------------------------------------------------
    def spend_nuyen(self, amount: int) -> None:
        if type(amount) is not int or amount < 0:
            raise ValidationError([f"cannot spend {amount!r}"])
        if amount > self.nuyen:
            raise ValidationError([f"costs {amount}¥, the crew has {self.nuyen}¥"])
        self.nuyen -= amount

    def heal(self, runner_id: str, boxes: int) -> int:
        """Unmark boxes, Stun first then Physical (`[P2]`'s ordering), and return boxes healed."""
        if type(boxes) is not int or boxes < 0:
            raise ValidationError([f"cannot heal {boxes!r} boxes"])
        sheet = next((entry for entry in self.runners if entry.id == runner_id), None)
        if sheet is None:
            raise ValidationError([f"no Runner {runner_id!r} in the crew"])
        healed = min(boxes, sheet.stun)
        sheet.stun -= healed
        rest = min(boxes - healed, sheet.physical)
        sheet.physical -= rest
        return healed + rest

    def advance_day(self) -> None:
        """One Hub day (§1.3): the day advances, the crew rests `[P2]`, the board rotates `[P4]`."""
        self.hub_day += 1
        for sheet in self.runners:
            self.heal(sheet.id, HUB_RECOVER_BOXES_PER_DAY)
        if self.hub_day % JOB_OFFER_ROTATION_DAYS == 0:
            self.roll_offers()

    def mark_flag(self, name: str, value: bool = True) -> None:
        """A *world* flag — persisted, and distinct from a conversation's Job-scoped `flags.*`."""
        self.flags[name] = value

    # -- the save document (world.md §10.4) --------------------------------------------------------
    def to_save_dict(self, schema_version: int, *, saved_at: str | None = None) -> dict[str, Any]:
        """§10.4's document, key for key. `schema_version` is `save.py`'s to own."""
        return {
            "schema_version": schema_version,
            "saved_at": saved_at or _now_iso(),
            "rng_note": RNG_NOTE,
            "campaign": {
                "seed": self.seed,  # see from_save_dict: rng.campaign_seed() says to store this
                "job_count": self.job_count,
                "hub_day": self.hub_day,
                "advance_log": [dict(entry) for entry in self.advance_log],
            },
            "crew": {
                "nuyen": self.nuyen,
                "runners": [sheet.to_dict() for sheet in self.runners],
                "stash": [entry.to_dict() for entry in self.stash],
            },
            "world": {
                "heat": self.heat,
                "rep": {"fixer": self.rep_fixer, "factions": dict(self.rep_factions)},
                "flags": dict(self.flags),
            },
            "job": {
                "active": None if self.active is None else self.active.to_dict(),
                "offers": [entry.to_dict() for entry in self.offers],
            },
        }

    @classmethod
    def from_save_dict(cls, doc: Mapping[str, Any]) -> CampaignState:
        """The inverse. Collects every complaint and raises once, the way `content` loads its files.

        `campaign.seed` is not in §10.4's example, and it has to be stored: `rng.campaign_seed` says
        "Create the root seed once, at campaign start. Store it on the save", and without it a loaded
        campaign cannot derive another Run's seed or the Hub's own draws.
        """
        complaints: list[str] = []
        for root in ("campaign", "crew", "world", "job"):
            if root not in doc:
                complaints.append(f"the save has no {root!r} root (world.md §10.4)")
        if complaints:
            raise ValidationError(complaints)
        campaign = dict(doc["campaign"])
        crew = dict(doc["crew"])
        world = dict(doc["world"])
        job = dict(doc["job"])
        if "seed" not in campaign:
            complaints.append(
                "campaign.seed is missing: the save must store the root seed (rng.campaign_seed)"
            )
        rep = dict(world.get("rep") or {})
        active = job.get("active")
        runners = [
            RunnerSheet.from_dict(dict(entry), complaints=complaints)
            for entry in crew.get("runners") or []
        ]
        offers = [
            JobOffer(
                id=str(entry["id"]),
                job_type=str(entry["type"]),
                payout_base=int(entry.get("payout_base", 0)),
                attempts=int(entry.get("attempts", 0)),
            )
            for entry in job.get("offers") or []
        ]
        state = cls(
            seed=int(campaign.get("seed", 0)),
            runners=runners,
            job_count=int(campaign.get("job_count", 0)),
            hub_day=int(campaign.get("hub_day", HUB_DAY_START)),
            advance_log=[dict(entry) for entry in campaign.get("advance_log") or []],
            nuyen=int(crew.get("nuyen", STARTING_NUYEN)),
            stash=[
                StashEntry(item=str(entry["item"]), count=int(entry.get("count", 1)))
                for entry in crew.get("stash") or []
            ],
            heat=int(world.get("heat", HEAT_START)),
            rep_fixer=int(rep.get("fixer", 0)),
            rep_factions={str(k): int(v) for k, v in (rep.get("factions") or {}).items()},
            flags={str(k): bool(v) for k, v in (world.get("flags") or {}).items()},
            active=None
            if active is None
            else ActiveJob.from_dict(dict(active), complaints=complaints),
            offers=offers,
        )
        if state.heat < 0 or state.heat > HEAT_MAX:
            complaints.append(f"world.heat {state.heat} is outside 0..{HEAT_MAX} (world.md §8.4)")
        if complaints:
            raise ValidationError(complaints)
        return state

    # -- internals --------------------------------------------------------------------------------
    def _declare_owned(self) -> None:
        """The keys §5's table gives to campaign state, with the write rules it states."""
        for key, default, scope, writable in (
            ("heat", HEAT_START, SCOPE_WORLD, False),
            ("rep.fixer", 0, SCOPE_WORLD, True),
            ("crew.nuyen", STARTING_NUYEN, SCOPE_WORLD, True),
            ("job.id", "", SCOPE_JOB, False),
            ("job.type", "", SCOPE_JOB, False),
            ("job.payout_base", 0, SCOPE_JOB, False),
            ("job.payout_agreed", 0, SCOPE_JOB, True),
            ("job.accepted", False, SCOPE_JOB, True),
            ("job.state", "offered", SCOPE_JOB, True),
            ("job.intel_scouted", False, SCOPE_JOB, False),
        ):
            self.declare(key, default, scope, writable=writable)

    def _var(self, key: str) -> Variable:
        """The declared entry for a key, or a refusal. The declaration carries its own type and rule."""
        var = self._vars.get(key)
        if var is None:
            raise ValidationError([f"{key!r} is not declared; dialogue.md §5 owns the key list"])
        return var

    def _check(self, var: Variable, value: Any) -> None:
        if not var.writable:
            raise ValidationError([f"{var.key!r} is read-only to dialogue (dialogue.md §5)"])
        if not _type_ok(value, var.kind):
            raise ValidationError(
                [f"{var.key!r} is {getattr(var.kind, '__name__', var.kind)}, got {value!r}"]
            )

    def _pc_sheet(self) -> RunnerSheet:
        if self._pc is None:
            raise ValidationError(
                ["no Runner is bound; bind_pc() before reading skill.* or attr.*"]
            )
        sheet = next((entry for entry in self.runners if entry.id == self._pc), None)
        if sheet is None:
            raise RuntimeFailure([f"the bound Runner {self._pc!r} left the crew"])
        return sheet

    def _skill(self, name: str) -> int:
        if name not in SKILLS:
            raise ValidationError([f"unknown skill {name!r}; DECISIONS §2 lists {sorted(SKILLS)}"])
        return self._pc_sheet().skills.get(name, 3)  # content.py's default for an unrated skill

    def _attribute(self, name: str) -> int:
        sheet = self._pc_sheet()
        if name == "edge":
            return sheet.edge
        if name not in ATTRIBUTES:
            raise ValidationError(
                [f"unknown attribute {name!r}; DECISIONS §1 lists {list(ATTRIBUTES)}"]
            )
        return sheet.attributes[name]

    def _flag_read(self, key: str) -> bool:
        """§5.2 maps `flags.*` to the Job record; the declared entry is the file's `vars` default."""
        name = key[len("flags.") :]
        if self.active is not None and name in self.active.flags:
            return self.active.flags[name]
        if key in self._vars:
            return self._vars[key].value
        raise ValidationError([f"{key!r} is not declared; dialogue.md §5 owns the key list"])

    def _job_read(self, key: str) -> Any:
        if self.active is None:
            raise ValidationError(
                [f"{key!r} needs a bound Job, and none is active (dialogue.md §5)"]
            )
        field_name = {
            "job.id": "id",
            "job.type": "job_type",
            "job.payout_base": "payout_base",
            "job.payout_agreed": "payout_agreed",
            "job.accepted": "accepted",
            "job.state": "state",
            "job.intel_scouted": "intel_scouted",
        }.get(key)
        if field_name is None:
            raise ValidationError([f"{key!r} is not one of dialogue.md §5's Job variables"])
        return getattr(self.active, field_name)

    def _job_write(self, key: str, value: Any) -> None:
        active = self._require_active(f"set({key!r})")
        if key == "job.payout_agreed":
            active.payout_agreed = int(value)
        elif key == "job.accepted":
            active.accepted = bool(value)
        elif key == "job.state":
            if value not in JOB_STATES:
                raise ValidationError([f"job.state {value!r} is not one of {list(JOB_STATES)}"])
            active.state = str(value)
        else:
            raise ValidationError([f"{key!r} is read-only to dialogue (dialogue.md §5)"])

    def _require_active(self, what: str) -> ActiveJob:
        if self.active is None:
            raise ValidationError([f"{what} needs a bound Job, and none is active"])
        return self.active

    def _owned_items(self) -> frozenset[str]:
        """Everything the crew is carrying: loadout items and anything in the stash.

        A frozenset rather than a `set[...]` annotation, because this class has a method named `set`
        and inside its body that name is the method, not the builtin (mypy says so first).
        """
        items = [item for sheet in self.runners for item in sheet.loadout]
        items.extend(entry.item for entry in self.stash if entry.count > 0)
        return frozenset(items)


def new_campaign(seed: int | None = None) -> CampaignState:
    """A campaign at day one: four Runners, `STARTING_NUYEN`, no Heat, no reputation, three offers.

    `seed` defaults to `rng.campaign_seed()`, which is the one number that makes every Site in the
    campaign reproducible; the save stores it.
    """
    state = CampaignState(
        seed=rng_mod.campaign_seed() if seed is None else seed,
        runners=[RunnerSheet.opening(slug) for slug in CLASSES],
    )
    state.roll_offers()
    return state


# ==============================================================================================
# Acceptance test
# ==============================================================================================
def demo() -> None:
    """The state half of roadmap Phase 2: what persists, what a Job costs, and what dialogue reads."""
    from .save import SCHEMA_VERSION  # save.py owns the version; imported here to avoid a cycle

    state = new_campaign(20260918)

    # ---- 1. the opening campaign ---------------------------------------------------------------
    assert [sheet.id for sheet in state.runners] == list(CLASSES), "all four Runners start"
    assert state.nuyen == STARTING_NUYEN, "STARTING_NUYEN from the contract"
    assert state.heat == HEAT_START == 0
    assert state.hub_day == HUB_DAY_START == 1
    assert state.rep_fixer == 0 and state.rep_factions == {} and state.flags == {}
    assert state.active is None, "nothing is active before Depart"
    assert len(state.offers) == JOB_OFFERS == 3, "JOB_OFFERS [P4]"
    assert {offer.job_type for offer in state.offers} == set(OFFER_TYPES) == {"extraction"}
    assert all(
        offer.payout_base == round(BASE_PAYOUT * JOB_TYPE_MULT["extraction"])
        for offer in state.offers
    ), "payout_base is 12,000 x TYPE_MULT (DECISIONS §16: the negotiation is not in the base)"
    adept = state.runners[0]
    assert adept.attributes["agility"] == 7 and adept.edge == 3, "the sheet is crew.json's numbers"
    assert adept.physical_max == 8 + -(-6 // 2) == 11, "8 + ceil(body/2), DECISIONS §4"
    assert adept.loadout == ["medkit"], "the opening loadout is crew.json's inventory"
    assert len(adept.skills) == len(SKILLS) == 13, "content.build_runner fills every skill"
    assert len(state.runners) == 4 and len({sheet.id for sheet in state.runners}) == 4

    # ---- 2. the store reads through to live state (dialogue.md §5.2) ----------------------------
    state.bind_pc("adept")
    assert state.get("heat") == 0
    assert state.get("rep.fixer") == 0
    assert state.get("rep.faction.corp_arasaka") == 0, "an unknown faction is neutral"
    assert state.get("crew.nuyen") == 5000
    assert state.get("attr.agility") == 7 and state.get("attr.edge") == 3
    assert state.get("skill.close_combat") == 5, "the adept's own rating"
    assert state.get("skill.negotiation") == 3, "unrated skills are 3, as content.py fills them"
    assert state.has_item("medkit") and not state.has_item("katana")
    state.change_rep("fixer", 2)
    state.change_rep("faction:street_kobun", -1)
    assert state.get("rep.fixer") == 2 and state.get("rep.faction.street_kobun") == -1
    assert state.rep_factions["street_kobun"] == -1

    # read-only, undeclared and wrongly typed keys all raise rather than write
    for bad in (
        lambda: state.set("heat", 3),
        lambda: state.get("nope"),
        lambda: state.set("nope", 1),
    ):
        try:
            bad()
        except ValidationError:
            pass
        else:  # pragma: no cover - a failure here is the assert
            raise AssertionError("an illegal store access must raise")
    try:
        state.set("job.accepted", "yes")
    except ValidationError:
        pass
    else:  # pragma: no cover
        raise AssertionError("a bool field must reject a string")
    try:
        state.get("skill.brew_coffee")
    except ValidationError:
        pass
    else:  # pragma: no cover
        raise AssertionError("an unknown skill slug must raise, not read a default")
    state.set("rep.fixer", 99)
    assert state.rep_fixer == REP_MAX, "clamped to +5"
    state.rep_fixer = 0
    try:
        state.change_rep("fixer", 3)
    except ValidationError:
        pass
    else:  # pragma: no cover
        raise AssertionError("change_rep must refuse |delta| > REP_DELTA_MAX")
    try:
        state.change_rep("fixer", 0)
    except ValidationError:
        pass
    else:  # pragma: no cover
        raise AssertionError("a zero delta is not a change")

    # a raise-only key (npc.alert_level, dialogue.md §5.1) can only go up
    state.declare("npc.alert_level", 0, SCOPE_RUN, writable=True, raise_only=True)
    state.set("npc.alert_level", 2)
    state.set("npc.alert_level", 1)
    assert state.get("npc.alert_level") == 2, "a botched bribe escalates and cannot calm"
    state.reset_scope(SCOPE_RUN)
    assert state.get("npc.alert_level") == 0, "Run-scoped keys reset (§10.2)"

    # ---- 3. the snapshot is pre-array, so `a: b` then `b: a` swaps (§3.3 step 3) ------------------
    state.set("crew.nuyen", 1000)
    snap = state.snapshot()
    state.set("crew.nuyen", 2000)
    assert snap.get("crew.nuyen") == 1000, "the snapshot must not follow the live store"
    try:
        snap.set("crew.nuyen", 5)
    except RuntimeFailure:
        pass
    else:  # pragma: no cover
        raise AssertionError("a snapshot is read-only")
    state.set("crew.nuyen", STARTING_NUYEN)

    # ---- 4. a Job: board -> Legwork -> conversation -> Extraction ---------------------------------
    offer = state.offers[0]
    active = state.begin_job(offer.id)
    assert active.run_counter == 1 and active.state == "offered" and not active.accepted
    assert active.run_seed == rng_mod.run_seed(state.seed, offer.id, 1), (
        "the seed is stored (§10.4)"
    )
    agreed = BASE_PAYOUT + 2 * PAYOUT_PER_NET_NEGOTIATION_HIT  # a two-net-hit haggle
    assert state.get("job.payout_base") == BASE_PAYOUT, "the base carries no negotiation"
    assert state.get("job.payout_agreed") == BASE_PAYOUT
    assert state.get("job.state") == "offered"
    state.set("job.payout_agreed", agreed)
    assert state.get("job.payout_agreed") == agreed, "the haggle writes the agreed figure"
    state.start_job()
    assert state.get("job.accepted") is True and state.get("job.state") == "accepted"
    state.legwork_scout()
    assert state.get("job.intel_scouted") is True and active.scout == 1
    jacket = GEAR_PRICES["armoured_jacket"]
    state.legwork_buy_gear("armoured_jacket", jacket)
    assert state.nuyen == STARTING_NUYEN - jacket and state.has_item("armoured_jacket")
    assert active.buy_gear == 1, "the three actions are counted on the Job (world.md §3)"
    state.change_rep("fixer", 1)
    state.legwork_favour()
    assert active.favour == 1 and active.clock_credit == FAVOUR_CLOCK_CREDIT == 2
    assert state.rep_fixer == 0, "a Favour spends FAVOUR_REP_COST of standing"
    try:
        state.legwork_favour()
    except ValidationError:
        pass
    else:  # pragma: no cover
        raise AssertionError("a Favour needs the reputation to pay for it")

    # voluntary extraction: payout, Heat -1 (floor 0), Fixer +1, Job complete and off the board
    before_offers = len(state.offers)
    nuyen_before = state.nuyen
    state.heat = 5
    state.apply_extraction(
        security.Extraction(payout=agreed, heat_delta=-1, reputation_delta=1, forced=False)
    )
    assert state.nuyen == nuyen_before + agreed, "12,000¥ + 100 × net hits reached the crew"
    assert state.heat == 4, "-1 per successful Job"
    assert state.rep_fixer == 1, "0 after the Favour, then +1 for a voluntary extraction"
    assert state.job_count == 1 and state.active is None
    assert len(state.offers) == before_offers - 1, "a completed Job leaves the board"

    # forced extraction: pays zero, Heat +2, Fixer -1, and the offer stays for a retry
    second = state.offers[0]
    state.begin_job(second.id)
    state.apply_extraction(
        security.Extraction(payout=0, heat_delta=2, reputation_delta=-1, forced=True)
    )
    assert state.get("heat") == 6 and state.rep_fixer == 0, "+2 Heat, -1 Fixer"
    assert state.job_count == 2
    assert any(entry.id == second.id for entry in state.offers), "a failed Job can be retried"
    again = state.begin_job(second.id)
    assert again.run_counter == 2, "the second attempt increments the counter"
    assert again.run_seed != rng_mod.run_seed(state.seed, second.id, 1), "so the Site differs"
    state.apply_extraction(
        security.Extraction(payout=0, heat_delta=2, reputation_delta=-1, forced=True)
    )

    # ---- 5. Heat's floor and ceiling are security.py's, so this applies its deltas rather than
    #          clamping again: at the extremes heat_after already returns a zero delta ----------------
    state.heat = 0
    floor_delta = security.heat_after(0, success=True) - 0
    assert floor_delta == 0, "a successful Job at zero Heat cannot cool further"
    state.begin_job(state.offers[0].id)  # an Extraction always closes a Job
    state.apply_extraction(
        security.Extraction(payout=0, heat_delta=floor_delta, reputation_delta=0, forced=False)
    )
    assert state.heat == 0, "floor 0"
    state.heat = HEAT_MAX
    ceiling_delta = security.heat_after(HEAT_MAX, success=False, forced=True) - HEAT_MAX
    assert ceiling_delta == 0, "a forced extraction at the ceiling adds nothing"
    state.begin_job(state.offers[0].id)
    state.apply_extraction(
        security.Extraction(payout=0, heat_delta=ceiling_delta, reputation_delta=0, forced=True)
    )
    assert state.heat == HEAT_MAX, "ceiling HEAT_MAX"

    # ---- 6. a Hub day: rest heals Stun first, and the board rotates every [P4] days ----------------
    state.runners[0].stun, state.runners[0].physical = 1, 2
    state.roll_offers()
    ids_before = [offer.id for offer in state.offers]
    day_before = state.hub_day
    state.advance_day()
    assert state.hub_day == day_before + 1
    assert (state.runners[0].stun, state.runners[0].physical) == (0, 1), "2 boxes: Stun first"
    assert [offer.id for offer in state.offers] == ids_before, "the board holds until [P4]'s day"
    while state.hub_day % JOB_OFFER_ROTATION_DAYS:
        state.advance_day()
    # Phase 2 posts one Job type, so a rotation cannot be seen in the offers themselves until
    # Phase 3 adds the other three; what is asserted is that the day and the rotation both happened.
    assert len(state.offers) == JOB_OFFERS, "the board rotated"

    # ---- 7. the save document round-trips every persisted group ------------------------------------
    # The common case first: a save with no Job active, which is what the safehouse writes.
    idle = CampaignState.from_save_dict(state.to_save_dict(SCHEMA_VERSION))
    assert idle.active is None
    assert [offer.id for offer in idle.offers] == [offer.id for offer in state.offers]
    state.runners[1].perks.append(Perk("perk_sure_grip", "lock:job_014:node_sec_2"))
    state.runners[2].stun, state.runners[2].physical = 2, 3
    state.runners[3].totem = "bear"
    state.runners[3].xp = 14
    state.runners[3].loadout.append("armoured_jacket")
    state.mark_flag("met_fixer")
    state.roll_offers()
    state.declare("flags.bribed_the_guard", False, SCOPE_JOB, writable=True)  # the loader's job
    job = state.begin_job(state.offers[1].id)
    state.start_job()  # the Hub accepts before Depart, so a load must show it accepted
    state.legwork_scout()
    state.set("flags.bribed_the_guard", True)
    job.ledger.append("fixer_offer:offer:0")
    doc = state.to_save_dict(SCHEMA_VERSION, saved_at="2026-01-01T00:00:00Z")

    assert doc["schema_version"] == SCHEMA_VERSION == 1
    assert doc["rng_note"] == RNG_NOTE
    assert set(doc) == {
        "schema_version",
        "saved_at",
        "rng_note",
        "campaign",
        "crew",
        "world",
        "job",
    }
    assert set(doc["crew"]) == {"nuyen", "runners", "stash"}
    assert set(doc["world"]) == {"heat", "rep", "flags"}
    assert set(doc["job"]) == {"active", "offers"}
    assert "qi" not in str(doc), "Qi is per-Run and never persisted (§14 item 19)"
    assert doc["crew"]["runners"][0]["class"] == "physical_adept", "§10.4's spelling"
    assert doc["crew"]["runners"][0]["attributes"]["edge"] == 3, "the Edge rating is on the sheet"

    back = CampaignState.from_save_dict(doc)
    assert back.seed == state.seed and back.hub_day == state.hub_day
    assert back.job_count == state.job_count and back.nuyen == state.nuyen
    assert back.heat == state.heat and back.rep_fixer == state.rep_fixer
    assert back.rep_factions == state.rep_factions and back.flags == state.flags
    assert back.stash == state.stash and back.stash, "the bought gear survives"
    assert [sheet.loadout for sheet in back.runners] == [sheet.loadout for sheet in state.runners]
    assert back.runners[1].perks == [Perk("perk_sure_grip", "lock:job_014:node_sec_2")], (
        "with source"
    )
    assert (back.runners[2].stun, back.runners[2].physical) == (2, 3), "monitor boxes persist"
    assert back.runners[3].totem == "bear" and back.runners[3].xp == 14
    assert back.active is not None and state.active is not None
    assert back.active.run_seed == state.active.run_seed, "the Run seed is stored, not recomputed"
    assert back.active.run_counter == state.active.run_counter
    assert back.active.scout == 1 and back.active.state == "accepted"
    assert back.active.flags == {"bribed_the_guard": True} and back.active.ledger == [
        "fixer_offer:offer:0"
    ]
    assert [offer.id for offer in back.offers] == [offer.id for offer in state.offers]
    assert back.to_save_dict(SCHEMA_VERSION, saved_at="2026-01-01T00:00:00Z") == doc, "round-trip"
    assert back.get("flags.bribed_the_guard") is True, "a loaded Job flag is readable again"
    back.bind_pc("decker")
    assert back.get("skill.cybercombat") == 5, "the shipped kit makes the Decker the hacker"

    # ---- 8. a malformed document is refused, and the complaint names what is wrong -----------------
    # A structural failure stops the walk (nothing after a missing root can be read), so the two cases
    # are separate: the loader collects what it can reach, and refuses the rest.
    missing = state.to_save_dict(SCHEMA_VERSION)
    del missing["world"]
    try:
        CampaignState.from_save_dict(missing)
    except ValidationError as exc:
        assert "world" in str(exc), str(exc)
    else:  # pragma: no cover
        raise AssertionError("a save missing a root must be refused")

    wrong_class = state.to_save_dict(SCHEMA_VERSION)
    wrong_class["crew"]["runners"][1]["class"] = "street_samurai"
    try:
        CampaignState.from_save_dict(wrong_class)
    except ValidationError as exc:
        assert "street_samurai" in str(exc), str(exc)
    else:  # pragma: no cover
        raise AssertionError("an unknown class slug must be refused")

    hot = state.to_save_dict(SCHEMA_VERSION)
    hot["world"]["heat"] = HEAT_MAX + 5
    try:
        CampaignState.from_save_dict(hot)
    except ValidationError as exc:
        assert "heat" in str(exc), str(exc)
    else:  # pragma: no cover
        raise AssertionError("Heat past the ceiling must be refused, not clamped silently")

    print(
        f"OK  campaign: {len(state.runners)} Runners, {state.job_count} Jobs resolved, "
        f"nuyen {state.nuyen}, heat {state.heat}, rep {state.rep_fixer}, "
        f"{len(state.stash)} stash entries, save round-trip exact"
    )


if __name__ == "__main__":
    demo()

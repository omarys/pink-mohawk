"""The Hub: the authored district, the turn-based world clock, and the screens that open on it.

`world.md` §1 owns the district (80×38, five Zones, the two north–south crossings), §2 the Job loop,
§3 the three Legwork actions, §8.3 the difficulty tiers, and `DECISIONS.md` §16 fixes every number.
The geometry is data (`data/hub.json`) because §1 says so: the layout is a constant and only which
Jobs the Fixer posts and what the shop stocks is seeded.

Layer 3, and no `tcod` on purpose — this module is the district plus the queries over it, and
`render.py` draws it.

The split with `campaign.py`
----------------------------
`campaign.py` owns every persisted fact and every state transition: it rolls the board, begins the
Job and derives its seed, spends Legwork, applies an Extraction, heals a Runner, advances the day.
The Hub owns *place and time*: where the Crew may stand, what a Zone opens, what the world clock
does, and the order the loop runs in. So this module contains no second copy of a transition — it
drives `CampaignState` and decides when.

Four places the two modules do not yet compose, reported rather than papered over:

1. `CampaignState.legwork_buy_gear(item, price, qty)` spends the action *and* one purchase together,
   while §3.2 says the action "opens the gear shop for this Job only" — purchases then follow and are
   not limited to one. The Hub therefore spends the action itself (`ActiveJob.buy_gear += 1`, its own
   public field) and calls `spend_nuyen` per purchase.
2. `CampaignState.legwork_favour()` always buys the Clock head start, so §3.3's other outcome — the
   device reveal — has no home. The Hub spends the reputation through `change_rep` and records the
   reveal itself, transiently.
3. `CampaignState.advance_day()` is the only time op; there is no `campaign.advance_log`, so the
   safehouse's Advance cannot record itself in §10.1's growth history.
4. The safehouse Advance has no `CampaignState` method, so the Hub implements it against
   `RunnerSheet`'s public ratings, XP and the caps — including the Adept's two raisable attributes.
5. `CampaignState.advance_day()` heals the whole Crew `HUB_RECOVER_BOXES_PER_DAY` boxes, so *every*
   day heals: a Legwork day and a Depart day as much as a day of rest. §1.2 gives resting as the
   safehouse's own mechanic and §1.3 lists it as its own committed action, so the Hub's `rest()` is a
   Zone that spends a day and reports the boxes off rather than a second healer.

One naming difference, not a conflict: §8.3's table has five Heat tiers where `placement.heat_tier`
returns four, because the table's tiers 3 and 4 carry identical numbers and only the tier-4 freeze
differs. The Hub reads `placement`'s, which is the only place the bands exist.

`RunSpec.clock_credit` is the Favour's buffer, and `security.Clock` has no credit field to spend it
against, so a Run currently starts with the credit unanswered.

    .venv/bin/python -m pinkmohawk.hub      # runs demo()
"""

from __future__ import annotations

import json
import pathlib
import random
from collections import deque
from dataclasses import dataclass
from typing import Any, Final

from . import embed, mission_graph, placement
from . import rng as rng_mod
from .campaign import ActiveJob, CampaignState, JobOffer, RunnerSheet, new_campaign
from .constants import (
    ADEPT_CAP,
    ADEPT_RAISABLE,
    ADVANCE_COST_ATTRIBUTE_PER_RATING,
    ADVANCE_COST_SKILL_PER_RATING,
    ATTRIBUTE_CAP,
    BASE_PAYOUT,
    CLINIC_COST_PER_BOX,
    CLINIC_REVIVE_DOWNED,
    FAVOUR_CLOCK_CREDIT,
    FAVOUR_REP_COST,
    GEAR_PRICES,
    HUB_RECOVER_BOXES_PER_DAY,
    HUB_TICKS_PER_DAY,
    JOB_OFFER_ROTATION_DAYS,
    JOB_OFFERS,
    JOB_TYPE_MULT,
    SHOP_STOCK_SIZE,
    SKILL_CAP,
    TRAUMA_PATCH_COST,
)
from .errors import RuntimeFailure, ValidationError
from .grid import TileMap
from .run import DIRECTIONS
from .security import Extraction

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

#: §3's three Legwork actions, in the order the doc lists them.
LEGWORK_ACTIONS: Final = ("scout", "buy_gear", "favour")

#: §3.3's two outcomes. Exactly one is chosen per use.
FAVOUR_OUTCOMES: Final = ("clock_credit", "device_reveal")

#: Every priced item: §9's table plus §16's one addition. Derived, never restated.
PRICES: Final[dict[str, int]] = {**GEAR_PRICES, "trauma_patch": TRAUMA_PATCH_COST}


def _document(name: str) -> dict[str, Any]:
    """Read a data file and drop its `_note` keys, which document the file in place of a schema."""
    raw = json.loads((DATA / name).read_text())
    return {key: value for key, value in raw.items() if not key.startswith("_")}


HUB_DOC: Final[dict[str, Any]] = _document("hub.json")
SHOP_DOC: Final[dict[str, Any]] = _document("shop.json")
JOBS_DOC: Final[dict[str, Any]] = _document("jobs.json")


@dataclass(frozen=True, slots=True)
class Zone:
    """One Zone of §1.2. Mechanics are per interaction, not per cell."""

    id: str
    name: str
    kind: str
    rect: tuple[int, int, int, int]  # x, y, w, h
    door: tuple[int, int]
    mechanics: tuple[str, ...]

    @property
    def cells(self) -> list[tuple[int, int]]:
        x, y, w, h = self.rect
        return [(cx, cy) for cy in range(y, y + h) for cx in range(x, x + w)]

    @property
    def center(self) -> tuple[int, int]:
        """The Zone's middle cell: where an Extraction lands the Crew (§1.2's Transit point)."""
        x, y, w, h = self.rect
        return (x + w // 2, y + h // 2)

    def contains(self, cell: tuple[int, int]) -> bool:
        x, y, w, h = self.rect
        return x <= cell[0] < x + w and y <= cell[1] < y + h


@dataclass(frozen=True, slots=True)
class NPC:
    """A Hub NPC. Its glyph is an ASCII codepoint, not a Private Use tile.

    §1.1 draws Zone labels as text on the floor fill, so the Hub is a text screen; an NPC that
    borrowed a sprite codepoint from the Site's actor block would want a tileset remap the Run does
    not have. Only the Fixer carries a `dialogue` (`dialogue.md` §10.2).
    """

    id: str
    name: str
    zone: str
    pos: tuple[int, int]
    glyph: str
    dialogue: str | None = None
    service: str | None = None


@dataclass(frozen=True, slots=True)
class RunSpec:
    """What the caller needs to start a Run, plus what the Hub revealed to get there."""

    job_id: str
    job_type: str
    run_seed: int
    heat: int
    clock_credit: int
    intel_scouted: bool
    devices_revealed: bool
    payout_agreed: int


def downed(sheet: RunnerSheet) -> bool:
    """§4: a Runner whose Physical monitor is full. The Hub's own word for it; `campaign` stores boxes."""
    return sheet.physical >= sheet.physical_max


class Hub:
    """The district, the world clock, the Job board, the shops and Legwork."""

    def __init__(self, campaign: CampaignState) -> None:
        self.campaign = campaign
        width, height = HUB_DOC["size"]
        self.map = TileMap.load_rows(HUB_DOC["rows"], wall="#", floor=".")
        if (self.map.w, self.map.h) != (width, height):
            raise ValidationError(
                [f"hub.json rows are {self.map.w}x{self.map.h}, size says {width}x{height}"]
            )
        self.zones: list[Zone] = [
            Zone(
                z["id"],
                z["name"],
                z["kind"],
                tuple(z["rect"]),
                tuple(z["door"]),
                tuple(z["mechanics"]),
            )
            for z in HUB_DOC["zones"]
        ]
        self.npcs: list[NPC] = [
            NPC(
                n["id"],
                n["name"],
                n["zone"],
                tuple(n["pos"]),
                n["glyph"],
                n.get("dialogue"),
                n.get("service"),
            )
            for n in HUB_DOC["npcs"]
        ]
        self.pos: tuple[int, int] = tuple(HUB_DOC["spawn"])
        self.facing: str = "s"
        #: Ticks inside the current day. Transient: §10.1 persists `hub_day`, not the tick counter.
        self.ticks: int = 0
        self.legwork_budget: int = int(HUB_DOC["legwork_actions_per_job"])
        #: The Favour's device reveal, for the coming Run. §10.4 has no key for it (see the module
        #: docstring), so it lives here and dies with the session rather than being written nowhere.
        self.devices_revealed: bool = False
        self._preview: (
            tuple[mission_graph.MissionGraph, embed.Site, placement.Population] | None
        ) = None
        self._preview_key: tuple[Any, ...] | None = None

    # -- the district ----------------------------------------------------------------------
    def zone_at(self, cell: tuple[int, int]) -> Zone | None:
        return next((zone for zone in self.zones if zone.contains(cell)), None)

    @property
    def zone(self) -> Zone | None:
        """The Zone the Crew stands in, or None in the streets between them."""
        return self.zone_at(self.pos)

    def npc_at(self, cell: tuple[int, int]) -> NPC | None:
        return next((npc for npc in self.npcs if npc.pos == cell), None)

    def zone_of_kind(self, kind: str) -> Zone:
        """The one Zone of a kind. Every kind in §1.2 is unique, so a missing one is a data bug."""
        zone = next((entry for entry in self.zones if entry.kind == kind), None)
        if zone is None:
            raise ValidationError([f"hub.json has no Zone of kind {kind!r}"])
        return zone

    def step(self, direction: str) -> bool:
        """Take one Hub Step and return whether it landed.

        §1.3: one step is one tick, and walking is nearly free because a day is `HUB_TICKS_PER_DAY`
        of them. A blocked step still spends its tick — the tick is the world clock, not the
        movement's price, and a free wall would let a player burn no time against one.
        """
        delta = DIRECTIONS.get(direction)
        if delta is None:
            raise ValidationError([f"unknown direction {direction!r}; known: {sorted(DIRECTIONS)}"])
        self.tick()
        target = (self.pos[0] + delta[0], self.pos[1] + delta[1])
        if self.map.is_wall(*target):
            return False
        self.pos = target
        self.facing = direction
        return True

    def tick(self, times: int = 1) -> None:
        """Advance the world clock, rolling whole days into `hub_day`."""
        if times < 0:
            raise ValidationError([f"cannot tick {times} times"])
        self.ticks += times
        while self.ticks >= HUB_TICKS_PER_DAY:
            self.ticks -= HUB_TICKS_PER_DAY
            self.campaign.advance_day()

    # -- the safehouse ---------------------------------------------------------------------
    def rest(self) -> int:
        """A day of rest at the safehouse (§1.2), returning how many boxes came off.

        The unmarking and its Stun-first order belong to `campaign.advance_day`, which is also where
        the day is spent; what is the Hub's is the Zone that offers it and the count the summary
        screen wants. Note that `campaign` heals on *every* day rather than only on a day of rest —
        item 5 in the module docstring.
        """
        before = sum(sheet.stun + sheet.physical for sheet in self.campaign.runners)
        self.campaign.advance_day()
        return before - sum(sheet.stun + sheet.physical for sheet in self.campaign.runners)

    def advance(self, runner_id: str, kind: str, key: str) -> bool:
        """Spend XP to raise one rating (§1.2). False when XP, the cap or the key says no.

        Costs no day: §1.3's table of committed actions does not list it. The Adept's edge is §1's
        exception — Agility and Strength may reach `ADEPT_CAP` where every other rating stops at 6.
        """
        if kind not in ("skill", "attribute"):
            raise ValidationError([f"kind must be 'skill' or 'attribute', got {kind!r}"])
        sheet = next((entry for entry in self.campaign.runners if entry.id == runner_id), None)
        if sheet is None:
            raise ValidationError([f"no Runner {runner_id!r} in the crew"])
        table = sheet.skills if kind == "skill" else sheet.attributes
        if key not in table:
            raise ValidationError([f"no {kind} {key!r} on {runner_id!r}"])
        current = int(table[key])
        adept_raise = kind == "attribute" and sheet.klass == "adept" and key in ADEPT_RAISABLE
        cap = (ADEPT_CAP if adept_raise else ATTRIBUTE_CAP) if kind == "attribute" else SKILL_CAP
        cost = (current + 1) * (
            ADVANCE_COST_SKILL_PER_RATING if kind == "skill" else ADVANCE_COST_ATTRIBUTE_PER_RATING
        )
        if current >= cap or sheet.xp < cost:
            return False
        sheet.xp -= cost
        table[key] = current + 1  # §14 item 8: the cost is the NEW rating times the per-rating cost
        return True

    # -- the clinic ------------------------------------------------------------------------
    def clinic_bill(self, sheet: RunnerSheet) -> int:
        """`CLINIC_COST_PER_BOX` per filled box, both tracks (§1.2)."""
        return (sheet.stun + sheet.physical) * CLINIC_COST_PER_BOX

    def clinic_treat(self, sheet: RunnerSheet) -> bool:
        """Heal every filled box at once. False, and nothing changes, when it is unaffordable."""
        bill = self.clinic_bill(sheet)
        if self.campaign.nuyen < bill:
            return False
        self.campaign.spend_nuyen(bill)
        sheet.stun = 0
        sheet.physical = 0
        return True

    def clinic_revive(self, sheet: RunnerSheet) -> bool:
        """Bring a Downed Runner back for `CLINIC_REVIVE_DOWNED` instead of waiting out the boxes.

        "Downed" at the Hub is a full Physical monitor, so paying clears that track — which is what
        makes the revive an alternative to a week of resting rather than a separate state.
        """
        if not downed(sheet) or self.campaign.nuyen < CLINIC_REVIVE_DOWNED:
            return False
        self.campaign.spend_nuyen(CLINIC_REVIVE_DOWNED)
        sheet.physical = 0
        return True

    # -- Legwork ---------------------------------------------------------------------------
    def _active(self) -> ActiveJob:
        if self.campaign.active is None:
            raise RuntimeFailure("no active Job: take one from the Fixer's board first")
        return self.campaign.active

    @property
    def legwork_remaining(self) -> int:
        """Actions left for the active Job: three per Job (§2, DECISIONS §9), repeats allowed."""
        active = self.campaign.active
        if active is None:
            return 0
        return self.legwork_budget - (active.scout + active.buy_gear + active.favour)

    def legwork(self, action: str, *, outcome: str | None = None) -> None:
        """Spend one Legwork action. Each costs one of the three slots and one day (§3)."""
        if action not in LEGWORK_ACTIONS:
            raise ValidationError(
                [f"unknown Legwork action {action!r}; known: {list(LEGWORK_ACTIONS)}"]
            )
        active = self._active()
        if self.legwork_remaining <= 0:
            raise RuntimeFailure(
                [f"no Legwork left this Job: {self.legwork_budget} actions, all spent"]
            )
        if action == "scout":
            self.campaign.legwork_scout()
        elif action == "buy_gear":
            # §3.2 spends the action to open the shop. `campaign.legwork_buy_gear` bundles the action
            # with a single purchase instead; this is the bridge until that method splits (item 1 in
            # the module docstring).
            active.buy_gear += 1
        else:
            self._favour(outcome)
        self.campaign.advance_day()

    def _favour(self, outcome: str | None) -> None:
        """§3.3: `FAVOUR_REP_COST` of Fixer standing buys one of two reveals."""
        if outcome not in FAVOUR_OUTCOMES:
            raise ValidationError(
                [f"Favour outcome must be one of {list(FAVOUR_OUTCOMES)}, got {outcome!r}"]
            )
        if outcome == "clock_credit":
            self.campaign.legwork_favour()  # spends the reputation and adds the credit
            return
        active = self._active()
        if self.campaign.rep_fixer < FAVOUR_REP_COST:
            raise RuntimeFailure(
                [f"a Favour costs {FAVOUR_REP_COST} Fixer reputation and needs at least that much"]
            )
        self.campaign.change_rep("fixer", -FAVOUR_REP_COST)
        active.favour += 1
        self.devices_revealed = True

    @property
    def shop_open(self) -> bool:
        """§3.2: buying requires having spent Buy Gear."""
        return self.campaign.active is not None and self.campaign.active.buy_gear > 0

    # -- the pre-Run briefing --------------------------------------------------------------
    def preview(self) -> tuple[mission_graph.MissionGraph, embed.Site, placement.Population]:
        """Build the coming Site without starting it, cached per (Job, attempt, Heat).

        The steps are `run.build_run`'s, in its order and from its own named streams, so a briefing
        describes the Run the Crew will actually get rather than a similar-looking one.
        """
        active = self._active()
        key = (active.id, active.run_counter, self.campaign.heat)
        if self._preview is None or self._preview_key != key:
            streams = rng_mod.make_static_rngs(active.run_seed)
            graph = mission_graph.build_graph(self.job_type(active), streams["gen.graph"])
            site = embed.embed(graph, active.run_seed)
            rooms = {nid: (room.x, room.y, room.w, room.h) for nid, room in site.rooms.items()}
            population = placement.place(
                graph, rooms, streams["gen.place"], heat=self.campaign.heat
            )
            self._preview, self._preview_key = (graph, site, population), key
        return self._preview

    @staticmethod
    def job_type(active: ActiveJob) -> str:
        """The canonical job type. `dialogue.md` calls the paydata Job `paydata`; §16 makes
        `extraction` canonical, and `data/jobs.json` holds the alias."""
        return str(JOBS_DOC["aliases"].get(active.job_type, active.job_type))

    def scout_reveal(self) -> list[dict[str, Any]]:
        """§3.1: every node's type and every edge, and which of them are Security nodes.

        Types and edges only. Enemy counts, device types and device ratings stay hidden, which is
        what keeps `Scan` and the Favour's device reveal worth their action.
        """
        active = self._active()
        if not active.intel_scouted:
            raise RuntimeFailure(["the briefing needs Scout Site first"])
        graph, _site, _population = self.preview()
        return [
            {"id": node.id, "kind": node.kind, "edges": sorted(node.outgoing)}
            for node in graph.nodes.values()
        ]

    def device_reveal(self) -> list[dict[str, Any]]:
        """§3.3: the full device list — type and rating, on every node. `Scan` at unlimited radius."""
        if not self.devices_revealed:
            raise RuntimeFailure(["the briefing needs a Favour's device reveal first"])
        _graph, _site, population = self.preview()
        return [
            {
                "node": spawn.node_id,
                "kind": spawn.template,
                "rating": spawn.rating,
                "cell": list(spawn.cell),
            }
            for spawn in population.devices()
        ]

    # -- the Job loop ----------------------------------------------------------------------
    @property
    def rotation_window(self) -> int:
        """The first day of the current board window, on `campaign.advance_day`'s own boundary.

        `advance_day` re-rolls when `hub_day % JOB_OFFER_ROTATION_DAYS == 0`, so a window is the run
        of days ending on one of those. The Hub needs the same boundary to seed shop stock stably
        across a window, and taking it from the module that rotates the board keeps one convention
        instead of two.
        """
        day = self.campaign.hub_day
        return day - (day % JOB_OFFER_ROTATION_DAYS)

    def offers(self) -> list[JobOffer]:
        """The Fixer's board.

        `campaign` draws it and re-rolls it when a day lands on the rotation boundary; the Hub asks
        rather than deciding, so the board has one owner. The case the Hub does handle is a board
        that does not exist yet, which is what a save with no offers would load as.
        """
        if not self.campaign.offers:
            return self.campaign.roll_offers()
        return self.campaign.offers

    def take_job(self, offer_id: str) -> ActiveJob:
        """§2 (B)→(D): take an offer, derive the `run_seed`, and pay the day it costs.

        `run_counter` and the stored seed are `begin_job`'s, so a retry after a failed Run walks a
        different Site from the one that beat the Crew (§5.5).
        """
        active = self.campaign.begin_job(offer_id)
        self.campaign.advance_day()  # §1.3: Take a Job / Depart costs one day
        self._preview = None
        self.devices_revealed = False
        return active

    def run_spec(self) -> RunSpec:
        """Everything `run.build_run` needs, and nothing it has to derive again."""
        active = self._active()
        return RunSpec(
            job_id=active.id,
            job_type=self.job_type(active),
            run_seed=active.run_seed,
            heat=self.campaign.heat,
            clock_credit=active.clock_credit,
            intel_scouted=active.intel_scouted,
            devices_revealed=self.devices_revealed,
            payout_agreed=active.payout_agreed,
        )

    def report_extraction(self, extraction: Extraction) -> dict[str, Any]:
        """§2 (F) and (G): apply all three consequences, close the Job, and come home.

        `campaign.apply_extraction` applies them — one site, so no caller can apply two of the three
        or one of them twice. The Hub's part is bringing the Crew back to the Transit tile, which is
        where §1.2 says every Extraction lands them, and dropping the briefing state that belonged to
        the Job that just ended.
        """
        if self.campaign.active is None:
            raise RuntimeFailure(["no active Job to extract from"])
        self.campaign.apply_extraction(extraction)
        self.pos = self.zone_of_kind("transit").center  # §1.2: landed back at the Transit point
        self.ticks = 0
        self.devices_revealed = False
        self._preview, self._preview_key = None, None
        # The board is NOT re-rolled here: `apply_extraction` has already taken a finished Job off it
        # and left a failed one on for the retry, and re-rolling would renumber the offers around it.
        return {
            "payout": extraction.payout,
            "heat_delta": extraction.heat_delta,
            "reputation_delta": extraction.reputation_delta,
            "forced": extraction.forced,
        }

    # -- the shops -------------------------------------------------------------------------
    @property
    def heat_tier(self) -> int:
        """§8.3's difficulty tier. `placement` owns the bands; the Hub only asks."""
        return placement.heat_tier(self.campaign.heat)

    def shop_stock(self) -> list[str]:
        """`SHOP_STOCK_SIZE` items, seeded from (Job, rotation) and banded by Heat tier (§3.2).

        Seeded per rotation rather than per day, so standing in the shop twice shows the same shelf:
        a re-roll costs a Legwork action on the next Job, or waiting the rotation out.
        """
        active = self._active()
        window = self.rotation_window
        stream = random.Random(rng_mod.derive(self.campaign.seed, f"hub:{window}:shop:{active.id}"))
        pool = SHOP_DOC["pools"][str(self.heat_tier)]
        return sorted(stream.sample(pool, SHOP_STOCK_SIZE))

    def medical_stock(self) -> list[str]:
        """The clinic's consumables (§1.2). Their prices are `PRICES`', not the data file's."""
        return list(SHOP_DOC["medical"])

    def price(self, item: str) -> int:
        if item not in PRICES:
            raise ValidationError([f"no price for {item!r}; priced: {sorted(PRICES)}"])
        return PRICES[item]

    def buy(self, item: str, runner_id: str) -> bool:
        """Buy one item into a Runner's loadout. False when the Crew cannot afford it.

        §3.2: gear bought at the Hub is in the loadout at Run start and persists, so the item is
        attached to a Runner now rather than only to the shared stash.
        """
        if not self.shop_open:
            raise RuntimeFailure(["the gear shop needs the Buy Gear Legwork action first"])
        stock = self.shop_stock()
        if item not in stock:
            raise ValidationError([f"{item!r} is not in today's stock: {stock}"])
        sheet = next((entry for entry in self.campaign.runners if entry.id == runner_id), None)
        if sheet is None:
            raise ValidationError([f"no Runner {runner_id!r} in the crew"])
        price = self.price(item)
        if self.campaign.nuyen < price:
            return False
        self.campaign.spend_nuyen(price)
        sheet.loadout.append(item)
        return True


# ==============================================================================================
# Acceptance test
# ==============================================================================================
def demo() -> None:
    from .run import build_run, extract

    campaign = new_campaign(seed=20260918)
    hub = Hub(campaign)

    # ---- 1. the district is the doc's, cell for cell ---------------------------------------
    assert (hub.map.w, hub.map.h) == (80, 38), "world.md §1.1: 80x38"
    documented = {
        "safehouse": ((2, 2, 19, 12), (10, 14)),
        "clinic": ((28, 2, 21, 12), (38, 14)),
        "gear_shop": ((60, 2, 19, 12), (68, 14)),
        "fixer_bar": ((2, 29, 17, 8), (10, 28)),
        "transit": ((60, 29, 19, 8), (68, 28)),
    }
    assert {zone.id for zone in hub.zones} == set(documented), "the five Zones of §1.2"
    for zone in hub.zones:
        want_rect, want_door = documented[zone.id]
        assert zone.rect == want_rect, f"{zone.id}: rect {zone.rect} != §1.2's {want_rect}"
        assert zone.door == want_door, f"{zone.id}: door {zone.door} != §1.2's {want_door}"
        assert not hub.map.is_wall(*zone.door), f"{zone.id}: its doorway must be walkable"
        assert all(not hub.map.is_wall(*cell) for cell in zone.cells), (
            f"{zone.id}: floor is walkable"
        )
        assert zone.mechanics, f"{zone.id}: §1.2 gives every Zone mechanics"
    # §1.1: the two north-south crossings are the Hub's single navigational fact
    assert [x for x in range(80) if not hub.map.is_wall(x, 20)] == [22, 23, 56, 57]
    assert all(not hub.map.is_wall(x, y) for y in (15, 16, 26, 27) for x in range(80))
    assert not hub.map.is_wall(*hub.pos), "the Crew loads onto floor"
    spawn_zone = hub.zone
    assert spawn_zone is not None and spawn_zone.kind == "safehouse", "§1.2: Crew spawn on load"
    assert len(hub.npcs) == 3
    fixer = next(npc for npc in hub.npcs if npc.id == "fixer")
    fixer_zone = hub.zone_at(fixer.pos)
    assert fixer_zone is not None and fixer_zone.id == "fixer_bar"
    assert fixer.dialogue == "fixer_offer", (
        "dialogue.md §10.2: the NPC record names the conversation"
    )
    assert all(not hub.map.is_wall(*npc.pos) for npc in hub.npcs)
    assert not hub.map.is_wall(*next(n for n in hub.npcs if n.id == "fixer").pos)

    # every walkable cell is reachable from the spawn, so no Zone is walled off by a typo
    seen, queue = {hub.pos}, deque([hub.pos])
    while queue:
        cell = queue.popleft()
        for delta in DIRECTIONS.values():
            nxt = (cell[0] + delta[0], cell[1] + delta[1])
            if not hub.map.is_wall(*nxt) and nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    walkable = {(x, y) for y in range(38) for x in range(80) if not hub.map.is_wall(x, y)}
    assert seen == walkable, f"{len(walkable - seen)} cells unreachable from the spawn"

    # ---- 2. collision, and a blocked Step still spends its tick ---------------------------
    assert hub.step("n") is True and hub.pos == (10, 7)
    assert hub.ticks == 1, "one Step is one tick (§1.3)"
    for _ in range(20):
        hub.step("n")  # the safehouse's north wall stops the Crew at y=2
    assert hub.pos == (10, 2), "the walk stopped at the safehouse's top row"
    ticks_before = hub.ticks
    day_before = campaign.hub_day
    assert hub.step("n") is False, "into the wall"
    assert hub.pos == (10, 2), "and it did not move"
    assert hub.ticks == ticks_before + 1, "a blocked Step costs its tick too"
    assert campaign.hub_day == day_before, "no day passed"

    # ---- 3. the world clock: HUB_TICKS_PER_DAY ticks is exactly one day --------------------
    hub.pos = tuple(HUB_DOC["spawn"])
    hub.ticks = 0
    day_start = campaign.hub_day
    hub.tick(HUB_TICKS_PER_DAY - 1)
    assert campaign.hub_day == day_start, "a day needs the full tick budget"
    hub.tick(1)
    assert campaign.hub_day == day_start + 1, "HUB_TICKS_PER_DAY ticks advance hub_day by one"
    assert hub.ticks == 0, "and the remainder rolls over"

    # ---- 4. rest: HUB_RECOVER_BOXES_PER_DAY, Stun before Physical, one day -----------------
    sheet = campaign.runners[0]
    sheet.stun, sheet.physical = 3, 3
    day_before = campaign.hub_day
    healed = hub.rest()
    assert campaign.hub_day == day_before + 1, "a day of rest costs a day (§1.3)"
    assert healed >= HUB_RECOVER_BOXES_PER_DAY
    assert (sheet.stun, sheet.physical) == (3 - HUB_RECOVER_BOXES_PER_DAY, 3), (
        "Stun comes off first"
    )
    sheet.stun, sheet.physical = 0, 3
    hub.rest()
    assert sheet.physical == 3 - HUB_RECOVER_BOXES_PER_DAY, "then Physical"

    # ---- 5. the clinic: per box, and the revive -------------------------------------------
    sheet.stun, sheet.physical = 2, 3
    assert hub.clinic_bill(sheet) == 5 * CLINIC_COST_PER_BOX
    purse = campaign.nuyen
    assert hub.clinic_treat(sheet) is True
    assert campaign.nuyen == purse - 5 * CLINIC_COST_PER_BOX
    assert (sheet.stun, sheet.physical) == (0, 0)
    sheet.physical = sheet.physical_max
    assert downed(sheet) is True
    purse = campaign.nuyen
    assert hub.clinic_revive(sheet) is True and campaign.nuyen == purse - CLINIC_REVIVE_DOWNED
    assert downed(sheet) is False, "the revive clears the Physical track"
    assert hub.clinic_revive(sheet) is False, "and does nothing for a healthy Runner"
    broke = new_campaign(seed=1)
    broke.nuyen = 0
    broke.runners[0].stun = 1
    assert Hub(broke).clinic_treat(broke.runners[0]) is False, "cannot afford it"
    assert broke.nuyen == 0 and broke.runners[0].stun == 1, "and nothing was changed"

    # ---- 6. Advance: the caps, the cost, and the Adept's exception -------------------------
    campaign = new_campaign(seed=20260918)
    hub = Hub(campaign)
    adept = next(entry for entry in campaign.runners if entry.id == "adept")
    adept.xp = 0
    before = adept.skills["close_combat"]
    assert hub.advance("adept", "skill", "close_combat") is False, "no XP, no Advance"
    assert adept.skills["close_combat"] == before, "and nothing changed"
    adept.xp = 100
    assert hub.advance("adept", "skill", "close_combat") is True
    assert adept.skills["close_combat"] == before + 1
    assert adept.xp == 100 - (before + 1) * ADVANCE_COST_SKILL_PER_RATING, "§14 item 8's cost"
    adept.skills["close_combat"] = SKILL_CAP
    adept.xp = 1000
    assert hub.advance("adept", "skill", "close_combat") is False, "ratings stop at SKILL_CAP"
    # the Adept may take Agility and Strength past the general cap, and nothing else may
    adept.attributes["agility"] = ADEPT_CAP
    assert hub.advance("adept", "attribute", "agility") is False, "the Adept's cap is ADEPT_CAP too"
    adept.attributes["agility"] = ATTRIBUTE_CAP
    assert hub.advance("adept", "attribute", "agility") is True, "Agility may reach ADEPT_CAP"
    assert adept.attributes["agility"] == ADEPT_CAP
    mage = next(entry for entry in campaign.runners if entry.id == "mage")
    mage.xp = 1000
    mage.attributes["agility"] = ATTRIBUTE_CAP
    assert hub.advance("mage", "attribute", "agility") is False, "the exception is the Adept's"
    try:
        hub.advance("adept", "talent", "close_combat")
    except ValidationError:
        pass
    else:
        raise AssertionError("only 'skill' and 'attribute' are Advance kinds")

    # ---- 7. the Job board: JOB_OFFERS offers, re-rolled once a rotation --------------------
    campaign = new_campaign(seed=20260918)
    hub = Hub(campaign)
    offers = hub.offers()
    assert len(offers) == JOB_OFFERS, "§1.2: the Fixer posts JOB_OFFERS jobs"
    for offer in offers:
        assert offer.payout_base == round(BASE_PAYOUT * JOB_TYPE_MULT[offer.job_type]), (
            "§4.1's base: round(12000 x TYPE_MULT[type])"
        )
    assert hub.offers() is offers, "the board is stable within a rotation"
    # the §16 multiplier table is the one being read, for every type
    assert [
        round(BASE_PAYOUT * JOB_TYPE_MULT[t])
        for t in ("extraction", "sabotage", "protection", "courier")
    ] == [12000, 13800, 13200, 10800]
    campaign.advance_day()
    assert campaign.hub_day == 2
    assert hub.offers() is offers, "a day that is not the rotation boundary does not re-roll"
    campaign.advance_day()
    assert campaign.hub_day % JOB_OFFER_ROTATION_DAYS == 0, "day 3 is the boundary"
    rotated = hub.offers()
    assert rotated is not offers, "the boundary re-rolls the board"
    assert len(rotated) == JOB_OFFERS
    assert hub.offers() is rotated, "and the new board is stable in its turn"

    # ---- 8. Legwork: three actions, one day each, and their effects ------------------------
    campaign = new_campaign(seed=20260918)
    hub = Hub(campaign)
    assert hub.legwork_budget == 3, "DECISIONS §9: up to 3 actions per Job"
    active = hub.take_job(hub.offers()[0].id)
    assert hub.legwork_remaining == 3
    day = campaign.hub_day
    hub.legwork("scout")
    assert active.intel_scouted is True
    assert campaign.hub_day == day + 1, "a Legwork action costs one Hub day (§1.3)"
    reveal = hub.scout_reveal()
    graph = hub.preview()[0]
    assert {n["id"] for n in reveal} == set(graph.nodes), "§3.1: every node"
    assert sorted(edge for n in reveal for edge in n["edges"]) == sorted(
        edge for node in graph.nodes.values() for edge in node.outgoing
    ), "§3.1: every edge"
    assert any(n["kind"] == mission_graph.SECURITY for n in reveal), "and which are Security nodes"
    hub.legwork("buy_gear")
    assert hub.shop_open is True, "Buy Gear opens the shop for this Job"
    campaign.rep_fixer = 2
    hub.legwork("favour", outcome="clock_credit")
    assert campaign.rep_fixer == 2 - FAVOUR_REP_COST, "§3.3: a Favour costs reputation"
    assert campaign.active is not None and campaign.active.clock_credit == FAVOUR_CLOCK_CREDIT
    assert hub.legwork_remaining == 0
    try:
        hub.legwork("scout")
    except RuntimeFailure:
        pass
    else:
        raise AssertionError("a fourth Legwork action must be refused")
    # the other Favour outcome, and a Favour the crew cannot afford
    other = Hub(new_campaign(seed=5))
    other.take_job(other.offers()[0].id)
    other.campaign.rep_fixer = 0
    try:
        other.legwork("favour", outcome="device_reveal")
    except RuntimeFailure:
        pass
    else:
        raise AssertionError("a Favour needs reputation >= FAVOUR_REP_COST")
    assert other.legwork_remaining == 3, "a refused action is not spent"
    other.campaign.rep_fixer = 1
    other.legwork("favour", outcome="device_reveal")
    assert other.campaign.rep_fixer == 1 - FAVOUR_REP_COST
    assert other.devices_revealed is True
    active_after = other.campaign.active
    assert active_after is not None
    assert active_after.clock_credit == 0, "the two outcomes are alternatives, not a bundle"
    assert other.legwork_remaining == 2

    # ---- 9. the reveal, and the briefing matching the Run it describes ---------------------
    devices = other.device_reveal()
    assert devices, "§3.3: the full device list"
    assert all({"node", "kind", "rating"} <= set(entry) for entry in devices)
    assert {entry["node"] for entry in devices} == {n.id for n in other.preview()[0].nodes.values()}
    spec = other.run_spec()
    assert spec.devices_revealed is True and spec.job_type == "extraction"
    run = build_run(spec.job_type, spec.run_seed, heat=spec.heat)
    preview_graph, preview_site, preview_population = other.preview()
    assert sorted((n.id, n.kind) for n in preview_graph.nodes.values()) == sorted(
        (n.id, n.kind) for n in run.graph.nodes.values()
    ), "the briefing describes the Run itself"
    assert {nid: (room.x, room.y, room.w, room.h) for nid, room in preview_site.rooms.items()} == {
        nid: (room.x, room.y, room.w, room.h) for nid, room in run.site.rooms.items()
    }, "and the Site it describes is the Site it generates"
    assert [(s.kind, s.template, s.cell) for s in preview_population.spawns] == [
        (s.kind, s.template, s.cell) for s in run.population.spawns
    ], "down to every spawn"

    # ---- 10. Depart: the seed is derived, stored, and different on a retry -----------------
    campaign = new_campaign(seed=20260918)
    hub = Hub(campaign)
    offer = hub.offers()[0]
    day = campaign.hub_day
    first = hub.take_job(offer.id)
    assert campaign.hub_day == day + 1, "Take a Job / Depart costs one day (§1.3)"
    assert first.run_seed == rng_mod.run_seed(campaign.seed, offer.id, 1)
    assert campaign.active is not None and campaign.active.run_seed == first.run_seed, (
        "§5.5: derived once at Depart, then stored"
    )
    spec = hub.run_spec()
    assert spec.run_seed == first.run_seed and spec.job_id == offer.id
    # a forced Extraction leaves the offer on the board, and the retry walks a different Site
    hub.report_extraction(Extraction(payout=0, heat_delta=2, reputation_delta=-1, forced=True))
    assert campaign.active is None
    assert any(entry.id == offer.id for entry in campaign.offers), "a failed Job stays on the board"
    second = hub.take_job(offer.id)
    assert second.run_counter == 2, "run_counter counts attempts at this Job"
    assert second.run_seed != first.run_seed, "so the retry gets a different Site"
    assert second.run_seed == rng_mod.run_seed(campaign.seed, offer.id, 2)

    # ---- 11. Extraction: all three consequences, and the Crew comes home -------------------
    campaign = new_campaign(seed=20260918)
    campaign.nuyen, campaign.heat, campaign.rep_fixer = 1_000, 4, 2
    hub = Hub(campaign)
    offer = hub.offers()[0]
    hub.take_job(offer.id)
    run = build_run("extraction", campaign.active.run_seed, heat=campaign.heat)
    for _ in range(5):
        run.clock.tick("gunfire")  # 10 segments: security converges
    assert run.clock.converged
    extraction = extract(run, voluntary=True, net_negotiation_hits=4)
    assert extraction.forced is True, "a converged Clock overrides a voluntary extraction"
    assert extraction.payout == 0, "§9: a forced extraction pays zero"
    summary = hub.report_extraction(extraction)
    assert summary["payout"] == 0 and campaign.nuyen == 1_000, "and pays nothing"
    assert campaign.heat == 4 + extraction.heat_delta > 4, "Heat rises"
    assert campaign.rep_fixer == 2 + extraction.reputation_delta < 2, "and Fixer standing falls"
    assert campaign.active is None, "the Job is closed"
    assert hub.zone is not None and hub.zone.kind == "transit", (
        "§1.2: every Extraction lands the Crew on the Transit tile, not at the safehouse"
    )
    assert hub.ticks == 0
    # a voluntary Extraction pays, and takes the offer off the board
    hub.take_job(offer.id)
    paid_run = build_run("extraction", campaign.active.run_seed, heat=campaign.heat)
    objective = paid_run.paydata_cell()
    assert objective is not None, "an extraction Job has a vault"
    paid_run.crew[0].pos = objective  # success in v1 is standing on the Paydata
    assert paid_run.crew_at_objective()
    good = extract(paid_run, voluntary=True, net_negotiation_hits=6)
    assert good.forced is False and good.payout == BASE_PAYOUT + 600
    summary = hub.report_extraction(good)
    assert summary["payout"] == BASE_PAYOUT + 600
    assert campaign.nuyen == 1_000 + BASE_PAYOUT + 600
    assert not any(entry.id == offer.id for entry in campaign.offers), (
        "a finished Job leaves the board"
    )

    # ---- 12. the shop: seeded, tier-banded, gated, and priced by the contract --------------
    campaign = new_campaign(seed=20260918)
    hub = Hub(campaign)
    assert hub.heat_tier == 0
    hub.take_job(hub.offers()[0].id)
    stock = hub.shop_stock()
    assert len(stock) == SHOP_STOCK_SIZE, "§3.2: a six-item draw per Job"
    assert set(stock) <= set(SHOP_DOC["pools"]["0"]), "tier 0 stocks from the tier-0 pool"
    assert hub.shop_stock() == stock, "and the shelf does not re-roll on a second look"
    try:
        hub.buy(stock[0], "adept")
    except RuntimeFailure:
        pass
    else:
        raise AssertionError("buying without the Buy Gear action must be refused")
    hub.legwork("buy_gear")
    assert hub.shop_open is True
    item = "armoured_vest"
    purse = campaign.nuyen
    assert hub.buy(item, "adept") is True
    assert campaign.nuyen == purse - GEAR_PRICES[item], "§9's price, not a data file's"
    adept = next(entry for entry in campaign.runners if entry.id == "adept")
    assert item in adept.loadout, "§3.2: in the loadout at Run start, and it persists"
    assert hub.price("trauma_patch") == TRAUMA_PATCH_COST, "§16 prices the item §9 does not"
    assert set(hub.medical_stock()) <= set(PRICES)
    broke = Hub(new_campaign(seed=7))
    broke.campaign.nuyen = 10
    broke.take_job(broke.offers()[0].id)
    broke.legwork("buy_gear")
    before = list(next(e for e in broke.campaign.runners if e.id == "adept").loadout)
    assert broke.price(item) > broke.campaign.nuyen
    assert broke.buy(item, "adept") is False, "cannot afford it"
    assert broke.campaign.nuyen == 10, "and nothing was spent"
    assert next(e for e in broke.campaign.runners if e.id == "adept").loadout == before
    # a richer Heat tier stocks from a wider pool, through the one tier table placement owns
    hot = Hub(new_campaign(seed=20260918))
    hot.campaign.heat = 12
    hot.take_job(hot.offers()[0].id)
    hot.legwork("buy_gear")
    assert hot.heat_tier == 3, "Heat 12 is placement's top band"
    assert set(hot.shop_stock()) <= set(SHOP_DOC["pools"]["3"])
    exclusive = set(SHOP_DOC["pools"]["3"]) - set(SHOP_DOC["pools"]["0"])
    assert set(hot.shop_stock()) & exclusive, "the ceiling tier can stock what the floor cannot"
    # the shelf is today's draw, not the whole catalogue: an unstoked item is not for sale
    hot_stock = hot.shop_stock()
    unstoked = next(entry for entry in SHOP_DOC["pools"]["3"] if entry not in hot_stock)
    purse = hot.campaign.nuyen
    try:
        hot.buy(unstoked, "adept")
    except ValidationError:
        pass
    else:
        raise AssertionError("§3.2: the shop sells today's stock only")
    assert hot.campaign.nuyen == purse, "and a refused purchase costs nothing"

    # ---- 13. Heat reaches difficulty through placement, not a second copy ------------------
    assert [placement.heat_tier(h) for h in (0, 2, 3, 5, 6, 8, 9, 11, 12, 20)] == [
        0,
        0,
        1,
        1,
        2,
        2,
        3,
        3,
        3,
        3,
    ], "§8.3's bands as `placement` implements them, read from the module that owns them"
    quiet = Hub(new_campaign(seed=20260918))
    quiet.take_job(quiet.offers()[0].id)
    loud = Hub(new_campaign(seed=20260918))
    loud.campaign.heat = 12
    loud.take_job(loud.offers()[0].id)
    quiet_kinds = {spawn.template for spawn in quiet.preview()[2].spawns}
    loud_kinds = {spawn.template for spawn in loud.preview()[2].spawns}
    assert not quiet_kinds & {"security_drone", "corp_mage"}, "tier 0 is the difficulty floor"
    assert loud_kinds & {"security_drone", "corp_mage"}, "tier 3 has the wider roster"
    assert quiet.run_spec().heat == 0 and loud.run_spec().heat == 12, "the Run is handed the Heat"

    print(
        f"OK  hub: 80x38 district, {len(hub.zones)} Zones, {HUB_TICKS_PER_DAY} ticks a day, "
        f"{JOB_OFFERS} offers a rotation of {JOB_OFFER_ROTATION_DAYS} days, "
        f"{hub.legwork_budget} Legwork actions, {SHOP_STOCK_SIZE} shop items at tier "
        f"{hot.heat_tier}; the briefing matches the Run it describes, spawn for spawn"
    )


if __name__ == "__main__":
    demo()

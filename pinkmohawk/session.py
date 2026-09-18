"""Session: the between-Jobs composition root, and Phase 2's acceptance test.

`run.py` is the composition root for one Run; this is the root above it. It owns the four things that
only exist *between* Runs and that no single module could own alone:

- the **CampaignState** and its one save slot (world.md §10.5: safehouse and payout, nothing else),
- the **Hub** the crew stands in,
- the **Dialogue Graph host** - the adapter that lets `dialogue.py`'s runner read and write the
  campaign without the engine ever importing it,
- the **handoff** in both directions: a `hub.run_spec()` into `run.build_run`, and an
  `Extraction` back through `hub.report_extraction`.

Three lanes built `campaign`, `save`, `dialogue` and `hub` from the same documents. They agreed
everywhere except one word - the store protocol asked for `spec(key).type`, the store called it `kind`
- which is what the adapter and that one alias in `campaign.py` exist to close.

`.venv/bin/python -m pinkmohawk.session      # the roadmap's Phase 2 acceptance test
"""

from __future__ import annotations

import pathlib
import random
from dataclasses import dataclass, field
from typing import Any

from . import campaign as campaign_mod
from . import dialogue, entities
from . import hub as hub_mod
from . import run as run_mod
from . import save as save_mod
from .campaign import CampaignState
from .constants import AUTO_ADVANCE_BUDGET
from .errors import RuntimeFailure
from .security import Extraction

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIALOGUE_DIR = ROOT / "data" / "dialogue"
SAVE_PATH = ROOT / "saves" / "campaign.json"  # §10.5: one slot, and the player never picks a name


@dataclass
class CampaignHost:
    """`dialogue.Host`: the effects that touch live state (dialogue.md §3.1).

    A conversation at the Hub has no Clock and no actors, which is why validation refuses `tick_clock`
    in a `"context": "hub"` file (dialogue.md §7.2). So the host holds an optional Run and says so
    rather than pretending: asking a Hub conversation to tick the Clock is a programming error, and
    one that the validator has already made impossible.
    """

    campaign: CampaignState
    run: run_mod.RunState | None = None
    tests: list[tuple[str, str, int]] = field(default_factory=list)

    def tick_clock(self, reason: str, segments: int) -> None:
        if self.run is None:
            raise RuntimeFailure([f"no Run to tick the Clock for event {reason!r}"])
        self.run.world.clock.tick(reason, times=segments)

    def give_item(self, item_id: str, qty: int) -> None:
        self.campaign.give_item(item_id, qty)

    def on_test(self, conversation_id: str, key: str, roll: Any, net: int) -> None:
        """Report a resolved roll. ADR-0006's XP and Perk payout is Phase 3's consumer; recording it
        here is what keeps the payout hook out of the engine."""
        self.tests.append((conversation_id, key, net))

    def pool_bonus(self) -> int:
        """§4's Wound Modifier on the speaking Runner's pool, from their sheet rather than an Actor:
        at the Hub nobody is spawned, and the boxes are Hub state (§10.3)."""
        sheet = self._pc_sheet()
        return entities.wound_modifier_from_boxes(sheet.physical, sheet.stun)

    def _pc_sheet(self) -> campaign_mod.RunnerSheet:
        runner_id = getattr(self.campaign, "_pc", None)
        for sheet in self.campaign.runners:
            if runner_id is None or sheet.id == runner_id:
                return sheet
        raise RuntimeFailure(["no bound Runner to speak for the crew"])


@dataclass
class ScriptedPresenter:
    """`dialogue.Presenter` that keeps what a screen would have shown, so a test can assert on it."""

    lines: list[tuple[str, str]] = field(default_factory=list)
    shown: list[tuple[str, ...]] = field(default_factory=list)
    closed: str | None = None

    def line(self, speaker: str, text: str) -> None:
        self.lines.append((speaker, text))

    def choices(self, texts: tuple[str, ...] | list[str]) -> None:
        self.shown.append(tuple(texts))

    def close(self, reason: str) -> None:
        self.closed = reason


def choose_index(shown: tuple[str, ...], wants: tuple[str, ...]) -> int:
    """The index to pick at a choice screen: the first `wants` entry that matches a shown choice.

    Selecting by text rather than by index, because a gated choice is *filtered out* when its
    condition fails - so the same index means different things to a Runner who qualifies and one who
    does not, which is exactly what the acceptance test has to drive.
    """
    for want in wants:
        for index, text in enumerate(shown):
            if want in text:
                return index
    return 0


def play(
    runner: dialogue.DialogueRunner,
    conversation: dialogue.Conversation,
    *,
    wants: tuple[str, ...] = (),
    pc_actor: str = "pc",
) -> ScriptedPresenter:
    """Drive a conversation to its end, preferring `wants` at every choice screen.

    The budget is the engine's own AUTO_ADVANCE_BUDGET, so a conversation that cannot finish fails
    here the way it fails in play rather than hanging a test.
    """
    runner.start(
        actors={conversation.interlocutor or "npc": "npc", conversation.pc: pc_actor},
        pc_actor=pc_actor,
    )
    for _ in range(AUTO_ADVANCE_BUDGET):
        if runner.state == dialogue.RunnerState.WAITING_CONTINUE:
            runner.advance()
        elif runner.state == dialogue.RunnerState.WAITING_CHOICE:
            runner.choose(choose_index(runner.presenter.shown[-1], wants))
        else:
            break
    return runner.presenter


@dataclass
class Session:
    """A campaign, the Hub it happens in, and at most one Run in flight."""

    campaign: CampaignState
    path: pathlib.Path = SAVE_PATH
    run: run_mod.RunState | None = None
    hub: hub_mod.Hub = field(init=False)

    def __post_init__(self) -> None:
        self.hub = hub_mod.Hub(self.campaign)

    # -- lifecycle -------------------------------------------------------------------------
    @classmethod
    def new(cls, seed: int | None = None, path: pathlib.Path = SAVE_PATH) -> Session:
        session = cls(campaign_mod.new_campaign(seed), path)
        session.save()  # §10.5: the safehouse autosave, which is where a campaign starts
        return session

    @classmethod
    def load(cls, path: pathlib.Path = SAVE_PATH) -> Session:
        return cls(save_mod.load(path), path)

    def save(self) -> pathlib.Path:
        return save_mod.save(self.campaign, self.path)

    def resume(self) -> Session:
        """Save, then load it back. The round-trip a player makes between sessions."""
        self.save()
        return Session.load(self.path)

    # -- talking ---------------------------------------------------------------------------
    def talk(
        self,
        conversation_id: str,
        *,
        runner_id: str | None = None,
        wants: tuple[str, ...] = (),
        presenter: ScriptedPresenter | None = None,
        dice: Any = None,
        seed: int = 0,
    ) -> ScriptedPresenter:
        """Run one conversation at the Hub. Returns what the screen would have shown.

        `dice` is injected rather than assumed: play passes the seeded stream, and a test passes
        ScriptedDice so a social roll's outcome is chosen rather than hoped for.
        """
        conversation = dialogue.load_conversation(
            DIALOGUE_DIR / f"{conversation_id}.json", known_flags=self.campaign.flags
        )
        self._declare(conversation)
        if runner_id is not None:
            self.campaign.bind_pc(runner_id)
        engine = dialogue.DialogueRunner(
            conversation,
            self.campaign,
            presenter or ScriptedPresenter(),
            dice if dice is not None else dialogue.RandomDice(random.Random(seed)),
            CampaignHost(self.campaign, self.run),
        )
        return play(engine, conversation, wants=wants)

    def _declare(self, conversation: dialogue.Conversation) -> None:
        """Declare a conversation's own `test.*` and `flags.*` keys in the campaign store.

        The engine resolves a key through the store, so a conversation's private keys have to exist
        before it runs; `declare` never overwrites, so a key another conversation or the save already
        seeded keeps its value.
        """
        for key in conversation.test_keys:
            for suffix, kind, default in (
                ("hits", int, 0),
                ("net", int, 0),
                ("glitch", bool, False),
            ):
                self.campaign.declare(
                    f"test.{key}.{suffix}",
                    default,
                    campaign_mod.SCOPE_RUN,
                    writable=True,
                    kind=kind,
                )
        for name, default in conversation.vars.items():
            self.campaign.declare(
                f"flags.{name}", bool(default), campaign_mod.SCOPE_JOB, writable=True, kind=bool
            )

    def take(self, offer_id: str) -> campaign_mod.ActiveJob:
        return self.hub.take_job(offer_id)

    # -- the handoff -----------------------------------------------------------------------
    def depart(self) -> run_mod.RunState:
        """Hub to Run: the `RunSpec` is everything `build_run` needs, and the roster is what carries
        a purchase, an Advance and a filled monitor into the Site."""
        spec = self.hub.run_spec()
        self.run = run_mod.build_run(
            spec.job_type,
            spec.run_seed,
            heat=spec.heat,
            clock_credit=spec.clock_credit,
            roster=list(self.campaign.runners),
        )
        return self.run

    def come_home(self, *, voluntary: bool, net_negotiation_hits: int = 0) -> Extraction:
        """Run to Hub: price it, apply all three consequences in one place, and autosave."""
        if self.run is None:
            raise RuntimeFailure(["no Run in flight"])
        extraction = run_mod.extract(
            self.run, voluntary=voluntary, net_negotiation_hits=net_negotiation_hits
        )
        self.hub.report_extraction(extraction)
        self.run = None
        self.save()
        return extraction


# ==============================================================================================
# The acceptance test - roadmap.md Phase 2, points 1-5
# ==============================================================================================
def demo() -> None:
    # ---- 1. a choice gated on skill.negotiation changes the payout and writes the store -------
    # The Fixer's offer node carries both choices, the second gated on `skill.negotiation >= 4`; the
    # gated one runs an opposed test and writes `job.payout_agreed = payout_base + 100 x net`. All 6s
    # make that roll succeed by a known margin, so the test asserts the formula rather than a seed.
    HAGGLE = ("risk is 15k",)

    def haggle(negotiation: int, seed: int) -> tuple[int, int, Any]:
        state = campaign_mod.new_campaign(seed)
        for sheet in state.runners:
            sheet.skills["negotiation"] = negotiation
        session = Session(state, pathlib.Path("/tmp") / "_unused.json")
        # The board comes first: taking the Job is what binds `job.*`, so the Fixer negotiates against
        # a real record rather than an offer with no agreed price to move yet.
        session.take(session.hub.offers()[0].id)
        base = int(state.get("job.payout_base"))
        session.talk(
            "fixer_offer",
            runner_id="adept",
            wants=(*HAGGLE, "I'm in"),
            dice=dialogue.ScriptedDice([6] * 40),
            seed=seed,
        )
        return base, int(state.get("job.payout_agreed")), state.get("job.state")

    base, shy, state_shy = haggle(3, 20261001)
    _, bold, state_bold = haggle(4, 20261001)
    assert shy == base, f"without the rating the gated choice is filtered out: {shy} vs {base}"
    assert bold > base, f"the negotiation gate must move the money: {base} -> {bold}"
    assert (bold - base) % 100 == 0, "and it moves in whole net hits, per section 4.1's formula"
    assert state_shy == state_bold == "accepted", (
        f"either way the conversation accepted the Job, got {state_shy!r} and {state_bold!r}"
    )

    # ---- 2 and 3. extraction: voluntary pays and cools, forced pays nothing and costs ---------
    def extract_with(voluntary: bool) -> tuple[int, int, int]:
        session = Session(
            campaign_mod.new_campaign(20261002), pathlib.Path("/tmp") / "_unused.json"
        )
        session.campaign.heat = 5  # above zero, or a decay is invisible against the floor
        session.take(session.hub.offers()[0].id)
        before = (session.campaign.nuyen, session.campaign.heat, session.campaign.rep_fixer)
        run = session.depart()
        # A voluntary extraction is only successful if a living Runner stands on the Paydata, since
        # `extract` pro-rates on `crew_at_objective()` (world.md 4.1). Put one there rather than
        # asserting a payout the engine would refuse to pay.
        paydata = run.paydata_cell()
        assert paydata is not None, "an extraction Site has a paydata cell"
        run.crew[0].pos = paydata
        assert run.crew_at_objective(), "the crew reached the vault"
        session.come_home(voluntary=voluntary, net_negotiation_hits=2)
        after = (session.campaign.nuyen, session.campaign.heat, session.campaign.rep_fixer)
        return (after[0] - before[0], after[1] - before[1], after[2] - before[2])

    paid, cooled, _ = extract_with(True)
    assert paid == 12000 + 100 * 2, f"12,000 plus 100 per net hit, got {paid}"
    assert cooled == -1, "a successful Job decays Heat by 1 (item 4)"

    forced_pay, forced_heat, forced_rep = extract_with(False)
    assert forced_pay == 0, "a forced extraction pays nothing"
    assert forced_heat == 2, "and adds Heat +2"
    assert forced_rep == -1, "and drops Fixer reputation by 1"

    # ---- 4. gear bought at the Hub is in the Runner's hands on the Site ----------------------
    session = Session(campaign_mod.new_campaign(20261003), pathlib.Path("/tmp") / "_unused.json")
    buyer = session.campaign.runners[0]
    session.campaign.nuyen = 50_000
    session.take(session.hub.offers()[0].id)
    # 3.2's Buy Gear action is what opens the shop, so a purchase costs a Legwork slot, not just money.
    session.hub.legwork("buy_gear")
    stock = [item for item in session.hub.shop_stock() if item not in buyer.loadout]
    stock = [item for item in stock if item != "ammunition"]  # a reload is not a loadout entry
    assert stock, f"the shop stocks something the Runner lacks: {session.hub.shop_stock()}"
    item = stock[0]
    bought = session.hub.buy(item, buyer.id)
    assert bought, f"the shop sold the {item}"
    assert item in buyer.loadout, f"and the loadout is where a purchase lands: {buyer.loadout}"
    run = session.depart()
    spawned = next(actor for actor in run.crew if actor.id == 1)  # the buyers' actor id
    role = spawned.role
    assert isinstance(role, entities.RunnerRole)
    carried = [entry.slug for entry in role.inventory]
    assert item in carried, f"the Run's Runner carries the purchase, got {carried}"

    # ---- 5. a save round-trips, and the next Run's Site differs by run counter ---------------
    session = Session(campaign_mod.new_campaign(20261004), pathlib.Path("/tmp") / "_unused.json")
    offer = session.hub.offers()[0]
    # Taking a Job costs a day (§1.3), and a day's rest heals two boxes (Stun first). Set the boxes
    # after it, or this asserts the recovery rather than what the save actually keeps.
    session.take(offer.id)
    sheet = session.campaign.runners[0]
    sheet.physical = 2
    sheet.stun = 1
    sheet.xp = 9
    session.campaign.heat = 6
    session.campaign.rep_fixer = 2
    session.campaign.change_rep("faction:corp_arasaka", -1)
    assert session.campaign.active is not None, "taking an offer binds the Job"
    seed_one = session.campaign.active.run_seed

    reloaded = session.resume()
    back = reloaded.campaign
    assert back.active is not None, "the active Job round-trips"
    assert back.nuyen == session.campaign.nuyen and back.heat == 6, "nuyen and Heat round-trip"
    assert back.rep_fixer == 2, "Fixer reputation round-trips"
    assert back.rep_factions.get("corp_arasaka") == -1, "and a faction's, unprefixed"
    assert back.flags == session.campaign.flags, "world flags round-trip"
    assert (back.runners[0].physical, back.runners[0].stun) == (2, 1), "monitor boxes round-trip"
    assert back.runners[0].xp == 9, "XP round-trips"
    assert back.active is not None and back.active.run_seed == seed_one, "the Run seed is stored"
    assert "qi" not in back.runners[0].to_dict(), "Qi resets per Run and is never persisted"

    # a deliberate retry at the same Job increments the counter, so the Site is a new one. Attempt 2
    # only exists after attempt 1 has closed, and a forced extraction is what closes a failed Job.
    assert reloaded.campaign.active is not None, "the Job is still bound"
    job_type = hub_mod.Hub.job_type(reloaded.campaign.active)
    first = reloaded.depart()
    reloaded.come_home(voluntary=False)
    assert reloaded.campaign.active is None, "a closed Job stops being active"
    retry = reloaded.take(offer.id)
    assert retry.run_seed != seed_one, "attempt 2 at one Job draws a different Site"
    again = run_mod.build_run(job_type, seed_one, roster=list(reloaded.campaign.runners))
    assert room_layout(again.site) == room_layout(first.site), (
        "the same seed gives the same Site, so nothing is re-drawn by accident"
    )
    second = reloaded.depart()
    assert room_layout(second.site) != room_layout(first.site), (
        "and a new attempt gives a different one"
    )
    print(
        f"OK  session: negotiation gate {shy} -> {bold} (base {base}), voluntary +{paid} heat {cooled}, "
        f"forced {forced_pay} heat +{forced_heat} rep {forced_rep}, "
        f"seed stored and retry differs, {len(back.runners)} sheets round-tripped"
    )


def room_layout(site: Any) -> list[tuple[int, int, int, int]]:
    """A Site's shape, independent of its node ids: the room rectangles in a stable order."""
    return sorted((room.x, room.y, room.w, room.h) for room in site.rooms.values())


if __name__ == "__main__":
    demo()

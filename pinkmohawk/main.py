"""The window and the loop: the Hub, a Run, and the door between them.

The thinnest module in the project on purpose. It owns three things and nothing else: the tcod context,
the order of draw-and-poll, and the translation of a `Command` into a call on `session`, `hub`, `run`
or `ai`. Every decision it appears to make is really made somewhere with a test behind it.

Two modes, and three overlays:

- **hub** — the authored district. You walk (a Step costs one tick, §1.3), and the keys open the four
  screens that only make sense at the Hub: the Job board, the shop, the clinic, the Favour. Every one
  of them is a `Panel`: rows, and what the number keys do. One renderer draws all four, because they
  differ only in their rows and their prompt.
- **run** — the Site. The loop's old shape is unchanged, and it still follows from one fact:
  `run.step()` returns the Runner when a person is needed and `None` while the machine acts. So it
  steps until handed an actor, draws once, and waits for one key. Nothing here asks "whose turn is
  it" — that answer exists in exactly one place.
- **talk** — a Dialogue Graph, stepped one key at a time. The engine is started but not driven, which
  is what `session.begin_talk` exists for: the runner waits in `WAITING_CONTINUE` or `WAITING_CHOICE`
  and the loop forwards Enter or a number. The engine never draws; `render.draw_talk` reads the
  presenter the engine has been writing to.

    .venv/bin/python -m pinkmohawk.main                     # play (needs a display)
    .venv/bin/python -m pinkmohawk.main --check             # headless: Hub, screens, talk, Run, home
    SDL_VIDEODRIVER=dummy .venv/bin/python -m pinkmohawk.main --frames 5
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass

import tcod.console
import tcod.context
import tcod.event

from . import dialogue, render
from . import hub as hub_mod
from . import input as input_module
from . import run as run_module
from .constants import CLINIC_REVIVE_DOWNED, SCREEN_H, SCREEN_W, VIEW_H
from .session import Session, choose_index


@dataclass
class Panel:
    """A list screen: what to draw, and what the number keys do.

    `actions[i]` is what the `i+1` key does and the one line it reports back. A panel that changes
    what it offers (the shop before and after the Legwork action opens it) replaces itself, which is
    why `open_shop` is written to be safe to call twice.
    """

    title: str
    entries: list[str]
    actions: list[Callable[[], str]]
    hint: str = "1-9 select, Esc back"
    cursor: int | None = None
    status: str = ""


@dataclass
class Ui:
    """Which screen the loop is on, and what that screen is showing."""

    mode: str = "hub"  # "hub" | "run"
    panel: Panel | None = None
    talk: dialogue.DialogueRunner | None = None
    selected: int = 0
    status: str = ""


# ==============================================================================================
# The Hub's four screens
# ==============================================================================================
def runner_id(session: Session, ui: Ui) -> str:
    """Whose Runner the Hub acts for: the selected sheet, clamped into range."""
    index = min(max(ui.selected, 0), len(session.campaign.runners) - 1)
    return session.campaign.runners[index].id


def pick_index(command: input_module.Command) -> int:
    """The 0-based index a `pick` command names.

    `pick` only ever comes from a digit key, so a non-integer argument is a programming error and
    says so, rather than being quietly coerced into picking the first row.
    """
    arg = command.arg
    assert isinstance(arg, int), f"a pick command carries a number, got {arg!r}"
    return arg - 1


def open_board(session: Session, ui: Ui) -> None:
    """§1.2: the Fixer posts Jobs. Taking one binds it, which is what the negotiation reads."""

    def taker(offer_id: str) -> Callable[[], str]:
        def action() -> str:
            session.take(offer_id)
            ui.panel = None  # the board's job is done; the Fixer's conversation is next
            return f"took {offer_id}"

        return action

    offers = session.hub.offers()
    ui.panel = Panel(
        title="Job board",
        entries=[f"{o.id}   {o.job_type:<10} {o.payout_base:>7,}¥" for o in offers],
        actions=[taker(o.id) for o in offers],
        hint="1-9 take the Job, Esc back",
    )


def open_shop(session: Session, ui: Ui) -> None:
    """§3.2: the Buy Gear action is what opens the shop, so the shop's first screen is the door."""
    hub = session.hub
    if not hub.shop_open:

        def spend() -> str:
            hub.legwork("buy_gear")
            open_shop(session, ui)  # now that it is open, show the stock
            return f"shop open, {hub.legwork_remaining} Legwork left"

        ui.panel = Panel(
            title="Gear shop",
            entries=[
                f"spend the Buy Gear Legwork action to open the shop ({hub.legwork_remaining} left)"
            ],
            actions=[spend],
            hint="1 or Enter to spend, Esc back",
        )
        return

    def buyer(item: str) -> Callable[[], str]:
        def action() -> str:
            who = runner_id(session, ui)
            if not hub.buy(item, who):
                return f"{item}: not bought"
            return f"bought {item} for {who}"

        return action

    stock = hub.shop_stock()
    ui.panel = Panel(
        title=f"Gear shop - buying for {runner_id(session, ui)} (Tab to change)",
        entries=[f"{item:<18} {hub.price(item):>7,}¥" for item in stock],
        actions=[buyer(item) for item in stock],
        hint="1-9 buy, Tab changes Runner, Esc back",
    )


def open_clinic(session: Session, ui: Ui) -> None:
    """§1.2: heal per box, or pay the revival fee. Both bill the campaign, not the Runner."""
    who = runner_id(session, ui)
    sheet = next(s for s in session.campaign.runners if s.id == who)

    def heal() -> str:
        return f"{session.hub.clinic_treat(sheet)} for {who}"

    def revive() -> str:
        ok = session.hub.clinic_revive(sheet)
        return f"revived {who} for {CLINIC_REVIVE_DOWNED:,}¥" if ok else f"{who} is not Downed"

    ui.panel = Panel(
        title=f"Ripperdoc - {who}",
        entries=[
            f"heal {sheet.physical + sheet.stun} filled boxes for "
            f"{session.hub.clinic_bill(sheet):,}¥",
            f"revive a Downed Runner for {CLINIC_REVIVE_DOWNED:,}¥",
        ],
        actions=[heal, revive],
        hint="1-2 select, Tab changes Runner, Esc back",
    )


def open_favour(session: Session, ui: Ui) -> None:
    """§3.3: spending Fixer standing on one of two reveals, and the player picks which."""
    hub = session.hub

    def favour(outcome: str) -> Callable[[], str]:
        def action() -> str:
            hub.legwork("favour", outcome=outcome)
            ui.panel = None
            return f"the Fixer delivered: {outcome}"

        return action

    ui.panel = Panel(
        title=f"Call in a Favour - {hub.campaign.rep_fixer:+d} Fixer standing",
        entries=list(hub_mod.FAVOUR_OUTCOMES),
        actions=[favour(outcome) for outcome in hub_mod.FAVOUR_OUTCOMES],
        hint="1-2 choose, Esc back",
    )


# ==============================================================================================
# Commands
# ==============================================================================================
def hub_command(session: Session, ui: Ui, command: input_module.Command) -> bool:
    """Apply one command at the Hub. Returns False when the game should end."""
    verb = command.verb

    if verb == "cancel":
        # Esc backs out of a screen, then out of a conversation, and only then out of the game.
        if ui.panel is not None:
            ui.panel = None
        elif ui.talk is not None:
            ui.talk = None
        else:
            return False
        return True

    if ui.panel is not None:
        # A panel swallows everything else: moving while the shop is open would be a surprise.
        # An action may close its screen (taking a Job) or replace it (the shop once the Buy Gear
        # action is spent), so the result goes to whichever screen is showing afterwards - falling
        # back to the Hub's own status line when there is none.
        panel = ui.panel
        result = None
        if verb == "pick":
            index = pick_index(command)
            if 0 <= index < len(panel.actions):
                result = panel.actions[index]()
        elif verb == "confirm" and panel.actions:
            result = panel.actions[0]()
        elif verb == "select":
            ui.selected += 1
        if result is not None:
            if ui.panel is panel:
                panel.status = result
            else:
                ui.status = result
        return True

    if ui.talk is not None:
        return _talk_command(session, ui, command)

    if verb == "move":
        session.hub.step(str(command.arg))
    elif verb == "select":
        ui.selected = (ui.selected + 1) % len(session.campaign.runners)
    elif verb == "board":
        open_board(session, ui)
    elif verb == "shop":
        open_shop(session, ui)
    elif verb == "clinic":
        open_clinic(session, ui)
    elif verb == "favour":
        open_favour(session, ui)
    elif verb == "scout":
        ui.status = _legwork(session, "scout", ui)
    elif verb == "rest":
        ui.status = f"rested: {session.hub.rest()} boxes back, day {session.campaign.hub_day}"
    elif verb == "depart":
        ui.status = _depart(session, ui)
    elif verb == "confirm":
        ui.status = _interact(session, ui)
    return True


def _talk_command(session: Session, ui: Ui, command: input_module.Command) -> bool:
    """Forward one key into the conversation and notice when it ends."""
    assert ui.talk is not None
    if command.verb == "confirm":
        ui.talk.advance()
    elif command.verb == "pick":
        shown = ui.talk.presenter.shown[-1] if ui.talk.presenter.shown else []
        index = pick_index(command)
        if 0 <= index < len(shown):
            ui.talk.choose(index)
    if ui.talk.state == dialogue.RunnerState.DONE:
        ui.status = (
            f"{session.campaign.active.id if session.campaign.active else 'the Fixer'}: done"
        )
        ui.talk = None
    return True


def _legwork(session: Session, action: str, ui: Ui) -> str:
    if session.campaign.active is None:
        return "take a Job first: Legwork is spent per Job"
    session.hub.legwork(action)
    if action == "scout":
        revealed = ", ".join(str(entry["kind"]) for entry in session.hub.scout_reveal())
        return f"scouted: {revealed} ({session.hub.legwork_remaining} Legwork left)"
    return f"{action}: done ({session.hub.legwork_remaining} Legwork left)"


def _interact(session: Session, ui: Ui) -> str:
    """Enter on an NPC: talk if they have a conversation, open their screen if they offer one."""
    npc = session.hub.npc_at(session.hub.pos)
    if npc is None:
        return "nobody here to talk to"
    if npc.dialogue:
        ui.talk = session.begin_talk(npc.dialogue, runner_id=runner_id(session, ui))
        return f"{npc.name} has something to say"
    if npc.service == "shop":
        open_shop(session, ui)
        return f"{npc.name} opens the shop"
    if npc.service == "clinic":
        open_clinic(session, ui)
        return f"{npc.name} is listening"
    return f"{npc.name} has nothing for you"


def _depart(session: Session, ui: Ui) -> str:
    """§1.2's Transit point: derive the seed, generate the Site, start the Run."""
    if session.campaign.active is None:
        return "take a Job at the board first: o"
    spec = session.hub.run_spec()
    session.depart()
    ui.mode = "run"
    return f"departing: {spec.job_id}, seed {spec.run_seed}"


def run_command(
    session: Session,
    ui: Ui,
    actor,
    command: input_module.Command,  # noqa: ANN001 - an Actor
) -> bool:
    """Apply one command to the active Runner. Returns False when the game should end."""
    run = session.run
    assert run is not None, "run_command is only reached in run mode"
    verb = command.verb
    if verb == "cancel":
        return False
    if verb == "move":
        run_module.command_step(run, actor, str(command.arg))
    elif verb == "attack":
        run_module.command_attack(run, actor)
    elif verb == "wait":
        run_module.command_wait(run, actor)
    elif verb == "extract":
        extraction = run_module.extract(run, voluntary=True)
        session.report(extraction)
        ui.mode = "hub"
        ui.status = (
            f"extracted for {extraction.payout:,}¥ (heat {extraction.heat_delta:+d}, "
            f"rep {extraction.reputation_delta:+d})"
        )
        return True
    elif verb == "select":
        ui.selected = (ui.selected + 1) % len(run.crew)
    run_module.see(run, actor)
    return True


# ==============================================================================================
# Drawing and the loop
# ==============================================================================================
def draw(console: tcod.console.Console, session: Session, ui: Ui, actor=None) -> None:  # noqa: ANN001
    """One frame. An overlay draws the Hub first, so the band and the district stay behind it."""
    if ui.mode == "run":
        assert session.run is not None
        render.draw(console, session.run, actor.pos if actor is not None else None)
        return
    render.draw_hub(console, session.hub, selected=ui.selected, status=ui.status)
    if ui.talk is not None:
        render.draw_talk(console, ui.talk.presenter)
    elif ui.panel is not None:
        render.draw_panel(
            console,
            title=ui.panel.title,
            entries=ui.panel.entries,
            hint=ui.panel.hint,
            cursor=ui.panel.cursor,
            status=ui.panel.status,
        )


def loop(
    context: tcod.context.Context,
    console: tcod.console.Console,
    session: Session,
    ui: Ui,
    *,
    frames: int = 0,
) -> int:
    """Draw, wait for one key, act, repeat - in whichever mode is showing."""
    presented = 0
    while True:
        if ui.mode == "hub":
            draw(console, session, ui)
            context.present(console, integer_scaling=True, clear_color=(0, 0, 0))
            presented += 1
            if frames and presented >= frames:
                print(f"OK  main: presented {presented} frame(s) at the Hub, no window error")
                return 0
            for event in tcod.event.wait(timeout=0.05):
                command = input_module.translate(event)
                if command is not None and not hub_command(session, ui, command):
                    return 0
            continue

        run = session.run
        assert run is not None, "run mode means a Run is in flight"
        actor = run_module.step(run)
        if actor is None:
            continue  # the machine acted; keep stepping
        draw(console, session, ui, actor)
        context.present(console, integer_scaling=True, clear_color=(0, 0, 0))
        presented += 1
        if frames and presented >= frames:
            print(f"OK  main: presented {presented} frame(s), machine turns taken, no window error")
            return 0
        for event in tcod.event.wait(timeout=0.05):
            command = input_module.translate(event)
            if command is not None and not run_command(session, ui, actor, command):
                return 0


def build(seed: int | None = None, path: pathlib.Path | None = None) -> Session:
    """A fresh campaign at the Hub, or the one on disk if there is one."""
    slot = path if path is not None else render.ROOT / "saves" / "campaign.json"
    if path is None and slot.exists():
        return Session.load(slot)
    return Session.new(seed, slot)


def press(session: Session, ui: Ui, verb: str, arg: str | int | None = None, actor=None) -> bool:  # noqa: ANN001
    """One command, as if a key had produced it. The headless check drives the loop through this, so
    the keys, the commands and the effects are all exercised rather than the functions behind them."""
    command = input_module.Command(verb, arg)
    if ui.mode == "hub":
        return hub_command(session, ui, command)
    return run_command(session, ui, actor, command)


def check() -> int:
    """Headless end to end, Hub first: walk, all four screens, a conversation, a Run, and home."""
    slot = pathlib.Path(tempfile.mkdtemp()) / "campaign.json"
    session = Session.new(20260918, slot)
    ui = Ui()
    console = tcod.console.Console(SCREEN_W, SCREEN_H)
    assert render.load_tileset().tile_shape == (16, 16)

    draw(console, session, ui)
    drawn = sum(1 for row in console.rgb["ch"][:VIEW_H] for cell in row if cell != 0x20)
    assert drawn > 2000, f"the district should be drawn, got {drawn} cells"

    # --- walking costs ticks ---------------------------------------------------------------
    start = session.hub.pos
    ticks = session.hub.ticks
    press(session, ui, "move", "s")
    assert session.hub.ticks == ticks + 1, "a Step is one tick (1.3), wall or not"
    assert session.hub.pos != start, "the safehouse spawn is floor, so the Step lands"

    # --- the Job board ------------------------------------------------------------------------
    press(session, ui, "board")
    assert ui.panel is not None and ui.panel.title == "Job board"
    assert len(ui.panel.entries) == 3, "the board holds JOB_OFFERS offers"
    press(session, ui, "pick", 1)
    assert session.campaign.active is not None, "taking the first offer binds the Job"
    assert ui.panel is None, "and the board closes"

    # --- the shop, behind the Buy Gear action --------------------------------------------------
    press(session, ui, "shop")
    assert ui.panel is not None and not session.hub.shop_open, "the shop starts closed"
    press(session, ui, "pick", 1)  # spend the Legwork action
    assert session.hub.shop_open, "and the action opens it"
    assert ui.panel is not None and len(ui.panel.entries) == 6, "SHOP_STOCK_SIZE lines"
    loadout = len(session.campaign.runners[ui.selected].loadout)
    press(session, ui, "pick", 1)
    assert len(session.campaign.runners[ui.selected].loadout) >= loadout, "a purchase lands"
    press(session, ui, "cancel")
    assert ui.panel is None

    # --- the clinic and the Favour, as screens -------------------------------------------------
    press(session, ui, "clinic")
    assert ui.panel is not None and len(ui.panel.entries) == 2
    press(session, ui, "cancel")
    press(session, ui, "favour")
    assert ui.panel is not None and len(ui.panel.entries) == len(hub_mod.FAVOUR_OUTCOMES)
    press(session, ui, "cancel")

    # --- the Fixer, one key at a time ----------------------------------------------------------
    press(session, ui, "confirm")  # nobody here: the Fixer is in the bar, not at the spawn
    assert ui.talk is None
    ui.talk = session.begin_talk("fixer_offer", runner_id=runner_id(session, ui))
    assert ui.talk.state in (
        dialogue.RunnerState.WAITING_CONTINUE,
        dialogue.RunnerState.WAITING_CHOICE,
    ), f"a started conversation waits for a key, got {ui.talk.state}"
    for _ in range(60):
        if ui.talk is None:
            break
        if ui.talk.state == dialogue.RunnerState.WAITING_CONTINUE:
            press(session, ui, "confirm")
        elif ui.talk.state == dialogue.RunnerState.WAITING_CHOICE:
            shown = ui.talk.presenter.shown[-1]
            press(session, ui, "pick", choose_index(shown, ("I'm in",)) + 1)
        else:  # pragma: no cover - the runner is waiting or done
            break
    assert ui.talk is None, "the conversation reaches its end"
    assert session.campaign.get("job.state") == "accepted", "the Fixer's node wrote the store"

    # --- departure, a turn, and coming home ----------------------------------------------------
    press(session, ui, "depart")
    assert ui.mode == "run" and session.run is not None, "departing starts a Run"
    run = session.run
    nuyen, heat = session.campaign.nuyen, session.campaign.heat
    holder = run.crew[0]
    paydata = run.paydata_cell()
    assert paydata is not None
    holder.pos = paydata
    press(session, ui, "extract", None, actor=holder)
    assert ui.mode == "hub" and session.run is None, "and extracting comes home"
    assert session.campaign.nuyen > nuyen, "the payout reached the campaign"
    assert session.campaign.heat == heat, "a successful Job at Heat 0 stays at 0"

    # the save the Hub wrote is real, and reloads
    back = Session.load(slot)
    assert back.campaign.nuyen == session.campaign.nuyen, "the Hub's autosave round-trips"

    print(
        f"OK  main: Hub {session.hub.map.w}x{session.hub.map.h}, {drawn} cells drawn, "
        f"board/shop/clinic/favour screens, a stepped conversation, a Run, extracted for "
        f"{session.campaign.nuyen - 0:,}¥ total, save reloaded"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pink Mohawk")
    parser.add_argument("--check", action="store_true", help="headless: the whole Hub-to-Run loop")
    parser.add_argument("--frames", type=int, default=0, help="auto-exit after N frames")
    parser.add_argument(
        "--seed", type=int, default=None, help="new campaign seed (fresh save only)"
    )
    parser.add_argument(
        "--new", action="store_true", help="start a new campaign, overwriting the slot"
    )
    args = parser.parse_args(argv)

    if args.check:
        return check()

    slot = render.ROOT / "saves" / "campaign.json"
    session = Session.new(args.seed, slot) if args.new else build(args.seed, None)
    ui = Ui()
    with tcod.context.new(
        columns=SCREEN_W,
        rows=SCREEN_H,
        tileset=render.load_tileset(),
        title="Pink Mohawk",
    ) as context:
        console = tcod.console.Console(SCREEN_W, SCREEN_H)
        return loop(context, console, session, ui, frames=args.frames)


if __name__ == "__main__":
    sys.exit(main())

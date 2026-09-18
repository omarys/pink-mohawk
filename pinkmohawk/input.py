"""Input: tcod events in, commands out. One of the three modules allowed to import `tcod`.

The keyboard mapping lives here and nowhere else, so the loop in `main.py` never inspects a key. A
command is a frozen record, so it can be logged, replayed, or produced by a test without an event
object existing.

`translate` is duck-typed on purpose: it reads `sym` if the event has one and asks `isinstance` only
for `Quit`. That keeps it testable with a two-line stub instead of a real SDL event.

    .venv/bin/python -m pinkmohawk.input      # runs demo()
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

import tcod.event

#: Two schemes, because both are reflexes: arrows and the vi keys.
MOVE_KEYS: Final = {
    tcod.event.KeySym.UP: "n",
    tcod.event.KeySym.DOWN: "s",
    tcod.event.KeySym.LEFT: "w",
    tcod.event.KeySym.RIGHT: "e",
    tcod.event.KeySym.K: "n",
    tcod.event.KeySym.J: "s",
    tcod.event.KeySym.H: "w",
    tcod.event.KeySym.L: "e",
    tcod.event.KeySym.Y: "nw",
    tcod.event.KeySym.U: "ne",
    tcod.event.KeySym.B: "sw",
    tcod.event.KeySym.N: "se",
}

#: The Hub's verbs. They are mapped here rather than in `main` for the same reason as `MOVE_KEYS`:
#: the loop never inspects a key, so it can be handed a `Command` from a test, a replay or a script.
#: The keys avoid the eight directions and the Run's own verbs on purpose - `j`, `k`, `l`, `y`, `u`,
#: `b` and `n` are movement, and `a`, `.` and `e` belong to a Run.
HUB_KEYS: Final = {
    tcod.event.KeySym.O: "board",
    tcod.event.KeySym.I: "shop",
    tcod.event.KeySym.C: "clinic",
    tcod.event.KeySym.R: "rest",
    tcod.event.KeySym.V: "scout",
    tcod.event.KeySym.T: "favour",
    tcod.event.KeySym.D: "depart",
}

#: Choices in a conversation or a list screen are picked by number, one through nine.
DIGIT_KEYS: Final = {getattr(tcod.event.KeySym, f"N{digit}"): digit for digit in range(1, 10)}


@dataclass(frozen=True, slots=True)
class Command:
    """What the loop should do about one keypress, without knowing which key it was.

    A Run answers to move/attack/wait/extract/crew; the Hub to move/confirm/board/shop/clinic/rest/
    scout/favour/depart/select; both to pick (a numbered choice) and cancel (back out, or quit when
    there is nothing to back out of).
    """

    verb: str
    arg: str | int | None = None


def translate(event: Any) -> Command | None:
    """One event to one command, or None when the key means nothing here."""
    if isinstance(event, tcod.event.Quit):
        return Command("cancel")
    sym = getattr(event, "sym", None)
    if sym is None:
        return None  # a mouse move, a window resize: not ours
    if sym == tcod.event.KeySym.ESCAPE:
        return Command("cancel")
    if sym in MOVE_KEYS:
        return Command("move", MOVE_KEYS[sym])
    if sym in DIGIT_KEYS:
        return Command("pick", DIGIT_KEYS[sym])
    if sym in HUB_KEYS:
        return Command(HUB_KEYS[sym])
    if sym in (tcod.event.KeySym.RETURN, tcod.event.KeySym.KP_ENTER, tcod.event.KeySym.SPACE):
        return Command("confirm")
    if sym == tcod.event.KeySym.A:
        return Command("attack")
    if sym == tcod.event.KeySym.PERIOD:
        return Command("wait")
    if sym == tcod.event.KeySym.E:
        return Command("extract")
    if sym == tcod.event.KeySym.TAB:
        return Command("select")
    return None


def demo() -> None:
    class KeyDown:
        """A stand-in for a keypress: `translate` only needs `.sym`."""

        def __init__(self, sym: int) -> None:
            self.sym = sym

    K = tcod.event.KeySym
    assert translate(KeyDown(K.UP)) == Command("move", "n")
    assert translate(KeyDown(K.H)) == Command("move", "w")
    assert translate(KeyDown(K.Y)) == Command("move", "nw")
    assert translate(KeyDown(K.A)) == Command("attack")
    assert translate(KeyDown(K.PERIOD)) == Command("wait")
    assert translate(KeyDown(K.E)) == Command("extract")
    assert translate(KeyDown(K.TAB)) == Command("select")
    assert translate(KeyDown(K.ESCAPE)) == Command("cancel")
    assert translate(KeyDown(K.Z)) is None, "an unbound key is not a command"
    assert translate(tcod.event.Quit()) == Command("cancel")
    assert translate(object()) is None, "an event without a sym is ignored, not crashed on"

    # The Hub's verbs, and the numbered choices a conversation and a list screen both use.
    assert translate(KeyDown(K.O)) == Command("board")
    assert translate(KeyDown(K.D)) == Command("depart")
    assert translate(KeyDown(K.RETURN)) == Command("confirm")
    assert translate(KeyDown(K.SPACE)) == Command("confirm")
    assert translate(KeyDown(K.N3)) == Command("pick", 3)
    assert translate(KeyDown(K.N9)) == Command("pick", 9)
    hub_verbs = set(HUB_KEYS.values())
    assert len(hub_verbs) == len(HUB_KEYS), f"one verb per key: {sorted(hub_verbs)}"
    assert hub_verbs.isdisjoint(set(MOVE_KEYS.values())), (
        f"a Hub verb may not shadow a direction: {sorted(hub_verbs & set(MOVE_KEYS.values()))}"
    )
    assert len(DIGIT_KEYS) == 9, "nine choices, and no tenth"

    directions = list(MOVE_KEYS.values())
    assert len(set(directions)) == 8, (
        f"eight distinct directions expected, got {sorted(set(directions))}"
    )
    assert set(directions) == {"n", "ne", "e", "se", "s", "sw", "w", "nw"}

    print(
        f"OK  input: {len(MOVE_KEYS)} movement bindings (arrows + vi keys), {len(HUB_KEYS)} Hub verbs,"
        f" {len(DIGIT_KEYS)} number keys, attack/wait/extract/select/cancel, "
        f"unbound keys and foreign events ignored"
    )


if __name__ == "__main__":
    demo()

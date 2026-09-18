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


@dataclass(frozen=True, slots=True)
class Command:
    """What the loop should do about one keypress, without knowing which key it was."""

    verb: str  # "move" | "attack" | "wait" | "extract" | "crew" | "quit"
    arg: str | int | None = None


def translate(event: Any) -> Command | None:
    """One event to one command, or None when the key means nothing here."""
    if isinstance(event, tcod.event.Quit):
        return Command("quit")
    sym = getattr(event, "sym", None)
    if sym is None:
        return None  # a mouse move, a window resize: not ours
    if sym == tcod.event.KeySym.ESCAPE:
        return Command("quit")
    if sym in MOVE_KEYS:
        return Command("move", MOVE_KEYS[sym])
    if sym == tcod.event.KeySym.A:
        return Command("attack")
    if sym == tcod.event.KeySym.PERIOD:
        return Command("wait")
    if sym == tcod.event.KeySym.E:
        return Command("extract")
    if sym == tcod.event.KeySym.TAB:
        return Command("crew")
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
    assert translate(KeyDown(K.TAB)) == Command("crew")
    assert translate(KeyDown(K.ESCAPE)) == Command("quit")
    assert translate(KeyDown(K.Z)) is None, "an unbound key is not a command"
    assert translate(tcod.event.Quit()) == Command("quit")
    assert translate(object()) is None, "an event without a sym is ignored, not crashed on"

    directions = list(MOVE_KEYS.values())
    assert len(set(directions)) == 8, (
        f"eight distinct directions expected, got {sorted(set(directions))}"
    )
    assert set(directions) == {"n", "ne", "e", "se", "s", "sw", "w", "nw"}

    print(
        f"OK  input: {len(MOVE_KEYS)} movement bindings (arrows + vi keys), "
        f"attack/wait/extract/crew/quit, unbound keys and foreign events ignored"
    )


if __name__ == "__main__":
    demo()

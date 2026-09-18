"""The window and the loop: build a Run, draw it, take commands, and let the machine take its turns.

The thinnest module in the project on purpose. It owns three things and nothing else: the tcod context,
the order of draw-and-poll, and the translation of a `Command` into a call on `run` or `ai`. Every
decision it appears to make is really made somewhere with a test behind it.

The loop's shape follows from one fact: `run.step()` returns the Runner when a person is needed and
`None` while the machine acts. So the loop steps until it is handed an actor, draws once, and waits for
one key. Nothing here asks "whose turn is it" — that answer only exists in one place.

    .venv/bin/python -m pinkmohawk.main                  # play (needs a display)
    .venv/bin/python -m pinkmohawk.main --check          # headless: build, draw, step, extract
    SDL_VIDEODRIVER=dummy .venv/bin/python -m pinkmohawk.main --frames 5     # headless window
"""

from __future__ import annotations

import argparse
import sys

import tcod.console
import tcod.context
import tcod.event

from . import input as input_module
from . import render
from . import run as run_module
from .constants import UI_ROWS, VIEW_H, VIEW_W


def handle(run: run_module.RunState, actor, command: input_module.Command) -> bool:
    """Apply one command to the active Runner. Returns False when the Run should end."""
    if command.verb == "quit":
        return False
    if command.verb == "move":
        run_module.command_step(run, actor, str(command.arg))
    elif command.verb == "attack":
        run_module.command_attack(run, actor)
    elif command.verb == "wait":
        run_module.command_wait(run, actor)
    elif command.verb == "extract":
        run_module.extract(run, voluntary=True)
        return False
    elif command.verb == "crew":
        pass  # one active Runner in v1; the slot is reserved
    run_module.see(run, actor)
    return not run.finished


def loop(
    context: tcod.context.Context,
    console: tcod.console.Console,
    run: run_module.RunState,
    *,
    frames: int = 0,
) -> int:
    """Step until a person is needed, draw, take one command, repeat."""
    presented = 0
    while not run.finished:
        actor = run_module.step(run)
        if actor is None:
            continue  # the machine acted; keep stepping
        render.draw(console, run, actor.pos)
        context.present(console, integer_scaling=True, clear_color=(0, 0, 0))
        presented += 1

        for event in tcod.event.wait(timeout=0.05):
            command = input_module.translate(event)
            if command is not None and not handle(run, actor, command):
                return 0

        if frames and presented >= frames:
            print(f"OK  main: presented {presented} frame(s), machine turns taken, no window error")
            return 0
    return 0


def build(job_type: str = "extraction", seed: int = 20260918) -> run_module.RunState:
    return run_module.build_run(job_type, seed)


def check() -> int:
    """Headless end to end: tileset, a frame, machine turns, a Runner's turn, an extraction."""
    run = build()
    tileset = render.load_tileset()
    assert tileset.tile_shape == (16, 16)

    console = tcod.console.Console(VIEW_W, VIEW_H + UI_ROWS)
    render.draw(console, run)
    drawn = sum(1 for row in console.rgb["ch"] for cell in row if cell != 0x20)
    assert drawn > 100, f"expected a populated frame, drew {drawn}"

    scout = run.crew[0]
    run_module.see(run, scout)
    for direction in ("e", "s", "w", "n", "e"):
        run_module.command_step(run, scout, direction)

    # Initiative decides who goes first, and a Runner may legitimately win the roll, so the check is
    # "the machine acts during a Round", not "the machine acts first".
    machine_steps = 0
    waiting = run_module.step(run)
    while waiting is None and machine_steps < 40:
        waiting = run_module.step(run)
        machine_steps += 1
    assert waiting is not None, "within a Round a Runner should get a turn"
    for _ in range(30):
        # `waiting` is legitimately None at the top of a pass: that IS the machine's turn, which is
        # why this guards the call instead of asserting the value.
        if waiting is not None:
            run_module.command_wait(run, waiting)
        else:
            machine_steps += 1
        waiting = run_module.step(run)
    assert machine_steps > 0, "over a Round the machine must take turns"

    paid = run_module.extract(run, voluntary=True)
    print(
        f"OK  main: Run built ({len(run.actors)} actors), {drawn} cells drawn, "
        f"{machine_steps} machine steps then a Runner's turn, extracted for "
        f"{paid.payout} (forced={paid.forced})"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pink Mohawk")
    parser.add_argument("--check", action="store_true", help="headless build/draw/step/extract")
    parser.add_argument("--frames", type=int, default=0, help="auto-exit after N frames")
    parser.add_argument("--seed", type=int, default=20260918)
    parser.add_argument("--job", default="extraction")
    args = parser.parse_args(argv)

    if args.check:
        return check()

    run = build(args.job, args.seed)
    with tcod.context.new(
        columns=VIEW_W, rows=VIEW_H + UI_ROWS, tileset=render.load_tileset(), title="Pink Mohawk"
    ) as context:
        console = tcod.console.Console(VIEW_W, VIEW_H + UI_ROWS)
        return loop(context, console, run, frames=args.frames)


if __name__ == "__main__":
    sys.exit(main())

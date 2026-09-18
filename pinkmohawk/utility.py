"""Utility scoring: ranking candidates, and the commitment rule that stops an actor vibrating.

DECISIONS §8 carries the formula and the per-archetype weights; `docs/design/ai.md` §6 is the
specification this implements, including §6.3's tie-break order, hysteresis rule and worked example.

Layer 1: this module imports coordinates-and-numbers only. It must never import `entities` — the
layer law in `data-model.md` §15 — so a candidate arrives as an opaque **handle** plus a frozen
record of the facts the caller measured. `ai.py` owns the measuring; this module owns the arithmetic.
That split is what lets the scorer be tested with hand-built facts and no world at all, and it is why
the worked example below can be asserted directly out of the document.

The formula (DECISIONS §8), with `distance` in Chebyshev cells:

    score = w_threat · 1/max(1, distance)
          + w_visible · (1 if visible else 0)
          + w_objective · objective_value
          − w_ally_risk · allied_fire_risk

`max(1, distance)` keeps the threat term finite when a target shares the actor's cell, which a player
command can produce. `objective_value` is 1.0 for a candidate inside the room named by the actor's
`objective` and 0.0 otherwise, so it needs no normalisation scale. `allied_fire_risk` is binary in v1:
1.0 when the firing corridor between the candidate and the target passes adjacent to a living ally.

    .venv/bin/python -m pinkmohawk.utility      # runs demo()
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final, Protocol

from .constants import ARCHETYPE_WEIGHTS

#: Below this many cells the threat term saturates. One cell is the closest two actors can stand.
MIN_DISTANCE: Final = 1


class Comparable(Protocol):
    """A handle must be orderable so ties resolve deterministically: ids for actors, cells for cells."""

    def __lt__(self, other: Any) -> bool: ...


@dataclass(frozen=True, slots=True)
class Weights:
    """One archetype's parameter block (DECISIONS §8)."""

    w_threat: float
    w_visible: float
    w_objective: float
    w_ally_risk: float
    hysteresis: float

    @classmethod
    def for_archetype(cls, archetype: str) -> Weights:
        """Read the contract's table. Raises for an archetype that has no block."""
        block = ARCHETYPE_WEIGHTS.get(archetype)
        if block is None:
            raise KeyError(
                f"no weight block for archetype {archetype!r}; known: {sorted(ARCHETYPE_WEIGHTS)}"
            )
        return cls(
            block["w_threat"],
            block["w_visible"],
            block["w_objective"],
            block["w_ally_risk"],
            block["hysteresis"],
        )


@dataclass(frozen=True, slots=True)
class CandidateFacts:
    """What the caller measured about one candidate. Facts, never scores or verdicts."""

    distance: int  # Chebyshev cells; 0 means a shared cell
    visible: bool
    objective_value: float = 0.0  # 1.0 inside the object's room, else 0.0
    allied_fire_risk: float = 0.0  # binary in v1: 0.0 or 1.0
    reaction: int = 0  # the candidate's Reaction, for the §6.3 tie-break


def score(weights: Weights, facts: CandidateFacts) -> float:
    """The §8 formula. Pure arithmetic, no clamping: the caller sees the real number.

    No normalisation scale is applied to `objective_value`: the contract fixed it at 1.0/0.0, and an
    earlier draft divided by a `MAX_OBJECTIVE_VALUE` that the contract does not have.
    """
    threat = weights.w_threat * (1.0 / max(MIN_DISTANCE, facts.distance))
    seen = weights.w_visible * (1.0 if facts.visible else 0.0)
    objective = weights.w_objective * facts.objective_value
    risk = weights.w_ally_risk * facts.allied_fire_risk
    return threat + seen + objective - risk


def choose[T: Comparable](
    weights: Weights,
    candidates: Sequence[tuple[T, CandidateFacts]],
    incumbent: T | None = None,
) -> T | None:
    """argmax by the §6.3 rule, then apply the commitment margin. `None` when nothing is available.

    Switching requires beating the incumbent by `weights.hysteresis`; a healthy incumbent that merely
    still scores well is kept, so an actor makes one decision rather than one per step. An incumbent
    that is no longer among the candidates (Downed, off-board, pin released) loses immediately.
    """
    if not candidates:
        return None

    scored = [(handle, facts, score(weights, facts)) for handle, facts in candidates]
    # sort, not max: the full key makes the winner independent of the input order
    scored.sort(key=lambda item: (-item[2], -item[1].reaction, item[0]))
    best_handle, _best_facts, best_score = scored[0]

    if incumbent is None:
        return best_handle
    incumbent_score = next((s for handle, _f, s in scored if handle == incumbent), None)
    if incumbent_score is None:
        return best_handle  # dropped this step -> no margin applies
    if best_score > incumbent_score + weights.hysteresis:
        return best_handle
    return incumbent


# ==============================================================================================
# Acceptance test — the worked example is the document's, not mine
# ==============================================================================================
def demo() -> None:
    guard = Weights.for_archetype("corp_guard")  # 1.0 / 2.0 / 1.5 / 3.0, hysteresis 0.10
    assert (guard.w_threat, guard.w_visible, guard.w_objective, guard.w_ally_risk) == (
        1.0,
        2.0,
        1.5,
        3.0,
    )
    assert guard.hysteresis == 0.10

    # ---- 1. ai.md §6.3's worked example, to the digit -----------------------------------
    a = CandidateFacts(
        distance=4, visible=True, objective_value=0.0, allied_fire_risk=0.0, reaction=5
    )
    b = CandidateFacts(
        distance=2, visible=True, objective_value=1.0, allied_fire_risk=1.0, reaction=6
    )
    assert score(guard, a) == 2.25, score(guard, a)
    assert score(guard, b) == 1.00, score(guard, b)
    # the guard declines to shoot through its own Ganger even for the closer, objective-critical
    # target: A wins on score, so with B as incumbent it must switch
    assert choose(guard, [("A", a), ("B", b)], incumbent="B") == "A"
    assert choose(guard, [("A", a), ("B", b)], incumbent=None) == "A"

    # ---- 2. the margin, in all three of §6.3's cases ------------------------------------
    near_a = CandidateFacts(distance=4, visible=True, reaction=5)  # 2.25
    assert score(guard, near_a) == 2.25
    # a candidate scoring 2.30 against an incumbent on 2.25: 2.30 > 2.35 is false -> stay
    strong_b = CandidateFacts(
        distance=2, visible=True, objective_value=1.0, allied_fire_risk=0.0, reaction=6
    )  # 0.5 + 2.0 + 1.5 = 4.0
    assert score(guard, strong_b) == 4.0
    assert choose(guard, [("A", near_a), ("B", strong_b)], incumbent="A") == "B"  # 4.0 > 2.35
    # an equal-scoring challenger can never win: it must *beat* the margin, not match it
    twin = CandidateFacts(distance=4, visible=True, reaction=9)  # also 2.25
    assert score(guard, twin) == score(guard, near_a)
    assert choose(guard, [("A", near_a), ("B", twin)], incumbent="A") == "A"

    # ---- 3. an incumbent that is no longer a candidate loses ---------------------------
    assert choose(guard, [("A", near_a)], incumbent="B") == "A"  # B went Down

    # ---- 4. the tie-break order: score, then Reaction, then handle ---------------------
    t1 = CandidateFacts(distance=2, visible=True, reaction=4)  # 0.5 + 2.0 = 2.5
    t2 = CandidateFacts(distance=2, visible=True, reaction=7)  # also 2.5
    assert score(guard, t1) == score(guard, t2)
    assert choose(guard, [("A", t1), ("B", t2)]) == "B", "higher Reaction wins the tie"
    t3 = CandidateFacts(distance=2, visible=True, reaction=7)
    assert choose(guard, [("B", t3), ("A", t2)]) == "A", "then lower handle wins"
    # and the answer does not depend on the order the caller supplied
    assert choose(guard, [("A", t2), ("B", t3)]) == choose(guard, [("B", t3), ("A", t2)]) == "A"

    # ---- 5. distance: a shared cell does not divide by zero ----------------------------
    touching = CandidateFacts(distance=0, visible=True)
    assert score(guard, touching) == 1.0 * 1.0 + 2.0, score(guard, touching)
    assert MIN_DISTANCE == 1

    # ---- 6. no candidates, or none visible, still returns a handle ---------------------
    assert choose(guard, []) is None
    blind = CandidateFacts(distance=3, visible=False)  # 1/3 + 0 = 0.333
    assert score(guard, blind) == 1.0 / 3
    assert choose(guard, [("A", blind)]) == "A", (
        "invisibility is not disqualifying, only unrewarded"
    )

    # ---- 7. every archetype in the contract loads, and its weights are usable ---------
    for archetype in sorted(ARCHETYPE_WEIGHTS):
        w = Weights.for_archetype(archetype)
        assert 0.0 <= w.hysteresis <= 1.0, (archetype, w.hysteresis)
        assert w.w_threat > 0.0, archetype
        assert score(w, a) == score(w, a)  # deterministic
    try:
        Weights.for_archetype("dragon")
        raise AssertionError("an unknown archetype must be refused")
    except KeyError:
        pass

    # ---- 8. the design intent, asserted rather than described --------------------------
    # The same two candidates, two archetypes: the Guard's 3.0 ally-risk makes it take the long
    # unobstructed shot, the Hellhound's 0.5 lets it fire into the melee. That difference is the
    # whole reason the weight exists (DECISIONS §8), so it is worth an assertion.
    hellhound = Weights.for_archetype("hellhound")  # 2.0 / 2.0 / 1.0 / 0.5
    risky = CandidateFacts(distance=1, visible=True, objective_value=1.0, allied_fire_risk=1.0)
    safe = CandidateFacts(distance=6, visible=True)
    assert score(guard, risky) == 1.5
    assert score(guard, safe) == 2.0 + 1.0 / 6
    assert choose(guard, [("risky", risky), ("safe", safe)]) == "safe"
    assert score(hellhound, risky) == 4.5
    assert choose(hellhound, [("risky", risky), ("safe", safe)]) == "risky"

    print(
        f"OK  utility: §6.3 worked example reproduced (A 2.25, B 1.00), margin keeps the "
        f"incumbent, ties by Reaction then handle, {len(ARCHETYPE_WEIGHTS)} archetype blocks load"
    )


if __name__ == "__main__":
    demo()

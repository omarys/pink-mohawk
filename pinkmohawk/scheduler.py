"""Turn order: an Energy bucket queue, with a binary heap kept alongside it for comparison.

DECISIONS §5 (Initiative Score as Energy, Pass, tie-break) and §13 row 5; rationale, the
bucket-versus-heap derivation and the canonical references are in docs/design/data-model.md §5.

The model, in one line: an actor's Initiative Score **is** its Energy for the turn, actions cost
fixed Energy, and when it cannot afford even a Step the Pass ends (`Score -= 10`) and a new Pass
begins while the Score is still positive.

Bucket queue rather than a binary heap, and the honest reason is not speed. Energy is an integer by
construction (Reaction + Intuition + 1d6, plus bounded Reflexes dice), so bucketing it makes that
an enforced invariant: Energy can never become a float, a negative, or unbounded. The heap is kept
because the comparison is the lesson, and `demo()` asserts the two agree on ordering.

This is layer 1: it operates on duck-typed actors (`.id`, `.attrs`, `.score`, `.energy`, `.pass_no`
and optionally `.improved_reflexes_dice`, `.bt`). It must never import `entities` — see the layer
law in docs/design/data-model.md §15. `_TestActor` below exists only for the self-check.

    .venv/bin/python -m pinkmohawk.scheduler      # runs demo()
"""

from __future__ import annotations

import heapq
import random
from typing import Any, Protocol

from .constants import (
    INITIATIVE_DICE_BASE,
    INITIATIVE_DICE_MAX,
    MAX_ENERGY,
    PASS_DROP,
    PASS_END_THRESHOLD,
)


class ActorLike(Protocol):
    """What the scheduler needs from an actor. Structural, so `entities.Actor` need not inherit."""

    id: int
    attrs: dict[str, int]
    score: int
    energy: int
    pass_no: int


def _tie_key(actor: Any) -> tuple[int, int]:
    """Within one Energy bucket: higher Reaction first, then lower actor id (DECISIONS §5)."""
    return (-int(actor.attrs["reaction"]), int(actor.id))


class BucketQueue:
    """Dial-style bucket queue over integer Energy. Ties resolve inside the bucket."""

    __slots__ = ("max_energy", "buckets", "top", "_count")

    def __init__(self, max_energy: int = MAX_ENERGY) -> None:
        self.max_energy = max_energy
        self.buckets: list[list[Any]] = [[] for _ in range(max_energy + 1)]
        self.top = -1
        self._count = 0

    def insert(self, actor: Any, energy: int) -> None:
        e = max(0, min(int(energy), self.max_energy))  # clamp: never index out of range
        self.buckets[e].append(actor)
        self._count += 1
        if e > self.top:
            self.top = e

    def pop_max(self) -> Any | None:
        while self.top >= 0:
            bucket = self.buckets[self.top]
            if bucket:
                best = min(range(len(bucket)), key=lambda i: _tie_key(bucket[i]))
                self._count -= 1
                return bucket.pop(best)
            self.top -= 1  # cursor only ever moves down during pops
        return None

    def __len__(self) -> int:
        return self._count

    def __bool__(self) -> bool:
        return self._count > 0


class HeapQueue:
    """The same schedule as a binary heap, for the comparison in docs/design/data-model.md §5.

    Key is a max-heap on Energy expressed as a min-heap: (-energy, -reaction, actor_id), which
    encodes the same tie-break as the bucket scan.
    """

    __slots__ = ("_heap", "_tie")

    def __init__(self, max_energy: int = MAX_ENERGY) -> None:
        self._heap: list[tuple[int, int, int, int, Any]] = []
        self._tie = 0

    def insert(self, actor: Any, energy: int) -> None:
        e = max(0, min(int(energy), MAX_ENERGY))
        self._tie += 1
        heapq.heappush(
            self._heap, (-e, -int(actor.attrs["reaction"]), int(actor.id), self._tie, actor)
        )

    def pop_max(self) -> Any | None:
        return heapq.heappop(self._heap)[-1] if self._heap else None

    def __len__(self) -> int:
        return len(self._heap)

    def __bool__(self) -> bool:
        return bool(self._heap)


def initiative_dice(actor: Any) -> int:
    """1d6, plus 1d6 per Improved Reflexes rating, capped at +2d6 in v1 (DECISIONS §5)."""
    bonus = min(int(getattr(actor, "improved_reflexes_dice", 0) or 0), INITIATIVE_DICE_MAX)
    return INITIATIVE_DICE_BASE + bonus


def begin_round(actors: list[Any], rng: random.Random, queue: Any = None) -> Any:
    """Roll Initiative for every actor and seed the queue. Order is RNG-dependent, so seed it."""
    q = queue if queue is not None else BucketQueue()
    for a in actors:
        dice = initiative_dice(a)
        roll = sum(rng.randint(1, 6) for _ in range(dice))
        a.score = int(a.attrs["reaction"]) + int(a.attrs["intuition"]) + roll
        a.energy = a.score
        a.pass_no = 0
        q.insert(a, a.energy)
    return q


def next_actor(queue: Any) -> Any | None:
    """One pop = one action, never a whole turn, which is what keeps play interruptible."""
    return queue.pop_max()


def tick_cooldowns(actor: Any) -> None:
    """Ticked once per Pass, at the Pass boundary — not per Energy charge.

    A Behavior Tree's cooldowns are measured in Passes and must survive `reset_tree` or an abort
    (DECISIONS §8); this is the only thing that advances them.
    """
    bt = getattr(actor, "bt", None)
    if bt is None:
        return
    hook = getattr(bt, "tick_cooldowns", None)
    if callable(hook):
        hook()
        return
    counters = getattr(bt, "cooldowns", None)
    if isinstance(counters, dict):
        for name in list(counters):
            counters[name] -= 1
            if counters[name] <= 0:
                del counters[name]


def end_pass(queue: Any, actor: Any) -> None:
    """The Pass boundary. Advances the Pass and spends **no** Energy.

    Reached two ways: Energy ran out mid-Pass, or a Behavior Tree root returned FAILURE. The second
    is why this must never charge: billing a no-op would re-insert the actor into the same Pass and
    an actor with nothing to do would burn Energy in a loop.
    """
    actor.score -= PASS_DROP
    actor.pass_no += 1
    tick_cooldowns(actor)
    if actor.score >= PASS_END_THRESHOLD:
        actor.energy = actor.score
        queue.insert(actor, actor.energy)


def end_turn(queue: Any, actor: Any, action_cost: int) -> None:
    """Charge for one action, then either continue the Pass or end it."""
    actor.energy -= action_cost
    if actor.energy >= PASS_END_THRESHOLD:
        queue.insert(actor, actor.energy)
    else:
        end_pass(queue, actor)


def run_round(
    queue: Any,
    actors: list[Any],
    rng: random.Random,
    cost_of: Any = lambda a: 10,
    limit: int = 10_000,
) -> list[tuple[int, int]]:
    """Drive a whole Round for the self-check: returns (actor id, pass_no) per action taken."""
    begin_round(actors, rng, queue)
    trace: list[tuple[int, int]] = []
    steps = 0
    while (a := next_actor(queue)) is not None:
        steps += 1
        if steps > limit:
            raise RuntimeError("scheduler livelock: an actor is being re-inserted without progress")
        trace.append((int(a.id), int(a.pass_no)))
        end_turn(queue, a, cost_of(a))
    return trace


# ======================================================================================
# Acceptance test
# ======================================================================================
def demo() -> None:
    class _TestActor:
        def __init__(
            self,
            aid: int,
            reaction: int,
            intuition: int,
            reflexes: int = 0,
            cooldowns: dict[str, int] | None = None,
        ) -> None:
            self.id = aid
            self.attrs = {"reaction": reaction, "intuition": intuition}
            self.improved_reflexes_dice = reflexes
            self.score = 0
            self.energy = 0
            self.pass_no = 0
            if cooldowns is not None:
                self.bt = type("BT", (), {"cooldowns": cooldowns})()

    # ---- 1. equal Energy: higher Reaction wins, then lower id ---------------------------
    q = BucketQueue()
    a, b = _TestActor(7, 4, 4), _TestActor(3, 4, 4)
    a.energy = b.energy = 8
    q.insert(a, 8)
    q.insert(b, 8)
    assert q.pop_max() is b, "lower id must win a Reaction tie"
    assert q.pop_max() is a
    assert q.pop_max() is None and not q

    weaker = _TestActor(1, 2, 2)
    stronger = _TestActor(2, 6, 2)
    q.insert(weaker, 4)
    q.insert(stronger, 8)
    assert q.pop_max() is stronger, "higher Energy goes first regardless of Reaction"

    # ---- 2. Reaction breaks a tie before id does ---------------------------------------
    q2 = BucketQueue()
    slow, fast = _TestActor(1, 2, 6), _TestActor(9, 6, 2)  # both Energy 8
    q2.insert(slow, 8)
    q2.insert(fast, 8)
    assert q2.pop_max() is fast, "higher Reaction wins even with a higher id"

    # ---- 3. clamping, and no crash on out-of-range Energy -------------------------------
    q3 = BucketQueue()
    huge = _TestActor(9, 6, 6)
    q3.insert(huge, 999)
    assert q3.pop_max() is huge
    q4 = BucketQueue()
    neg = _TestActor(5, 3, 3)
    q4.insert(neg, -5)
    assert q4.pop_max() is neg, "negative Energy clamps to 0 rather than raising IndexError"

    # ---- 4. the heap agrees with the buckets on ordering --------------------------------
    rng = random.Random(4242)
    for _ in range(50):
        cast = [_TestActor(i, rng.randint(1, 7), rng.randint(1, 7)) for i in range(12)]
        energies = [rng.randint(0, 30) for _ in cast]
        bq, hq = BucketQueue(), HeapQueue()
        for actor, e in zip(cast, energies, strict=True):
            bq.insert(actor, e)
            hq.insert(actor, e)
        popped_b = [bq.pop_max() for _ in range(len(cast))]
        popped_h = [hq.pop_max() for _ in range(len(cast))]
        order_b = [a.id for a in popped_b if a is not None]
        order_h = [a.id for a in popped_h if a is not None]
        assert order_b == order_h, f"bucket and heap disagree: {order_b} vs {order_h}"

    # ---- 5. Pass arithmetic: Score 18 -> Passes at 18 and 8, then done -------------------
    solo = _TestActor(1, 10, 8)  # Energy 18 before dice
    solo.score = solo.energy = 18
    q5 = BucketQueue()
    q5.insert(solo, solo.energy)
    trace = []
    while (act := next_actor(q5)) is not None:
        trace.append((act.pass_no, act.energy))
        end_turn(q5, act, 10)  # a 10-Energy attack each time
    assert trace == [(0, 18), (0, 8), (1, 8)], f"unexpected Pass trace: {trace}"
    assert solo.score == -2 and solo.pass_no == 2, (solo.score, solo.pass_no)

    # ---- 6. FAILURE path: end_pass charges no Energy (the ai.md test-19 property) --------
    idle = _TestActor(2, 8, 4)
    idle.score = idle.energy = 12
    q6 = BucketQueue()
    end_pass(q6, idle)  # a Behavior Tree root returned FAILURE
    assert (idle.score, idle.energy, idle.pass_no) == (2, 2, 1), (
        f"end_pass must advance the Pass without charging: {(idle.score, idle.energy, idle.pass_no)}"
    )
    assert len(q6) == 1, "the actor must be re-inserted at its next Pass"

    # ---- 7. a whole Round where every tree fails still terminates ------------------------
    idle2 = _TestActor(3, 5, 5)
    idle2.score = idle2.energy = 25
    q7 = BucketQueue()
    q7.insert(idle2, idle2.energy)
    guard = 0
    while (act := next_actor(q7)) is not None:
        guard += 1
        assert guard < 20, "an all-FAILURE round must terminate"
        end_pass(q7, act)
    assert idle2.score < PASS_END_THRESHOLD and idle2.pass_no == 3

    # ---- 8. cooldowns tick once per Pass and are not charged per action -----------------
    cd = _TestActor(4, 6, 6, cooldowns={"call_backup": 3, "relay_alarm": 1})
    cd.score = cd.energy = 12
    q8 = BucketQueue()
    end_pass(q8, cd)
    assert cd.bt.cooldowns == {"call_backup": 2}, f"cooldowns wrong: {cd.bt.cooldowns}"

    # ---- 9. Improved Reflexes buys dice, capped at +2 -----------------------------------
    plain, reflexed, overkill = (
        _TestActor(1, 4, 4),
        _TestActor(2, 4, 4, reflexes=2),
        _TestActor(3, 4, 4, reflexes=9),
    )
    assert initiative_dice(plain) == 1 and initiative_dice(reflexed) == 3
    assert initiative_dice(overkill) == 1 + INITIATIVE_DICE_MAX, "the bonus dice must be capped"
    r = random.Random(1)
    begin_round([plain], r)
    assert plain.score == plain.energy, "Energy is initialised from the Initiative Score"
    assert plain.pass_no == 0, "a fresh Round starts in Pass 0"
    assert 8 + 1 <= plain.score <= 8 + 6, plain.score  # Reaction 4 + Intuition 4 + 1d6

    # ---- 10. begin_round resets Pass state and is RNG-deterministic ---------------------
    cast = [_TestActor(i, 5, 4, reflexes=1) for i in range(4)]
    for a in cast:
        a.pass_no = 7  # stale state must be cleared
    first = run_round(BucketQueue(), cast, random.Random(99))
    second = run_round(BucketQueue(), cast, random.Random(99))
    assert first == second, "the same seed must produce the same Round"
    assert all(pn == 0 for _, pn in first[:4]), "begin_round must reset pass_no"
    third = run_round(BucketQueue(), cast, random.Random(100))
    assert third != first or len(third) != len(first), "a different seed should differ somewhere"

    print(
        f"OK  scheduler: bucket/heap agree on {50} random casts, Pass trace {trace}, "
        f"FAILURE path charges nothing, a {len(first)}-action Round is reproducible"
    )


if __name__ == "__main__":
    demo()

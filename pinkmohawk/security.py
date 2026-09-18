"""The Security Clock: the pressure that replaces permadeath.

ADR-0005: nobody dies permanently in v1, so **the Clock is the tension**. Loud actions and failed
tests tick it; when it fills, security converges, the crew is forced to extract, the payout goes to
zero, and Heat and Fixer reputation take the loss. DECISIONS §9 owns the numbers.

This module also holds the three consequences of ending a Run — payout, Heat, reputation — because
they are the same decision seen from three sides, and splitting them across modules is how they drift
apart.

Layer 2, importing `constants` only: the Clock knows about segments and events, not about actors.
When an action is loud is the *action's* business (`ai.py`, `rules.py`); this module only records it.

    .venv/bin/python -m pinkmohawk.security      # runs demo()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .constants import (
    ALERT_THRESHOLD,
    BASE_PAYOUT,
    CLOCK_SEGMENTS,
    CLOCK_TICKS,
    CONVERGE_THRESHOLD,
    HEAT_DECAY_PER_SUCCESS,
    HEAT_FORCED_EXTRACTION,
    HEAT_MAX,
    HEAT_VALVE_DECAY,
    HEAT_VALVE_THRESHOLD,
    LOCKDOWN_THRESHOLD,
    PAYOUT_PER_NET_NEGOTIATION_HIT,
    REP_FORCED_EXTRACTION,
    REP_VOLUNTARY_EXTRACTION,
)
from .errors import ValidationError


class ClockState(Enum):
    """The three thresholds of §9, plus the state before any of them."""

    CALM = "calm"
    ALERT = "alert"  # 4 segments: patrols converge, alert_level 1
    LOCKDOWN = "lockdown"  # 7 segments: doors lock, guards +2 armour, alert_level 2
    CONVERGED = "converged"  # 10 segments: forced extraction


@dataclass(slots=True)
class Tick:
    """One logged event, so the UI can say *why* the Clock moved and the player can learn from it."""

    event: str
    delta: int
    total: int


@dataclass(slots=True)
class Clock:
    """Ten segments, a tick table, and three thresholds (§9)."""

    segments: int = 0
    log: list[Tick] = field(default_factory=list)
    _converged: bool = False

    def tick(self, event: str, times: int = 1) -> int:
        """Record a loud (or silent) event and return the segments it added.

        An unknown event is refused rather than silently ignored: a typo in an event name would
        otherwise make an action free, which is the kind of bug that only shows up as "the Clock
        never fills".
        """
        if event not in CLOCK_TICKS:
            raise ValidationError([f"unknown clock event {event!r}; known: {sorted(CLOCK_TICKS)}"])
        if times < 1:
            raise ValidationError([f"times must be at least 1, got {times}"])
        delta = CLOCK_TICKS[event] * times
        self.segments = min(CLOCK_SEGMENTS, self.segments + delta)
        self._converged = self._converged or self.segments >= CONVERGE_THRESHOLD
        self.log.append(Tick(event, delta, self.segments))
        return delta

    # -- reading the state ----------------------------------------------------------------
    @property
    def state(self) -> ClockState:
        if self._converged:
            return ClockState.CONVERGED
        if self.segments >= LOCKDOWN_THRESHOLD:
            return ClockState.LOCKDOWN
        if self.segments >= ALERT_THRESHOLD:
            return ClockState.ALERT
        return ClockState.CALM

    @property
    def alert_level(self) -> int:
        """The Blackboard value every actor's floor is raised to (§8): 0 Calm, 1 Alert, 2 Lockdown."""
        return {
            ClockState.CALM: 0,
            ClockState.ALERT: 1,
            ClockState.LOCKDOWN: 2,
            ClockState.CONVERGED: 2,
        }[self.state]

    @property
    def converged(self) -> bool:
        return self._converged

    @property
    def remaining(self) -> int:
        return CLOCK_SEGMENTS - self.segments

    def reset(self) -> None:
        """A Run's Clock does not carry into the next Run (§9: per-Run state)."""
        self.segments = 0
        self.log.clear()
        self._converged = False


# ----------------------------------------------------------------------------------------------
# Ending a Run: payout, Heat, reputation
# ----------------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Extraction:
    """What extracting paid and cost, all three consequences together."""

    payout: int
    heat_delta: int
    reputation_delta: int
    forced: bool


def payout(
    net_negotiation_hits: int = 0,
    *,
    objectives_completed: int = 1,
    objectives_total: int = 1,
    forced: bool = False,
) -> int:
    """§9: `12,000 ¥ ± 100 × net Negotiation Hits`, pro-rated to the objectives completed.

    Forced extraction pays **zero**. The pro-rating is this module's reading of "voluntary extraction
    pays for objectives completed" — the base figure is the contract's, and `world.md` §4.1's
    per-Job multipliers apply on top. Integer nuyen, rounded down.
    """
    if forced:
        return 0
    if objectives_total < 1 or not 0 <= objectives_completed <= objectives_total:
        raise ValidationError(
            [f"objectives {objectives_completed}/{objectives_total} is impossible"]
        )
    base = max(0, BASE_PAYOUT + PAYOUT_PER_NET_NEGOTIATION_HIT * net_negotiation_hits)
    return base * objectives_completed // objectives_total


def heat_after(heat: int, *, success: bool, forced: bool = False) -> int:
    """§9's Heat economy, in one place: a forced extraction hurts, a successful Job cools things.

    The valve above `HEAT_VALVE_THRESHOLD` decays twice as fast, because otherwise a crew on a losing
    streak has no way back down and the campaign becomes unwinnable rather than tense (ADR-0012 asks
    for exactly this floor). Clamped to `HEAT_MAX`.
    """
    if forced:
        heat += HEAT_FORCED_EXTRACTION
    if success:
        heat -= HEAT_VALVE_DECAY if heat > HEAT_VALVE_THRESHOLD else HEAT_DECAY_PER_SUCCESS
    return max(0, min(HEAT_MAX, heat))


def reputation_after(*, forced: bool) -> int:
    """§9: +1 for a voluntary extraction, −1 for a forced one. The Favour is the only sink."""
    return REP_FORCED_EXTRACTION if forced else REP_VOLUNTARY_EXTRACTION


def end_run(
    clock: Clock,
    *,
    net_negotiation_hits: int = 0,
    objectives_completed: int = 1,
    objectives_total: int = 1,
    heat: int = 0,
    voluntary: bool = False,
) -> Extraction:
    """Close out a Run and report all three consequences.

    `voluntary` is whether the crew chose to leave. A converged Clock overrides it: when security has
    already converged there is no such thing as a voluntary extraction.
    """
    forced = clock.converged or not voluntary
    success = voluntary and not forced
    return Extraction(
        payout=payout(
            net_negotiation_hits,
            objectives_completed=objectives_completed,
            objectives_total=objectives_total,
            forced=forced,
        ),
        heat_delta=heat_after(heat, success=success, forced=forced) - heat,
        reputation_delta=reputation_after(forced=forced),
        forced=forced,
    )


# ==============================================================================================
# Acceptance test
# ==============================================================================================
def demo() -> None:
    # ---- 1. the tick table is the contract's, and unknown events are refused ------------
    assert CLOCK_TICKS["gunfire"] == 2 and CLOCK_TICKS["body_found"] == 3
    assert CLOCK_TICKS["silent_takedown"] == 0 and CLOCK_TICKS["successful_hack"] == 0
    quiet = Clock()
    assert quiet.tick("silent_takedown") == 0 and quiet.segments == 0
    assert quiet.tick("successful_hack") == 0, "a quiet Run must be able to stay at zero"
    try:
        quiet.tick("sneeze")
        raise AssertionError("an unknown event must be refused, not ignored")
    except ValidationError:
        pass

    # ---- 2. thresholds: Calm -> Alert 4 -> Lockdown 7 -> Converged 10 -------------------
    clock = Clock()
    assert clock.state is ClockState.CALM and clock.alert_level == 0
    clock.tick("gunfire", 2)  # 4
    assert clock.segments == 4 and clock.state is ClockState.ALERT and clock.alert_level == 1
    clock.tick("body_found")  # 7
    assert clock.state is ClockState.LOCKDOWN and clock.alert_level == 2
    assert not clock.converged and clock.remaining == 3
    clock.tick("guard_killed")  # 9
    assert clock.state is ClockState.LOCKDOWN and clock.remaining == 1
    clock.tick("failed_hack")  # 10
    assert clock.segments == 10 and clock.converged
    assert clock.state is ClockState.CONVERGED and clock.alert_level == 2

    # ---- 3. it clamps, and the log explains itself ---------------------------------------
    clock.tick("gunfire", 5)  # would be 20
    assert clock.segments == CLOCK_SEGMENTS, "segments clamp at the maximum"
    assert clock.remaining == 0
    assert [t.event for t in clock.log][-1] == "gunfire"
    assert clock.log[-1].delta == 10 and clock.log[-1].total == 10
    assert sum(t.delta for t in clock.log) > CLOCK_SEGMENTS, (
        "the log keeps what was lost to clamping"
    )
    clock.reset()
    assert clock.segments == 0 and not clock.converged and clock.log == [], "a Run resets its Clock"

    # ---- 4. payout: base, negotiation, pro-rating, and zero when forced ------------------
    assert payout() == BASE_PAYOUT
    assert payout(3) == BASE_PAYOUT + 300, "100 nuyen per net Negotiation hit"
    assert payout(objectives_completed=1, objectives_total=3) == BASE_PAYOUT // 3, "rounds down"
    assert payout(objectives_completed=3, objectives_total=3) == BASE_PAYOUT
    assert payout(5, forced=True) == 0, "a forced extraction pays nothing"
    assert payout(0, objectives_completed=0, objectives_total=2) == 0
    try:
        payout(objectives_completed=4, objectives_total=3)
        raise AssertionError("more objectives completed than exist must be refused")
    except ValidationError:
        pass

    # ---- 5. Heat: the loss, the cooling, the valve, the ceiling --------------------------
    assert heat_after(0, success=True) == 0, "Heat cannot go below zero"
    assert heat_after(5, success=True) == 4, "−1 per successful Job"
    assert heat_after(6, success=False, forced=True) == 8, "+2 on a forced extraction"
    assert heat_after(9, success=True) == 7, "above the valve it cools by 2"
    assert heat_after(HEAT_MAX, success=False, forced=True) == HEAT_MAX, "clamped at the ceiling"
    assert heat_after(0, success=False, forced=False) == 0, "an abort with no force costs no Heat"

    # ---- 6. reputation, and the whole extraction in one call -----------------------------
    assert reputation_after(forced=False) == 1 and reputation_after(forced=True) == -1
    clean = Clock()
    clean.tick("silent_takedown")
    good = end_run(
        clean,
        net_negotiation_hits=2,
        objectives_completed=2,
        objectives_total=2,
        heat=5,
        voluntary=True,
    )
    assert not good.forced and good.payout == BASE_PAYOUT + 200
    assert good.heat_delta == -1 and good.reputation_delta == 1

    blown = Clock()
    blown.tick("gunfire", 5)  # converged
    bad = end_run(
        blown,
        net_negotiation_hits=9,
        objectives_completed=1,
        objectives_total=1,
        heat=5,
        voluntary=True,
    )
    assert bad.forced, "a converged Clock overrides a voluntary extraction"
    assert bad.payout == 0 and bad.heat_delta == 2 - 0 and bad.reputation_delta == -1

    print(
        f"OK  security: {len(CLOCK_TICKS)} tick events, thresholds "
        f"{ALERT_THRESHOLD}/{LOCKDOWN_THRESHOLD}/{CONVERGE_THRESHOLD} -> alert_level 1/2, forced "
        f"extraction pays 0, Heat valve above {HEAT_VALVE_THRESHOLD}, ceiling {HEAT_MAX}"
    )


if __name__ == "__main__":
    demo()

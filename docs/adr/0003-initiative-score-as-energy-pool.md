# Initiative Score doubles as the Energy pool

There is no action-point system and no separate initiative-pass rule. An actor's Initiative Score (Reaction + Intuition + dice) *is* the Energy it spends that turn; actions have fixed costs (a step is 1, an attack is 10); when Energy can no longer cover the cheapest useful action the Pass ends, the Score drops by ten, and another Pass begins. Multiple passes per round therefore fall out of the arithmetic rather than being a special case, and buying initiative dice literally buys extra passes.

**Considered options**: a global time-cost scheduler with one priority queue for all actors (deferred, not rejected — it is the natural successor if Energy proves too coarse); HBS-style fixed action points (rejected: initiative investment collapses into a single AP threshold); one action per turn (rejected: speed stops mattering).

**Consequences**: tuning a single number (Initiative Score) simultaneously controls turn frequency and how much a fast actor does per turn, so the two cannot be balanced independently. This is the most likely source of future balance pain.

Extra passes are thresholded, which the first draft of this ADR glossed over. With a Pass ending at 1 Energy, a Score of 11 yields a second Pass worth exactly one Step; a *substantial* second Pass needs 15 or more and a third needs 25. At the starting range of 8–16 a Runner therefore gets one full Pass and sometimes a short one, so "initiative buys passes" only bites once Improved Reflexes pushes the Score past 15. Re-check this ADR the moment anyone tunes starting Reaction and Intuition upward.

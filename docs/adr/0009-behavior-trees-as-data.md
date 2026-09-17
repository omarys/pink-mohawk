# Every non-player brain is a data-defined Behavior Tree plus a utility scorer

Enemies, Spirits, and Hub NPCs are driven by Behavior Trees authored as JSON — selector, sequence, condition, action, plus decorators — interpreted by a hand-written ticker. Choosing *which* target or action to commit to is a separate Utility Score over candidates, so trees express intent ("close to melee range", "investigate the noise") and utility expresses choice. Trees share one library and differ by per-archetype parameters.

**Considered options**: utility AI alone (rejected: expressing ordered behaviour becomes awkward and it is hard to explain afterwards why an actor did something); state machines with script hooks (rejected: transition tangle past a handful of states, and AI becomes code instead of content); GOAP (deferred: the deepest learning but plan-search cost per actor per turn and opaque debugging are not worth it before the game loop works).

**Consequences**: AI is content and can be tuned without touching Python, which also means tree authoring needs a schema validator and a way to trace a tick, or a malformed tree fails silently at runtime. The player controls all four Runners directly, so no ally AI is required in v1 — Spirits are the only friendly actors with a brain.

# AI: Behavior Trees, Blackboard, and Utility Score

The spec for every non-player brain: the JSON tree format, the ticker, the Blackboard, the Utility Score, the five enemy archetypes' trees plus the Spirit, and how to test all of it.
Vocabulary is `CONTEXT.md`; numbers are `docs/design/DECISIONS.md` (cited as §n); rationale is `docs/adr/0009-behavior-trees-as-data.md`.

This document owns: tree schema, tick semantics, ticker algorithm, Blackboard keys, Utility Score, action and condition catalogues, the archetype trees, the debug trace, the test plan.
It does **not** own: FOV/LOS (map + FOV modules), A\*/flow-map pathing (pathfinding module), the Energy scheduler (§5, §13), the cover predicate's geometry (`DECISIONS.md` §4), or the Security Clock (§9).

---

## 1. Runtime shape in one paragraph

The scheduler pops an actor and grants it a decision step. Before the step, the brain refreshes its senses and re-scores targets with the Utility Score, writing `target` and friends to the Blackboard. Then the tree is ticked **from the root** by an explicit-stack ticker. One leaf resolves per decision step: an Action spends Energy and returns SUCCESS, FAILURE, or RUNNING. The Pass continues while the actor has Energy (§5) and the tree keeps returning something actionable. When Energy cannot cover the cheapest useful action, the Pass ends, Score −= 10, and the tree is reset for the next Pass.

```
scheduler (§5)
  └─ run_pass(actor)                       # while Energy >= 1
       ├─ refresh(actor)                   # FOV, morale, Utility Score -> target, alert floor
       └─ tick(actor)                      # explicit stack, one atomic Action per step
            └─ condition / action leaves   # read and write the Blackboard
```

---

## 2. Behavior Tree document schema

A tree is one JSON document. The eight node types of §8 map to the `type` values below — one spelling per concept, lowercase:

| §8 node type | JSON `type` | Kind |
|---|---|---|
| Selector | `selector` | composite |
| Sequence | `sequence` | composite |
| Condition | `condition` | leaf |
| Action | `action` | leaf |
| Inverter | `inverter` | decorator |
| Succeeder | `succeeder` | decorator |
| Cooldown | `cooldown` | decorator |
| Repeat | `repeat` | decorator |

### 2.1 Document object

```json
{
  "id": "corp_guard",
  "archetype": "Corp Guard",
  "params": {},
  "root": {
    "type": "selector",
    "name": "root",
    "children": [
      { "type": "action", "action": "patrol" }
    ]
  }
}
```

| key | type | required | meaning |
|---|---|---|---|
| `id` | string, unique | yes | tree identity; used in traces and in the loader's duplicate check |
| `archetype` | string | no | must equal one of the five §8 archetypes, or `"spirit"`; binds the parameter block of §6.2 |
| `params` | object | no | per-archetype parameter overrides (utility weights, `flee_threshold`); keys must exist in that archetype's block |
| `root` | node | yes | the single root node |

### 2.2 Node keys — exact, per type

Every node is an object with `type`. `name` is optional on every node type; it is a string used only in traces and error messages. **Any key not listed for that type is a load error.**

| `type` | required keys | optional keys | children declaration |
|---|---|---|---|
| `selector` | `type`, `children` | `name`, `reactive` | `children`: array of node objects, length ≥ 1, ticked left→right |
| `sequence` | `type`, `children` | `name` | `children`: array of node objects, length ≥ 1, ticked left→right |
| `condition` | `type`, `check` | `name`, `args` | none (leaf) |
| `action` | `type`, `action` | `name`, `args` | none (leaf) |
| `inverter` | `type`, `child` | `name` | `child`: exactly one node object |
| `succeeder` | `type`, `child` | `name` | `child`: exactly one node object |
| `cooldown` | `type`, `child`, `passes` | `name` | `child`: exactly one node object; `passes`: integer ≥ 1 |
| `repeat` | `type`, `child`, `times` | `name` | `child`: exactly one node object; `times`: integer ≥ 0 (0 = unbounded: one repetition per decision step, §4.5) |

- `check` must be a key of the Condition catalogue (§8). `action` must be a key of the Action catalogue (§7).
- `args` is an object whose keys are declared per condition/action; undeclared keys or wrong types are load errors.
- `reactive` on a selector defaults to `true`. See §3.3 for the difference.
- The loader assigns every node a dotted path id — `root`, `root.0`, `root.0.2` — used as the key for runtime state (§4.2) and in traces. Authors never write ids.

### 2.3 Malformed trees

Each of these is rejected at load with the exact code shown. The tree is never partially loaded: validation returns **all** errors, then the loader refuses the file. Silence at runtime is impossible because nothing malformed reaches runtime.

```text
1. Unknown type
{"type":"selector","children":[{"type":"sequencer","children":[{"type":"action","action":"patrol"}]}]}
  E_UNKNOWN_NODE_TYPE  root.0  "sequencer" is not one of selector|sequence|condition|action|
                                 inverter|succeeder|cooldown|repeat

2. Empty composite
{"type":"selector","children":[]}
  E_EMPTY_CHILDREN     root  selector requires >= 1 child

3. Wrong decorator arity
{"type":"inverter","child":{"type":"action","action":"patrol"},"children":[...]}
  E_DECORATOR_ARITY    root  inverter takes exactly "child"; "children" is not a valid key
  E_UNKNOWN_KEY        root  "children"

4. Missing cooldown parameter
{"type":"cooldown","child":{"type":"action","action":"call_backup"}}
  E_MISSING_KEY        root  cooldown requires "passes"

5. Unknown leaf name
{"type":"action","action":"backflip"}
  E_UNKNOWN_ACTION     root  "backflip" is not in the Action catalogue

6. Undeclared argument
{"type":"condition","check":"alert_below","args":{"lvl":2}}
  E_BAD_ARGS           root  alert_below takes {"level": int}; got {"lvl":2}

7. Missing root
{"id":"corp_guard","archetype":"Corp Guard"}
  E_NO_ROOT            document requires "root"
```

A **catalogue** error (not a tree error): any Action whose declared Energy cost is 0 is `E_ZERO_COST`. Every Action costs ≥ 1 Energy, otherwise the Pass loop of §3.1 can spin without spending.

---

## 3. Tick semantics

### 3.1 Decision step and Pass

Turn structure is §5: an actor's Energy *is* its Initiative Score, actions have fixed costs, and the Pass ends when Energy cannot cover the cheapest useful action.

- **Decision step** = one pop of the actor by the scheduler while it still has Energy. It resolves **at most one atomic Action**.
- **Movement is one Step per decision step** (§5: Step = 1 Energy per tile). A move leaf returns RUNNING after each Step, so a moving actor is interruptible at tile granularity and RUNNING has an honest meaning rather than being decorative.
- **Pass loop**:

```python
def run_pass(actor):
    reset_tree(actor)                  # resume indices + repeat counters cleared; cooldowns survive
    while actor.energy >= 1:           # §5
        refresh(actor)                 # senses, morale, Utility Score -> target, alert floor
        status, spent = tick(actor)    # §4.3
        if status == FAILURE: break    # nothing applies: no useful action -> Pass ends
        actor.energy -= spent          # the ONLY place Energy is deduced; leaves never spend
        if spent == 0: break           # cannot buy anything useful -> Pass ends
    end_pass(actor)                    # Score -= 10, cooldowns -= 1, §5
```

`FAILURE` at the root is "no branch applies", which is exactly "Energy cannot cover the cheapest **useful** action".

### 3.2 The three statuses

| status | Condition | Action | Composite | What it means to the scheduler |
|---|---|---|---|---|
| SUCCESS | predicate true | the atomic action completed this step | per node rules (§4.3) | the step was spent; continue the Pass |
| FAILURE | predicate false | prerequisites unmet **or** the action could not be done | per node rules | at the root: end the Pass |
| RUNNING | never returned | the action is in progress (a move mid-path, a repeating hold) | per node rules | the step was spent; resume this branch next step |

- A **Condition never returns RUNNING and never writes the Blackboard**. It evaluates one predicate in the current decision step.
- An **Action checks all prerequisites *before* spending Energy**. Unmet prerequisites return FAILURE and cost 0 Energy, so a Sequence falls through cleanly and nothing is half-paid.
- An aborted branch returns nothing: `reset_subtree` discards it (§4.4).

### 3.3 Re-tick, resume, reset, abort — the exact rules

1. **Re-ticked** once per decision step, always **from the root**, with an empty stack. Re-entry from the root is what lets a higher-priority branch preempt; the nodes' `resume` index is what makes a RUNNING branch continue instead of restarting.
2. **Resumed**: a composite that returned RUNNING remembers the child index in `resume`; on the next decision step it enters at that index. A Sequence resumes **past** its already-satisfied conditions. If a segment needs mid-action re-checking, wrap that segment in its own reactive Selector — do not expect a Sequence to re-test its head.
3. **Re-selected (full reset)**: at the start of every Pass, and on Run start. `reset_tree` clears every `resume`, `running`, and `repeat` entry and calls each leaf's `reset()`. Cooldown counters are **not** cleared: they are measured in Passes.
4. **Aborted**: a reactive Selector that is currently RUNNING child *j* preempts to an earlier child *i* < *j* → it calls `reset_subtree(children[j])`. Example: a Corp Guard walking to `noise_pos` while morale crosses its floor → the flee branch takes over and the walk is cleanly discarded.
5. **Never** is a tree ticked between the actor's own decision steps, and never at render cadence. There is no frame loop in this game.

---

## 4. The ticker

### 4.1 Why an explicit stack

`docs/design/DECISIONS.md` §13 fixes the implementation as an **explicit-stack ticker**. Reasons, in order:

1. **Determinism and inspectability.** The stack *is* the trace. Dumping `[(node id, phase, idx)]` after a step answers "why did it do that" (§10) with no instrumentation inside the leaves. A recursive ticker has no such object.
2. **No recursion ceiling.** Trees are content and may be machine-generated or deeply nested. Python's recursion limit is a real failure mode; the stack is heap-allocated and unbounded.
3. **Per-node state is awkward with recursion.** Resume indices, repeat counters, and abort bookkeeping belong in tables keyed by node id. Rebuilding a call stack each tick to carry them is work the loop already does.
4. **Allocation control.** One stack, reused per actor, frames mutated in place. No per-tick frame objects on the GC path.

### 4.2 Runtime state (per actor, never on the Blackboard)

| state | key | meaning |
|---|---|---|
| `resume` | node id | composite child index to enter at |
| `running` | node id | child index currently RUNNING (reactive-abort bookkeeping) |
| `repeat` | node id | completed repetitions |
| `cooldown` | node id | Passes remaining until ready; 0 = ready; **survives reset** |
| `root_status` | — | last status delivered by the root |
| `senses` | — | FOV cell set, LOS cache; refreshed by `refresh()` |
| `stack` | — | list of `Frame`; empty between ticks |

Leaf-private state that is **not** on the Blackboard either: path cache, aim stacks, cover reservation inside the leaf object, cleared by that leaf's `reset()`.

### 4.3 Pseudocode

```python
class Frame:
    node; phase; idx; status        # phase in {"DESCEND", "ASCEND"}

def tick(actor):
    actor.stack = [Frame(actor.root, "DESCEND", enter_index(actor.root), None)]

    while actor.stack:
        f = actor.stack[-1]; n = f.node

        if f.phase == "DESCEND":
            t = n.type
            if t == "condition":
                actor.stack.pop(); deliver(actor, n.evaluate(actor))
            elif t == "action":
                actor.stack.pop(); deliver(actor, n.act(actor))
            elif t == "selector":
                if f.idx >= len(n.children):
                    resume[n.id] = 0; actor.stack.pop(); deliver(actor, FAILURE)
                else:
                    actor.stack.append(child_frame(n, f.idx))
            elif t == "sequence":
                if f.idx >= len(n.children):
                    resume[n.id] = 0; actor.stack.pop(); deliver(actor, SUCCESS)
                else:
                    actor.stack.append(child_frame(n, f.idx))
            elif t in ("inverter", "succeeder"):
                actor.stack.append(child_frame(n, 0))
            elif t == "cooldown":
                if cooldown.get(n.id, 0) > 0: actor.stack.pop(); deliver(actor, FAILURE)
                else:                          actor.stack.append(child_frame(n, 0))
            elif t == "repeat":
                if n.times > 0 and repeat.get(n.id, 0) >= n.times:
                    repeat[n.id] = 0; actor.stack.pop(); deliver(actor, SUCCESS)
                else:
                    actor.stack.append(child_frame(n, 0))
            else:
                raise SchemaError(n.id)          # unreachable: rejected at load

        else:  # ASCEND -- f.status is what the child at f.idx returned
            s = f.status; t = n.type
            if t == "selector":
                if s == FAILURE:
                    f.idx += 1; f.status = None; f.phase = "DESCEND"
                elif s == RUNNING:
                    abort_if_preempted(actor, n, winner=f.idx)   # an earlier child may preempt
                    running[n.id] = f.idx; resume[n.id] = f.idx
                    actor.stack.pop(); deliver(actor, RUNNING)
                else:                                        # SUCCESS
                    abort_if_preempted(actor, n, winner=f.idx)
                    resume[n.id] = 0                         # next tick re-scans from the top
                    actor.stack.pop(); deliver(actor, SUCCESS)
            elif t == "sequence":
                if s == SUCCESS:
                    f.idx += 1; f.status = None; f.phase = "DESCEND"
                elif s == RUNNING:
                    resume[n.id] = f.idx; actor.stack.pop(); deliver(actor, RUNNING)
                else:
                    resume[n.id] = 0; actor.stack.pop(); deliver(actor, FAILURE)
            elif t == "inverter":
                actor.stack.pop()
                deliver(actor, RUNNING if s == RUNNING else
                               (SUCCESS if s == FAILURE else FAILURE))
            elif t == "succeeder":
                actor.stack.pop()
                deliver(actor, RUNNING if s == RUNNING else SUCCESS)
            elif t == "cooldown":
                if s == SUCCESS: cooldown[n.id] = n.passes     # arm on success only
                actor.stack.pop(); deliver(actor, s)
            elif t == "repeat":
                if s == FAILURE:
                    repeat[n.id] = 0; actor.stack.pop(); deliver(actor, FAILURE)
                elif s == RUNNING:
                    actor.stack.pop(); deliver(actor, RUNNING)
                else:                                          # SUCCESS
                    repeat[n.id] = repeat.get(n.id, 0) + 1
                    if n.times == 0:                           # forever: one rep per step
                        resume[n.id] = 0; actor.stack.pop(); deliver(actor, RUNNING)
                    elif repeat[n.id] >= n.times:
                        repeat[n.id] = 0; actor.stack.pop(); deliver(actor, SUCCESS)
                    else:
                        resume[n.id] = 0; f.idx = 0; f.status = None; f.phase = "DESCEND"

    # The ticker does NOT mutate Energy (DECISIONS §8, resolved item 25). It reports the cost the
    # leaf declared through its tick context; the caller deducts it once, in run_pass above. An
    # earlier draft returned `energy0 - actor.energy`, which double-charges once run_pass deducts
    # `spent` as well.
    return actor.root_status, actor.context.cost

def deliver(actor, s):
    if not actor.stack: actor.root_status = s
    else:
        top = actor.stack[-1]; top.status = s; top.phase = "ASCEND"

def child_frame(n, i):
    c = n.children[i] if n.type in ("selector", "sequence") else n.child
    return Frame(c, "DESCEND", enter_index(c), None)

def enter_index(n):                       # resume index used when a node is first pushed
    if n.type == "selector": return 0 if n.reactive else resume.get(n.id, 0)
    if n.type == "sequence": return resume.get(n.id, 0)
    return 0

def abort_if_preempted(actor, sel, winner):
    if not sel.reactive: return
    prev = running.get(sel.id)
    if prev is not None and prev != winner:
        reset_subtree(sel.children[prev], actor)     # the branch we were in is abandoned
    running[sel.id] = None

def reset_subtree(n, actor):
    resume.pop(n.id, None); running.pop(n.id, None); repeat[n.id] = 0
    n.reset()                                        # leaf accumulators only
    for c in children_of(n): reset_subtree(c, actor)
    # cooldown[n.id] is deliberately untouched: cooldowns are measured in Passes
```

### 4.4 Node rules, stated plainly

- **Selector** = fallback/OR. First non-FAILURE child wins. FAILURE advances to the next child. RUNNING remembers the index; SUCCESS and total FAILURE clear it. If `reactive`, it always re-enters at child 0 and aborts any branch it was in when an earlier child takes over; if not `reactive`, it resumes at the remembered index instead (a sustained mission survives new information — used for the Security Drone's rigid patrol).
- **Sequence** = AND. First non-SUCCESS child stops it. FAILURE resets the index; RUNNING remembers it.
- **Inverter** = NOT. SUCCESS↔FAILURE, RUNNING passes through.
- **Succeeder** = force success. A child FAILURE becomes SUCCESS; RUNNING passes through. Used for optional steps.
- **Cooldown** = rate limit measured in the actor's Passes. While `cooldown > 0` it returns FAILURE without ticking the child. It arms only on a child SUCCESS. It is **not** cleared by `reset_tree` or by an abort — otherwise fleeing once would re-arm `call_backup`.
- **Repeat** = run the child `times` times per decision step. `times = 0` (forever) runs one repetition per decision step and returns RUNNING after each child SUCCESS, which bounds the loop. A child FAILURE fails the Repeat and clears the counter.

### 4.5 Worked trace — Corp Guard, three decision steps

Actor `corp_guard#3`, tree §9.1, `morale` healthy, ally `ganger#2` between it and the target.

```
Pass 1 | E20  reset_tree (cooldowns untouched)
 step 1  E20 -> E15  root>flee                    low_morale             = FAILURE
                    root>combat                  has_target             = SUCCESS
                    root>combat>can_see_target   can_see_target         = SUCCESS
                    root>combat>engage>call_backup alert_below(2)        = SUCCESS
                    ...  cooldown(4)                                     = SUCCESS (arms)
                    ...  call_backup                                     = SUCCESS  spent 5E
 step 2  E15 -> E14  root>combat>engage>shoot     in_weapon_range        = SUCCESS
                                                 not_blocked_by_ally    = FAILURE (ganger#2 on the line)
                    root>combat>engage>reload    ammo_empty             = FAILURE
                    root>combat>engage>hold_cover has_cover_available   = SUCCESS
                    ...  at_cover                                        = FAILURE
                    ...  seek_cover                                      = RUNNING  spent 1E
 step 3  E14 -> E13  root>combat>engage>hold_cover>seek_cover resumed (Step 2 of N)  spent 1E
```

The step-2 trace is the whole "why": `in_weapon_range` passed, `not_blocked_by_ally` failed, so the guard did not shoot through its own Ganger and fell through reload to cover. Decision steps 1 and 3 show the cooldown arming and a resumed RUNNING branch. `spent` is energy actually deducted, never a guess.

---

## 5. Blackboard schema

The Blackboard is the per-actor dictionary of §8. It holds **exactly these twelve keys**; leaf-private state (§4.2) is not a Blackboard key. Any other key is a load-time error in the code that writes it — the board is a fixed typed struct, not an open dictionary.

| key | type | writer | readers | lifetime |
|---|---|---|---|---|
| `target` | Runner id or `null` | `refresh()` — the Utility Score (§6), or the `command_target` pin when one is set (§9.6) | `has_target`, `can_see_target`, `in_weapon_range`, `in_melee_range`, `not_blocked_by_ally`, `low_morale`, `flank_target`, `retreat`, `track_by_scent`, `seek_cover`, `attack_target`, `use_power` | **turn** — re-scored every decision step, committed across steps by hysteresis; cleared when no candidate is known |
| `last_known_pos` | cell `(x, y)` or `null` | `refresh()` — the winning candidate's last seen cell | `has_last_known_pos`, `move_to_blackboard`, `seek_cover` fallback, `track_by_scent` | **Run** — survives turns until overwritten; cleared at Run start |
| `home_pos` | cell `(x, y)` | the site embed at spawn (§10) | `at_home`, `move_to_blackboard`, `retreat {dest:"home"}` | **Run** — immutable after spawn |
| `cover_pos` | cell `(x, y)` or `null` | `seek_cover`, `take_cover` | `move_to_blackboard`, `at_cover` | **turn** — cleared by `refresh()` when the cell no longer gives cover against `target` |
| `noise_pos` | cell `(x, y)` or `null` | the site's noise broadcast on any loud event (§9: gunfire, alarm, body found), copied onto every actor in earshot | `noise_heard`, `move_to_blackboard` | **turn** — cleared when the actor reaches it or its Pass ends |
| `alert_level` | int 0 Calm / 1 Alert / 2 Lockdown | `refresh()` — raised to 1 on the first sighting of a Runner; `call_backup` writes 2; the site raises **every actor's floor** to 1 at 4 Security Clock segments and 2 at 7 (§9, DECISIONS §8) | `alert_below`, every tree's top branch | **Run** — monotonic; never falls within a Run |
| `morale` | int (0 or negative; at most `morale_bonus[archetype]`) | `refresh()` | `low_morale` | **turn** — recomputed every decision step |
| `objective` | Mission Graph node id (string) or `"hostile"` for a freed Spirit | the site embed at spawn (§10); rewritten to `"hostile"` by a failed Conjuring of §7 | `objective_is`, and the `objective_value` term of the Utility Score | **Run** |
| `pacified` | bool | a dialogue `set` effect (`dialogue.md` §5.1: a successful bribe or Intimidation) | `pacified` — the guard tree's stand-down check | **Run** — set once by dialogue; never cleared within the Run |
| `command_target` | cell `(x, y)` or actor id, or `null` | a player command to a Spirit or a protectee (DECISIONS §8) | `refresh()` — resolves the pin into `target`; a protectee's `move_to_blackboard` | **Run** — holds until the player issues another command |
| `summoner_id` | actor id (Spirits only) | the conjure at summon (§7, §9.6) | `follow_summoner` | **Run** — the summoner reference for the Spirit's lifetime |
| `rounds_bound` | int (Spirits only) | the conjure at summon, set to 3 (§7, §9.6) | the site's Spirit-lifetime check | **Run** — decremented each Round; the Spirit expires at 0 |

Every key above except `pacified` and `command_target` is owned by the simulation — the brain, `refresh()`, or the site embed. `pacified` is written only by dialogue and `command_target` only by a player command, so those are the two keys an external layer may write (DECISIONS §8).

`morale` is the only derived key:

```
morale = wound_modifier                     # §4: -1 per 3 filled boxes, both tracks together
       + morale_bonus[archetype]            # DECISIONS §8; per-archetype value in §6.2
       - allies_downed_on_my_side
low_morale  <=>  morale <= flee_threshold[archetype]
```

`flee_threshold[Ganger] = -3` is fixed by §8 ("flees at Wound Modifier −3"); with `morale_bonus[Ganger] = 0` and no Downed allies the Ganger flees at exactly Wound Modifier −3. `flee_threshold[Hellhound]` is unreachable (−99): §8, "never flees".

---

## 6. Utility Score

Choosing *which* Runner to commit to is a separate Utility Score over candidates (§8, ADR-0009); trees express intent, the score expresses choice. It runs in `refresh()`, once per decision step.

### 6.1 Formula and facts

```
score(candidate) = w_threat    · (1 / max(1, distance))
                 + w_visible   · visible
                 + w_objective · objective_value
                 - w_ally_risk · allied_fire_risk
```

| term | definition |
|---|---|
| `distance` | **Chebyshev distance** `max(dx, dy)` in tiles from the actor to the candidate's known cell. A straight-line grid metric, not a path length: walls and line of sight never enter it — the `visible` term carries visibility (DECISIONS §13) |
| `visible` | `1.0` if the candidate is in the actor's FOV, else `0.0` |
| `objective_value` | `1.0` if the candidate stands inside the room of the Mission Graph node named by the actor's `objective`; else `0.0` (§10: the node's room has bounds) |
| `allied_fire_risk` | `1.0` if the actor's line of fire to the candidate crosses any allied actor's cell, else `0.0`; for an area ability, `allied cells in the template / cells in the template`, clamped to [0, 1] |

Scores are unitless and are only ever compared **within one actor** on the same decision step. A weight is a preference, not a probability.

Candidate set:

1. Every Runner currently in the actor's FOV.
2. Plus, for an actor with the `tracks_by_scent` trait (Hellhound only, §8), every living Runner, whether visible or not — `visible` is then 0 for the unseen ones and the term does its job.
3. If the set is empty: `target = null`, `last_known_pos` keeps its last value. `has_target` fails, the tree falls through to investigate/pursue branches.
4. If a Spirit (or a protectee) carries a player-issued `command_target` (DECISIONS §14 — Spirit control, resolved), the pin wins outright: `refresh()` resolves it into `target` and the score is not run.

### 6.2 Per-archetype parameters

Weights are per-archetype parameters (§8). The table below is the **proposed** block — see Open questions, item 1. Values are defaults and are meant to be tuned.

| archetype | `w_threat` | `w_visible` | `w_objective` | `w_ally_risk` | `target_hysteresis` | `morale_bonus` | `flee_threshold` |
|---|---|---|---|---|---|---|---|
| Corp Guard | 1.0 | 2.0 | 1.5 | 3.0 | 0.10 | +1 | −4 |
| Security Drone | 1.2 | 3.0 | 1.0 | 2.0 | 0.15 | — | never (machine) |
| Ganger | 1.5 | 1.5 | 0.5 | 2.5 | 0.05 | 0 | −3 |
| Corp Mage | 0.8 | 2.5 | 1.0 | 3.5 | 0.20 | 0 | −4 |
| Hellhound | 2.0 | 2.0 | 1.0 | 0.5 | 0.25 | — | never (§8) |
| Spirit | 2.0 | 2.0 | 1.0 | 1.0 | 0.10 | — | never (it is conjured) |

Rationale, one line each:

- **Corp Guard** — objective-weighted (it holds a post, it does not chase), and the highest ally-risk weight in the game: a guard with a rifle line through its own squad holds fire.
- **Security Drone** — visibility-dominated; it reacts to what it sees and nothing else (rigid, §8). Never flees: a machine has no morale branch at all.
- **Ganger** — threat-dominated and objective-blind (an opportunist, §8), and the lowest hysteresis, so it dithers between two near-equal targets. That dithering *is* "poor discipline"; do not "fix" it with a bigger margin.
- **Corp Mage** — the highest ally-risk weight (it casts area and single-target magic from among its own squad) and the highest hysteresis: once it commits to a counterspell target it finishes the job.
- **Hellhound** — the highest threat weight and near-zero ally-risk (it is a melee animal with no area attacks); the highest hysteresis: single-minded, never switches mid-run.
- **Spirit** — neutral: it fights the pin the Shaman gave it, or the nearest threat otherwise.

### 6.3 Deterministic ties and hysteresis

**Tie-break**, reusing §5's deterministic order, no re-rolls: `score` descending, then the candidate's **Reaction** descending, then **actor id** ascending. Identical inputs produce identical output, so a replayed seed is bit-identical.

**Hysteresis** — the commitment rule. Let `incumbent` be `target` from the previous decision step (skipped if `null`):

```
best = argmax over candidates by (score, Reaction desc, id asc)
switch  <=>  score(best) > score(incumbent) + target_hysteresis
           or incumbent is not a candidate this step (Downed, off-board, pin released)
```

The incumbent is neither dropped nor re-scored by anything else; it only loses on the margin rule. This is the "hysteresis" row of §13 and it is what stops an actor vibrating between two near-equal Runners.

**Worked example.** Corp Guard at (10,10), weights 1.0 / 2.0 / 1.5 / 3.0, hysteresis 0.10.

| candidate | distance | visible | objective_value | allied_fire_risk | score |
|---|---|---|---|---|---|
| Runner A | 4 | 1 | 0 | 0 | `1.0·0.25 + 2.0·1 + 1.5·0 − 3.0·0` = **2.25** |
| Runner B | 2 | 1 | 1 | 1 (Ganger on the line) | `1.0·0.50 + 2.0·1 + 1.5·1 − 3.0·1` = **1.00** |

- Incumbent B, scores 2.25 vs 1.00: `2.25 > 1.00 + 0.10` → switch to A. The guard declines to shoot through its own Ganger even for the closer, objective-critical target.
- Near-tie, scores 2.25 (A) vs 2.30 (B), incumbent A: `2.30 > 2.25 + 0.10` is false → **stay on A**. One decision was made, not one per step.
- A at 2.40 vs incumbent A 2.25 → no switch. B at 2.40 vs incumbent A 2.25: `2.40 > 2.35` → switch.

---

## 7. Action catalogue

Every leaf action a tree can call. `Energy` is per invocation and comes from §5; every action costs ≥ 1, so the Pass loop of §3.1 always makes progress or ends. Prerequisites are checked **before** Energy is spent; an unmet prerequisite returns FAILURE at 0 Energy. Movement actions move exactly one Step per decision step and return RUNNING until their destination is reached.

| action | args | Energy | prerequisites | Blackboard effect | returns |
|---|---|---|---|---|---|
| `patrol` | — | 1 per Step | the actor has a patrol ring in its spawn record | none | RUNNING (a patrol never finishes) |
| `move_to_blackboard` | `key` | 1 per Step (2 per 3 tiles if `sprint:true`) | `key` holds a cell; a path exists; Energy ≥ cost of one Step | none | RUNNING until arrived, then SUCCESS |
| `move_to_adjacent` | `key`, `sprint` | 1 per Step | as above | none | RUNNING until adjacent, then SUCCESS |
| `flank_target` | — | 1 per Step | `target` known; a walkable cell adjacent to `target` exists | none | RUNNING |
| `track_by_scent` | — | 1 per Step | `has_last_known_pos` | refreshes `last_known_pos` from the tracked Runner's current cell before stepping (walls do not break the trail) | RUNNING until adjacent, then SUCCESS |
| `retreat` | `dest` ∈ `home`/`exit`/`fallback` | 1 per Step | `home` needs `home_pos`; `exit` needs a Mission Graph exit node; `fallback` needs `target` | none | RUNNING |
| `follow_summoner` | — | 1 per Step | the summoner is alive and known | none | RUNNING until adjacent, then SUCCESS |
| `seek_cover` | — | 1 per Step | `target` known; a cell exists that breaks LOS from `target` and is reachable | writes `cover_pos` when it selects one | RUNNING until on `cover_pos`, then SUCCESS |
| `take_cover` | — | 5 | the actor's cell gives cover against someone | writes `cover_pos` = the actor's cell | SUCCESS |
| `attack_target` | `weapon` | 10 | `target` known; in the weapon's range; LOS; `not_blocked_by_ally`; magazine not empty | none (damage is applied by the combat resolver; gunfire publishes a noise event) | SUCCESS |
| `use_power` | `power`, `force` | 10 | Caster (§7 class) and the power's own prereqs; Force ∈ 1–8 (DECISIONS §6); Drain payable (§6) | none for single-target; area powers re-read `target` after resolving | SUCCESS |
| `aim` | — | 5 | aim stacks < +2 (§5) | none | SUCCESS |
| `reload` | — | 5 | equipped weapon; magazine not full | none | SUCCESS |
| `call_backup` | — | 5 (Use item 5) | `alert_level ≥ 1`; the actor carries a commlink **and its tree includes a `call_backup` leaf** (Corp Guard, Security Drone; the Ganger carries no commlink, the Hellhound nothing, and the Corp Mage carries one but never calls backup — §9.4); `alert_level < 2` | writes `alert_level = 2`; trips the site alarm = Security Clock +2 (§9, "Alarm tripped") | SUCCESS |
| `use_item` | `item` | 5 | the actor carries `item` | per item | SUCCESS |
| `stand_up` | — | 5 | the actor is prone | none | SUCCESS |

Action names use one spelling per concept: `"assault_rifle"`, `"smg"`, `"heavy_pistol"`, `"katana"` are the §4 weapon names lowercased and underscored, and `"bite"` is the Hellhound's natural weapon (DECISIONS §4). The four Spirit attacks are one name per type, and `classes.md` §7.3 is the naming authority: it names each ability and gives the type's DV/AP and range, so the catalogue takes those names rather than inventing them — `"beast_strike"` `(Force+3)P` AP 1 melee, `"air_bolt"` `(Force+1)P` AP 0 range 8, `"earth_slam"` `(Force+2)P` AP 2 melee, `"water_burst"` `(Force)S` AP 0 range 6 radius 2. A Spirit is not a Caster, so every Spirit attack is an `attack_target`, never a `use_power` (§7). Non-player actors never hack (there is no enemy Decker archetype, §8) and never summon.

---

## 8. Condition catalogue

Conditions are pure, instantaneous, and never write the Blackboard. Each is a named predicate with declared args — the same "no language, just a graph of named nodes" stance as the Dialogue Graph of ADR-0010.

| condition | args | true when |
|---|---|---|
| `has_target` | — | `target != null` |
| `can_see_target` | — | `target` is in the actor's FOV **and** has LOS from the actor's cell |
| `in_weapon_range` | `weapon` | `target` is inside that weapon's range (DECISIONS §4, in cells: heavy pistol 8, SMG 10, assault rifle 14, shotgun 6, melee 1; spells 12 with LOS) |
| `in_melee_range` | — | `target` occupies one of the actor's eight neighbouring cells |
| `not_blocked_by_ally` | — | the actor's line of fire to `target` crosses no allied cell |
| `has_cover_available` | — | a reachable cell exists that breaks LOS from `target` |
| `at_cover` | — | the actor's cell == `cover_pos` |
| `has_last_known_pos` | — | `last_known_pos != null` |
| `low_morale` | — | `morale <= flee_threshold[archetype]` |
| `wound_modifier_at_most` | `value` (int ≤ 0) | the actor's Wound Modifier (§4) is ≤ `value` |
| `noise_heard` | — | `noise_pos != null` |
| `at_home` | — | the actor's cell == `home_pos` |
| `alert_below` | `level` (1 or 2) | `alert_level < level` |
| `ammo_empty` | — | the equipped magazine holds 0 |
| `is_prone` | — | the actor is prone |
| `spirit_type_is` | `type` ∈ Beast/Air/Earth/Water | the summon's type matches (§7) |
| `objective_is` | `value` (string) | `objective == value` |
| `enemy_spell_active` | — | a Runner is sustaining a spell inside the actor's FOV |
| `pacified` | — | the actor's Blackboard `pacified` flag is set: dialogue has stood this actor down (DECISIONS §8) |

---

## 9. The trees

All six are valid against §2: only the eight node types, only catalogue names, only declared args. `name` is present on branch roots because traces read better with it.

### 9.1 Corp Guard — patrol, escalate, call backup; holds its post

```json
{
  "id": "corp_guard",
  "archetype": "Corp Guard",
  "root": {
    "type": "selector",
    "name": "root",
    "children": [
      {
        "type": "sequence",
        "name": "pacified",
        "children": [
          { "type": "condition", "check": "pacified" },
          { "type": "action", "action": "move_to_blackboard", "args": { "key": "home_pos" } }
        ]
      },
      {
        "type": "sequence",
        "name": "flee",
        "children": [
          { "type": "condition", "check": "low_morale" },
          { "type": "action", "action": "retreat", "args": { "dest": "exit" } }
        ]
      },
      {
        "type": "sequence",
        "name": "combat",
        "children": [
          { "type": "condition", "check": "has_target" },
          { "type": "condition", "check": "can_see_target" },
          {
            "type": "selector",
            "name": "engage",
            "children": [
              {
                "type": "sequence",
                "name": "call_backup",
                "children": [
                  { "type": "condition", "check": "alert_below", "args": { "level": 2 } },
                  { "type": "cooldown", "passes": 4, "child": { "type": "action", "action": "call_backup" } }
                ]
              },
              {
                "type": "sequence",
                "name": "shoot",
                "children": [
                  { "type": "condition", "check": "in_weapon_range", "args": { "weapon": "assault_rifle" } },
                  { "type": "condition", "check": "not_blocked_by_ally" },
                  { "type": "action", "action": "attack_target", "args": { "weapon": "assault_rifle" } }
                ]
              },
              {
                "type": "sequence",
                "name": "reload",
                "children": [
                  { "type": "condition", "check": "ammo_empty" },
                  { "type": "action", "action": "reload" }
                ]
              },
              {
                "type": "sequence",
                "name": "hold_cover",
                "children": [
                  { "type": "condition", "check": "has_cover_available" },
                  { "type": "inverter", "child": { "type": "condition", "check": "at_cover" } },
                  { "type": "succeeder", "child": { "type": "action", "action": "seek_cover" } },
                  { "type": "action", "action": "take_cover" }
                ]
              },
              {
                "type": "sequence",
                "name": "close",
                "children": [
                  { "type": "action", "action": "move_to_blackboard", "args": { "key": "last_known_pos" } }
                ]
              }
            ]
          }
        ]
      },
      {
        "type": "sequence",
        "name": "investigate_noise",
        "children": [
          { "type": "condition", "check": "noise_heard" },
          { "type": "action", "action": "move_to_blackboard", "args": { "key": "noise_pos" } }
        ]
      },
      {
        "type": "sequence",
        "name": "pursue_last_known",
        "children": [
          { "type": "condition", "check": "has_last_known_pos" },
          { "type": "action", "action": "move_to_blackboard", "args": { "key": "last_known_pos" } }
        ]
      },
      {
        "type": "sequence",
        "name": "return_to_post",
        "children": [
          { "type": "inverter", "child": { "type": "condition", "check": "at_home" } },
          { "type": "action", "action": "move_to_blackboard", "args": { "key": "home_pos" } }
        ]
      },
      { "type": "action", "action": "patrol" }
    ]
  }
}
```

Tactics: **a pacified guard — a successful bribe or Intimidation (`dialogue.md` §5.1) — walks home and stops looking: the `pacified` branch is first, so it preempts combat.** Otherwise: patrol the ring; on sight, **call backup once per 4 Passes** (escalation, §8) and shoot at rifle range; reload rather than stand idle; **fall back to cover instead of shooting through its own squad**; close to `last_known_pos` when out of range and pursue after the Runner breaks LOS. The `succeeder` around `seek_cover` means "if I cannot find cover, still take the cell I have" — an optional step that does not kill the branch.

### 9.2 Security Drone — hackable, flies, rigid patrol

```json
{
  "id": "security_drone",
  "archetype": "Security Drone",
  "root": {
    "type": "selector",
    "name": "root",
    "reactive": false,
    "children": [
      {
        "type": "sequence",
        "name": "relay_alarm",
        "children": [
          { "type": "condition", "check": "has_target" },
          { "type": "condition", "check": "alert_below", "args": { "level": 2 } },
          { "type": "cooldown", "passes": 3, "child": { "type": "action", "action": "call_backup" } }
        ]
      },
      {
        "type": "sequence",
        "name": "fire",
        "children": [
          { "type": "condition", "check": "has_target" },
          { "type": "condition", "check": "can_see_target" },
          { "type": "condition", "check": "in_weapon_range", "args": { "weapon": "smg" } },
          { "type": "condition", "check": "not_blocked_by_ally" },
          { "type": "action", "action": "attack_target", "args": { "weapon": "smg" } }
        ]
      },
      {
        "type": "sequence",
        "name": "track_and_aim",
        "children": [
          { "type": "condition", "check": "can_see_target" },
          { "type": "action", "action": "aim" }
        ]
      },
      { "type": "action", "action": "patrol" }
    ]
  }
}
```

Tactics: **relay the alarm, then hold the patrol post at SMG range**. There is no investigate branch (rigid, §8), no flee branch (a machine), and no cover branch (it flies). `aim` instead of closing: it stacks to +2 (prerequisite stops it at the cap) and turns held Energy into a better next shot. The root is `"reactive": false`, so it finishes what it started before re-scanning — the rigid-patrol lever. The Decker can seize it for 3 rounds (§7, Drone rating 4).

### 9.3 Ganger — opportunist, poor discipline, flees at Wound Modifier −3

```json
{
  "id": "ganger",
  "archetype": "Ganger",
  "root": {
    "type": "selector",
    "name": "root",
    "children": [
      {
        "type": "sequence",
        "name": "flee",
        "children": [
          { "type": "condition", "check": "low_morale" },
          { "type": "action", "action": "retreat", "args": { "dest": "exit" } }
        ]
      },
      {
        "type": "sequence",
        "name": "fight",
        "children": [
          { "type": "condition", "check": "has_target" },
          {
            "type": "selector",
            "name": "engage",
            "children": [
              {
                "type": "sequence",
                "name": "melee",
                "children": [
                  { "type": "condition", "check": "can_see_target" },
                  { "type": "condition", "check": "in_melee_range" },
                  { "type": "condition", "check": "not_blocked_by_ally" },
                  { "type": "action", "action": "attack_target", "args": { "weapon": "katana" } }
                ]
              },
              {
                "type": "sequence",
                "name": "shoot",
                "children": [
                  { "type": "condition", "check": "can_see_target" },
                  { "type": "condition", "check": "in_weapon_range", "args": { "weapon": "heavy_pistol" } },
                  { "type": "condition", "check": "not_blocked_by_ally" },
                  { "type": "action", "action": "attack_target", "args": { "weapon": "heavy_pistol" } }
                ]
              },
              {
                "type": "sequence",
                "name": "flank",
                "children": [
                  { "type": "condition", "check": "can_see_target" },
                  { "type": "action", "action": "flank_target" }
                ]
              },
              {
                "type": "sequence",
                "name": "pursue",
                "children": [
                  { "type": "action", "action": "move_to_blackboard", "args": { "key": "last_known_pos" } }
                ]
              }
            ]
          }
        ]
      },
      { "type": "action", "action": "patrol" }
    ]
  }
}
```

Tactics: **flee at morale ≤ −3** (Wound Modifier −3, §8) — the flee branch is first, so an abort mid-fight is immediate. Otherwise close the distance with `flank_target`, melee with the katana when adjacent, pistol when not. No `call_backup` anywhere: poor discipline means no commlink and no escalation. Low `target_hysteresis` (0.05) means it changes its mind between two near-equal Runners — deliberate.

### 9.4 Corp Mage — counterspells, casts from range, retreats

The counterspell branch uses the Mage's Counterspell (DECISIONS §7: opposed Sorcery test, range 12). Everything else uses §7's Mage kit and §6's Drain.

```json
{
  "id": "corp_mage",
  "archetype": "Corp Mage",
  "root": {
    "type": "selector",
    "name": "root",
    "children": [
      {
        "type": "sequence",
        "name": "flee",
        "children": [
          { "type": "condition", "check": "low_morale" },
          { "type": "action", "action": "retreat", "args": { "dest": "exit" } }
        ]
      },
      {
        "type": "sequence",
        "name": "kite",
        "children": [
          { "type": "condition", "check": "has_target" },
          { "type": "condition", "check": "in_melee_range" },
          { "type": "action", "action": "retreat", "args": { "dest": "fallback" } }
        ]
      },
      {
        "type": "sequence",
        "name": "wounded_fall_back",
        "children": [
          { "type": "condition", "check": "wound_modifier_at_most", "args": { "value": -2 } },
          { "type": "condition", "check": "has_cover_available" },
          { "type": "action", "action": "seek_cover" },
          { "type": "action", "action": "take_cover" }
        ]
      },
      {
        "type": "sequence",
        "name": "counterspell",
        "children": [
          { "type": "condition", "check": "has_target" },
          { "type": "condition", "check": "can_see_target" },
          { "type": "condition", "check": "enemy_spell_active" },
          { "type": "cooldown", "passes": 2, "child": { "type": "action", "action": "use_power", "args": { "power": "counterspell", "force": 3 } } }
        ]
      },
      {
        "type": "sequence",
        "name": "manabolt",
        "children": [
          { "type": "condition", "check": "has_target" },
          { "type": "condition", "check": "can_see_target" },
          { "type": "condition", "check": "in_weapon_range", "args": { "weapon": "manabolt" } },
          { "type": "condition", "check": "not_blocked_by_ally" },
          { "type": "action", "action": "use_power", "args": { "power": "manabolt", "force": 4 } }
        ]
      },
      {
        "type": "sequence",
        "name": "reposition",
        "children": [
          { "type": "action", "action": "move_to_blackboard", "args": { "key": "last_known_pos" } }
        ]
      }
    ]
  }
}
```

Tactics: **counterspell first** when a Runner is sustaining, then Manabolt (Force 4, Drain `max(2, 4−3)` = 2 by §6) at casting range; **retreats** — it withdraws one Step at a time whenever a Runner is adjacent (the `kite` branch, `dest:"fallback"`), and at Wound Modifier −2 or worse it falls back to cover and holds there rather than trading swings. `force` is baked per branch; a tuned Mage can raise Force at the cost of Drain (§6).

### 9.5 Hellhound — fast melee, tracks by scent, never flees

```json
{
  "id": "hellhound",
  "archetype": "Hellhound",
  "root": {
    "type": "selector",
    "name": "root",
    "children": [
      {
        "type": "sequence",
        "name": "bite",
        "children": [
          { "type": "condition", "check": "has_target" },
          { "type": "condition", "check": "can_see_target" },
          { "type": "condition", "check": "in_melee_range" },
          { "type": "condition", "check": "not_blocked_by_ally" },
          { "type": "action", "action": "attack_target", "args": { "weapon": "bite" } }
        ]
      },
      {
        "type": "sequence",
        "name": "charge",
        "children": [
          { "type": "condition", "check": "has_target" },
          { "type": "condition", "check": "can_see_target" },
          { "type": "action", "action": "move_to_adjacent", "args": { "key": "target", "sprint": true } }
        ]
      },
      {
        "type": "sequence",
        "name": "track",
        "children": [
          { "type": "condition", "check": "has_target" },
          { "type": "action", "action": "track_by_scent" }
        ]
      },
      { "type": "action", "action": "patrol" }
    ]
  }
}
```

Tactics: **sprint straight to melee and bite** (`bite`: melee range 1, `(Strength + 2)P` AP 1 — DECISIONS §4); when the Runner breaks LOS the scent trait keeps the Hellhound's candidate set populated, so `has_target` stays true and `track_by_scent` closes through walls (it still has to path around them). **No flee branch exists in the document** — §8's "never flees" is structural, not a condition. No `call_backup`: no commlink, and no squad worth calling.

### 9.6 Spirit — follows the summoner; Beast, Air, Earth, Water

The Shaman sets the Spirit's `command_target` (player-issued, DECISIONS §14 — Spirit control, resolved); `refresh()` resolves it into `target`, so the pin wins over the Utility Score. When a Conjuring fails or Glitches (§7) the site rewrites `objective` to `"hostile"` and the *same* tree attacks the nearest Runner, summoner included.

```json
{
  "id": "spirit",
  "archetype": "spirit",
  "root": {
    "type": "selector",
    "name": "root",
    "children": [
      {
        "type": "sequence",
        "name": "beast_strike",
        "children": [
          { "type": "condition", "check": "spirit_type_is", "args": { "type": "Beast" } },
          { "type": "condition", "check": "has_target" },
          { "type": "condition", "check": "can_see_target" },
          { "type": "condition", "check": "in_melee_range" },
          { "type": "condition", "check": "not_blocked_by_ally" },
          { "type": "action", "action": "attack_target", "args": { "weapon": "beast_strike" } }
        ]
      },
      {
        "type": "sequence",
        "name": "earth_slam",
        "children": [
          { "type": "condition", "check": "spirit_type_is", "args": { "type": "Earth" } },
          { "type": "condition", "check": "has_target" },
          { "type": "condition", "check": "can_see_target" },
          { "type": "condition", "check": "in_melee_range" },
          { "type": "condition", "check": "not_blocked_by_ally" },
          { "type": "action", "action": "attack_target", "args": { "weapon": "earth_slam" } }
        ]
      },
      {
        "type": "sequence",
        "name": "air_bolt",
        "children": [
          { "type": "condition", "check": "spirit_type_is", "args": { "type": "Air" } },
          { "type": "condition", "check": "has_target" },
          { "type": "condition", "check": "can_see_target" },
          { "type": "condition", "check": "in_weapon_range", "args": { "weapon": "air_bolt" } },
          { "type": "condition", "check": "not_blocked_by_ally" },
          { "type": "action", "action": "attack_target", "args": { "weapon": "air_bolt" } }
        ]
      },
      {
        "type": "sequence",
        "name": "water_burst",
        "children": [
          { "type": "condition", "check": "spirit_type_is", "args": { "type": "Water" } },
          { "type": "condition", "check": "has_target" },
          { "type": "condition", "check": "can_see_target" },
          { "type": "condition", "check": "in_weapon_range", "args": { "weapon": "water_burst" } },
          { "type": "action", "action": "attack_target", "args": { "weapon": "water_burst" } }
        ]
      },
      {
        "type": "sequence",
        "name": "close_melee",
        "children": [
          {
            "type": "selector",
            "name": "is_melee_type",
            "children": [
              { "type": "condition", "check": "spirit_type_is", "args": { "type": "Beast" } },
              { "type": "condition", "check": "spirit_type_is", "args": { "type": "Earth" } }
            ]
          },
          { "type": "condition", "check": "has_target" },
          { "type": "action", "action": "move_to_adjacent", "args": { "key": "target" } }
        ]
      },
      {
        "type": "sequence",
        "name": "close_ranged",
        "children": [
          {
            "type": "selector",
            "name": "is_ranged_type",
            "children": [
              { "type": "condition", "check": "spirit_type_is", "args": { "type": "Air" } },
              { "type": "condition", "check": "spirit_type_is", "args": { "type": "Water" } }
            ]
          },
          { "type": "condition", "check": "has_target" },
          { "type": "action", "action": "move_to_blackboard", "args": { "key": "last_known_pos" } }
        ]
      },
      {
        "type": "sequence",
        "name": "free_spirit",
        "children": [
          { "type": "condition", "check": "objective_is", "args": { "value": "hostile" } },
          { "type": "action", "action": "move_to_adjacent", "args": { "key": "target", "sprint": true } }
        ]
      },
      { "type": "action", "action": "follow_summoner" }
    ]
  }
}
```

Tactics: type drives the branch, and each type gets its own attack from `classes.md` §7.3 — Beast `beast_strike` `(Force+3)P` AP 1 and Earth `earth_slam` `(Force+2)P` AP 2 close to melee and strike, Air `air_bolt` `(Force+1)P` AP 0 shoots at range 8, Water `water_burst` `(Force)S` AP 0 bursts a radius-2 area at range 6. A Spirit is not a Caster, so every Spirit attack is `attack_target`, not `use_power` (§7); `water_burst`'s radius 2 is resolved by the combat resolver. With no target — or with the Enemy in another room — the Spirit **follows the summoner** rather than wandering. `free_spirit` is the fallback that turns a broken summon into a threat. It lasts 3 rounds (§7); that is the site's business, not the tree's.

---

## 10. Debugging — because a JSON tree fails silently

ADR-0009 is explicit: a malformed tree must not fail silently. Three layers, cheapest first.

1. **Load-time validation** (§2.3). Every archetype tree is loaded and validated at startup. All errors, with node ids and codes. This is where 90% of authoring bugs die.
2. **Runtime invariants**. The ticker raises `SchemaError` on an unknown node type rather than returning FAILURE (the load already rejected it). Every Blackboard write goes through a typed setter that rejects an unknown key. Every condition and action is a named entry in a registry; an unknown name cannot reach runtime.
3. **The trace**. One `TraceStep` per decision step, kept in a per-actor ring buffer (last 32 steps):

```
TraceStep {
  pass_no, energy_before, energy_after,
  path:      ["root", "combat", "engage", "shoot"],   # node names, root first
  statuses:  {"root":"SUCCESS","combat":"SUCCESS","shoot":"FAILURE",
              "not_blocked_by_ally":"FAILURE"},       # every node touched this step
  first_failure: "not_blocked_by_ally",               # the whole "why"
  spent: 0, candidate_scores: {"runner#1": 2.25, "runner#2": 1.00},
  target_before: 2, target_after: 1, bb_delta: {"target": [2, 1]}
}
```

`explain(actor)` renders the last step as one line, and `explain(actor, n)` the last *n*. It answers "why did it do that" directly: **the first FAILURE on the path is the reason, and the previous sibling statuses are the alternatives it rejected.**

```
Pass 2 E15 | root>combat>engage>hold_cover>seek_cover
  shoot:      in_weapon_range=SUCCESS  not_blocked_by_ally=FAILURE (ganger#2 on the line of fire)
  reload:     ammo_empty=FAILURE
  hold_cover: has_cover_available=SUCCESS  at_cover=FAILURE
  -> seek_cover resumed (Step 2 of N) | spent 1E | target runner#1 (2.25) > runner#2 (1.00)
```

Practices that keep the trace useful:

- **Log transitions, not ticks.** Print a line only when the resolved leaf, `target`, or `alert_level` changes. Per-step logs of a 20-actor fight are noise; the ring buffer holds the detail for a post-mortem.
- **Score bars, not trees, on screen.** The renderer draws one Glyph per cell (ADR-0004), so there is no overlay tree to draw. The active path and the candidate scores go in a text debug panel (a side console), and the selected actor's cell gets a foreground tint. The tree itself is inspected as a JSON file plus the trace log.
- **Reproduce with the seed.** The Run seed is `job id + run counter` (§9). Any randomness in the brain (there is little; tie-breaks are deterministic) comes from `random.Random(derive(run_seed, f"ai:{actor_id}"))` — the sha256-based `derive()` of `data-model.md` §14, a **per-actor stream**, so actor iteration order cannot change outcomes. The builtin `hash()` is salted per process (`PYTHONHASHSEED`) and is forbidden. Never a shared global RNG.
- **Assert the reset contract.** If a timed action "finishes instantly" after re-entry, a missing `reset()`, or a `cooldown` wrongly cleared by `reset_tree`, is the cause. Both are unit-tested (§11, items 12–13).

---

## 11. Deterministic test plan

Everything is unit-testable because the brain touches the world through two small interfaces and one seed.

```python
class MockWorld:
    grid: list[list[bool]]                 # walkable mask
    actors: dict[str, MockActor]
    calls: list[tuple]                     # every method call, for assertions
    def fov(self, actor) -> set[cell]      # stub: FOV from §13's recursive shadowcasting, or a fixed set
    def los(self, a, b) -> bool            # stub: Bresenham, no RNG
    def path(self, a, b) -> list[cell]     # stub: fixed A*, Chebyshev
    def damage(self, target_id, dv) -> None

class MockActor:
    id; archetype; cell; reaction
    energy; wound_modifier; prone; ammo; weapons; powers
    blackboard: Blackboard
    brain: ActorBrain                      # holds §4.2 state

def run_actor(tree_json, world, actor, seed, passes=3) -> list[TraceStep]
```

| # | test | asserts |
|---|---|---|
| 1 | selector/sequence semantics | first non-FAILURE wins; first non-SUCCESS stops; child order in the trace |
| 2 | decorators | Inverter flips; Succeeder swallows FAILURE and passes RUNNING; Repeated child FAILURE clears the counter |
| 3 | Cooldown | `call_backup` fires, arms; the next 4 Passes it returns FAILURE without ticking the child; resets do not re-arm |
| 4 | Repeat `times:0` | returns RUNNING, one child repetition per decision step; the ticker terminates (no spin) |
| 5 | **never shoots through an ally** | ally on the line → `not_blocked_by_ally` FAILURE, `attack_target` never invoked, `world.damage` records zero ally hits over 20 decision steps |
| 6 | **seeks cover under fire** | under fire with a cover cell available → resolves to `seek_cover`; on arrival `at_cover` true and ranged defence includes the +2 of §4 |
| 7 | **flees at the morale threshold** | Ganger at Wound Modifier −2 fights; at −3 the `flee` branch wins and the actor's distance to `target` strictly increases each Step |
| 8 | Hellhound tracks by scent | Runner out of FOV → `has_target` still true, `track_by_scent` chosen, distance decreases without LOS |
| 9 | Spirit follows and obeys | no target → `follow_summoner`, ends adjacent; pinned target → attacks it, not the summoner; `objective: "hostile"` → attacks the nearest Runner |
| 10 | hysteresis | two candidates within the margin → `target` unchanged across 10 steps; a challenger beyond the margin → switches once |
| 11 | deterministic ties | identical scores → higher Reaction wins; equal Reaction → lower actor id |
| 12 | RUNNING resumes in the Pass | a 6-tile move takes 6 decision steps, always at the same node id, then SUCCESS |
| 13 | RUNNING is reset at the Pass boundary | same move with 3 Energy: three Steps, Pass ends, next Pass re-enters the tree from the root; `cooldowns` unchanged |
| 14 | abort contract | Ganger mid-flank with morale crossing the floor → `reset_subtree` clears the flank branch's `resume`; next entry into flank starts at child 0 |
| 15 | malformed trees | each §2.3 snippet raises the exact code; a tree with an unknown key raises `E_UNKNOWN_KEY`, not a warning |
| 16 | zero-cost catalogue entry | `E_ZERO_COST` at catalogue load |
| 17 | no recursion | a 5 000-deep `inverter` chain ticks without `RecursionError`; the stack depth equals the chain depth |
| 18 | determinism | `run_actor(..., seed=7, passes=10)` twice → byte-identical trace list |
| 19 | Pass economy | Energy never goes negative; the Pass ends at Energy < 1; a FAILURE root ends the Pass without spending |
| 20 | every shipped tree validates | the six documents of §9 pass the loader and, run in a one-tile box with no Runners, return FAILURE/patrol without raising |

Assertions are on the **trace**, not on internal variables: the trace is the contract the debugger shows and the thing a designer reasons about. `MockWorld.calls` catches the side effects (damage, noise, alarm).

---

## 12. Open questions

**All five items are closed.** They now live in `DECISIONS.md` §8 as contract values, so nothing here can
drift from the code:

1. **Utility weights and hysteresis** — values adopted as unplaytested defaults in `DECISIONS.md` §8.
2. **Morale bonuses and flee thresholds** — likewise, in the same table.
3. **Cover predicate** — settled by `DECISIONS.md` §4 (previous text kept as a cross-reference only).
4. **Self-targeted Heal** — allowed at the standard Drain (`DECISIONS.md` §7).
5. **Local rules** — `Repeat times: 0` is one repetition per decision step, cooldowns are measured in Passes
   and survive a reset, and movement is one Step per decision step. The last is what makes a Pass
   interruptible and `RUNNING` meaningful rather than decorative, and it is now a contract rule rather than a
   recommendation (`DECISIONS.md` §8, §14 items 23–30).

---

## Sources

Patterns and vocabulary borrowed from the installed skill files:

- `.agents/skills/ai-behavior-trees-utility-ai/SKILL.md` — hybrid BT/Utility split, three-value `Status` contract, "build the tree once at spawn", hysteresis for near-ties.
- `.agents/skills/ai-behavior-trees-utility-ai/references/behavior-tree-core.md` — `Node`/`Composite`/`Decorator` taxonomy, memory vs reactive composites, the `Reset()`-on-abandon contract, Inverter/Succeeder/Cooldown/Repeat semantics, the Blackboard as a typed key/value store.
- `.agents/skills/ai-behavior-trees-utility-ai/references/utility-ai-system.md` — argmax selection with an inertia bonus for the committed choice.
- `.agents/skills/ai-behavior-trees-utility-ai/references/practical-examples.md` — the guard Patrol→Combat fallback shape, per-archetype parameter blocks, utility-as-a-leaf hybrid.
- `.agents/skills/ai-behavior-trees-utility-ai/references/best-practices-and-pitfalls.md` — log transitions not ticks, one seeded RNG per agent, draw the decision, assert the `Reset()` contract.
- `.agents/skills/game-ai/SKILL.md` and `references/behavior-trees.md` — Selector/Sequence status combination, blackboard keys for target/home/path, the guard tree sketch, "leaves that never return RUNNING restart the action".

Deviations from the skill references, deliberate: recursion replaced by the explicit stack (§4.1, required by §13); `Cooldown` measured in Passes rather than seconds because the game has no frame clock; one atomic action per decision step so RUNNING means "one Step further" rather than "next frame".

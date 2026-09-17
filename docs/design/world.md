# World: the Hub, the Job loop, and Site generation

How the Crew moves between Jobs, what a Job is made of, and how a Site is built from a seed.

Vocabulary is `CONTEXT.md`. Notation: `DEC §n` is a section of `docs/design/DECISIONS.md` (the
parameter contract); a bare `§n` is a section of this document. Every number here either comes
from the contract or is proposed in **§11 Open questions** with a `[Pn]` tag. Do not treat a
`[Pn]` value as settled.

---

## 1. The Hub

One authored district, **80×38 cells**, on a 1280×720 screen with 16px tiles: the screen is 80×45
cells and the bottom **7 rows are reserved for UI** — the Security Clock, crew status, and the
dialogue box (DEC §9). The district is 80×38 and not 80×45 because a full-screen district leaves
nowhere to draw them. Not procedural: the layout is a constant, the Zones are rects in a data file,
and only which Jobs the Fixer posts and what the shop stocks is seeded.

### 1.1 Layout

```
        x=0                                                                    x=79
y=00  ################################################################################
y=01  ################################################################################
y=02  ##...................#######.....................###########...................#
y=03  ##...................#######.....................###########...................#
y=04  ##...................#######.....................###########...................#
y=05  ##...................#######.....................###########...................#
y=06  ##...................#######.....................###########...................#
y=07  ##...................#######.....................###########...................#
y=08  ##.....SAFEHOUSE.....#######......RIPPERDOC......###########.....GEAR SHOP.....#
y=09  ##...................#######.....................###########...................#
y=10  ##...................#######.....................###########...................#
y=11  ##...................#######.....................###########...................#
y=12  ##...................#######.....................###########...................#
y=13  ##...................#######.....................###########...................#
y=14  ##########+###########################+#############################+###########
y=15  ================================================================================
y=16  ================================================================================
y=17  ######################==################################==######################
y=18  ######################==################################==######################
y=19  ######################==################################==######################
y=20  ######################==################################==######################
y=21  ######################==################################==######################
y=22  ######################==################################==######################
y=23  ######################==################################==######################
y=24  ######################==################################==######################
y=25  ######################==################################==######################
y=26  ================================================================================
y=27  ================================================================================
y=28  ##########+#########################################################+###########
y=29  ##.................#########################################...................#
y=30  ##.................#########################################...................#
y=31  ##.................#########################################...................#
y=32  ##.................#########################################...................#
y=33  ##....FIXER BAR....#########################################......TRANSIT......#
y=34  ##.................#########################################...................#
y=35  ##.................#########################################...................#
y=36  ##.................#########################################...................#
y=37  ################################################################################

  .  walkable floor              =  walkable street
  #  building / impassable       +  doorway (chokepoint, Zone entrance)
  A Zone label is drawn on the floor fill and occupies no special tile.
```

The map is 38 rows; rows y=38–44 of the 1280×720 screen are the UI band and are not part of the
district (DEC §9). The central mass (x 24–55, y 17–25) is impassable tenement. The two `==` vertical
runs at x 22–23 and x 56–57 are the only north–south crossings; that is deliberate — it is the Hub's
only navigational fact and it is a constant, not a generation problem.

### 1.2 Zones

Mechanics are per interaction, not per cell. Standing on a Zone's floor and pressing the
interact key opens its screen. Movement is turn-based steps (DEC §14 Q1, `[P1]`).

| Zone | Rect (x, y, w, h) | Doors | Mechanics |
|---|---|---|---|
| Crew safehouse | 2, 2, 19, 12 | (10, 14) | Crew spawn on load. **Advance**: spend XP to raise a skill or attribute rating — a skill Advance costs `new rating × 3` XP, an attribute Advance `new rating × 5` (DEC §14, resolved item 8). Perk review. Rest: a full day of rest clears `HUB_RECOVER_BOXES_PER_DAY [P2]` boxes, Stun first, then Physical. Autosave point. |
| Ripperdoc / clinic | 28, 2, 21, 12 | (38, 14) | Buys the same recovery instantly: `CLINIC_COST_PER_BOX [P3]` ¥ per filled box. A **Downed** Runner is revived for `CLINIC_REVIVE_DOWNED [P3]` ¥ instead of waiting out the boxes. Sells medical consumables at the DEC §9 gear prices (medkit 500 ¥; the trauma patch is `[P5]`). |
| Gear shop | 60, 2, 19, 12 | (68, 14) | Only place to spend nuyen on gear. Prices are the DEC §9 **Gear prices** table — weapons, armour, ammunition and the medkit are all priced there. Stock is a seeded 6-item draw per Job from that table, weighted to the current Heat tier (`§8.3`). Buying requires having spent the **Buy Gear** Legwork action (§3.2). |
| Fixer bar | 2, 29, 17, 8 | (10, 28) | The **Fixer**. Take a Job, negotiate payout (Opposed Test, DEC §9), report the result, get paid. Displays Heat and Fixer reputation. **Call in a Favour** Legwork action (§3.3). Job offers refresh every `JOB_OFFER_ROTATION_DAYS [P4]`. |
| Transit point | 60, 29, 19, 8 | (68, 28) | **Depart**: consumes the Job, derives the `run_seed` (§5.5), generates the Site, starts the Run. Every **Extraction** lands the Crew back on this tile. |

Nothing else in the district has mechanics. Decorative cells cost nothing to walk on and
nothing to build.

### 1.3 Hub time

Turn-based steps, one step = one Hub tick. A day is `HUB_TICKS_PER_DAY [P1]` ticks, which is
more than enough to walk the district twice, so walking is effectively free and days only pass
on committed actions:

| Action | Days |
|---|---|
| Free-roam steps | 0 (absorbed by the day's tick budget) |
| One Legwork action (§3) | 1 |
| A day of rest at the safehouse | 1 |
| Take a Job / Depart | 1 |

`hub_day` is persisted. Days are pacing, not pressure: nothing in the Hub fails or expires on a
timer, and Heat never decays from passing time.

---

## 2. The Job loop

```
 (A) HUB  ──────────────────────────────────────────────────────────────────────
      |   stand anywhere in the district; Hub tick per step
      v
 (B) FIXER BAR ────────────────────────────────────────────────────────────────
      |   read JOB_OFFERS [P4] offers -> pick one -> Negotiation Opposed Test
      |     base payout = 12000 x TYPE_MULT[type]  +  100 x net Hits   (DEC §9)
      |     a Glitch on the negotiation costs 1 offer slot: take this Job or none
      v
 (C) LEGWORK ──────────────────────────────────────────────────────────────────
      |   up to 3 actions (DEC §9), any order, repeats allowed, 1 day each
      |     Scout Site | Buy Gear | Call in a Favour
      v
 (D) TRANSIT ──────────────────────────────────────────────────────────────────
      |   Depart -> run_seed = f(job id, run counter)  (§5.5, stored)
      |   -> Mission Graph (§5) -> Embed (§6) -> Populate (§7)
      v
 (E) RUN  ─────────────────────────────────────────────────────────────────────
      |   Clock starts at CLOCK_START[type] [P18], normally 0
      |   +2 gunfire      +2 guard killed   +3 body found   +1 failed hack
      |   +2 loud spell (Force >= 4)        +2 alarm tripped
      |   +1 lock forced  +1 Critical Glitch (DEC §3)
      |   Clock >= 4  Alert     patrols converge (Blackboard alert_level -> 1)
      |   Clock >= 7  Lockdown  doors lock, guards +2 armour
      |   Clock = 10   Converge  security converges: forced Extraction
      |
      +---- every required objective cleared -> reach the exit node -> VOLUNTARY
      |
      v
 (F) PAYOUT ───────────────────────────────────────────────────────────────────
      |   voluntary: pays for objectives completed (formula, §4.1)
      |   forced   : 0 nuyen, Heat +2, Fixer reputation -1        (DEC §9)
      v
 (G) HEAT / REP UPDATE ────────────────────────────────────────────────────────
      |   successful Job: Heat -1  (DEC §14, resolved 4; -2 above Heat 8)
      |   Clock >= 7 at Extraction: Heat +1 [P19]
      |   Fixer reputation: +1 voluntary / -1 forced; side objectives: +0
      v
 (H) DOWNTIME ─────────────────────────────────────────────────────────────────
      |   recover boxes (rest or clinic), Advance, review Perks, shop
      |
      +----------------------------------------------------------> back to (A)
```

Saving happens at (A) and immediately after (F). A Run is never saved mid-flight: a failed Run
cannot be reloaded into a better one (§10.4).

---

## 3. Legwork

Three actions per Job (DEC §9). Each costs one action and one Hub day; each changes the coming Run
only — nothing in Legwork is persisted except the reputation and nuyen it spends. Legwork is
never mandatory: taking a Job with zero Legwork is legal and common at low Heat.

### 3.1 Scout Site

*Cost: 1 action, 0 ¥.*
*Effect: reveals the Mission Graph on the pre-Run briefing screen — every node's type and every
edge — and marks which nodes are Security nodes.*

It does not reveal enemy counts, device types, or device ratings. `Scan`, `Analyze Device`, and
the Favour's device reveal (§3.3) keep their value.

Design consequences: with no Scout the player picks a loadout blind, so the recommended default
is Scout first. Scout turns the Run from a maze into a route problem, which is the whole point of
naming the graph before embedding it (ADR-0011).

### 3.2 Buy Gear

*Cost: 1 action, plus nuyen spent.*
*Effect: opens the gear shop for this Job only.*

Prices are the DEC §9 **Gear prices** table and nothing else: weapons (DEC §4 gives DV/AP, DEC §9
gives the price), armour, ammunition at 100 ¥ per reload, and the medkit at 500 ¥. The only item
the contract does not price is the **trauma patch**, which keeps a local price `[P5]`.

The shop's stock is seeded from `(job id, hub_day)` so an offer can be re-checked by standing in
it; re-rolling stock means waiting `JOB_OFFER_ROTATION_DAYS [P4]`. Two consumables exist: a
**medkit** (500 ¥, DEC §9) heals 1 box per use, `MEDKIT_USES [P5] = 3` uses; a **trauma patch**
(`TRAUMA_PATCH_COST [P5]`) stops Stun-to-Physical Overflow for one Runner for the rest of the
Run, once. Gear bought here is in the loadout at Run start and persists (§10.1).

Buy Gear competes directly with Scout and the Favour for the three slots. That competition is the
entire mechanical content of the three-action budget.

### 3.3 Call in a Favour

*Cost: 1 action, 1 Fixer reputation (`FAVOUR_REP_COST [P6]`), requires reputation ≥ 1.*
*Effect: choose exactly one of two outcomes.*

| Outcome | Effect in the coming Run |
|---|---|
| **Clock head start** | `clock_credit = FAVOUR_CLOCK_CREDIT [P6]` segments. Each segment the Security Clock would gain is spent down against the credit first; the credit is per-Run and does not carry over. |
| **Device reveal** | Full device list for the Site: every device's type and rating, on every node. This is `Scan` (DEC §7) at unlimited radius, before Depart. |

A Clock head start cannot push the Clock below 0 — it is a buffer, not a starting value. That is
why it is modelled as credit rather than as a negative start: `Clock` stays `>= 0` everywhere and
`clock >= 4` keeps meaning Alert.

The Favour is the only Legwork action whose cost is reputation, so it is the only one that makes
a later Job's negotiation worse. Spending down to reputation 0 is a real decision.

---

## 4. Job types

Four in v1 (DEC §9). All four share the payout pipeline; they differ in what the objective nodes do
and how loud the objective forces the Crew to be.

| Type | Required objective nodes | Objective act | `TYPE_MULT [P7]` | Typical Clock at Extraction | Payout shape |
|---|---|---|---|---|---|
| **Extraction** (paydata) | 1 (vault) | reach the vault node, take the Paydata device, leave | 1.00 | 4–7 | flat base + side caches |
| **Sabotage** | 2 (parallel) | destroy or disable both target devices, leave | 1.15 | 6–9 | highest base, but risky |
| **Protection** | 1 (hold) | keep the VIP alive: escort to exit, or hold the node `PROTECTION_ROUNDS [P9]` rounds | 1.10 | 3–8 (spiky) | base + side; fails if the VIP dies |
| **Courier** | 1 (drop) | carry the package from entry to the drop node, then exit | 0.90 | 1–4 | low base, `COURIER_DISCRETION_BONUS [P9]` for a quiet finish |

### 4.1 Payout

```
net        = net Hits on the payout Negotiation Opposed Test (may be negative)
base       = round(12000 * TYPE_MULT[type]) + 100 * net
required   = number of required objective nodes for the Job type
cleared    = required objective nodes completed at Extraction
side       = optional (side) objectives completed

payout =
    0                                                    if forced Extraction (DEC §9)
    round(base * cleared / required)                     if voluntary, cleared < required
    base                                                 if voluntary, cleared == required
  + SIDE_OBJECTIVE_PAYOUT [P8] * side
  + COURIER_DISCRETION_BONUS [P9]   if type == courier and Clock <= 2 at Extraction
```

`base` is clamped at 0: a Fixer never charges the Crew, they just pay nothing.
Partial credit is deliberate — it makes "grab one of two and run" a legitimate Sabotage plan.
Payouts are on the DEC §9 price scale the Crew spends against (§3.2): a 12,000 ¥ base is about two
and a half assault rifles, which is the ratio to hold when tuning either number.

### 4.2 Objective structures in detail

**Extraction** — one objective node, type *vault*, holding the Paydata device (§7). The objective
device is a rating-3 Commlink-class terminal: reading it needs a successful hack
(`Cybercombat`, threshold = device rating, Drain `ceil(3/2)` Stun, DEC §6) or physically carrying the
deck out. Taking it is silent. Leaving is the loud part.

**Sabotage** — two objective nodes fanned in parallel from one security fork and merged into one
security node (§5.3). Each target is a rating-4 machine-class device. Disabling one is a
threshold-4 test or 10 damage to the device; **destruction is a gunfire-equivalent Clock event
(+2 each)**. That is where the 1.15 multiplier is paid for: the type is loud by construction.

**Protection** — one objective node, type *hold*. The protectee is a non-player actor with a
Behavior Tree (§7), following the Crew. Its `objective` is a Mission Graph node id — the exit node
for an escort, the hold node for a hold — never a prose value, because DEC §8's `objective` is a
node id string and anything else silently zeroes the Utility Score's objective term. Player commands
to it go in `command_target` (`DEC §8`). Two sub-modes chosen at Job generation:

- *Escort*: the protectee must reach the exit node. The exit only counts as reached while the
  protectee is on it.
- *Hold*: the protectee stays in the objective node for `PROTECTION_ROUNDS [P9]` rounds while the
  node's **placed** garrison attacks; extraction is legal any time after the timer expires. v1 has
  no Mid-Run spawner: the "wave" is part of the §7 population pass, placed at embed like every
  other enemy (`DEC §9` escalates behaviour and armour, not numbers).

A dead protectee fails the objective but does not end the Run: the Crew may extract with side
objectives only. That keeps a bad Protection from being a hard loss (ADR-0005 leans on the Clock,
not on instant failure).

**Courier** — one objective node, type *drop*, gated by a security checkpoint node. The package is
an inventory device that is scanned by Optics devices: passing within the FOV radius of an
unhacked Optics device sets `alert_level += 1` and ticks the Clock `+1` ("alarm tripped").
This is the type that rewards the Decker: hacking the checkpoint's Optics and Door is the
difference between a 2-segment and a 6-segment Run.

---

## 5. Mission Graph

Typed nodes — **entry, security, objective, side, exit** (DEC §10). Built first, embedded second
(ADR-0011). Represented as an adjacency list; the node type is the only thing that carries into
embedding.

### 5.1 Node types

| Type | Count per graph | Role | Embeds as |
|---|---|---|---|
| `entry` | exactly 1 | Crew spawn; must have in-degree 0 | medium room on a Site edge |
| `security` | 1–3 | a gate on the main path; holds the guard post | small room |
| `objective` | 1–2 | required objective (§4.2) | size by Job type (§6.1) |
| `side` | 0–3 | optional objective / loot; dead-ends | small room |
| `exit` | exactly 1 | Extraction point; must have out-degree 0 | medium room on the opposite Site edge |

### 5.2 Edge constraints

Enforced as assertions in the builder; a graph failing any of them is discarded before embedding.

1. `entry` in-degree 0, out-degree ≥ 1.
2. `exit` in-degree ≥ 1, out-degree 0.
3. Every Objective node is reachable from `entry` by a directed path.
4. `exit` is reachable from every Objective node.
5. `security` nodes are never terminal and never a source: in-degree ≥ 1, out-degree ≥ 1.
6. In-degree ≤ 2 (`MAX_IN_DEGREE [P12]`). A node with in-degree 2 is a merge; that is the only
   diamond the graph may contain.
7. A `side` node has exactly one parent, the parent is on some `entry -> objective -> exit`
   path, and a `side` node has no outgoing edge to any main-path node. **Side branches dead-end.**
8. Side chains are capped: at most `SIDE_CHAIN_MAX [P11]` `side` nodes in a single chain, and each
   chain hangs off one parent. Side nodes can have `side` children, never `security` or
   `objective` children.
9. The graph is a DAG. Cycle detection runs separately from the union-find connectivity check —
   union-find cannot see cycles.

The two graph-wide properties from DEC §10 are checked directly: objectives reachable from entry (#3)
and exit reachable from every objective (#4). Both are forward-reachability passes from `entry`
and from each objective, not transitive closure of the whole graph.

### 5.3 Generation parameters

```python
JOB_GRAPH = {
    # sec_pre  security nodes between entry and the first objective
    # sec_post security nodes between the last objective and exit
    # objectives: 1 = single node; 2 = fanned in parallel from one node and merged
    "extraction": {"sec_pre": 2, "sec_post": 1, "objectives": 1, "side_max": 3, "min_len": 5},
    "sabotage":   {"sec_pre": 1, "sec_post": 1, "objectives": 2, "side_max": 2, "min_len": 5},
    "protection": {"sec_pre": 1, "sec_post": 1, "objectives": 1, "side_max": 1, "min_len": 4},
    "courier":    {"sec_pre": 1, "sec_post": 0, "objectives": 1, "side_max": 2, "min_len": 3},
}
SIDE_CHAIN_P = 0.25   # chance a side node grows a side child
```

`min_len` is the minimum number of nodes on the entry→exit path. A drawn graph shorter than
`min_len` is re-rolled from the same RNG stream.

### 5.4 Builder

```python
def build_graph(job_type, rng):
    cfg = JOB_GRAPH[job_type]
    g = Graph()

    cur = g.add("entry")
    for _ in range(cfg["sec_pre"]):
        n = g.add("security"); cur = g.link(cur, n)          # link() asserts 6.2

    if cfg["objectives"] == 1:
        cur = g.link(cur, g.add("objective"))
    else:
        objs = [g.add("objective") for _ in range(cfg["objectives"])]
        for o in objs: g.link(cur, o)
        merge = g.add("security")
        for o in objs: g.link(o, merge)
        cur = merge

    for _ in range(cfg["sec_post"]):
        cur = g.link(cur, g.add("security"))
    g.link(cur, g.add("exit"))

    # side branches: parents are main-path nodes, never entry/exit, weighted to mid-depth
    for parent in g.pick_side_parents(rng, rng.randint(0, cfg["side_max"])):
        node = g.add("side"); g.link(parent, node)
        while rng.random() < SIDE_CHAIN_P and g.side_chain_len(node) < SIDE_CHAIN_MAX:
            node = g.link(node, g.add("side"))

    assert g.is_dag() and g.objectives_reachable() and g.exit_reachable_from_objectives()
    assert g.path_len("entry", "exit") >= cfg["min_len"]
    return g
```

`pick_side_parents` samples without replacement from main-path nodes, weighted toward the middle
third of the depth ordering, so a side branch reads as a detour rather than a shortcut. `side`
nodes carry a `side_marker` that the embedding stage reads when seeding loot (§7).

### 5.5 Seed derivation

One seed per Run. `run_seed` is derived once at Depart from `(job id, run counter)` and then
**stored on the save** (§10.1, §10.4). Generation reads the stored `run_seed`; it never recomputes
it from the job id. Recomputing would silently change a saved Site the moment generation code
changed, which is the one thing a save must never do (DEC §9, Persistence). `run_counter`
increments on every attempt at the same Job — including a retry after a failed Run — so a retried
Job is a *new* Site, not a memorised one.

Every subsystem's randomness comes from the project's one seeding scheme, `derive(run_seed,
stream_name)` — a sha256-based derivation over named per-subsystem streams (DEC §9). There are no
sibling seeds and no XOR: the graph stage's stream is `gen.graph`, embedding is `gen.embed`, and
population is `gen.place`.

| Stage | Stream | RNG |
|---|---|---|
| Mission Graph (§5.4) | `gen.graph` | `random.Random(derive(run_seed, "gen.graph"))` |
| Embedding (§6.2) | `gen.embed` | `random.Random(derive(run_seed, "gen.embed"))` |
| Population (§7) | `gen.place` | `random.Random(derive(run_seed, "gen.place"))` |

Separate named streams rather than one shared stream mean a change to the population pass does not
reshuffle every Site's layout, and a bug in the embedding pass can be reproduced without replaying
the graph pass. The engine behind each stream is `random.Random` (Mersenne Twister) — stable within
a CPython line, and pinned for a release; note this in the save so a platform RNG change is
detectable. The builtin `hash()` is salted per process (`PYTHONHASHSEED`) and is forbidden.

Legwork never enters the seed. `clock_credit` and the reveal flags are Run state set *after*
generation.

### 5.6 Worked example: Extraction, Job `job_014`

`{"sec_pre": 2, "sec_post": 1, "objectives": 1, "side_max": 3}` → 2 side branches drawn of a
possible 3, each 2 nodes deep.

```
+--------------+     +--------------+     +----------------+     +--------------+
|    entry     |---->|  security-1  |---->|objective-vault |---->|  security-3  |
+--------------+     +------+-------+     +-------+--------+     +------+-------+
                            |                     |                     |
                            |                     |                     |
                            v                     v                     v
                     +--------------+     +----------------+     +--------------+
                     |    side-1    |     |     side-2     |     |     exit     |
                     +------+-------+     +-------+--------+     +--------------+
                            |                     |
                            v                     v
                     +--------------+     +----------------+
                     |   side-1a    |     |    side-2a     |
                     +--------------+     +----------------+

  adjacency: e->s1, s1->v, s1->x1, x1->x1a, v->s3, v->x2, x2->x2a, s3->exit
  depth:     e0  s1-1  v-2  s3-3  exit-4      sides branch at -1 and -2
  objective: 1 required (Paydata); 4 optional (2 caches, 2 chained caches)
  expected:  9 nodes, 10 enemies at Heat tier 0, Clock target 4-7
```

Two sides hanging off one security gate is legal (both are dead-ends, neither shortcuts the exit)
and is the common shape — the gate is where the Crew is already standing.

### 5.7 Worked example: Sabotage, Job `job_031`

`{"sec_pre": 1, "sec_post": 1, "objectives": 2}` → parallel fan, 1 side drawn.

```
                                              +----------------+
                                              |  objective-A   |
                                          |-->|  generator, 4  |--------
                                          |   +----------------+        |
                                          |                             |
                                          |                             |
+--------------+     +--------------+     |                             |  +--------------+         +--------------+
|    entry     |---->|  security-1  |-----+                             +->|  security-3  |-------->|     exit     |
+--------------+     +------+-------+     |                             |  |   (merge)    |         +--------------+
                            |             |                             |  +--------------+
                            |             |                             |
                            |             |                             |
                            |             |   +----------------+        |
                            |             |   |  objective-B   |        |
                            |             |-->|   server, 4    |--------
                            |                 +----------------+
                            v
                     +--------------+
                     |    side-1    |
                     |  ammo cache  |
                     +--------------+

  adjacency: e->s1, s1->a, s1->b, a->s3, b->s3, s3->exit, s1->x1
  depth:     e0  s1-1  a/b-2  s3-3  exit-4
  objective: 2 required, fanned from security-1 and merged at security-3.
             Partial credit pays round(base * cleared / 2).
  expected:  loud by construction: each target destroyed = +2 Clock (gunfire-equivalent)
```

The fan is the reason two Sabotage objectives are harder than one Extraction objective at
similar node counts: both must be reached from the same gate, so the Crew splits or backtracks.

### 5.8 Worked example: Courier, Job `job_052`

`{"sec_pre": 1, "sec_post": 0, "objectives": 1}` → 2 side branches, 3 side nodes, short path.

```
+----------------+     +----------------+     +----------------+     +----------------+
|     entry      |---->|   security-1   |---->| objective-drop |---->|      exit      |
|   (package)    |     |  checkpoint:   |     |   (scanner)    |     +----------------+
+----------------+     |   Optics-2,    |     +-------+--------+
                       |     Door-2     |             |
                       +-------+--------+             |
                               v                      v
                       +----------------+     +----------------+
                       |     side-1     |     |     side-2     |
                       |     medkit     |     |   contraband   |
                       +-------+--------+     +----------------+
                               v
                       +----------------+
                       |    side-1a     |
                       +----------------+

  adjacency: e->s1, s1->drop, s1->x1, x1->x1a, drop->exit, drop->x2
  depth:     e0  s1-1  drop-2  exit-3
  objective: 1 required (deliver the package), 3 optional (2 loot rooms, 1 chained).
             Clock target 1-4.
  expected:  smallest graph in v1; the checkpoint at security-1 is the whole Job
```

Shortest graph in the game and the one with the lowest payout — which is correct: it is the
cheapest Job to run *and* the only one that pays extra for not being loud
(`COURIER_DISCRETION_BONUS [P9]`).

---

## 6. Embedding

Turn the graph into a tile map. Rooms by node type, L-corridors for edges, union-find for
connectivity (ADR-0004: no libtcod `BSP`; we write it, and DEC §13 lists BSP as the intended
structure).

### 6.1 Room sizing by node type

Both map sizes are contract (DEC §9): a Site is **60×60**, camera-scrolled, and the Hub is **80×38**,
one screen minus the 7-row UI band. Sizes here are interior dimensions, walls excluded.

| Node / element | Interior size | Notes |
|---|---|---|
| `entry` | 10×8 | must fit four Runners plus their spawn ring |
| `exit` | 10×8 | same, so an extraction under fire is not a traffic jam |
| `security` | 8×6 | a guard post: desks, a camera corner, one corridor through |
| `objective` — Extraction vault | 14×10 | the largest room in v1; the Paydata sits at its far end |
| `objective` — Sabotage target | 10×8 | machine bay |
| `objective` — Protection hold | 12×10 | must hold a defence timer without becoming a firing pit |
| `objective` — Courier drop | 6×5 | small, deliberately: the drop is a doorway, not a destination |
| `side` | 6×5 | smallest room; a dead-end with loot in it |
| corridor | 1 cell wide | DEC §10 says corridors are 1-wide; no exceptions in v1 |
| corridor junction | 3×3 | carved wherever two or more corridors meet, so junctions are passable |

### 6.2 Algorithm

```
1. BSP-split the 60×60 grid until the leaf count equals the node count.
     split the longer axis; min leaf edge = 8 cells.
2. Order the leaves along the graph's depth ordering, then walk it in a
   serpentine so consecutive leaves are spatially adjacent.
     entry -> the first leaf;  exit -> the last leaf.
3. Place one room per leaf: pick the room size from §6.1 for that node type,
   then a random position inside the leaf with >= 1 cell of wall margin.
4. For each graph edge, carve an L-corridor between the two room centres:
     coin-flip H-then-V or V-then-H.  Corridors are 1 cell; overlapping
     corridors are absorbed, not widened.
5. Carve one doorway cell in each room wall on the side the corridor meets.
6. Populate (§7).
7. Verify (§6.3).
```

Step 2 is the reason a Site reads as a proposition rather than a scatter: nodes that are close in
the graph are close on the Site, so entry and vault are never adjacent and the exit is never the
first room you find.

### 6.3 Connectivity verification and retry

Union-find over room centres, merged across every corridor that actually connects two rooms.

```python
def verify(site, graph):
    uf = UnionFind(site.room_centres)
    for a, b in graph.edges:
        if corridor_connects(site, a, b):
            uf.union(a, b)

    # 1. every room in one component, rooted at entry
    assert all(uf.find(r) == uf.find(entry) for r in site.room_centres)

    # 2. entry -> exit is a real tile path (re-checked with A*, not just union-find)
    assert astar(site, entry_door, exit_door) is not None

    # 3. the vault is not next to the entrance (ADR-0011's named failure mode)
    assert manhattan(entry_centre, nearest_objective_centre) >= MIN_OBJECTIVE_DISTANCE [P13]

    # 4. every required objective is reachable, and the exit from each of them
    for o in graph.objectives:
        assert uf.find(o) == uf.find(entry)
        assert astar(site, o.door, exit_door) is not None
```

Union-find answers "one component"; A* answers "there is a walkable path" — a corridor can be
carved and still blocked by a later room's wall. Both run, because they fail for different bugs.

**Retry policy.** `MAX_EMBED_ATTEMPTS = 8 [P16]`.

- Attempt `i` uses `random.Random(derive(run_seed, f"gen.embed:{i}"))`, so every attempt is a different
  deterministic layout and the whole sequence is reproducible from the stored `run_seed`.
- A failed attempt is discarded entirely; it does not reuse rooms or corridors.
- After 8 failures, fall back to the **spine layout**: rooms placed left-to-right in graph depth
  order at fixed y, connected by straight horizontal corridors. It is guaranteed connected by
  construction and cannot fail verification. The fallback is logged with the seed and the failing
  assertion, and is a bug report, not a design outcome.
- A Site that fails verification is never handed to the player (procedural-gen's first pitfall).

---

## 7. Site contents by node type

Populated after embedding, from the `gen.place` stream. Placement order per node:
devices → enemies → loot, so the pass is deterministic for a given `run_seed`.

Device ratings and their effects are in DEC §7; enemy archetypes in DEC §8. `enemies.md` §7 is the
detailed authority for device ratings, mandatory cells and Heat-tier gates; this table is the
population checklist and must match it (DEC §7).

| Node | Devices (rating) | Enemies (Heat tier 0) | Loot |
|---|---|---|---|
| `entry` | Door/lock 2 (the way in), Lights 3, Commlink 3 (guard desk) | 0; 1 Corp Guard if Heat tier ≥ 2 | none |
| corridor | Lights 3 every `CORRIDOR_LIGHT_EVERY [P17]` cells; Door/lock 2–4 at 50% | 0; 1 patrolling Corp Guard if Heat tier ≥ 2 | none |
| `security` | Drone 4 (itself hackable, Heat tier ≥ 1), Optics 2 (camera), Gun 2 turret at 50%, Door/lock 2–4 (through-door), Lights 3, Commlink 3 (desk, 50%) | 1 Corp Guard + tier extras; 1 Security Drone at Heat tier ≥ 1 (§8.3); +1 Corp Mage if tier ≥ 2 | ammo or medkit cache at 25% |
| `objective` — Extraction vault | Door/lock 4 (vault door), Lights 3, **Paydata terminal** (Commlink 3), Optics 2 | 1 Corp Guard; 1 Security Drone at Heat tier ≥ 1 (§8.3); +1 Corp Mage if tier ≥ 2 | the Paydata |
| `objective` — Sabotage | target device 4 (machine-class), Optics 2, Door/lock 2–4, Lights 3 | 1–2 Corp Guard | ammo cache at 50% |
| `objective` — Protection | Gun 2 turret at 50%, Optics 2, Door/lock 2–4, Lights 3, Commlink 3 (the VIP's), Drone 4 (Heat tier ≥ 1), Cyberware 4 (if the VIP is augmented) | the held garrison: 2 + Heat tier, placed at embed (§4.2) | none |
| `objective` — Courier drop | Door/lock 2–4, Lights 3, Optics 2 (the scanner) | 1 Corp Guard | none |
| `side` | Door/lock 2–4, Optics 2 at 50%, Lights 3 | 1–2 Ganger at tier ≤ 1; 1 Corp Guard at tier ≥ 2 | weighted loot table, one draw |
| `exit` | Door/lock 2, Lights 3 | 0; 1 Corp Guard while Lockdown is active | none |

### 7.1 Placement rules

- **Devices.** Three mounts: `wall` (Lights, Optics — snapped to a room wall cell), `door` (on the
  room's doorway cell, or the corridor cell adjacent to it), `floor` (Drones, Commlinks,
  terminals — a free floor cell not on the room's single through-path). A `door` mount is why a
  locked room is a real obstacle and not decoration.
- **The Decker guarantee.** Every node on the main path carries at least one hackable device, and
  the vault door and both Sabotage targets are always rating 4. If a graph layout would leave a
  main-path node with no device, the population pass adds a Lights 3 rather than shipping an empty
  node. The Decker's kit is a device layer (ADR-0008); a node with nothing to hack is a node where
  one of four Runners has no class.
- **Enemies.** Placed on floor cells at least `ENEMY_SPAWN_MARGIN [P20]` = 4 cells from the room's
  corridor mouth, so the Crew is never shot at the instant it enters a room. Patrolling archetypes
  (Corp Guard, Security Drone) get 2 waypoints inside the room and `home_pos` set on the
  Blackboard; static archetypes (Corp Mage) hold the far corner. Hellhounds are released only at
  Heat tier ≥ 3.
- **Loot.** Only `side` nodes and the vault hold anything worth taking. `side` loot is one draw
  from a weighted table (weights: nuyen cache 50, data cache 30, consumable 20). Values are set
  against the DEC §9 gear price scale — a 2,000 ¥ side cache `[P8]` is half an assault rifle — so a
  Site's optional content is worth roughly a third of a Job's balance and never more. Side caches are
  how a cautious crew recovers payout it lost by leaving an objective incomplete.

---

## 8. The Security Clock and Heat

### 8.1 Security Clock

Ten segments, always visible (DEC §9, ADR-0005), always with a log line naming what ticked it.

| Threshold | State | Mechanical effect |
|---|---|---|
| 0–3 | Quiet | nothing |
| 4 | **Alert** | patrol Behavior Trees set `alert_level = 1`; enemy groups move toward the Crew's `last_known_pos` via a Dijkstra flow map (DEC §13) |
| 7 | **Lockdown** | every Door device locks (raise its rating to 4 until unlocked), guards `+2` armour (DEC §9) |
| 10 | **Converge** | Run ends; forced Extraction |

`alert_level` is `0 Calm / 1 Alert / 2 Lockdown` (DEC §8); an earlier draft of this table set Alert to 2, which collided with Lockdown and made the two tiers indistinguishable.

Tick events, from DEC §9 and DEC §3:

| Event | Segments |
|---|---|
| Gunfire | +2 |
| Guard killed | +2 |
| Body found | +3 |
| Failed hack | +1 |
| Loud spell (Force ≥ 4) | +2 |
| Alarm tripped | +2 |
| Lock forced | +1 |
| Critical Glitch | +1 |
| Silent takedown, successful hack | 0 |

Per-Job Clock start is `CLOCK_START[type] [P18]` — 0 for all four v1 types. It is a parameter,
not a constant, because ADR-0005 requires the Clock to be tunable per Job type; the tuning lever
is expected to be the *thresholds* or the *Clock budget* (§4 table), not the start.

### 8.2 Heat

Heat is a persistent integer, world-side (§10). It rises from loud and failed Runs and makes every
subsequent Site harder. Two sources in v1:

| Source | Heat |
|---|---|
| Forced Extraction (Clock 10) | +2 (DEC §9) |
| Extracted with Clock ≥ 7 (Lockdown reached) | +1 `[P19]` |

Nothing else raises Heat: no per-kill Heat, no per-glitch Heat. The Clock already charges for
loudness inside a Run; charging Heat per kill too would double-count it and make a killed guard
cost the Crew three times.

### 8.3 Heat's effect on difficulty

One tier table, applied at Site population time. Tier is a step function of Heat, which keeps the
numbers auditable and makes the ceiling explicit.

| Tier | Heat | Guards per security node | Skill ratings | Archetype roster | Devices |
|---|---|---|---|---|---|
| 0 | 0–2 | 1 | 3 | Corp Guard, Ganger | baseline |
| 1 | 3–5 | 1 (+1 at 50%) | 3 | + Security Drone | +1 Optics per security node |
| 2 | 6–8 | 2 | 4 | + Corp Mage | +1 Gun turret per security node |
| 3 | 9–11 | 2 (+1 at 50%) | 5 | + Hellhound | locks on the main path are rating 4 |
| 4 | 12+ | 3 (frozen) | 5 (frozen) | frozen | frozen |

**Guards per security node are placed as this table states: generation puts one Corp Guard at tier 0, not two.** `enemies.md` §2's "2 Corp Guards is a fair fight" is a statement about how hard a gate feels once the tier table has stacked guards and archetypes, not a placement rule; the per-node counts here and in §7 win.

Enemy skill ratings are clamped at 5, under the DEC §2 rating cap of 6, so a Runner with a maxed
skill is never outclassed outright.

**Difficulty floor** = tier 0: the baseline roster, one guard per gate, skill 3. A Run at Heat 0
is always winnable by a starting Crew, which is what makes the floor a floor.

**Difficulty ceiling** = tier 4, hard-frozen at Heat 12: the last row of the table is the last row
of the table. Heat above 12 changes nothing about numbers — it is tracked, it is displayed, and
it makes the Fixer's dialogue colder, but the Run stops getting harder.

That floor and ceiling pair is the ADR-0012 requirement: a crew on a losing streak has a
guaranteed-winnable tier to fall back to, and the spiral has a top that terminates it.

### 8.4 Heat decay

- Successful Job: `Heat -1` (DEC §9).
- Successful Job while `Heat >= 8`: `Heat -2` — the recovery valve (DEC §14, resolved item 4). A crew
  that got into the spiral is not condemned to it; the way down is to succeed once at the top of it.
- Forced Extraction never decays Heat.
- Floor is 0. Nothing goes below it.
- `HEAT_MAX = 20` (DEC §14, resolved item 4). This is a code clamp, not a world rule: it exists so a
  pathological sequence of forced extractions cannot overflow a saved integer or produce a nonsense
  display. It is well above tier 4, so hitting it has no mechanical effect.

The decay rule, the `-2` valve and the ceiling are all recorded in the contract (DEC §14, resolved
item 4). The one alternative that is **not** adopted is buying Heat down at the Hub: **not in v1.**

---

## 9. Pacing targets

Numbers to design against, not hard rules. Tunable by playtest.

| Target | v1 value | Derivation |
|---|---|---|
| Rounds per Run | 6–10 | one quiet approach, one loud objective, one quiet exit, plus a delay |
| Passes per Runner per round | 1, sometimes a short second | starting `Initiative Score 8–16` (DEC §5): a Pass ends at 1 Energy and the Score drops 10, so a *substantial* second Pass needs 15+ and a third needs 25 — most Runners get one full Pass and a short second one |
| Wall-clock per Run | `RUN_MINUTES_MEDIAN [P26] = 25`, band 15–40 | ~8 rounds × ~3 min per round at four Runners plus opposition |
| Clock at Extraction | 4–7 target, per type in §4 | a Run that extracts at 9 had one plan and no margin |
| Hub time per Job | 5–10 min real, 4–8 Hub days | 3 Legwork days + rest days |
| XP per Run | `XP_PER_RUN_ESTIMATE [P25] = 60–100` crew-wide, ~15–25 per Runner | 1 per successful test, 5 per failed test, failure paid once per obstacle (ADR-0006) |
| Jobs per Advance | ~1 | Advance cost is `new rating × 3` for a skill and `new rating × 5` for an attribute (DEC §14, resolved item 8): a skill 3→4 costs 12 XP, an attribute 3→4 costs 20, against ~15–25 XP per Runner per Run |
| Jobs per meaningful Advance | 1–2 | a "meaningful" Advance changes a class's core loop; raising the Decker's Cybercombat 3→5 is `12 + 15 = 27` XP, or the Adept's Agility past a defence breakpoint |
| Jobs in a v1 campaign | `CAMPAIGN_JOBS_V1 [P27] = 24` | 24 × ~35 min ≈ 13–14 hours; ~360–600 XP per Runner at `[P25]`, enough to reach Heat tier 3–4 and, at the new Advance price, to raise 8–13 skills from 3 to 6 (45 XP each) before attributes take their share |

**`ADVANCE_COST = 10 × target rating` is superseded** (DEC §14, resolved item 8) and nothing should
be re-derived from it. The contract price is `new rating × 3` for a skill and `new rating × 5` for an
attribute, so a skill Advance to rating 4 costs **12** XP, not the 40 the old formula gave. The
`XP per Run` / `Jobs per Advance` / campaign ratios above were recomputed from the new price.
Because Advance is now cheap relative to Run income, the binding constraint on growth is `[P25]` XP
income and the rating-6 cap (DEC §2), not Advance cost — so the campaign can approach a maxed skill
sheet inside 24 Jobs. That is the pacing risk in this table worth watching.

The intended difficulty arc, per level-design's rising sawtooth: Jobs 1–3 are tier 0 and teach the
Clock; Jobs 4–10 climb to tier 1–2 as the Crew spends XP; Jobs 11–18 should be spent at tier 2–3;
Jobs 19–24 are the top of the spiral, where the Crew should have either Heat under control through
clean runs or be deliberately farming tier 4 for the payout multipliers.

---

## 10. Persistence

Two state graphs (ADR-0012), one save file, versioned (DEC §13: schema-versioned JSON with a migration
function per version).

### 10.1 Persisted

| Group | Fields |
|---|---|
| Crew sheets | per Runner: class, attributes 1–6 (Adept excepted), skills with ratings, Edge rating, Totem passive (Shaman) |
| Growth | per Runner: XP banked, Perks with their source obstacle id (ADR-0006 pays each obstacle once), Advance history |
| Inventory | loadout per Runner, shared stash with counts, nuyen |
| World | Heat, Fixer reputation, faction reputations, world flags |
| Hub | `hub_day`, current Job offers, `job_count`, `run_counter` per Job id |
| Job | active Job id, type, stored `run_seed`, Legwork actions spent, `clock_credit` |
| Schema | `schema_version` |

### 10.2 Reset per Run

Site layout, enemy placement, Security Clock (DEC §9), plus: Edge points, Qi pool, Drain taken,
temporary spell effects and Wards, FOV and Memory, every Blackboard, and the message log.

### 10.3 Carried, but only because it is Hub state

Condition Monitors. **Filled boxes persist across Jobs as Hub state** and heal only by resting or
paying (§1.2). Accepted, closing this document's former `[P23]`: crew sheets carry across Jobs
(DEC §9) and the monitor boxes are part of the sheet. It is what gives the clinic, the rest day, and
the day budget any meaning at all; the discarded alternative — a full heal between Jobs — would
leave the clinic selling consumables and the Hub day counter with no cost.

At Run start the Crew carries whatever their monitors show. `Downed` (DEC §4) is a per-Run state and
clears at Extraction.

### 10.4 Save schema

```json
{
  "schema_version": 1,
  "saved_at": "2026-01-01T00:00:00Z",
  "rng_note": "random.Random/CPython",
  "campaign": {
    "job_count": 7,
    "hub_day": 12,
    "advance_log": [{"runner": "decker", "kind": "skill",
                     "id": "cybercombat", "from": 3, "to": 4, "day": 11}]
  },
  "crew": {
    "nuyen": 38500,
    "runners": [
      {
        "id": "adept", "class": "physical_adept",
        "attributes": {"body": 6, "agility": 7, "reaction": 6, "strength": 7,
                       "willpower": 4, "logic": 3, "intuition": 4, "charisma": 3,
                       "edge": 3},
        "skills": {"firearms": 4, "close_combat": 5, "athletics": 5, "stealth": 4},
        "xp": 14,
        "perks": [{"id": "perk_sure_grip", "source": "lock:job_014:node_sec_2"}],
        "condition": {"stun": 0, "physical": 3},
        "loadout": ["katana", "armoured_jacket"],
        "totem": null
      }
    ],
    "stash": [{"item": "medkit", "count": 2}]
  },
  "world": {
    "heat": 5,
    "rep": {"fixer": 3, "factions": {"corp_arasaka": -1, "street_kobun": 2}},
    "flags": {"met_fixer": true, "first_job_done": true}
  },
  "job": {
    "active": {
      "id": "job_015", "type": "sabotage",
      "run_counter": 1,
      "run_seed": 8675309698191342750,
      "legwork": {"scout": 1, "buy_gear": 0, "favour": 0},
      "clock_credit": 2
    },
    "offers": [
      {"id": "job_015", "type": "sabotage", "payout_base": 13800},
      {"id": "job_016", "type": "courier",  "payout_base": 10800},
      {"id": "job_017", "type": "protection","payout_base": 13200}
    ]
  }
}
```

Attribute and skill keys are `lower_snake` slugs of the DECISIONS names — the same spelling
conditions use (`attr.logic`, `skill.negotiation`) — and the values are the Adept block of
`classes.md` §1.1/§1.2. Item ids use the British spelling throughout (`armoured_jacket`,
`armoured_vest`), matching DECISIONS §4/§9's "Armoured" catalogue.

Deliberately absent: derived stats (recompute from base + modifiers), any generated Site
(regenerate from the stored `run_seed`), condition monitor *maximums* (derived, DEC §4), and
anything owned by the renderer.

Versioning rules follow the standard chain: an integer `schema_version`, migrations `vN -> vN+1` as
pure functions, refuse to load a save newer than the build, keep every old migration forever.

### 10.5 Save points

Autosave at the safehouse (A) and immediately after payout (F). There is no manual save and no
mid-Run save in v1. That is the anti-save-scum rule that makes §8.2's Heat meaningful without
permadeath: a Run that went wrong cannot be reloaded into a Run that went right.

---

## 11. Open questions

Item 1 is restated from `DECISIONS.md` §14 because this document cannot be implemented without
choosing. The rest are parameters this document needed that are not in `DECISIONS.md`; each carries
its recommendation. Per the project rule, none of these should be treated as settled until they land
in `DECISIONS.md`.

The parameters formerly proposed here as `[P15]`, `[P21]`, `[P22]`, `[P23]` and `[P24]` have landed
in the contract and their tags are retired: **Site size** 60×60 camera-scrolled (DEC §9), the **−2
Heat valve above Heat 8** and **`HEAT_MAX` 20** (DEC §14, resolved item 4), **Advance cost** (DEC
§14, resolved item 8), and **Condition Monitors persisting as Hub state** (§10.3). Each is folded
into the body above and none of them is open any more.

### 11.1 Named in DECISIONS.md §14

1. **Hub movement (DEC §14 Q1).** Turn-based steps with a world clock (recommended) versus real-time
   exploration. **This document assumes turn-based:** every Hub mechanic above is per-day, and
   real-time exploration would leave the day counter with no anchor. `[P1] HUB_TICKS_PER_DAY = 240`.

### 11.2 New parameters proposed here

| Tag | Parameter | Proposed | Why it is not in DECISIONS.md |
|---|---|---|---|
| `[P1]` | `HUB_TICKS_PER_DAY` | 240 | "world clock" (DEC §9) is named but not measured |
| `[P2]` | `HUB_RECOVER_BOXES_PER_DAY` | 2, Stun first then Physical | recovery rate at the Hub is unspecified |
| `[P3]` | `CLINIC_COST_PER_BOX` / `CLINIC_REVIVE_DOWNED` | 250 ¥ / 1,500 ¥ | clinic prices |
| `[P4]` | `JOB_OFFERS` / `JOB_OFFER_ROTATION_DAYS` | 3 / 3 | DEC §9 says the Fixer posts Jobs, not how many or how long |
| `[P5]` | `MEDKIT_USES` / `TRAUMA_PATCH_COST` | 3 uses / 750 ¥ | DEC §9 prices weapons, armour, ammunition and the medkit, but not the trauma patch or its use count |
| `[P6]` | `FAVOUR_REP_COST` / `FAVOUR_CLOCK_CREDIT` | 1 rep / 2 segments | DEC §9 names the Favour's two outcomes, not its numbers |
| `[P7]` | `TYPE_MULT` | extraction 1.00, sabotage 1.15, protection 1.10, courier 0.90 | DEC §9 gives one base payout for one Job type |
| `[P8]` | `SIDE_OBJECTIVE_PAYOUT` | 2,000 ¥ | DEC §9 does not price side objectives |
| `[P9]` | `PROTECTION_ROUNDS` / `COURIER_DISCRETION_BONUS` | 5 rounds / 3,000 ¥ | Job-type objective structure is not specified |
| `[P10]` | `JOB_GRAPH` counts (`sec_pre`, `sec_post`, `objectives`, `side_max`, `min_len`) | see §5.3 | DEC §10 names the node types, not how many of each |
| `[P11]` | `SIDE_CHAIN_MAX` | 2 | graph shape parameters |
| `[P12]` | `MAX_IN_DEGREE` | 2 | graph shape parameters |
| `[P13]` | `MIN_OBJECTIVE_DISTANCE` | 20 cells | ADR-0011 names "vault adjacent to the entrance" but sets no distance |
| `[P14]` | room sizes by node type | see §6.1 | DEC §10 says "vault large, corridor 1-wide" without numbers |
| `[P16]` | `MAX_EMBED_ATTEMPTS` | 8, then spine fallback | DEC §10 requires verification but not a retry budget |
| `[P17]` | `CORRIDOR_LIGHT_EVERY` | 15 cells | device density |
| `[P18]` | `CLOCK_START[type]` | 0 for all four | ADR-0005 requires Clock tunability per Job type |
| `[P19]` | Heat for extracting at Clock ≥ 7 | +1 | only forced Extraction's +2 is in DEC §9; loud-but-successful Runs are not priced |
| `[P20]` | `ENEMY_SPAWN_MARGIN` | 4 cells | placement fairness |
| `[P25]` | `XP_PER_RUN_ESTIMATE` | 60–100 crew-wide per Run | pacing estimate |
| `[P26]` | `RUN_MINUTES_MEDIAN` | 25 | pacing target |
| `[P27]` | `CAMPAIGN_JOBS_V1` | 24 | campaign length |
| `[P28]` | shop stock size / `side`-node loot weights | 6 items per Job / nuyen 50 · data 30 · consumable 20 | content density; DEC §9 gives an economy, not an item list |

### 11.3 Deliberately not opened

- **Heat purchased down at the Hub** (the alternative to DEC §14's resolved decay rule). Decay stays
  tied to success, so the recovery valve is *playing better*, not *spending money*. Revisit only if
  §8.4's tier bonus proves insufficient.
- **Mid-Run saves.** No, per §10.5. A mid-Run save is a save-scum button against the Clock.
- **A second Hub district.** No. The Hub is authored precisely so it can stay small (DEC §9).

---

## 12. Sources

Borrowed patterns, by file:

- `.agents/skills/procedural-gen/references/dungeon-generation.md` — BSP partition then
  L-corridor carving, and the "validate before shipping; cap attempts and accept fewer" rule that
  §6.3's retry policy and spine fallback come from.
- `.agents/skills/procedural-gen/SKILL.md` — one seeded RNG threaded through generation, and the
  "generate into a plain data grid first, decoupled from rendering" split between §5 and §6.
- `.agents/skills/roguelike/references/generation-fov-loot.md` — the connectivity pass as a
  first-class step (§6.3), weighted loot tables for `side` nodes (§7.1), and the run-state versus
  profile-state split that §10.1/§10.2 follows.
- `.agents/skills/rpg/references/stats-combat-quests.md` — the `available → active → complete →
  turned-in` objective state model behind §2's Job lifecycle, and "store authoritative state,
  recompute derived" behind §10.4.
- `.agents/skills/save-systems/references/versioning-and-migration.md` — integer `version`,
  pure-function migration chain, refuse-newer-on-load, and the load-time validation checklist
  used in §10.4/§10.5.
- `.agents/skills/level-design/references/pacing-and-flow.md` — the rising-sawtooth difficulty
  curve and "rest before climax" shaping §9's arc, and critical-path/golden-path/branch
  language behind the main-path versus side-branch split in §5.2.

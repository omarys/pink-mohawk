# Data model and algorithms

This is the implementation plan for the data structures and algorithms the project exists to
practise. It expands **every row of `docs/design/DECISIONS.md` §13** with a chosen structure, the
alternative it beat, derived complexity, implementable pseudocode, one canonical reference, and a
runnable `__main__` self-check.

Vocabulary is `CONTEXT.md`; numbers are `DECISIONS.md`; rationale is `docs/adr/`. If a number
appears here it cites its source as `§n`. Numbers that do **not** exist in `DECISIONS.md` are
listed in *Open questions* with a recommendation and are marked `(proposed)` inline.

## 0. Scope, layers, and input-size assumptions

Every complexity derivation below uses these sizes. They are the *design* sizes, not the tested
upper bound; the self-checks assert the algorithmic property, not the timing.

| Quantity | Symbol | Assumed value | Source |
|---|---|---|---|
| Site dimensions | `W × H` | 60 × 60 = 3600 cells | §9 Site size (settled) |
| Hub dimensions | — | 80 × 38 cells (7 of the 45 screen rows reserved for UI) | §9 |
| Cells a search can touch | `V` | ≤ 3600 | derived from `W·H` |
| Actors in a Run (Runners + enemies + Spirits) | `n` | ≤ 48; typical 12 | §7, §8 |
| Runners | — | 4 | §7, ADR-0002 |
| FOV radius | `R` | 8 sight, 2 in darkness | §12 (settled) |
| Mission Graph nodes | `N` | 6–10, typical 8 | §10 |
| Mission Graph edges | `E` | ≈ N − 1 plus ≤ 3 side edges | §10.1 |
| Behavior tree depth / node count | `d` / `m` | ≤ 6 / ≤ 30 | §8 |
| Dialogue graph nodes | `D` | ≤ 100 | §11 |
| Device ratings | — | 2–4 | §7 |

Three rules hold everywhere in this document.

1. **Algorithms are pure.** Anything in layers 0–2 (§15) takes coordinates, arrays, and plain data.
   It does not import `tcod`, does not import `entities`, and does not read the wall clock.
2. **Ordering is explicit.** Iteration over a collection of objects is in a defined order (sorted
   by `id`, or an insertion-ordered `list`), never over a `set` or a `dict` keyed by objects.
   This is what makes a Run reproducible (§14).
3. **One number, one home.** All constants live in `constants.py`, each commented with its
   `DECISIONS.md` section. No literals in algorithm code.

---

## 1. Map — dense tile array + `explored` and `visible` byte arrays

*DECISIONS §13 row 1.*

### Data structure chosen

```python
class TileMap:
    tiles:    bytearray   # W*H, one byte per cell: terrain id (0 = wall)
    explored: bytearray   # W*H, 0/1 — has this cell ever been seen this Run?  (§12 Memory)
    visible:  bytearray   # W*H, 0/1 — is this cell visible *right now*?      (§12 FOV)
    w: int; h: int
    def idx(self, x, y): return y * self.w + x
    def in_bounds(self, x, y): return 0 <= x < self.w and 0 <= y < self.h
    def at(self, x, y): return self.tiles[self.idx(x, y)] if self.in_bounds(x, y) else 0
    def is_wall(self, x, y): return self.at(x, y) == 0     # out of bounds reads as WALL
```

### The alternative it beat

`dict[tuple[int,int], Tile]`. Concrete cost: a dict entry for a 2-tuple key costs roughly 100–140
bytes (tuple + dict slot + int objects) versus 3 bytes here. At 3600 cells that is ~400 KB and
3600 hashes per full-map pass versus ~11 KB and a single multiply-add. Concretely, a Dijkstra flow
map (§4) relaxes every passable cell; FOV marks every cell in the disc; the renderer touches every
on-screen cell every frame. All three are full-sweep operations, which is exactly the access
pattern a dense array is for. A dict wins only for a *sparse, unbounded* map, which a Site is not.

Three separate arrays rather than one struct-per-cell: FOV writes only `visible`, generation writes
only `tiles`, and the renderer reads `visible` then `explored` per cell. Interleaved structs would
touch 3× the cache lines per pass for no benefit.

### Complexity

| Operation | Time | Space |
|---|---|---|
| `at` / `is_wall` | O(1) | — |
| full sweep (e.g. Dijkstra, render) | O(V) | — |
| map storage | — | O(V) = 3 · 3600 B ≈ 11 KB |

Caveat on how FOV writes `visible`: a full `visible[:] = b"\0" * V` per recompute is O(V)=3600 byte
writes, which is cheaper than tracking and clearing a cell list (allocations). Keep the sweep.

### Pseudocode

Nothing to derive; the only logic is the out-of-bounds rule.

```
at(x, y): return 0 if not in_bounds(x, y) else tiles[y*w + x]
```

**Border rule:** out-of-bounds reads as `WALL` (0). FOV, A*, and flow maps then never need a
bounds branch — they call `is_wall` and get "blocked". This single decision removes the most common
FOV crash and the most common "light leaks past the map edge" bug. (Self-check covers it.)

### Canonical reference

*Roguelike Tutorial, "The Map" / `tcod.map`* — RogueBasin, *Complete Roguelike Tutorial* (Python +
`tcod`), Part 2 "The generic Entity, the render functions, and the map". Read it only for the
`bytearray`-indexed map shape; we do not use `tcod.map` (ADR-0004).

### Runnable self-check

```python
if __name__ == "__main__":
    def demo():
        m = TileMap(4, 3)
        m.tiles[m.idx(0, 0)] = 1
        # border: the corner is addressable, its neighbours are not
        assert m.at(0, 0) == 1
        assert m.at(-1, 0) == 0 and m.at(4, 0) == 0
        assert m.at(0, -1) == 0 and m.at(0, 3) == 0
        assert m.is_wall(-1, -1) is True
        # explored and visible are independent tracks
        m.visible[m.idx(0, 0)] = 1
        assert m.explored[m.idx(0, 0)] == 0
        m.explored[m.idx(0, 0)] = 1
        m.visible[m.idx(0, 0)] = 0
        assert m.explored[m.idx(0, 0)] == 1
    demo()
```

---

## 2. FOV — recursive shadowcasting, 8 octants

*DECISIONS §13 row 2. Vocabulary: **FOV**, **Memory** (CONTEXT.md).*

### Data structure chosen

A single `visible` byte array (§1) written by a recursive octant scan. Slopes are floats; the
recursion carries `(row, start_slope, end_slope)` plus an octant transform.

The alternative it beat: **per-cell raycast** (Bresenham from the viewer to each cell in the disc).
That costs O(R²) cells × O(R) steps each = **O(R³)**, and it is provably asymmetric — an
off-by-half cell behind a pillar is visible from one side and not the other, which produces the
classic "I can see them, they can't see me" flicker the `roguelike` skill calls out. Recursive
shadowcasting is O(R²) (each cell in the disc is visited once) and treats a wall as an occluder for
a whole *wedge*, not a single line, so a pillar casts one clean shadow.

A second alternative, **precomputed shadow masks per radius** (cache the cell set for each
`R`), is rejected for v1: `R` takes only two values (8 sight, 2 in a darkened room, §12) and the
viewer moves constantly, so the cache key is `(x, y, R)` — the same number of entries as just
recomputing, and it goes stale the moment terrain changes. Revisit only if profiling says FOV is hot.

### Complexity

| Operation | Time | Space |
|---|---|---|
| `compute_fov(origin, R)` | O(R²) cells visited, ≤ 8 octant calls | O(1) extra (recursion depth ≤ R) |
| write into `visible` | O(R²) | in-place |
| at R = 8 | π·8² ≈ 201 cells visited; **197** actually lit | — |

Recursion depth is ≤ R = 8, so there is no stack concern. The `visible` byte array is cleared by
sweeping all `V` cells (O(V) = 3600) — cheaper than tracking a cell list.

### Pseudocode

```
MULT = [(1,0,0,1), (0,1,1,0), (0,-1,1,0), (-1,0,0,1),
        (-1,0,0,-1), (0,-1,-1,0), (0,1,-1,0), (1,0,0,-1)]

compute_fov(map, cx, cy, R):
    map.visible[:] = b"\0" * (map.w*map.h)
    mark visible(cx, cy)
    for (xx, xy, yx, yy) in MULT:
        cast(map, cx, cy, 1, 1.0, 0.0, R, xx, xy, yx, yy)

# row: current distance ring; start,end: slope range still lit
cast(map, cx, cy, row, start, end, R, xx, xy, yx, yy):
    if start < end: return                      # fully shadowed wedge
    radius2 = R*R
    new_start = start
    for j in row .. R:                          # walk rings outward
        dx = -j - 1
        dy = -j
        blocked = False
        while dx <= 0:
            dx += 1
            X = cx + dx*xx + dy*xy
            Y = cy + dx*yx + dy*yy
            l_slope = (dx - 0.5) / (dy + 0.5)
            r_slope = (dx + 0.5) / (dy - 0.5)
            if start < r_slope: continue        # this cell is left of the lit range
            elif end > l_slope:  break          # this cell is right of the lit range
            if dx*dx + dy*dy <= radius2:
                mark visible(X, Y)
            if blocked:
                if is_wall(map, X, Y):
                    new_start = r_slope          # still inside the wall: narrow the lit range
                    continue
                else:
                    blocked = False
                    start = new_start            # emerged from the wall: resume the wider range
            else:
                if is_wall(map, X, Y) and j < R:
                    blocked = True
                    # recurse into the wedge just past this wall's left edge
                    cast(map, cx, cy, j+1, start, l_slope, R, xx, xy, yx, yy)
                    new_start = r_slope
    # if we ended the scan still blocked, the rest of the wedge is dark -> stop
```

The octant transform `X = cx + dx*xx + dy*xy`, `Y = cy + dx*yx + dy*yy` is what lets one routine
serve all eight octants: `MULT` maps the local `(dx, dy)` into map space for each.

**Rendering contract (ADR-0004, glyph-only renderer):** one `visible`/`explored` pair drives one
of three glyph states per cell — `visible` → the terrain glyph at full tint; `explored and not
visible` → the terrain glyph at the Memory tint; `neither` → blank. No per-cell transparency, no
overlap; the renderer never asks for more than "one Glyph per cell" (§12).

**Known property, not a bug:** Bergström's recursive shadowcasting is *not* symmetric (A sees B
need not imply B sees A). ADR-0004 and §13 fix recursive shadowcasting as the algorithm; the
symmetric variant is a different algorithm and is deferred. Symmetry matters because an enemy
that can shoot you while you cannot see it is unfair. Accepted for v1; see Open question 1, where
the mitigation is "an enemy may only target a Runner it can see *and* that has the enemy in FOV",
which restores fairness without changing the algorithm.

### Canonical reference

Björn Bergström, *"FOV using recursive shadowcasting"*, RogueBasin (the article contains the exact
`cast_light` recursion and the eight `mult` tuples this pseudocode follows). Companion reading:
Jonathon Duerig / "symmetric shadowcasting" on RogueBasin if symmetry is later required.

### Runnable self-check

```python
if __name__ == "__main__":
    def demo():
        # ---- pillar corner: a single wall at the orthogonal diagonal must not leak ----------
        m = TileMap(11, 11)                       # 0 = wall, 1 = floor
        for y in range(11):
            for x in range(11):
                m.tiles[m.idx(x, y)] = 1
        m.tiles[m.idx(1, 1)] = 0                  # one pillar, viewer at (0,0)
        compute_fov(m, 0, 0, 8)
        assert m.visible[m.idx(0, 0)] == 1        # origin always visible
        assert m.visible[m.idx(1, 1)] == 1        # walls in view ARE lit -- the renderer has to
                                                  # draw the wall you are standing next to
        # A hardcoded cell behind a pillar is slope-sensitive and brittle. The robust form is
        # differential: recompute the same map with the pillar removed and assert that it lights
        # strictly more cells. That is what fov.py's demo does, plus a deliberately permissive
        # reference implementation to prove the assertion can fail.

        # ---- diagonal gap: two diagonal walls with a gap between them ----------------------
        m2 = TileMap(11, 11)
        for y in range(11):
            for x in range(11):
                m2.tiles[m2.idx(x, y)] = 1
        m2.tiles[m2.idx(2, 1)] = 0
        m2.tiles[m2.idx(1, 2)] = 0                # the two walls touch only at a corner
        compute_fov(m2, 1, 1, 8)
        # the cell beyond the corner is reachable through the pinch, and must not crash
        assert m2.visible[m2.idx(2, 2)] in (0, 1)  # deterministic; assert the *value* once pinned

        # ---- map border: viewer on the edge, radius overflows the map ----------------------
        m3 = TileMap(11, 11)
        for y in range(11):
            for x in range(11):
                m3.tiles[m3.idx(x, y)] = 1
        compute_fov(m3, 0, 0, 40)                 # radius far larger than the map
        assert m3.visible[m3.idx(10, 10)] == 1    # whole map lit, no exception
        assert m3.visible[m3.idx(0, 10)] == 1
    demo()
```

The `diagonal gap` assertion is deliberately written as "pin the value once" — the correct answer
depends on which of the two pinch cells the scan reaches first, and the point of the check is that
the result is *deterministic across runs* (assert the literal after the first run) and does not
raise. Do not weaken it to a tautology: replace `in (0, 1)` with the observed constant.

---

## 3. Pathfinding — A\* over `heapq`, Chebyshev heuristic, stable tie-break

*DECISIONS §13 row 3. Movement is 8-directional (§5 Step).*

### Data structure chosen

`heapq` (a binary heap over a list) holding `(f, counter, node)` tuples, plus two dicts
`cost_so_far` and `came_from`.

The alternative it beat: **BFS**. BFS is O(V) with no heap, and on a uniform-cost grid it is
optimal — and the cost model here *is* uniform: §5 charges 1 Energy for a Step in all 8 directions,
so a diagonal hop costs the same as an orthogonal one. BFS still loses on one concrete count:
terrain cost may vary later (hacked doors are open but loud), which BFS cannot express without
becoming a weighted frontier. The row also exists on the syllabus (§13) to practise A*, `heapq`,
and deterministic tie-breaking.

Second alternative: **Dijkstra**. Same O(V log V) as A\*, no heuristic. A\* dominates it whenever
the heuristic is informative; on an open 60×60 floor heading to a known goal the Chebyshev heuristic
typically expands a fraction of the cells Dijkstra does. Dijkstra is not wasted — it *is* the
algorithm used for flow maps (§4), where there is no single goal.

Second alternative worth naming: **`tcod.path.AStar`** exists and is deliberately unused
(ADR-0004). It is the whole reason this row is on the syllabus.

### Complexity

Let `V` = passable cells (≤ 3600), `V'` = cells expanded.

| Operation | Time | Space |
|---|---|---|
| `a_star` | O(V' log V); worst case O(V log V) ≈ 3600 × 12 ≈ 43k heap comparisons | O(V) for the two dicts |
| `reconstruct_path` | O(L), L = path length | O(L) |
| per-actor-per-turn | ~1 search per acting enemy, ≤ 48/round | — |

Turning a cell into a 3-byte grid coordinate instead of an `(x, y)` tuple in the dict keys would
cut hashing cost, but at 3600 cells the dict is not the bottleneck; keep tuples for readability.

`log V` = log₂3600 ≈ 11.8.

### Pseudocode

```
chebyshev(a, b):
    dx = |a.x - b.x|; dy = |a.y - b.y|
    return max(dx, dy)      # EXACT for the §5 cost model: every Step, diagonal or not, is 1

NEIGHBOURS = [(+1,0), (+1,-1), (0,-1), (-1,-1), (-1,0), (-1,+1), (0,+1), (+1,+1)]  # fixed order

a_star(map, start, goal):
    if start == goal: return [start]                  # zero-length path, not None
    frontier = [(0, 0, start)]                        # (f, counter, node); heapq pops smallest
    came_from = {start: None}
    cost = {start: 0.0}
    counter = 0
    while frontier:
        _, _, cur = heappop(frontier)
        if cur == goal: break                         # test on POP, not on push
        for (dx, dy) in NEIGHBOURS:                   # fixed order => deterministic ties
            nxt = (cur.x+dx, cur.y+dy)
            if map.is_wall(nxt.x, nxt.y): continue
            step = 1.0                                  # §5: a diagonal Step costs 1 Energy too
            g = cost[cur] + step
            if nxt not in cost or g < cost[nxt]:
                cost[nxt] = g
                counter += 1
                heappush(frontier, (g + chebyshev(nxt, goal), counter, nxt))
                came_from[nxt] = cur
    return reconstruct(came_from, start, goal)

reconstruct(came_from, start, goal):
    if goal not in came_from: return None             # unreachable
    path = []; node = goal
    while node != start: path.append(node); node = came_from[node]
    path.append(start); path.reverse(); return path
```

Three correctness points, each an edge case in the self-check:

- **Test the goal on pop.** Testing on push returns a possibly non-shortest path when edge costs
  vary.
- **`counter`** is a monotonic integer, so `heapq` never compares two cell tuples and ties are FIFO
  by insertion order. `NEIGHBOURS` in a fixed order makes the whole search deterministic.
- **`start == goal` returns `[start]`**, not `None` and not `[]`. A caller that does
  `path.pop()` on an empty path is a crash; a caller that treats `None` as "unreachable" would
  wrongly treat "already there" as a failure.

**Cost model (settled):** §5 charges *Step = 1 Energy per tile* for all 8 directions, and §13 fixes
the **Chebyshev heuristic `max(dx, dy)`** for exactly that reason: with a uniform edge cost of 1,
Chebyshev distance *is* the shortest-path cost, so the heuristic is not merely admissible but exact
(and therefore consistent). An octile heuristic would assume diagonal edges cost √2, overestimate
the true cost, and break admissibility. A\* and the scheduler now minimise and charge the same
quantity — Energy — so a diagonal-heavy route is genuinely as cheap as it looks and there is no
"geometric length vs Energy" split. The former tension between §5 and §13 is resolved in favour of
§5's cost model.

### Canonical reference

Amit J. Patel, *"Introduction to A\*"*, Red Blob Games (`redblobgames.com/pathfinding/a-star/
introduction.html`) — priority queue, `came_from`, reconstruction, admissibility, and the Chebyshev
row of its heuristic table.

### Runnable self-check

```python
if __name__ == "__main__":
    def demo():
        def open_map(w, h):
            m = TileMap(w, h)
            for y in range(h):
                for x in range(w):
                    m.tiles[m.idx(x, y)] = 1
            return m

        # ---- zero-length path --------------------------------------------------------------
        m = open_map(5, 5)
        assert a_star(m, (2, 2), (2, 2)) == [(2, 2)]

        # ---- unreachable goal (sealed room) -------------------------------------------------
        m = open_map(9, 9)
        for i in range(9):
            m.tiles[m.idx(4, i)] = 0                       # full wall column at x = 4
        assert a_star(m, (0, 0), (8, 8)) is None

        # ---- tie-breaking: two genuinely equal-cost routes resolve to ONE deterministic route
        m = open_map(5, 5)
        m.tiles[m.idx(2, 1)] = 0                           # forces the path either over or under
        # over  : (1,1) -> (2,0) -> (3,1)  = 2 Steps = 2 Energy
        # under : (1,1) -> (2,2) -> (3,1)  = 2 Steps = 2 Energy
        p1 = a_star(m, (1, 1), (3, 1))
        p2 = a_star(m, (1, 1), (3, 1))
        assert p1 == p2                                    # deterministic across calls
        assert p1[0] == (1, 1) and p1[-1] == (3, 1)
        assert len(p1) == 3                                # both routes are 2 diagonal steps
        # pin the literal once, after observing it: assert p1 == [(1,1), (2,0), (3,1)]
    demo()
```

---

## 4. Shared targeting — Dijkstra flow maps ("distance to each Runner")

*DECISIONS §13 row 4. Enemies target Runners via §8's Utility Score.*

### Data structure chosen

One **multi-source Dijkstra** pass per Runner, run *backwards* from the Runner's cell outward, into
a flat `array('i')` of distances indexed by `y*W+x`. Plus a `dist_to_runner` handle per Runner held
in the Run, invalidated when that Runner moves or terrain changes.

The alternative it beat: **A\* per (enemy, Runner) pair**. With `E` enemies and 4 Runners that is
up to `4E` searches per round; at E = 20, 80 searches × ~43k comparisons is real work, and every
enemy at the same distance from the same Runner recomputes the same answer. A flow map computes
*one* array that answers "how far to Runner i" for *every* cell, so all `E` enemies read it in
O(1). Cost comparison: per-pair A\* is `O(E · T · A*)`; flow maps are `O(T · Dijkstra)`. Flow maps
win whenever `E > 1` — i.e. always. The `game-ai` skill names this exact trade-off ("for many
agents heading to the same goal, compute one flow field").

Flow maps *lose* to A\* in two cases, and this is why both algorithms exist: (a) one actor, one
goal — Dijkstra expands the whole reachable map and A\* does not; and (b) **path quality** — a
gradient-following agent can hug a wall corner slightly differently from a true A\* path. For
enemy *approach* behaviour that is acceptable; for the player's own move preview, §13's A\* row is
the right tool.

### Complexity

| Operation | Time | Space |
|---|---|---|
| `flow_map(map, goals)` | O(V log V), V ≤ 3600 → ≈ 43k comparisons | O(V) `array('i')` = 14 KB |
| all 4 Runners | 4 × above, recomputed only on movement | 4 × 14 KB = 56 KB |
| `step_toward(flow, cell)` | O(8) = O(1) | — |

Recompute policy: a Runner's flow map is invalidated when that Runner changes cell, when the Run's
terrain changes (a door is hacked open), or at Pass boundaries. It is **not** recomputed per enemy
or per tick. Worst case per round is 4 Dijkstra passes = ~170k comparisons, which is nothing
next to one frame of rendering.

### Pseudocode

```
flow_map(map, goals):                       # goals: list of source cells (the Runner's cell)
    INF = 1 << 30
    dist = array('i', [INF]) * (map.w * map.h)
    heap = []
    for g in goals:                          # multi-source: seed every goal at distance 0
        dist[idx(g)] = 0
        heappush(heap, (0, 0, g)); counter += 1
    while heap:
        d, _, cur = heappop(heap)
        if d > dist[idx(cur)]: continue      # stale entry (lazy deletion)
        for (dx, dy) in NEIGHBOURS:          # same fixed order as A* -> deterministic gradient
            nxt = (cur.x+dx, cur.y+dy)
            if map.is_wall(nxt.x, nxt.y): continue
            step = 1.0                        # §5: uniform Step cost, diagonals included
            nd = d + step
            if nd < dist[idx(nxt)]:
                dist[idx(nxt)] = nd
                counter += 1
                heappush(heap, (nd, counter, nxt))
    return dist

step_toward(map, flow, cell):                # gradient descent: one cell closer to the Runner
    best = None
    for (dx, dy) in NEIGHBOURS:              # fixed order: first minimum wins -> deterministic
        nxt = (cell.x+dx, cell.y+dy)
        if map.is_wall(nxt.x, nxt.y): continue
        if best is None or flow[idx(nxt)] < flow[idx(best)]:
            best = nxt
    return best if (best is not None and flow[idx(best)] < flow[idx(cell)]) else None
```

`is_wall` returning 0 for out-of-bounds (§1) is what keeps the edge handling out of this loop.
`INF` propagates naturally: a walled-off Runner gives every cell on that side `INF`, and
`step_toward` returns `None`, which the AI reads as "no path".

### Canonical reference

Amit J. Patel, *"Flow Field Pathfinding"* (Red Blob Games, `redblobgames.com/pathfinding/tower-
defense/` and the flow-field section of the A\* pages) — Dijkstra from the goal outward plus
gradient descent. The formal algorithm is Dijkstra's, CLRS ch. 24.

### Runnable self-check

```python
if __name__ == "__main__":
    def demo():
        def open_map(w, h):
            m = TileMap(w, h)
            for y in range(h):
                for x in range(w):
                    m.tiles[m.idx(x, y)] = 1
            return m

        # ---- unreachable actor: a Runner walled off is INF from the wrong side --------------
        m = open_map(9, 9)
        for i in range(9):
            m.tiles[m.idx(4, i)] = 0
        f = flow_map(m, [(0, 0)])
        assert f[m.idx(4, 5)] == INF                       # the wall itself is never entered
        assert f[m.idx(8, 8)] == INF                       # other side of the seal
        assert f[m.idx(1, 0)] != INF

        # ---- multiple goals (multi-source) --------------------------------------------------
        f2 = flow_map(m, [(0, 0), (8, 8)])
        assert f2[m.idx(0, 0)] == 0 and f2[m.idx(8, 8)] == 0
        assert f2[m.idx(4, 4)] == INF                      # nothing crosses the column

        # ---- ties: two equally short routes -> step_toward must be deterministic -----------
        m3 = open_map(5, 5)
        f3 = flow_map(m3, [(2, 2)])
        a = step_toward(m3, f3, (0, 0)); b = step_toward(m3, f3, (0, 0))
        assert a == b
        assert f3[m3.idx(*a)] < f3[m3.idx(0, 0)]
    demo()
```

---

## 5. Scheduler — Energy bucket queue, `O(1)` pop, compared against a binary heap

*DECISIONS §13 row 5. Semantics: §5 (Initiative Score as Energy, Pass, tie-break).*
*Vocabulary: **Initiative Score**, **Energy**, **Pass** (CONTEXT.md).*

### Data structure chosen

A **bucket queue** (Dial's algorithm shape): an array of `MAX_ENERGY + 1` buckets, each a
`list[Actor]`, plus a `top` cursor that only moves down during pops. The actor's key is its
**remaining Energy in the current Pass**.

The alternative it beat: an actual **binary heap** — which is the point of the row, so both are
implemented and compared.

| | Bucket queue | `heapq` binary heap |
|---|---|---|
| push | O(1) — append to `buckets[e]` | O(log n) ≈ 5–6 comparisons at n = 48 |
| pop-max | O(1) amortised with a monotone `top` cursor; **O(MAX_ENERGY) worst case** when a high-energy insert forces the cursor back up | O(log n) |
| ties | actor scan within the bucket, O(k) | needs a compound key or a counter |
| key type | bounded non-negative **integer** only | any comparable |
| decrease-key | not supported (re-push) | not supported without an index map |

Why buckets win *here*: Energy is an integer by construction (§5: `Reaction + Intuition + 1d6`,
plus `1d6` per Improved Reflexes, max +2d6, so `3 ≤ Energy ≤ 30`), it is small and bounded, and
the schedule is dominated by pops. `MAX_ENERGY = 63` (a power of two minus one) covers the range
with headroom. The bucket's constant is a list-index instead of a sift, which is materially cheaper
than 6 comparisons per pop at 48 actors — but the honest reason to pick it is that it makes the
integer key a *documented invariant*: Energy can never be a float, a negative, or unbounded.

Why a heap would win back: if Energy ever became continuous (a real-time variant, or an action
cost that is a fraction of a tile), if energy needed a float or an unbounded key, or if the actor
count grew into the thousands where log n stops being free. It does not here. ADR-0003 already
names the *global time-cost priority queue* as the deferred successor; see the note below.

**Reconciliation with ADR-0003.** ADR-0003 defers "a global time-cost scheduler with one priority
queue for all actors" and §13 mandates an Energy bucket queue. They are not the same object and do
not conflict: the bucket queue here orders actors **within a Round** by their current Energy, which
is a direct implementation of "Initiative Score doubles as the Energy pool". The deferred global
queue would instead interleave actors on a single shared time axis with per-action cost. The
scheduler below is the §5 model, not the deferred one. (Recorded in the report; no ADR change.)

### Complexity

`n` = actors ≤ 48; `MAX_ENERGY = 63`.

| Operation | Time | Space |
|---|---|---|
| `insert(actor, energy)` | O(1) | O(n) |
| `pop_max()` | amortised O(1); worst case O(MAX_ENERGY) = 63 bucket skips; + O(k) tie-break within a bucket | O(MAX_ENERGY + n) |
| `begin_round` (roll Initiative for n actors) | O(n) rolls + O(n) inserts | O(n) |
| full Round | O(Σ pops) = O(actions taken) | — |

The `top` cursor only decreases during a run of pops; an insert above `top` raises it (O(1)). So
the scan cost across a whole Round is bounded by the total decrease, O(MAX_ENERGY · rounds), not by
pops. Put differently: at this size the scheduler is never the bottleneck, and the *reason* to know
that is the derivation, not a stopwatch.

### Pseudocode

```
MAX_ENERGY = 63

class BucketQueue:
    def __init__(self, max_energy=MAX_ENERGY):
        self.max_energy = max_energy                   # insert clamps against this
        self.buckets = [[] for _ in range(max_energy + 1)]
        self.top = -1
    def insert(self, actor, energy):
        e = min(energy, self.max_energy)          # clamp: never index out of range
        self.buckets[e].append(actor)
        if e > self.top: self.top = e
    def pop_max(self):
        while self.top >= 0:
            if self.buckets[self.top]:
                b = self.buckets[self.top]
                # tie-break inside one Energy bucket: higher Reaction, then lower actor id (§5)
                best = min(range(len(b)), key=lambda i: (-b[i].attrs["Reaction"], b[i].id))
                return b.pop(best)                # O(k), k = actors at this exact Energy
            self.top -= 1
        return None                                # empty

def begin_round(actors, rng):
    for a in actors:
        dice = 1 + a.improved_reflexes_dice        # §5: 1d6 base, +1d6 per Improved Reflexes
        a.score = a.attrs["Reaction"] + a.attrs["Intuition"] + roll_d6(rng, dice)
        a.energy = a.score
        a.pass_no = 0
        q.insert(a, a.energy)

def next_actor(q): return q.pop_max()

def end_turn(q, actor, action_cost):
    actor.energy -= action_cost
    if actor.energy >= PASS_END_THRESHOLD:         # §5: 1 = the cheapest action (a Step)
        q.insert(actor, actor.energy)              # same Pass, keeping the leftover Energy
    else:
        end_pass(q, actor)                         # §5: the Pass ends, with no further charge

def end_pass(q, actor):                            # the Pass boundary: advances the Pass, spends NO Energy
    actor.score -= 10                              # §5: the Pass ends
    actor.pass_no += 1
    tick_cooldowns(actor)                          # §8: cooldowns tick down once per Pass
    if actor.score >= PASS_END_THRESHOLD:          # §5: a new Pass begins while Score is positive
        actor.energy = actor.score
        q.insert(actor, actor.energy)
    # else: actor is done for this Round (not reinserted)
```

The schedule is `while (a := q.pop_max()) is not None: <actor acts once>; end_turn(...)`. One pop
= one action, never a whole turn, which is what makes it interruptible by player input. `end_pass`
is also the boundary a Behavior Tree takes when its root returns FAILURE: the Pass ends and the
actor is re-inserted only at its next Pass, with no Energy charged for the empty step (§13, ai.md
§3.1).

**`PASS_END_THRESHOLD = 1` (settled).** §5 ends a Pass when the actor cannot afford the cheapest
action, and a **Step costs 1 Energy**, so a Pass runs until even one Step is unaffordable. Step
*is* an action: it moves the actor, it ends exposure, it repositions a Runner or a guard, and it is
the unit the whole movement, A\*, and flow-map model is built on (§3, §4). An earlier draft set
this to 5 by treating Step as "not a useful action"; that is overruled, because it both
contradicts the worked example in §5 (Guard A at 9 Energy spends 5 + 4 Steps = 0) and would let an
actor sit on up to 4 Energy it can never convert into anything. The same value is the new-Pass
restart floor: after `Score −= 10` a Pass begins while the Score is still positive (`≥ 1`). This
constant is settled and lives in `constants.py`.

### Canonical reference

RogueBasin, *"Time Systems"* (energy/initiative schedulers) for the 100-point energy model this
adapts to an Initiative-Score-shaped budget. For the bucket queue itself: **Dial's algorithm**
(R. B. Dial, *"Algorithm 360: Shortest-path forest with topological ordering"*, CACM 1969), also
described in CLRS ch. 24 exercises and on cp-algorithms under "Dijkstra with buckets".

### Runnable self-check

```python
if __name__ == "__main__":
    def demo():
        def mk(id, rea, base):
            a = Actor(id=id, name=f"a{id}", attrs={"Reaction": rea, "Intuition": base})
            a.improved_reflexes_dice = 0
            return a

        # ---- two actors with equal energy: higher Reaction wins, then lower id ---------------
        q = BucketQueue()
        a, b = mk(7, 4, 4), mk(3, 4, 4)               # both Energy 8 once initiative is fixed
        a.energy = b.energy = 8
        q.insert(a, 8); q.insert(b, 8)
        assert q.pop_max() is b                        # lower id wins the Reaction tie
        assert q.pop_max() is a
        assert q.pop_max() is None                     # drained

        c, d = mk(1, 6, 2), mk(2, 4, 2)               # Energy 8 vs 6
        c.energy, d.energy = 8, 6
        q.insert(c, 8); q.insert(d, 6)
        assert q.pop_max() is c                        # higher Energy first

        # ---- clamps at MAX_ENERGY, and never returns a negative index ------------------------
        q2 = BucketQueue()
        e = mk(9, 6, 6); e.energy = 999
        q2.insert(e, 999)
        assert q2.pop_max() is e

        # ---- Pass arithmetic: Score 18 -> Passes at 18 and 8, then done (§5) ----------------
        f = mk(4, 6, 6); f.score = 18; f.energy = 18; f.pass_no = 0
        q3 = BucketQueue(); q3.insert(f, 18)
        f = q3.pop_max(); end_turn(q3, f, 18)          # spent the whole Pass
        assert f.score == 8 and f.energy == 8
        f = q3.pop_max(); assert f is not None
        end_turn(q3, f, 8)                             # spent the whole second Pass too
        assert f.score == -2                           # 8 - 10, below the positive restart floor
        assert q3.pop_max() is None                    # Pass chain ended
    demo()
```

---

## 6. Mission Graph — adjacency list, union-find connectivity, cycle detection

*DECISIONS §13 row 6. Semantics: §10.1; rationale ADR-0011.*

### Data structure chosen

```python
class MissionGraph:
    nodes: dict[str, Node]        # node id -> {id, kind, room_kind, payload}
    adj:   dict[str, list[str]]   # adjacency list, insertion-ordered
    entry: str                    # exactly one entry node
```

`kind ∈ {entry, security, objective, side, exit}` (§10). Nodes are few (`N` ≤ 10, §10), so an
adjacency *list* over string ids beats an adjacency *matrix* (N² = 100 cells mostly empty, and the
generator needs neighbour iteration far more often than `has_edge(u, v)`). A list also preserves
insertion order, which keeps generation deterministic (§14).

Two supporting structures, both O(N) regardless:

- **Union-find** (`unionfind.py`, union by size + path compression) for connectivity: "is this
  objective reachable from entry?" is `find(objective) == find(entry)`.
- **Cycle detection**: an edge whose endpoints are already in the same union-find set closes a
  cycle. For *side* edges this is the signal that a side branch has become an alternate route
  rather than a leaf — §10.1 says side nodes "hang off the main path without becoming required",
  so a side edge that closes a cycle is rejected and resampled.

Alternative rejected: **reachability by repeated DFS** after every edge insertion. Each DFS is
O(V+E) and the generator inserts O(N) edges, giving O(N·(V+E)) = O(N²) for the connectivity test
alone. Incremental union-find makes each insertion O(α(N)) ≈ O(1); at N = 10 that is the
difference between ~100 steps and ~10. Small in absolute terms, but the union-find is also the
structure §10.2 reuses to verify the *embedded* map, so it is written once and used twice.

Alternative rejected: **networkx**. A dependency for 10 nodes, and ADR-0011 makes this graph
construction a learning goal.

### Complexity

`N` = nodes ≤ 10, `E` = edges ≈ N + 3.

| Operation | Time | Space |
|---|---|---|
| `add_node` | O(1) | O(N) |
| `add_edge` (with union + cycle check) | O(α(N)) ≈ O(1) | O(E) |
| `build_adjacency` | O(N + E) | O(N + E) |
| whole `validate()` (DFS reachability of every objective from entry, and of exit from every objective) | O(N + E) | O(N) |
| union-find | — | O(N) |

### Pseudocode

```
JOB_GRAPH = {                                # world.md §5.3 owns the per-Job counts
    "extraction": {"sec_pre": 2, "sec_post": 1, "objectives": 1, "side_max": 3},
    "sabotage":   {"sec_pre": 1, "sec_post": 1, "objectives": 2, "side_max": 2},
    "protection": {"sec_pre": 1, "sec_post": 1, "objectives": 1, "side_max": 1},
    "courier":    {"sec_pre": 1, "sec_post": 0, "objectives": 1, "side_max": 2},
}
SIDE_CHAIN_MAX = 2                           # DEC §10: a side chain is at most this deep
SIDE_CHAIN_P   = 0.25                        # (proposed) chance a side node grows a side child

def build_graph(job_type, rng):
    cfg = JOB_GRAPH[job_type]
    g = MissionGraph()
    cur = g.add("entry", kind="entry")           # entry: exactly one
    for _ in range(cfg["sec_pre"]):             # security gate between entry and the first objective
        cur = g.add_edge(cur, g.add(kind="security"), kind="main")
    for _ in range(cfg["objectives"]):          # required objectives
        cur = g.add_edge(cur, g.add(kind="objective"), kind="main")
    for _ in range(cfg["sec_post"]):            # security gate between the last objective and exit
        cur = g.add_edge(cur, g.add(kind="security"), kind="main")
    g.add_edge(cur, g.add(kind="exit"), kind="exit")   # exit: exactly one

    # side branches: total 0..side_max across the graph, each chain at most SIDE_CHAIN_MAX deep
    budget = rng.randint(0, cfg["side_max"])
    for anchor in g.pick_side_parents(rng, budget):      # parents are main-path nodes
        if budget <= 0: break
        node = g.add_edge(anchor, g.add(kind="side"), kind="side"); budget -= 1
        while (budget > 0 and g.side_chain_len(node) < SIDE_CHAIN_MAX
               and rng.random() < SIDE_CHAIN_P):
            node = g.add_edge(node, g.add(kind="side"), kind="side"); budget -= 1

    if not g.validate():
        return build_graph(job_type, rng)              # resample, bounded by MAX_ATTEMPTS
    return g

def add_edge(g, u, v, kind):                                  # returns v, or None if refused
    if kind == "side" and g.uf.find(u) == g.uf.find(v):
        return None                                        # closes a cycle: side branches dead-end
    g.adj[u].append(v)
    if kind == "main": g.adj[v].append(u)                  # side edges are one-way attachments
    g.uf.union(u, v)
    return v

def validate(g):                                           # §10's graph-wide constraints
    root = g.uf.find(g.entry)
    if any(g.uf.find(o) != root for o in g.objectives()): return False    # every objective reachable
    if g.uf.find(g.exit) != root: return False                            # exit reachable
    for o in g.objectives():                                              # ... from every objective
        if not reaches(g, o, g.exit): return False
    return True
```

`reaches` is a bounded DFS from `o` following `main` edges. The per-Job counts (including `sec_post`)
come from world.md §5.3; the ceilings above — **entry exactly 1, security 1–3 in total across the pre-
and post-objective gates (at most 2 pre plus 1 post), objective 1–2, side 0–3 in chains no longer
than 2, exit exactly 1** — bound `N` at **10** nodes (DEC §10), down from the 20 this document
previously assumed. `SIDE_CHAIN_P` is content tuning, not a §-sourced number: `(proposed)` see Open
question 2.

### Canonical reference

CLRS ch. 21 (*Data Structures for Disjoint Sets* — union by rank/size + path compression, and the
`O(α(n))` bound) for union-find; CLRS ch. 22 (elementary graph algorithms — DFS, connectivity, DAG
reasoning) for reachability and cycle detection. For the *design* of the graph, ADR-0011.

### Runnable self-check

```python
if __name__ == "__main__":
    def demo():
        # ---- union-find: already-connected nodes -------------------------------------------
        uf = DisjointSet(["a", "b", "c"])
        assert uf.union("a", "b") is True
        assert uf.union("a", "b") is False                 # already connected
        assert uf.union("b", "a") is False                 # symmetric
        assert uf.find("a") == uf.find("b")
        assert uf.find("c") != uf.find("a")
        assert uf.union("b", "c") is True
        assert uf.find("a") == uf.find("c")

        # ---- cycle detection: a side edge that closes a loop is refused ---------------------
        g = MissionGraph()
        g.add("entry", kind="entry"); g.add("side", kind="side")
        assert g.add_edge("entry", "side", kind="side") == "side"
        assert g.add_edge("side", "entry", kind="side") is None         # closes the cycle

        # ---- a graph with an unreachable objective is rejected ------------------------------
        bad = MissionGraph()
        bad.add("entry", kind="entry"); bad.add("obj", kind="objective")
        bad.add("exit", kind="exit")
        bad.add_edge("entry", "exit", kind="main")                        # obj never attached
        assert bad.validate() is False

        # ---- a valid chain passes -----------------------------------------------------------
        ok = MissionGraph()
        ok.add("entry", kind="entry"); ok.add("obj", kind="objective"); ok.add("exit", kind="exit")
        ok.add_edge("entry", "obj", kind="main"); ok.add_edge("obj", "exit", kind="main")
        assert ok.validate() is True

        # ---- the builder expresses the paydata spine: entry -> sec_pre -> vault -> sec_post -> exit
        built = build_graph("extraction", random.Random(3))
        kinds = {n: built.nodes[n].kind for n in built.nodes}
        counts = {k: list(kinds.values()).count(k) for k in set(kinds.values())}
        assert counts["entry"] == 1 and counts["exit"] == 1
        assert 1 <= counts["security"] <= 3 and 1 <= counts["objective"] <= 2
        assert len(built.nodes) <= 10                        # DEC §10's ceiling
        assert built.validate() is True
    demo()
```

---

## 7. Embedding — BSP tree for room partition, L-corridor carving

*DECISIONS §13 row 7. Semantics: §10.2; rationale ADR-0011.*

### Data structure chosen

A **graph-aware BSP recursion**, not a symmetric BSP. The recursion is
`partition(subset_of_graph_nodes, rect)`:

- if `|subset| == 1` → carve one room inside `rect`;
- else split the node subset into two halves (BFS order from entry), split `rect` along its longer
  axis in proportion to the halves, and recurse.

This gives **exactly N rooms for N graph nodes**, and — because graph-adjacent nodes tend to land
in adjacent halves — short corridors between them. Edges are then carved as L-shaped corridors
between room centres, and connectivity is re-verified with the union-find from §6.

The alternative it beat: **symmetric BSP** (`bsp(node, depth)` splitting every leaf to a fixed
depth, then placing a room per leaf). Symmetric BSP produces 2^depth leaves, so the room count is
nobody's decision and the graph has to be *matched onto* rooms after the fact. That match is the
hard, arbitrary part ("which objective goes in which rectangle?") and it is exactly the
objective-blind scattering ADR-0011 rejected. The graph-aware version makes the graph choose, so
the layout is legible: the vault is far from the entry because the graph says so.

**Reconciliation with ADR-0011 (no conflict, stated explicitly).** ADR-0011 rejects *recursive BSP
as the Site generator*. §13 keeps BSP as the *embedding partition* inside a node that the Mission
Graph already typed and ordered. BSP here is subservient to the graph: it allocates rectangles, it
does not decide what goes where. This is the same rejection, applied one level down.

The alternative embedder rejected: **room-and-corridor scatter** over the whole Site. Same
objective-blindness defect, plus it cannot guarantee the requested room count per node kind.

### Complexity

`N` = rooms ≤ 10, `A` = area = 3600.

| Operation | Time | Space |
|---|---|---|
| `partition` | O(N log N) splits, each O(N) to halve the subset → O(N²) worst case, but N ≤ 10 → ≤ 100 | O(N) recursion |
| subset split | O(N + E) per level via BFS from entry | O(N) |
| corridor carving | O(N · L), L = corridor length ≈ O(√A/N) each → O(√A · N) ≈ 60·10 = 600 tile writes | in-place in `tiles` |
| connectivity repair + verify | O(A) flood, O(A) union-find join | O(A) |

The honest worst case is O(N² + A). At N = 10, A = 3600 that is a few thousand operations, i.e.
generation is dominated by the **validation** pass (O(A) over 3600 cells), not by the partition.
That is the right place for the cost to sit: it is the pass that guarantees the player never gets
a broken Site.

### Pseudocode

```
def embed(graph, map, rng):
    order = bfs_from(graph, graph.entry)                   # deterministic node order
    partition(graph, order, Rect(1, 1, map.w-2, map.h-2), map, rng)

    # edges -> L-corridors between the two rooms' centres
    for (u, v, kind) in graph.edge_list():                 # insertion order -> deterministic
        (ax, ay) = graph.nodes[u].center
        (bx, by) = graph.nodes[v].center
        if rng.random() < 0.5: carve_h_then_v(ax, ay, bx, by)
        else:                  carve_v_then_h(ax, ay, bx, by)
        graph.nodes[u].connected_to.append(v)

    repair_connectivity(map, graph)                        # §10.2: union-find over the carved grid
    return map

def partition(graph, subset, rect, map, rng):
    if len(subset) == 1:
        room = inset(rect, margin=MARGIN)                   # leave a wall ring
        carve_room(map, room)
        graph.nodes[subset[0]].room = room
        graph.nodes[subset[0]].center = room.center
        return
    if rect.w >= rect.h:
        cut = rng.randint(MIN_ROOM, rect.w - MIN_ROOM)
        left, right = rect.split_vertical(cut)
    else:
        cut = rng.randint(MIN_ROOM, rect.h - MIN_ROOM)
        left, right = rect.split_horizontal(cut)
    a, b = halve(subset)                                    # BFS halves, |a| = ceil(N/2)
    partition(graph, a, left,  map, rng)
    partition(graph, b, right, map, rng)

def repair_connectivity(map, graph):
    uf = DisjointSet(all carved floor cells)                 # join each cell to its carved neighbours
    for cell in carved_cells(map): uf.join_adjacent(cell)
    rooms = [graph.nodes[n].center for n in graph.nodes]
    for r in rooms[1:]:
        if uf.find(rooms[0]) != uf.find(r):
            carve_corridor(map, nearest_reached(uf, map), r)  # dig until reconnected
    assert all(uf.find(rooms[0]) == uf.find(r) for r in rooms)  # every room reachable
```

`MIN_ROOM` and `MARGIN` are content tuning (a corridor node is 1-wide per §10.2; the vault is
large). `(proposed)`; see Open question 2.

### Canonical reference

RogueBasin, *"Basic BSP Dungeon generation"* (the recursive split-and-connect pattern, including
`split_vertical` / `split_horizontal` and the "connect siblings as the recursion unwinds" step).
The graph-aware variant is not in that article; it is derived from ADR-0011.

### Runnable self-check

```python
if __name__ == "__main__":
    def demo():
        g = build_graph("extraction", random.Random(1))
        map = TileMap(60, 60)
        embed(g, map, random.Random(2))

        # ---- exactly one room per graph node, no more and no fewer -------------------------
        assert len([n for n in g.nodes.values() if n.room]) == len(g.nodes)
        # ---- no two rooms overlap -----------------------------------------------------------
        rooms = [g.nodes[n].room for n in g.nodes]
        for i in range(len(rooms)):
            for j in range(i + 1, len(rooms)):
                assert not rooms[i].overlaps(rooms[j])
        # ---- every room is inside the map, and has a wall ring around it --------------------
        for r in rooms:
            assert 0 < r.x and 0 < r.y and r.x2 < map.w - 1 and r.y2 < map.h - 1
            assert map.at(r.x - 1, r.center.y) == 0
        # ---- connectivity: every room centre reachable from the entry centre ---------------
        uf = flood_union(map, g.nodes[g.entry].center)
        for n in g.nodes:
            assert uf.find(g.nodes[n].center) == uf.find(g.nodes[g.entry].center)
    demo()
```

---

## 8. Behavior Tree — explicit-stack ticker, per-node cooldown counters

*DECISIONS §13 row 8. Semantics: §8; rationale ADR-0009.*
*Vocabulary: **Behavior Tree**, **Blackboard** (CONTEXT.md).*

### Data structure chosen

The tree is **immutable data** (loaded from JSON, ADR-0009). Per-actor mutable tick state lives in
a `BTState` beside the actor:

```python
@dataclass
class Frame:
    node: Node          # a node in the shared, frozen tree
    idx: int            # child index to (re)enter
    pending: Status|None  # status returned by the child just evaluated

class BTState:
    stack: list[Frame] | None            # None = not started; the explicit call stack
    last_root: Status | None
    cooldowns: dict[str, int]            # node id -> Passes remaining until ready (0 = ready)
```

**Why an explicit stack and not recursion.** A turn-based BT must **suspend mid-tree**: a `MoveTo`
leaf returns RUNNING after one Step, the scheduler takes over, and the next time this actor acts
the tree must resume *at that leaf*, not restart from the root. A recursive `tick()` cannot be
suspended and resumed without persisting the recursion — the explicit stack *is* that persistence.
It also removes any depth limit, and it makes the abort path ("a reactive Selector abandons a
running branch") an explicit stack truncation instead of an exception-free unwind.

The alternative it beat: **recursive `tick()`** as taught in `game-ai` and the BT-core reference.
Correct, shorter, and it is what the skill's examples show — but without a separate saved recursion
you cannot resume, and rebuilding a `Running` subtree from the root every turn restarts multi-turn
actions (the skill's own pitfall: *"Re-ticking a `Running` action from the root every frame
restarts it"*).

Second alternative: **event-driven / reactive tree with no memory** (re-evaluate from the root
every tick). Rejected as the default because generation, patrol, and Spirits all have multi-turn
intents; kept as an option per Selector (`reactive: true`), which is the combat case.

**Per-node cooldown counters are per-actor, keyed by node id, and measured in the actor's own
Passes**, never in wall-clock time, decision steps, or global ticks. A shared JSON node cannot
hold a counter — two Corp Guards share the same `Cooldown` node object — and a wall-clock cooldown
would make behaviour depend on how long the player thinks, breaking determinism (§14). Each Pass
boundary decrements every cooldown on that actor by 1; nothing else touches them.

**Cooldowns survive a reset.** `reset_tree` and the abort path clear the frame stack, `Repeat`
counters, and leaf accumulators, but **not** cooldowns. Otherwise a Guard that flees and returns
would re-arm `call_backup`, and the Alarm tick would fire every few steps until the Security Clock
stopped meaning anything. This is `ai.md`'s contract (`bt` owns the BT semantics); the code below
matches it. The Pass boundary decrements them: the scheduler's `end_pass` (§5) calls
`tick_cooldowns(actor)` (below) at every Pass boundary, whether the Pass ended because Energy ran
out or because a root returned FAILURE (§13).

### Node taxonomy (ADR-0009 §8)

| Kind | Node | Tick behaviour |
|---|---|---|
| Composite | `Sequence` | children left→right; stop at first non-SUCCESS |
| Composite | `Selector` | children left→right; stop at first non-FAILURE |
| Decorator | `Inverter` | swap SUCCESS↔FAILURE, pass RUNNING |
| Decorator | `Succeeder` | map FAILURE→SUCCESS, pass RUNNING |
| Decorator | `Repeat` | re-run child N times |
| Decorator | `Cooldown` | gate child on `state.cooldowns[node.id]` (Passes remaining; 0 = ready) |
| Leaf | `Condition` | pure test, returns SUCCESS/FAILURE |
| Leaf | `Action` | performs **exactly one Energy-costing world action**, returns SUCCESS/FAILURE/RUNNING |

v1 implements exactly these (§8). `Parallel` is not on the list and is not built.

### Complexity

`m` = nodes ≤ 30, `d` = depth ≤ 6, `n` = actors ≤ 48.

| Operation | Time | Space |
|---|---|---|
| `tick(actor)` | O(m) worst case per tick; O(1) amortised per action leaf (a tick stops at the first action) | O(d) stack = O(6) frames |
| cooldown lookup | O(1) dict hit per `Cooldown` node | O(m) per actor |
| building a tree | O(m) once per archetype, then shared read-only | O(m) shared |
| all 48 actors, one tick each | O(n·m) = 48·30 = 1440 node visits worst case, and usually far less | — |

### Pseudocode

```
def tick(actor, budget=1):
    st = actor.bt
    if st.stack is None:
        st.stack = [Frame(actor.tree.root, 0, None)]
    while st.stack:
        f = st.stack[-1]
        n = f.node

        # (a) a child has just returned a status: combine it into the composite
        if f.pending is not None:
            s = f.pending; f.pending = None
            if n.kind == SEQUENCE:
                if s == FAILURE:          pop(st); deliver(st, FAILURE); continue
                if s == RUNNING:          continue                     # re-enter the same child
                f.idx += 1                                             # child succeeded
                if f.idx == len(n.children): pop(st); deliver(st, SUCCESS); continue
            elif n.kind == SELECTOR:
                if s == SUCCESS:          pop(st); deliver(st, SUCCESS); continue
                if s == RUNNING:          continue
                f.idx += 1
                if f.idx == len(n.children): pop(st); deliver(st, FAILURE); continue
            elif n.kind == INVERTER:
                pop(st); deliver(st, invert(s)); continue
            elif n.kind == SUCCEEDER:
                pop(st); deliver(st, SUCCESS if s == FAILURE else s); continue
            elif n.kind == REPEAT:
                if s == RUNNING: continue
                n.done += 1
                if s == FAILURE or (n.count and n.done >= n.count):
                    pop(st); deliver(st, s); continue
                f.pending = None; continue                              # loop the same child
            elif n.kind == COOLDOWN:
                if s == SUCCESS: st.cooldowns[n.id] = n.passes      # arm: n Passes from now
                pop(st); deliver(st, s); continue
            continue

        # (b) descend, or evaluate the leaf
        if n.kind in (SEQUENCE, SELECTOR):
            f.idx = 0 if f.idx >= len(n.children) else f.idx
            st.stack.append(Frame(n.children[f.idx], 0, None)); continue
        if n.kind in (INVERTER, SUCCEEDER, REPEAT, COOLDOWN):
            if n.kind == COOLDOWN and st.cooldowns.get(n.id, 0) > 0:
                pop(st); deliver(st, FAILURE); continue                 # still cooling down
            st.stack.append(Frame(n.child, 0, None)); continue
        # LEAF
        s = eval_leaf(n, actor)                    # one action leaf = ONE world action + its Energy
        pop(st); deliver(st, s)
        if n.kind == ACTION:
            budget -= 1
            if budget == 0:
                return RUNNING if st.stack else (st.last_root or RUNNING)
    return st.last_root if st.last_root is not None else FAILURE

def deliver(st, s):
    if st.stack: st.stack[-1].pending = s
    else:        st.last_root = s

def reset(actor):                                  # abort/re-Pass contract (ADR-0009, BT-core §Reset)
    for f in (actor.bt.stack or []): f.node.reset_instance(actor)
    actor.bt.stack = None
    # cooldowns are NOT cleared: they are measured in Passes and must survive a retreat/re-entry

def tick_cooldowns(actor):                         # called by the scheduler's end_pass (§5) each Pass
    if actor.bt is None: return                    # a Runner has no tree (§12)
    for nid in actor.bt.cooldowns:                 # cooldowns tick down once per Pass
        actor.bt.cooldowns[nid] -= 1
```

The `budget == 0` return after one Action leaf is the **turn-based suspension point**: the tree has
performed its one world action and hands control back to the scheduler. Every later tick re-enters
through `st.stack` and lands back on that leaf if it returned RUNNING.

**Livelock guard:** a tick that produces no Action (the root returned FAILURE, e.g. "no target, no
patrol point") implies the actor has nothing worth doing. `ai.py` maps that to "end this Pass"
rather than reinserting the actor, so there is no spin. The Pass ends through `end_pass`, which
**charges no Energy** — ai.md §3.1: a FAILURE root ends the Pass without spending. The actor is
re-inserted only at its next Pass, and `end_pass` drops the Score by 10 each time, so a tree that
always FAILUREs leaves the Round instead of burning Energy in a loop.

**Reactive selectors (optional, per node):** if `n.reactive`, the ticker re-scans from
`n.children[0]` every tick and, when an earlier child returns non-FAILURE, calls `reset` on the
abandoned subtree before descending. This is the `ai-behavior-trees-utility-ai` reference's
`ReactiveSelector`, expressed as an option on the node rather than a second class.

`Repeat`'s counter lives on the node in the reference implementation; here it must live in
`BTState` (per-actor) for the same reason cooldowns do. `n.done` above is shorthand for
`st.repeat_counts[n.id]`.

### Canonical reference

Michele Colledanchise & Petter Ögren, *"Behavior Trees in Robotics and AI: An Introduction"*
(arXiv:1709.00084, also a CRC Press book) — the canonical text on the three-valued tick contract,
sequence/selector semantics, and the reactive-vs-memory distinction. Implementation shorthand:
`ai-behavior-trees-utility-ai/references/behavior-tree-core.md`.

### Runnable self-check

```python
if __name__ == "__main__":
    def demo():
        # A Sequence[ Condition(always true), Action(MoveTo) ] where MoveTo RUNNINGs then
        # SUCCEEDs. The Condition must run exactly ONCE; the MoveTo must be re-entered.
        calls = {"cond": 0, "move": 0}

        class Cond(Node):
            def eval(self, actor):
                calls["cond"] += 1
                return SUCCESS
        class MoveTo(Node):
            def eval(self, actor):
                calls["move"] += 1
                return RUNNING if calls["move"] < 2 else SUCCESS

        tree = Node(SEQUENCE, children=[Cond("c"), MoveTo("m", kind=ACTION)])
        actor = Actor(id=1, name="g", bt=BTState(tree=tree))

        s1 = tick(actor)                       # ---- RUNNING resume -------------------------
        assert s1 == RUNNING
        assert calls == {"cond": 1, "move": 1} # the condition was NOT re-run; MoveTo was entered
        s2 = tick(actor)
        assert s2 == SUCCESS
        assert calls == {"cond": 1, "move": 2} # resumed at MoveTo, never re-checked from the root

        # ---- cooldown: measured in Passes, and SURVIVES reset --------------------------------
        actor2 = Actor(id=2, name="h", bt=BTState(
            tree=Node(COOLDOWN, id="cb", passes=2, child=Node(ACTION, id="atk"))))
        assert tick(actor2) in (SUCCESS, RUNNING)    # arms "cb" for 2 Passes
        assert tick(actor2) == FAILURE               # still cooling down within the same Pass
        tick_cooldowns(actor2)                       # Pass boundary: cooldowns -= 1
        assert tick(actor2) == FAILURE               # one Pass remaining
        tick_cooldowns(actor2)
        assert tick(actor2) in (SUCCESS, RUNNING)    # ready again

        # ---- abort/reset clears the stack but NOT cooldowns (they are Pass-based) ----------------------------------------------------------------------------
        reset(actor2)
        assert actor2.bt.stack is None               # stack cleared
        assert actor2.bt.cooldowns.get("cb", 0) > 0  # cooldowns survive the reset
    demo()
```

---

## 9. Utility — weighted candidate scoring with hysteresis

*DECISIONS §13 row 9. The score formula is §8:*
`score = w_threat·(1 / max(1, distance)) + w_visible·visible + w_objective·objective_value − w_ally_risk·allied_fire_risk`

### Data structure chosen

Per actor, a list of **candidates** (targets or actions) scored by a pure function, with a
per-actor `current_target` remembered for hysteresis. No heap, no global structure: candidate
counts are small (targets ≤ 4 Runners + up to 4 Spirits; actions ≤ 8).

The alternative it beat: **a scored priority queue** built every tick. At ≤ 12 candidates the heap's
O(k log k) is not the problem; the *allocation* is — building and discarding a heap per actor per
turn is garbage churn for no ordering benefit. A single pass tracking `best` is O(k) and
allocation-free.

The other alternative, **a thicket of BT conditions** ("is enemy A visible and closer than enemy B
and…"), is what ADR-0009 rejects: trees express intent, utility expresses choice. Keeping the two
separate is the reason the scoring lives in its own module and is called from one BT leaf
(`ChooseTarget`), never from conditions.

**Each term is already in a bounded range, so there is no separate normalisation scale.**
`utility-ai-system.md` asks every consideration to output 0..1; §8's formula does that once
`distance` is guarded and `objective_value` is defined:

| Term | Formula (per §8) | Range | Why |
|---|---|---|---|
| threat | `1 / max(1, distance)` | (0, 1] | `distance` is **Chebyshev**; `max(1, ·)` keeps the term finite when a candidate shares the actor's cell (a player command can produce that), so the term is already capped at 1 |
| visible | `visible` | 0 or 1 | boolean |
| objective | `objective_value` | 0.0 or 1.0 | 1.0 when the candidate is inside the room named by `objective`, 0.0 otherwise; no scale to divide by |
| ally_risk | `allied_fire_risk` | content-defined 0..1 | content must author this 0..1 or it dominates |

An earlier draft normalised `1/distance` to `1/(1 + distance)` and divided `objective_value` by a
`MAX_OBJECTIVE_VALUE`, because it believed §8 left the objective term unscaled. Both are superseded
by the §8 formula above.

### Complexity

`k` = candidates ≤ 12, `t` = terms ≤ 4.

| Operation | Time | Space |
|---|---|---|
| `score(candidate)` | O(t) = O(1) | O(1) |
| `select(candidates)` | O(k·t) = O(48) | O(1) extra |
| per round | O(n·k·t) = 48·12·4 ≈ 2300 ops | — |

### Pseudocode

```
def score_of(actor, c, w):
    # §8: Chebyshev distance; objective_value is already 0/1, so no extra normalisation
    return (w.w_threat    * (1.0 / max(1.0, chebyshev(actor.pos, c.pos)))
          + w.w_visible   * (1.0 if visible(actor, c) else 0.0)
          + w.w_objective * c.objective_value            # 1.0 inside the objective room, else 0.0
          - w.w_ally_risk * allied_fire_risk(actor, c))

def select(actor, candidates, weights, target_hysteresis):
    # target_hysteresis is per-archetype (§8): 0.05–0.25, never one global constant
    scored = [(c, score_of(actor, c, weights))
              for c in sorted(candidates, key=lambda c: c.target_id)]   # deterministic order
    if not scored:
        actor.bb.current_target = None
        return None
    best = max(scored, key=lambda sc: (sc[1], -sc[0].target_id))     # tie -> lower target id
    incumbent = next((sc for sc in scored if sc[0].target_id == actor.bb.current_target), None)
    if incumbent is not None and best[1] <= incumbent[1] + target_hysteresis:
        return incumbent[0]                      # only a target beating it by > hysteresis wins
    actor.bb.current_target = best[0].target_id
    return best[0]

def consider_actions(action_utility_terms, weights):           # same shape for action choice
    ...                                                        # candidates: Attack/MoveTo/Cover/Flee/Wait
```

Two later rules from `utility-ai-system.md` that this design deliberately does **not** adopt in v1:
softmax selection (adds randomness; ADR-0009 wants trees explainable afterwards) and the
compensation factor (only matters with many considerations; `t ≤ 4` here). If enemies feel robotic,
softmax with the `ai` stream is the upgrade path and is already determinism-safe (§14).

### Canonical reference

Dave Mark, *Behavioral Mathematics for Game AI* (Course Technology, 2009) — normalisation,
response curves, and weighted scoring. Talk version: Dave Mark, *"Building a Better Centaur:
AI at Massive Scale"*, GDC. Implementation shorthand:
`ai-behavior-trees-utility-ai/references/utility-ai-system.md`.

### Runnable self-check

```python
if __name__ == "__main__":
    def demo():
        W = Weights(w_threat=1.0, w_visible=1.0, w_objective=1.0, w_ally_risk=1.0)

        # ---- hysteresis: the incumbent keeps a near-tie (§8: 0.05–0.25, per archetype) ------
        a = Actor(id=1, name="guard")
        a.bb.current_target = 2
        far  = Candidate(target_id=2, dist=3.0, visible=True, objective_value=0.0, risk=0.0)
        near = Candidate(target_id=3, dist=2.9, visible=True, objective_value=0.0, risk=0.0)
        assert select(a, [far, near], W, target_hysteresis=0.25).target_id == 2   # 0.345 < 0.333+0.25

        # ---- a clear winner overrides the incumbent -----------------------------------------
        closewin = Candidate(target_id=4, dist=0.5, visible=True, objective_value=0.0, risk=0.0)
        assert select(a, [far, closewin], W, target_hysteresis=0.25).target_id == 4  # 1.0 > 0.333+0.25

        # ---- objective_value is already 0/1: a candidate in the objective room wins ties -----
        go   = Candidate(target_id=9,  dist=3.0, visible=True, objective_value=1.0, risk=0.0)
        away = Candidate(target_id=10, dist=3.0, visible=True, objective_value=0.0, risk=0.0)
        a.bb.current_target = None
        assert select(a, [go, away], W, target_hysteresis=0.25).target_id == 9

        # ---- zero candidates: no crash, and the blackboard clears ----------------------------
        assert select(a, [], W, target_hysteresis=0.25) is None
        assert a.bb.current_target is None

        # ---- deterministic tie-break: equal scores -> lower target id ------------------------
        t7 = Candidate(target_id=7, dist=2.0, visible=True, objective_value=0.0, risk=0.0)
        t8 = Candidate(target_id=8, dist=2.0, visible=True, objective_value=0.0, risk=0.0)
        a.bb.current_target = None
        assert select(a, [t8, t7], W, target_hysteresis=0.25).target_id == 7
    demo()
```

---

## 10. Dialogue — graph dict, explicit queue runner, whitelisted-`ast` evaluator, reachability

*DECISIONS §13 row 10. Contract: §11; rationale ADR-0010.*

### Data structure chosen

- Graph, on disk: a `nodes` **array** — each element carries its own `id` (§11). Array, not
  object, because a JSON object silently keeps the last of duplicate keys, so a duplicate id could
  never be diagnosed; an array makes it a normal validation error the loader can report.
- Graph, loaded: `dict[str, Node]` with a `start` key — the loader indexes the array by `id`,
  checking uniqueness. O(1) jump by id, insertion-ordered for deterministic validation (§14).
- Runner: an **explicit FIFO queue** of nodes to visit, not recursion. Nodes with `next` and no
  player input (`line` + auto-advance, or a `set`-only node) are enqueued and drained *before* the
  UI is asked for anything, so a chain of effect nodes resolves in one pass without a stack and
  without a step per frame.
- Variable store: a flat `dict[str, value]` with **dotted keys** (`rep.fixer`, `heat`, `clock`,
  `flags`, `skill.negotiation`, `attr.logic`). §11 names the lowercase dotted form, and dotted
  names are not valid Python identifiers, so the evaluator resolves the whole dotted chain as one key.
- Condition evaluator: `ast.parse(expr, mode="eval")` over a whitelist.

The alternative it beat, for the graph: **a per-NPC Python callable** (ADR-0010 rejects it —
dialogue becomes code, no schema to validate). For the runner: **a recursive walk** — a `next`
cycle then recurses until `RecursionError`, and a linear chain of nodes becomes a call per node
instead of a queue drain. For the evaluator: **`eval()`** — see the self-check.

### The ast evaluator

Whitelist, from `dialogue-systems/references/runner.md`, extended by exactly one rule that §11's
syntax forces:

| Node type | Allowed | Resolves to |
|---|---|---|
| `Expression` | yes | its `body` |
| `Constant` | yes | the literal (`int`, `float`, `str`, `bool`, `None`) |
| `Name` | yes | `vars[node.id]`; a name not declared in the store raises `DialogueConditionError` — never a silent `None` |
| `Attribute` | **only** as a `Name`-rooted chain | the flattened key `"skill.negotiation"` looked up in `vars`; an undeclared key raises `DialogueConditionError` |
| `BoolOp` `And`/`Or` | yes | Python `and`/`or` over the values |
| `UnaryOp` `Not`, `USub` | yes | `not` / negation |
| `BinOp` `+ - * %` | yes | the matching `operator` function; **division (`/`, `//`) is not an allowed operator** |
| `Compare` (`== != < <= > >=`) | yes | chained comparison |
| `Call` | **only** a bare `Name` in the call whitelist (`has_item`), string-literal args | the whitelisted lambda `has_item(item_id)` |
| anything else (`Lambda`, `Subscript`, `Comprehension`, `IfExp`, …) | **no** | `raise ValueError` |

The `Attribute` rule is safe because the chain is used as a *key*, never as an attribute access on
a live object: `rep.fixer` resolves the single key `"rep.fixer"` in `vars`. `(1).__class__` is a
`Constant`-rooted chain, so it is rejected. **An undeclared name is not `None` and is not a
`NameError` — it is a content bug the loader rejects at load time and the runtime raises on**
(`DialogueConditionError`). `dialogue.md` owns this rule: conditions are expressions over a
*declared* variable store, so an unknown name can never be silently falsy. `Call` is allowed only
when the callee is a bare `Name` in the whitelist, so `has_item('chip')` resolves while `open(...)`
and `__import__('os')...` are rejected (their callees are not in the whitelist). This is the whole
security argument and it is enforced by the self-check's malicious inputs.

### Complexity

`D` = nodes ≤ 100, `E` = edges (each node's `next` plus its choices) ≤ ~300.

| Operation | Time | Space |
|---|---|---|
| `start` / `choose` / auto-advance | O(1) per node visited; a chain of `c` effect nodes drains in O(c) | O(c) queue |
| condition eval | O(len(expr)) parse + O(ast nodes) walk | O(ast nodes) |
| `validate()` | O(D + E) DFS/BFS once per dialogue file, at load | O(D) |
| whole conversation | O(nodes visited) | — |

Cache parsed conditions by expression string: authoring files reuse the same condition text, and
`ast.parse` is the only non-trivial cost here.

### Pseudocode

```
def run(graph, ui, vars, localize):
    queue = deque([graph.start])
    while queue:
        nid = queue.popleft()
        node = graph.nodes[nid]
        apply_effects(node.get("effects", []), vars)          # snapshot RHS, then commit
        if node.get("end"): ui.close(); return
        if len(node.get("choices", [])) > 0:
            shown = [c for c in node["choices"]
                     if evaluate(c.get("cond"), vars)]        # only passing choices are shown
            ui.show_line(node.get("speaker",""), localize(node["line"]))
            return ui.show_choices(shown)                     # suspend; the UI calls choose() later
        if node.get("line"): ui.show_line(node.get("speaker",""), localize(node["line"]))
        if node.get("goto"): queue.append(node["goto"])       # chain continues in this pass
        elif node.get("line"): return ui.show_continue()      # a line with no jump waits for input
    ui.close()

def choose(graph, ui, vars, localize, choice):
    apply_effects(choice.get("effects", []), vars)            # effects belong to the TRANSITION
    run_from(graph, ui, vars, localize, choice["goto"])

def apply_effects(effects, vars):
    staged = {}                                               # snapshot: `a: b` and `b: a` don't see
    for e in effects:                                         # each other's new values
        if   e["op"] == "set":       staged[e["set"]] = evaluate(e["value"], vars)
        elif e["op"] == "give_item": ...                      # routed to the crew inventory
        elif e["op"] == "start_job": ...
        elif e["op"] == "change_rep": ...
    vars.update(staged)

def validate(graph):
    missing = [n["goto"] for n in graph.nodes.values()
               if n.get("goto") and n["goto"] not in graph.nodes]
    assert not missing, f"unresolved goto: {missing}"         # every goto resolves
    for n in graph.nodes.values():
        for c in n.get("choices", []): assert c["goto"] in graph.nodes
        assert n.get("goto") or n.get("choices") or n.get("end"), "dead-end node"
        for c in n.get("choices", []):
            check_condition(c.get("cond"), graph.declared)   # parses AND every name is declared
    seen, stack = set(), [graph.start]                        # reachability from start
    while stack:
        nid = stack.pop()
        if nid in seen: continue
        seen.add(nid)
        n = graph.nodes[nid]
        stack.append(n["goto"]) if n.get("goto") else None
        stack += [c["goto"] for c in n.get("choices", [])]
    unreachable = set(graph.nodes) - seen                     # no unreachable nodes
    assert not unreachable, f"unreachable nodes: {unreachable}"
```

`next`-only chain nodes are drained by the queue without ever asking the UI, which is the "explicit
queue runner" of §13. `check_condition` walks the same whitelisted ast with a recording store stub,
so an undeclared variable is a **load-time** error (`dialogue.md` E6) rather than a runtime
surprise.

### Canonical reference

`dialogue-systems/references/runner.md` (graph schema, sandboxed evaluator, runner state machine,
validation checklist) — the reference implementation this is derived from, which is itself the
skill's answer to "build a graph interpreter, never a language". Contrast reading for the
build-vs-buy decision: Ink (`inklestudios/ink`) and Yarn Spinner docs, both rejected in ADR-0010.

### Runnable self-check

```python
if __name__ == "__main__":
    def demo():
        vars = {"rep.fixer": 3, "heat": 2, "skill.negotiation": 5, "job.accepted": False}

        # ---- malicious expressions must RAISE, never execute --------------------------------
        for evil in ["__import__('os').system('echo pwned')",
                     "open('/etc/passwd').read()",
                     "(1).__class__.__mro__",
                     "exec('x=1')",
                     "lambda: 1",
                     "[x for x in range(10)]"]:
            try:
                evaluate(evil, vars); assert False, f"executed: {evil}"
            except (DialogueParseError, DialogueConditionError, ValueError, SyntaxError):
                pass

        # ---- legitimate expressions, including the dotted names §11 uses --------------------
        assert evaluate("skill.negotiation >= 4", vars) is True
        assert evaluate("rep.fixer > 5", vars) is False
        assert evaluate("heat + 1 == 3 and job.accepted == False", vars) is True
        assert evaluate(None, vars) is True                    # absent condition = unconditional
        # ---- an undeclared name is a load-time/runtime error, never a silent None ------------
        try:
            evaluate("missing.name", vars); assert False
        except DialogueConditionError:
            pass

        # ---- validation: unresolved goto, dead end, unreachable node -------------------------
        bad = {"start": "a", "nodes": [
            {"id": "a", "line": "L", "choices": [{"text": "t", "goto": "nope"}]}]}
        try: validate(graph(bad)); assert False
        except AssertionError: pass
        orphan = {"start": "a", "nodes": [
            {"id": "a", "end": True}, {"id": "z", "end": True}]}
        try: validate(graph(orphan)); assert False             # z is unreachable
        except AssertionError: pass
        undeclared = {"start": "a", "nodes": [
            {"id": "a", "choices": [{"text": "t", "cond": "missing.name > 1", "goto": "b"}]},
            {"id": "b", "end": True}]}
        try: validate(graph(undeclared)); assert False         # undeclared name rejected at LOAD
        except DialogueConditionError: pass
        ok = {"start": "a", "nodes": [
            {"id": "a", "line": "L", "choices": [{"text": "t", "goto": "b"}]},
            {"id": "b", "end": True}]}
        validate(graph(ok))                                    # must not raise
        # ---- an on-disk array with a duplicate id is diagnosable (an object would hide it) --
        dupe = {"start": "a", "nodes": [
            {"id": "a", "end": True}, {"id": "a", "end": True}]}
        try: graph(dupe); assert False                         # loader rejects the duplicate id
        except AssertionError: pass
    demo()
```

---

## 11. Save — schema-versioned JSON with a migration function per version

*DECISIONS §13 row 11. Semantics: §9 Persistence, §14.3; rationale ADR-0012.*
*Vocabulary: **Crew**, **Hub**, **Heat**, **Perk**, **Advance** (CONTEXT.md).*

### Data structure chosen

One JSON document with a top-level integer `schema_version` and **four roots** — `campaign`,
`crew`, `world`, and `job` — matching ADR-0012's two persistent state graphs and world.md §10.4's
field names. Per-Run state is **not** saved: only the `run_seed` is, and the Site is regenerated
from it (§9: "Site layout, enemy placement, and the Clock reset per Run, generated from a seed").

The alternative it beat: **pickle / object graphs**. Pickle ties the file to class definitions, so
any refactor breaks every old save, and it is arbitrary-code-execution on load — disqualifying for
a file the player owns. JSON forces the discipline the `save-systems` skill demands: save *data*,
reconstruct objects on load.

Second alternative, **one file per state graph**: rejected because the roots are versioned
together by ADR-0012 and a single atomic write cannot half-commit across two files.

### What is stored vs recomputed

| Stored (authoritative) | Reconstructed on load (derived) |
|---|---|
| `crew.runners[]`: `class`, `attributes`, `skills`, `xp`, `perks`, `condition`, `loadout`, `totem`, and the **Edge rating** | Dice Pools, Wound Modifier, monitor maxima (§4) |
| `crew.nuyen`, `crew.stash` | Site `tiles`, enemy placement, devices (from `run_seed`, §10) |
| `world.heat`, `world.rep` (fixer + factions), `world.flags` | Security Clock segments (per Run) |
| `campaign.hub_day`, `job_count`, `advance_log`; `job.active`, `job.offers`, `job.run_counter`, `run_seed` | — |

**Never persist `qi`.** Qi is per-Run (DEC §6): it resets to the pool at Run start, so it belongs
with the per-Run state the save discards. **Edge is two concepts and both are named precisely:** the
**Edge rating** lives on the sheet and persists; **Edge points** are a per-Run pool refreshed at the
start of each Run and are never written.

Saving derived values invites desync when a formula changes in a patch and bloats the file
(`versioning-and-migration.md`). The monitor maxima are the clearest example: `8 + ceil(Body/2)`
(§4) must be recomputed, never stored.

### Complexity

`n` = crew (4). Save size is O(campaign + crew + world + job) ≈ a few KB.

| Operation | Time | Space |
|---|---|---|
| `dump` / `load` | O(size) | O(size) |
| migrate v→v+1 | O(size) per step; ≤ current version steps | O(size) |
| atomic write | O(size); 1 temp file + 1 rename | 2× file size on disk briefly |

### Pseudocode

```
SAVE_VERSION = 1

MIGRATIONS = { }        # v1 is the first version; each future change adds {1: migrate_1_to_2, ...}

def capture(campaign, crew, world, job):
    return {"schema_version": SAVE_VERSION,
            "campaign": campaign.to_data(),            # hub_day, job_count, advance_log
            "crew":     crew.to_data(),                # nuyen, runners[], stash — no qi, no edge points
            "world":    world.to_data(),               # heat, rep, flags
            "job":      job.to_data()}                 # active job, offers, run_counter, run_seed

def write_atomic(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, sort_keys=True)             # sort_keys: stable bytes for a diff/test
        f.flush(); os.fsync(f.fileno())
    if os.path.exists(path):
        shutil.copyfile(path, path + ".bak")          # keep the last good save before replacing
    os.replace(tmp, path)                              # atomic on POSIX

def read(path):
    data = json.loads(open(path, encoding="utf-8").read())
    v = data.get("schema_version", 1)
    if v > SAVE_VERSION: raise NewerSaveError(v)       # refuse, never guess
    while v < SAVE_VERSION:
        data = MIGRATIONS[v](data); v += 1; data["schema_version"] = v
    validate_save(data)                                # required keys, ranges, known item ids
    return data
```

Each migration is a pure `vN -> vN+1` function; old migrations are kept forever
(`versioning-and-migration.md`). The load path validates before instantiating and falls back to
`.bak` on a parse error. The single schema-versioned slot is settled (§9, §14.3), so the
`read`/`write_atomic` pseudocode targets one slot plus one `.bak`.

### Canonical reference

`save-systems/references/versioning-and-migration.md` — the version field, the migration chain,
atomic temp+rename writes, the backup, and the load-time validation checklist. Framework reference
for the pattern: `godot-resources`/`unity-scriptableobjects` are the engine analogues, not used
here (Python + JSON).

### Runnable self-check

```python
if __name__ == "__main__":
    def demo():
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "save.json")

        # ---- round-trip ---------------------------------------------------------------------
        data = {"schema_version": 1,
                "campaign": {"hub_day": 12, "job_count": 7},
                "crew": {"nuyen": 38500,
                         "runners": [{"id": "adept", "attrs": {"Body": 6}, "edge": 3}]},
                "world": {"heat": 2, "rep": {"fixer": 3}},
                "job": {"active": {"id": "paydata_01", "run_counter": 0, "run_seed": 12345}}}
        write_atomic(path, data)
        assert read(path) == data
        assert "qi" not in data["crew"]["runners"][0]     # Qi is per-Run: never persisted

        # ---- a newer save is refused, not guessed at -----------------------------------------
        write_atomic(path, {**data, "schema_version": 99})
        try: read(path); assert False
        except NewerSaveError as e: assert e.version == 99

        # ---- migration v1 -> v2 (additive: a field gains a default) --------------------------
        def m1(d): d["world"].setdefault("heat_floor", 0); return d
        global MIGRATIONS, SAVE_VERSION
        MIGRATIONS, SAVE_VERSION = {1: m1}, 2
        write_atomic(path, data)
        out = read(path)
        assert out["schema_version"] == 2 and out["world"]["heat_floor"] == 0
        SAVE_VERSION, MIGRATIONS = 1, {}

        # ---- a corrupt file raises instead of loading garbage -------------------------------
        open(path, "w").write("{not json")
        try: read(path); assert False
        except json.JSONDecodeError: pass
    demo()
```

---

## 12. Actor and entity model

`CONTEXT.md` names five different things that occupy the world: a **Runner** (a member of the
**Crew**), an enemy, a **Spirit** (conjured by the Shaman, §7), a **device** (hacked by the
Decker, §7), and an item. The model below says how they relate.

### The split: Actors vs WorldObjects

> **Only things that take turns are Actors.**

An Actor has Energy and a place in the scheduler (§5). A WorldObject sits in a cell and is acted
*upon*. That single rule decides every case:

| Entity | Is it an Actor? | Why |
|---|---|---|
| Runner | yes | §5: Runners take Passes and spend Energy |
| Enemy (Guard, Drone, Ganger, Corp Mage, Hellhound) | yes | §8: every non-player actor is a Behavior Tree |
| Spirit | yes | §7: "a Spirit lasts 3 rounds", it acts; §8: "the only friendly actors with a brain" |
| Drone | yes | §8 lists Security Drone as an enemy archetype that *flies* and patrols |
| Device (gun, optics, door, lights, commlink, drone-as-target) | **no** | §7: hacking resolves *immediately*; a door never takes a turn |
| Item, loot, corpse | **no** | no Energy, no brain; corpses are landmarks ("Body found" +3, §9) |

The alternative — one `Entity` base class carrying Energy, monitors, and a blackboard for
everything — forces items and doors to carry fields that mean nothing, and invites a door into the
scheduler. The alternative — four subclasses of `Actor` — duplicates the entire combat/monitor/
Energy code four times, and puts Spirit-only state (`summoner_id`, `rounds_left`) on Runners.

**Composition over inheritance, concretely.** `Actor` holds the universal turn-taking/combat
fields. What differs between a Runner, an enemy, and a Spirit is a **role component** attached to
`role`, present only on the kinds that need it.

```python
@dataclass
class Actor:
    id: int                       # stable, unique per Run; the §5 tie-break key
    name: str
    faction: str                  # "crew" | "security" | "spirit" | "neutral"
    pos: tuple[int, int]          # cell
    facing: int                   # 0..7, one of the 8 directions (§5)
    glyph: int                    # the ONE codepoint drawn in this cell (ADR-0004)
    tint: tuple[int, int, int]    # foreground recolour (§12)
    attrs: dict[str, int]         # §1: Body..Edge
    skills: dict[str, int]        # §2: the thirteen skills
    physical: Monitor             # §4: max = 8 + ceil(Body / 2)
    stun: Monitor                 # §4: max = 8 + ceil(Willpower / 2)
    cover: int = 0                # §4: +2 while in cover
    effects: list[Effect] = ()    # §6/§7 durations: blinded, burning, hacked, sustaining…
    score: int = 0                # §5: Initiative Score for the current Round
    energy: int = 0               # §5: Energy left in the current Pass
    pass_no: int = 0              # §5
    improved_reflexes_dice: int = 0   # §6: Qi Improved Reflexes adds 1d6 (§5 caps at +2d6)
    gear: list[DeviceRef] = ()    # §7: carried devices that the Decker can hack
    role: RunnerRole | EnemyRole | SpiritRole | None = None
    bt: BTState | None = None     # None <=> player-controlled (the four Runners, §7)
    bb: Blackboard | None = None

@dataclass
class Monitor:                    # §4
    boxes: int = 0                # filled boxes
    def max(self, attr): return 8 + ceil(attr / 2)
    def fill(self, n, attr):      # returns Overflow across the Stun->Physical 2:1 rule (§4)
        ...

@dataclass
class RunnerRole:                 # §7
    klass: str                    # "adept" | "mage" | "shaman" | "decker"
    edge: int = 3                 # §6
    qi: int = 0                   # §6, Adept only
    tradition: str | None = None  # §6: "Logic" (Mage/Decker) or "Charisma" (Shaman)
    inventory: list[ItemRef] = ()
    xp: int = 0                   # §2 Growth
    perks: list[str] = ()
    sustaining: list[str] = ()    # §6: each costs −2 dice

@dataclass
class EnemyRole:                  # §8
    archetype: str                # "corp_guard" | "security_drone" | "ganger" | "corp_mage" | "hellhound"
    weights: Weights              # §8: per-archetype utility weights
    target_hysteresis: float      # §8: how far a challenger must beat the incumbent, 0.05–0.25
    home_pos: tuple[int, int]
    flees_at_wound: int | None    # §8: Ganger flees at −3; Hellhound never flees (None)

@dataclass
class SpiritRole:                 # §7
    summoner_id: int
    spirit_type: str              # "beast" | "air" | "earth" | "water"
    rounds_left: int = 3          # §7
    hostile: bool = False         # §7: a failed Conjuring or a Glitch sets this

@dataclass
class WorldObject:                # never ticks
    id: int
    kind: str                     # "device" | "item" | "corpse"
    pos: tuple[int, int]
    glyph: int
    tint: tuple[int, int, int]
    state: dict                   # device: {rating, hacked_until, disabled_until}
                                  # item:   {type, qty}
                                  # corpse: {actor_id, faction}
```

### Relationships, spelled out

| Relationship | Shape | Note |
|---|---|---|
| Crew → Runner | 1:4, fixed | §7 / ADR-0002: all four from creation, no recruitment |
| Runner → RunnerRole | 1:1, always | `bt is None`: the player drives it (§7) |
| Enemy → EnemyRole | 1:1, always | `bt` is always set; the archetype selects the JSON tree (ADR-0009) |
| Spirit → SpiritRole | 1:1, always | `summoner_id` points at the Shaman's `Actor.id` |
| Shaman → Spirits | 1:0..k | a conjured Spirit is a full Actor; the Shaman does not puppeteer it (§8) |
| Decker → Device | many:many | a hack is an `Effect` on the target, applied immediately (§7, ADR-0008) |
| Actor → Actor | possession-free | inventory holds `ItemRef` ids, not objects, so saves stay flat |
| Drone | **Actor *and* hackable** | the one entity that is both: an Actor whose `gear` includes its own chassis device. A flag, not a class |

The Drone is worth calling out because it is the case that would tempt a hierarchy
(`HackableActor(Enemy)`). It is handled by `gear: list[DeviceRef]` on every Actor: an enemy's gun
(§7 rating 2) and a Drone's chassis (rating 4) are both entries in the same list, and the Decker's
hack is the same code path for a door and for a Drone. That is ADR-0008's "device layer is content,
not systems" expressed in the model.

### Complexity

| Operation | Time | Space |
|---|---|---|
| build a Run (≤ 48 actors, each a dataclass) | O(n) | O(n) |
| occupancy lookup | O(1) via a `dict[(x,y)] -> actor_id` index rebuilt on move | O(n) |
| all actor components | — | O(n) ≈ 48 objects, tens of KB |
| serialize/deserialize the crew | O(n) | O(n) |

An **occupancy index** (`dict[cell, actor_id]`) is maintained by the Run beside the actor list, so
"who is in this cell?" (bump-to-attack, Spirit conjuring, hacking range) is O(1) instead of a scan
over 48 actors. It is a derived cache, rebuilt on `move`, never saved.

### Canonical reference

Bob Nystrom, *Game Programming Patterns* — *Component* (and the *Type Object* pattern for
archetypes-as-data). The concrete decision rule ("only turn-takers are Actors") is this project's,
derived from §5 and §8.

### Runnable self-check

```python
if __name__ == "__main__":
    def demo():
        spirit = Actor(id=9, name="beast", faction="spirit", pos=(1, 1), facing=0,
                       glyph=ord("b"), tint=(0, 0, 0),
                       attrs=dict.fromkeys(ATTRS, 3), skills=dict.fromkeys(SKILLS, 3),
                       physical=Monitor(0), stun=Monitor(0),
                       role=SpiritRole(summoner_id=1, spirit_type="beast"),
                       bt=BTState(tree=Node(ACTION)))
        # ---- a Spirit is a full Actor: it has Energy and a tree ------------------------------
        assert spirit.bt is not None and spirit.energy == 0
        assert spirit.role.rounds_left == 3 and spirit.role.hostile is False

        runner = Actor(id=1, name="adept", faction="crew", role=RunnerRole(klass="adept", qi=4))
        # ---- a Runner has no tree: the player drives it --------------------------------------
        assert runner.bt is None and runner.role.edge == 3 and runner.role.qi == 4
        # ---- Spirit-only state does not exist on the Runner ----------------------------------
        assert not hasattr(runner.role, "summoner_id")

        door = WorldObject(id=5, kind="device", pos=(3, 3), glyph=ord("+"),
                           tint=(0, 0, 0), state={"rating": 2, "hacked_until": None})
        # ---- a device is not an Actor: no Energy, no pass, no blackboard ---------------------
        assert not hasattr(door, "energy") and not isinstance(door, Actor)

        # ---- monitor maxima are derived, never stored (§4) -----------------------------------
        assert Monitor(0).max(attr=6) == 8 + 3          # Body 6 -> 8 + ceil(6/2) = 11
        assert Monitor(0).max(attr=5) == 8 + 3          # Willpower 5
    demo()
```

---

## 13. Scheduler ↔ Behavior Tree ↔ input integration

Three claims, each with the code path that enforces it.

### Who owns turn order state

**The `Scheduler` owns it, exclusively.** The agenda (§5 `BucketQueue`), each actor's `score`,
`energy`, and `pass_no` are written only by `scheduler.begin_round`, `scheduler.pop_max`,
`scheduler.end_turn`, and `scheduler.end_pass`. Neither the Behavior Tree ticker nor the input
layer is allowed to touch them. Consequence: a tree cannot "give itself another turn", and an input handler cannot reorder
initiative. The ties in §5 ("higher Reaction, then lower actor id") are resolved in `pop_max`, in
one place.

### The loop

```
def play_round(run, ui):
    scheduler.begin_round(run.actors, run.rng["rules.initiative"])
    while (actor := scheduler.pop_max()) is not None:
        action = acquire_action(actor, run, ui)          # the ONLY branch on player vs AI
        applies(actor, action, run)                      # charge Energy, reinsert or end the Pass

def acquire_action(actor, run, ui):
    if actor.bt is None:                                 # a Runner: the player owns it (§7)
        return ui.get_action(actor, run)                 # blocks; returns one Action
    status = bt.tick(actor)                              # one tick == one action leaf == one Action
    if status == FAILURE: return None                    # nothing worth doing; see below
    return run.bb_action.get(actor.id)                   # the Action the tick's leaf performed

def applies(actor, action, run):
    if action is None:
        scheduler.end_pass(actor)                        # a FAILURE root ends its Pass, spending nothing
        return
    rules.resolve(actor, action, run)                    # §3/§4/§6/§7: roll, damage, effects
    scheduler.end_turn(actor, action.energy_cost)        # §5: charge Energy, Pass logic
```

`ui.get_action` (an `input.py` concern) and `bt.tick` (a `bt.py` concern) produce the **same
`Action` shape** — `Step(direction)`, `Attack(target_id)`, `UsePower(power, args)`, `Aim`,
`Reload`, `TakeCover`, `UseItem(id)`, `StandUp`. Only the branch at `acquire_action` knows which
one it is. This is the `input-systems` rule "never wire gameplay to raw keys" taken one step
further: **an enemy's melee and a player's melee are the same `Action`**. Spirit control is settled
as the §14.3 shape — a Spirit always has `bt` set and takes a target the player assigns — so the
`bt is None` branch stays exactly "the four Runners".

### The three integration rules

1. **One tick = one Action = one Energy charge.** A Behavior Tree `Action` leaf performs exactly
   one Energy-costing world action and returns RUNNING if it needs another turn. The scheduler
   charges the cost; the ticker never touches `energy`. This makes a multi-turn `MoveTo` behave
   identically to a player holding a direction.
2. **The BT suspends, the scheduler advances.** `bt.tick` returns after one Action leaf with the
   frame stack intact (§8). The next time the scheduler pops that actor, `tick` resumes on the same
   leaf. There is no per-frame ticking and no wall-clock delta — a turn-based tree has no `dt`.
3. **A tree with nothing to do ends its Pass without spending Energy.** A tick whose root returns
   FAILURE yields no Action, so `applies` calls `scheduler.end_pass(actor)` and never `end_turn`:
   the Pass ends, the Score drops by 10, and **no Energy is charged** (ai.md §3.1, "a FAILURE root
   ends the Pass without spending"; ai.md §11's test 19 asserts it). Charging `PASS_END_THRESHOLD`
   on this path would bill 1 Energy for a decision step that did nothing, re-insert the actor into
   the same Pass, and repeat — an actor burning Energy in a "think" loop, and every Root failing
   grinding the whole Round through those charges. The actor is re-inserted only at its next Pass,
   and because `end_pass` drops the Score too, a Round where every tree fails still terminates.

### Player input specifics

- Input is mapped to named actions, never keys (`input-systems`): a directional press becomes
  `Step(direction)` at 1 Energy, not a tile mutation. `Sprint` is the same `Step` with a
  `sprinting` flag that bills 2 Energy per 3 tiles (§5) and applies the −2 defence malus.
- The input layer never mutates the world. It returns an `Action`; `rules.resolve` validates it
  (is it this actor's turn? is the target in range? is the Pass still open?) and applies it.
  Range is the §4 contract: pistol 8, SMG 10, rifle 14, shotgun 6, spells 12 with line of sight,
  and 1 cell for every melee and natural weapon (katana, stun baton, Hellhound bite, Spirit strike).
- A rejected action does **not** charge Energy and re-prompts. A rejected *AI* action is a bug and
  should assert rather than silently skip — a tree that proposes an illegal action means the tree
  and the rules disagree.

### Runnable self-check

```python
if __name__ == "__main__":
    def demo():
        # a scripted two-actor round: actor 1 is player-controlled, actor 2 has a tree
        run = build_demo_run()                            # Runner(1) bt=None, Enemy(2) with a MoveTo
        run.rng["rules.initiative"] = random.Random(0)

        scripted = [Step(direction=0), Attack(target_id=2)]     # the player's scripted answers
        ui = ScriptedUI(scripted)
        sched = Scheduler()
        seen = []
        sched.begin_round(run.actors)
        while (a := sched.pop_max()) is not None:
            act = acquire_action(a, run, ui)
            seen.append((a.id, type(act).__name__ if act else None))
            applies(a, act, run)
        # ---- turn order is owned by the scheduler, not by the tree or the input -------------
        assert [i for (i, _) in seen][0] == max(run.actors, key=lambda x: (x.energy, x.attrs["Reaction"], -x.id)).id
        # ---- an AI action and a player action are the same type ------------------------------
        assert all(t in ("Step", "Attack", None, "Aim") for (_, t) in seen)
        # ---- a FAILURE root ends the Pass without spending Energy (ai.md §3.1, test 19) -------
        class FailingBT:                              # a tree whose root returns FAILURE
            def tick(self, actor): return FAILURE
        idle = Actor(id=9, name="idle"); idle.bt = FailingBT()
        idle.score = idle.energy = 12; idle.pass_no = 0
        assert acquire_action(idle, run, ui) is None  # no Action: nothing worth doing
        applies(idle, None, run)
        assert idle.pass_no == 1 and idle.score == 2  # the Pass ended...
        assert idle.energy == 2                       # ...and not one Energy was charged for it

        # ---- Energy was charged by the scheduler, and the tree never wrote it ---------------
        enemy = next(a for a in run.actors if a.bt is not None)
        assert enemy.energy < enemy.score              # at least one action was charged
        assert enemy.bb.current_target is not None     # the tree wrote the blackboard, not Energy
    demo()
```

---

## 14. Determinism and seeding

### The rule

> A **Run** is a pure function of `run_seed`. Same seed → identical Site, identical enemy
> placement, identical dice, identical AI choices, and therefore an identical state hash after the
> same sequence of player inputs.

`run_seed` is derived per §9 ("a seed of `job id + run counter`"), then **stored** in the save as
the derived integer rather than recomputed on load (§9 Persistence, §14.3), so renaming or
renumbering a Job later cannot silently change an in-flight Run. This is settled, not proposed.

### Per-subsystem streams

`random.Random` instances, one per subsystem. A module-level `random.*` call anywhere is a bug.

```
def derive(seed, name):
    h = hashlib.sha256(f"{seed}:{name}".encode()).digest()
    return int.from_bytes(h[:8], "big")

def make_rngs(run_seed, actor_ids):
    rng = {name: random.Random(derive(run_seed, name)) for name in STATIC_STREAMS}
    for aid in actor_ids:                                  # one stream per brain
        rng[f"ai:{aid}"] = random.Random(derive(run_seed, f"ai:{aid}"))
    return rng
```

**`derive(run_seed, name)` over per-subsystem stream names is the ONE seeding scheme for the whole
project.** Every stream below is `random.Random(derive(run_seed, name))`; no subsystem invents its
own seed arithmetic. This supersedes `world.md` §5.5's `seed_graph = site_seed ^ 0x01` (and its
FNV-1a sibling-seed variant): XOR-derived sibling seeds couple one subsystem's stream to another,
so a change to the graph pass can silently shift placement. Hashing a stream *name* keeps each
stream independent of every other. `run_seed` is the one integer that is **stored** (below), so it
and every stream derived from it survive a code change.

| Stream | Owner | Consumes | Isolation it buys |
|---|---|---|---|
| `gen.graph` | `mission_graph.py` | node kinds, edge counts, side-branch rolls | adding a room cannot shift combat dice |
| `gen.embed` | `embed.py` | BSP cut positions, corridor L-vs-⌐ choice, room insets | adding a corridor cannot shift loot |
| `gen.place` | `placement.py` | enemy/loot/device placement, weighted tables | placement is independently reproducible |
| `rules.initiative` | `scheduler.py` | the §5 `1d6` (+1d6 per Improved Reflexes) | a player's attack choice cannot re-roll the round's initiative |
| `rules.combat` | `rules.py` | all Dice Pools (§3), soak, Drain (§6), Glitches | combat is order-dependent *by design*; it is isolated from generation |
| `loot` | `placement.py` | weighted loot tables | a drop cannot perturb a later spawn roll |
| `ai:<actor_id>` | `ai.py` | utility softmax (if enabled), any stochastic choice | actor 5's choices are unaffected by actors 1–4 or by tick order |

**Why per-actor AI streams matter.** With one shared `ai` stream, inserting an extra guard
consumes a draw and silently changes every other enemy's subsequent behaviour — the "same seed,
different game" bug that is miserable to debug. With `ai:<id>`, each brain's sequence is
independent of how many other brains exist. This is the `ai-behavior-trees-utility-ai` pitfall
"Seed the `System.Random` used by softmax per agent. Never use a shared global RNG across agents,"
made concrete.

**Why generation and combat are separate.** Generation runs once, before the first action; combat
runs many times. If they shared a stream, every extra combat roll would change the *next* Run's
map — because the stream is per-Run and generation would then start from a shifted position. The
split makes "regenerate the current Site from `run_seed`" a guaranteed-identical operation, which
is exactly what the save needs (§11).

### Sources of non-determinism to forbid

| Forbidden | Why | Rule |
|---|---|---|
| `import random; random.random()` | global, order-dependent, unseedable | always pass a named `Random` instance |
| `time.time()` / frame delta in game logic | a turn-based game has no `dt` (§8, §13) | cooldowns count **the actor's own Passes** |
| the builtin `hash()` | salted per process (`PYTHONHASHSEED`) | `derive()` uses sha256, never `hash()` |
| iterating a `set`/`frozenset` of objects | iteration order is not specified | iterate `list`s, or `sorted(..., key=id)` |
| `dict` iteration over freshly built dicts where order matters | insertion order is stable in CPython but invisible to the reader | sort explicitly when order is semantic |
| float accumulation in a priority key | equal-cost routes can flip on the last bit | monotonic integer `counter` tie-break in heaps (§3, §4) |
| `tcod`'s RNG or any engine RNG | not ours, not seeded by us | ADR-0004 keeps `tcod` out of layers 0–3 (§15) |

### Reproducibility self-check

```python
if __name__ == "__main__":
    def demo():
        def state_hash(run):
            return hashlib.sha256(json.dumps(run.to_data(), sort_keys=True).encode()).hexdigest()

        # ---- same seed -> identical Site ----------------------------------------------------
        a = build_site(seed=4242, job_id="paydata_01", counter=0)
        b = build_site(seed=4242, job_id="paydata_01", counter=0)
        assert bytes(a.map.tiles) == bytes(b.map.tiles)
        assert [(e.id, e.pos) for e in a.enemies] == [(e.id, e.pos) for e in b.enemies]

        # ---- a different run counter -> a different Site -------------------------------------
        c = build_site(seed=4242, job_id="paydata_01", counter=1)
        assert bytes(c.map.tiles) != bytes(a.map.tiles)

        # ---- a draw in one subsystem does not perturb another --------------------------------
        a.rng["gen.place"].random()                      # burn a *placement* draw
        assert bytes(a.map.tiles) == bytes(b.map.tiles)  # terrain unchanged: gen.embed untethered

        # ---- per-actor AI streams are independent --------------------------------------------
        rngs = make_rngs(4242, actor_ids=[1, 2, 3])
        s1 = [rngs["ai:3"].random() for _ in range(5)]
        rngs2 = make_rngs(4242, actor_ids=[1, 2, 3, 4])
        s2 = [rngs2["ai:3"].random() for _ in range(5)]
        assert s1 == s2                                  # actor 4's presence changes nothing for 3

        # ---- same seed + same inputs -> identical state --------------------------------------
        assert state_hash(run_scripted(4242, ["E", "N", "attack"])) == \
               state_hash(run_scripted(4242, ["E", "N", "attack"]))
    demo()
```

---

## 15. Module decomposition

```
pinkmohawk/
  constants.py      # every number from DECISIONS.md, named, commented with its §. Imports: none.
  rng.py            # derive(), make_rngs(), the STATIC_STREAMS registry. Imports: hashlib, random.
  unionfind.py      # DisjointSet: union by size + path compression. Imports: none.
  utility.py        # response curves, considerations, weighted scoring, hysteresis. Imports: math.
  grid.py           # TileMap: tiles / explored / visible bytearrays + bounds rules. Imports: array.
  fov.py            # recursive shadowcasting. Imports: grid.
  pathfinding.py    # a_star, chebyshev, reconstruct, flow_map, step_toward. Imports: heapq, grid.
  scheduler.py      # BucketQueue, HeapQueue (for the comparison), Scheduler, Pass/Round. Imports: heapq.
  mission_graph.py  # MissionGraph, build_graph, add_edge, validate. Imports: rng, unionfind.
  embed.py          # graph-aware BSP partition, room carving, L-corridors, connectivity repair.
                    # Imports: grid, mission_graph, unionfind, rng.
  placement.py      # devices / enemies / loot by node type, weighted tables. Imports: grid,
                    # mission_graph, rng, constants.
  bt.py             # node kinds, JSON loader, explicit-stack ticker, Blackboard, BTState.
                    # Imports: utility, constants.
  entities.py       # Actor, Monitor, RunnerRole, EnemyRole, SpiritRole, WorldObject, DeviceRef.
                    # Imports: constants.
  rules.py          # Dice Pools, damage/soak, Drain, Energy costs, Action resolution.
                    # Imports: entities, constants, rng.
  security.py       # the Security Clock: segments, the §9 event table, Alert/Lockdown/Converge.
                    # Imports: constants.
  ai.py             # perception, blackboard fill, archetype tree library, action emission.
                    # Imports: bt, utility, fov, pathfinding, rules, entities.
  dialogue.py       # graph + runner + ast evaluator + validate(). Imports: ast, operator.
  save.py           # capture/read/write_atomic, SAVE_VERSION, MIGRATIONS. Imports: json, os.
  run.py            # RunState composition root: grid + actors + scheduler + clock + rngs.
                    # Imports: everything in layers 0-3.
  hub.py            # Hub, Legwork, economy, Heat decay. Imports: entities, save, constants.
  render.py         # the ONLY display module. tcod console, Tileset remaps, Glyph draw order,
                    # Memory dimming. Imports: tcod, grid, entities, constants.
  input.py          # tcod event -> Action mapping, action-name bindings. Imports: tcod, constants.
  main.py           # window, event loop, wiring. Imports: tcod, run, hub, render, input.
```

### Layer law

| Layer | Modules | May import |
|---|---|---|
| 0 | `constants`, `rng`, `unionfind`, `utility`, `dialogue`, `save` | stdlib only |
| 1 (algorithms) | `grid`, `fov`, `pathfinding`, `scheduler`, `mission_graph`, `embed`, `placement`, `bt` | layer 0, `grid` |
| 2 (domain) | `entities`, `rules`, `security` | layers 0–1 |
| 3 (glue) | `ai`, `run`, `hub` | layers 0–2 |
| 4 (tcod) | `render`, `input`, `main` | layers 0–3 + `tcod` |

Three rules, in priority order:

1. **`tcod` appears in exactly three files.** `render.py`, `input.py`, `main.py`. Nothing in layers
   0–3 may `import tcod`. This is ADR-0004 ("hand-written algorithms beneath tcod") made mechanical
   — and it is what lets every algorithm in this document be exercised headless by its `__main__`
   self-check with no window.
2. **Algorithms do not import `entities`.** `fov`, `pathfinding`, `scheduler`, `mission_graph`,
   `embed`, `bt`, and `utility` operate on coordinates, arrays, and plain data. `bt` receives an
   `eval_leaf` callback and a blackboard; it does not know what a Runner is. This keeps the practice
   code testable and keeps the dependency arrow pointing one way.
3. **No cycles.** Layer N imports only layers < N (plus its own layer where noted: `embed` →
   `grid`, `mission_graph`; `ai` → `run` only through the callback in `run.py`, never a module
   import). If a module needs something from a higher layer, the dependency is wrong.

### Enforcing rule 1 with a self-check

```python
# tests are not a directory in this phase; this lives in main.py's __main__ or a make target
if __name__ == "__main__":
    def demo():
        import pathlib, re
        root = pathlib.Path("pinkmohawk")
        importers = {p.name for p in root.glob("*.py")
                     if re.search(r"^\s*import\s+tcod|^\s*from\s+tcod", p.read_text(), re.M)}
        assert importers == {"render.py", "input.py", "main.py"}, importers
    demo()
```

### Canonical reference

Robert C. Martin, *Clean Architecture* — the Dependency Rule (source dependencies point inward),
applied here as a `tcod`-at-the-edge discipline. The concrete module list is derived from §13's
subsystem table and ADR-0004.

---

## 16. Where the difficulty actually lives

Three subsystems will eat a week, in this order of risk. The roadmap should sequence them first and
leave slack around each.

1. **Embedding (§7) — graph topology onto 2D space.** Everything is easy until a side branch has to
   attach without crossing the main path, a corridor has to route around a room it was not told
   about, and an L-corridor has to stop poking a hole in the vault wall. The failure is silent and
   *visual* — the connectivity assert passes while the Site reads like noise, and ADR-0011 makes
   layout quality entirely dependent on it. Budget the most time here, and build the room-count,
   no-overlap, and reachability asserts **before** tuning how it looks.
2. **The Behavior Tree ticker (§8) — suspend, resume, and abort.** The three-valued contract looks
   trivial and is not. The bugs are always the same three: a RUNNING leaf restarted from the root
   (multi-turn actions never progress), a composite that advances its child index after RUNNING
   (skipping the rest of the sequence), and a missing `reset` on an abandoned branch (a "wait 2
   turns" that returns instantly the second time). None of them throw. The self-check's "Condition
   runs exactly once" assertion is the cheapest possible defence and should be written on day one.
3. **Recursive shadowcasting (§2) — the slope arithmetic and the octant transforms.** This is the
   classic swamp: an off-by-half in `l_slope`/`r_slope` lights the cell behind the pillar, a wrong
   `MULT` tuple mirrors one octant, and the bug shows up only in one of eight directions. It is
   also the subsystem where a "looks right" screenshot is not evidence — the pillar-corner and
   diagonal-gap asserts are. Budget two days for the first octant and one for the seventh.

Honourable mention, deliberately *not* on this list: **the scheduler (§5)**. It is small, its data
structure is the simplest thing in the document, and it will not eat a week of *coding*. It will
eat a week of *balance* — ADR-0003 already warns that one number controls both turn frequency and
actions-per-turn. That is a tuning problem with the whole game attached, not an algorithm problem,
and it should be scheduled after the vertical slice exists.

**Disagreement with `docs/roadmap.md`, stated rather than smoothed over.** The roadmap's risk table
ranks the *coding* risks as Embedding, BT ticker + Utility, then the **scheduler**, and does not list
shadowcasting. This document swaps the last two: shadowcasting is the subsystem most likely to consume
*implementation* days (slope arithmetic that fails in one octant of eight), while the scheduler is the
subsystem most likely to consume *tuning* days. The roadmap's own mitigation for the scheduler — "freeze
§5 costs in Phase 1 and treat any change as a balance pass" — is a tuning mitigation, which is the same
claim this section makes. One of the two documents should move the FOV row into its risk table; the
difference is about which kind of week is at stake, not about how much work exists.

---

## 17. Open questions

Recommendations are the default; these are documented, not decided. Each is a parameter that does
not exist in `DECISIONS.md`.

1. **FOV symmetry.** Bergström's recursive shadowcasting is asymmetric; §13 names it, so it is the
   algorithm. **Recommended mitigation, no algorithm change:** an enemy may only target a Runner
   that both sees it and is seen by it, restoring fairness without switching to the symmetric
   variant. Confirm, or switch to symmetric shadowcasting (a different algorithm, and a change to
   §13). See §2's known-property note.
2. **Content-tuning constants not in `DECISIONS.md`:** `SIDE_CHAIN_P` (§6), `MIN_ROOM` and `MARGIN`
   (§7), and `MAX_ENERGY = 63` (§5). The ally-fire risk term must be authored 0..1 by content (§9)
   but has no single value. **Recommended defaults** are named where they are used; none of them is
   load-bearing for correctness, but each should land in `constants.py` with a comment.
3. **Per-archetype hysteresis values.** §8 settles that target switching needs the challenger to
   beat the incumbent by `target_hysteresis`, a value in **0.05–0.25 per archetype**, not one
   global constant. *Which* value each of the five archetypes uses is content tuning (the Corp
   Guard should be stickier than the Ganger). **Recommended** defaults live in `constants.py`;
   confirm against playtest rather than arithmetic.

---

## Sources

Skill files this document borrowed patterns from:

- `roguelike/SKILL.md` and `roguelike/references/generation-fov-loot.md` — the energy scheduler
  sketch, the FOV/explored-memory contract, connectivity passes, and the canvas for §1, §2, §5.
- `procedural-gen/SKILL.md`, `procedural-gen/references/noise.md`, and
  `procedural-gen/references/dungeon-generation.md` — seeded-RNG discipline, BSP partitioning,
  L-corridor carving, and the connectivity-validation pass for §6, §7, §14.
- `game-ai/SKILL.md`, `game-ai/references/pathfinding.md`, and
  `game-ai/references/behavior-trees.md` — the full A\* loop with the `counter` tie-break, the
  heuristic table, the flow-field note, and the three-valued tick contract for §3, §4, §8.
- `ai-behavior-trees-utility-ai/SKILL.md`, `references/behavior-tree-core.md`,
  `references/utility-ai-system.md`, and `references/best-practices-and-pitfalls.md` — the
  Blackboard, the `Reset()` abort contract, the reactive selector, the response-curve/normalisation
  rules, and the hysteresis bonus for §8, §9, and §14's per-agent RNG rule.
- `dialogue-systems/SKILL.md` and `dialogue-systems/references/runner.md` — the JSON graph schema,
  the whitelisted-`ast` evaluator, the runner state machine, and the validation checklist for §10.
- `save-systems/SKILL.md` and `save-systems/references/versioning-and-migration.md` — the version
  field, the migration chain, atomic temp+rename writes, and the load-time validation checklist for
  §11.
- `input-systems/SKILL.md` — "actions, not keys", and edge-vs-held, for §13's player-input path.

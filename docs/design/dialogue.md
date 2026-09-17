# Dialogue: the Dialogue Graph, the runner, and the shared variable store

Contract for the JSON **Dialogue Graph** (CONTEXT.md) and the runner that walks it. ADR-0010 is the decision: a custom JSON graph with a hand-written runner, conditions over a shared variable store, validation inside the runner. We build a graph and an interpreter, never a language — no expressions beyond a whitelisted `ast` subset, no `include`, no `divert`, no variables defined inside text.

Everything numeric in this document comes from `docs/design/DECISIONS.md` (§3, §9, §11). Anything that is not there is in **Open questions** with a recommendation, never silently invented.

The runner is pure Python and must not import `tcod`. The Hub and Site controllers own presentation; the runner owns flow, conditions, and effects. This is what makes a conversation testable headless.

---

## 1. File format

One conversation per file. Top level:

| Field | Type | Required | Rule |
|---|---|---|---|
| `id` | str | yes | `[a-z0-9_]+`; must equal the filename stem |
| `context` | `"hub"` \| `"site"` | yes | `"site"` means a Run is active (the Security Clock exists) |
| `cast` | object | yes | slug → display name. Slugs are `[a-z0-9_]+` |
| `pc` | str | no | cast slug that speaks for the Crew; defaults to `"pc"` |
| `interlocutor` | str | required if any node uses `npc.*` | cast slug whose Blackboard `npc.*` proxies to |
| `start` | str | yes | node id |
| `vars` | object | no | file-local flags: short name → bool default. Always stored as `flags.<name>` |
| `on_empty` | str | no | node id used if a choice set filters to empty at runtime (defensive backstop) |
| `nodes` | array | yes | node objects, each with its own `id` |

`nodes` is an **array**, not an object, for one reason: duplicate keys in a JSON object are silently last-wins in every parser we would use, so "duplicate id" could never be diagnosed. An array makes duplicates a normal validation error and matches DECISIONS §11, where the node carries its own `id`.

Minimal valid file:

```json
{
  "id": "corp_guard_smalltalk",
  "context": "site",
  "cast": { "guard": "Corp Guard", "pc": "Runner" },
  "interlocutor": "guard",
  "start": "guard_hail",
  "nodes": [
    { "id": "guard_hail", "speaker": "guard", "line": "Halt.", "end": true }
  ]
}
```

---

## 2. Node schema

### 2.1 Fields

| Field | Type | Applies to | Notes |
|---|---|---|---|
| `id` | str | every node | unique in the file, `[a-z0-9_]+` |
| `speaker` | str | any node with `line` | must be a key of `cast` |
| `line` | str | `line`, `choice` | display text; `{var}` and `{var:,}` placeholders (§2.4) |
| `choices` | array | `choice` | non-empty; layout in §2.3 |
| `cond` | str | `condition` | a condition expression (§5) |
| `then` / `else` | str | `condition` | node ids, both required |
| `effects` | array | `line`, `choice`, `command`, `end` | non-empty if present (§4) |
| `goto` | str | `line`, `command`, `jump` | node id |
| `end` | `true` | `line`, `command`, `end` | literal `true`, never `false` |

This is DECISIONS §11's node contract, settled: a node carries a `line` and/or `choices`, optional `effects` on entry, and **at most one flow terminator** (`goto` or `end`). It never yields both `choices` and `goto`, never both `goto` and `end`, never both `then` and `goto`.

### 2.2 Kinds, derived by precedence

The kind is derived from the fields present, highest precedence first. `speaker` does not affect the kind.

| # | Kind | Required | Forbidden | Terminator | Waits for player input |
|---|---|---|---|---|---|
| 1 | `choice` | `choices` | `cond`, `then`, `else`, `goto`, `end` | its `choices` | yes |
| 2 | `condition` | `cond`, `then`, `else` | `line`, `choices`, `effects`, `goto`, `end`, `speaker` | `then`/`else` | no |
| 3 | `line` | `speaker`, `line` | `cond`, `then`, `else` | `goto` or `end` | yes (continue) |
| 4 | `command` | `effects` | `cond`, `then`, `else`, `line`, `choices` | `goto` or `end` | no |
| 5 | `jump` | `goto` | everything else | `goto` | no |
| 6 | `end` | `end: true` | everything else | `end` | no |

Kinds 1–3 are the content nodes the UI sees; 2, 4, 5 are **silent routers**, walked without waiting for input. A `line` node with `choices` is kind `choice` (precedence 1) — the line is displayed and the choices are presented on the same screen.

Well-formed, one per kind:

```json
{ "id": "offer",      "speaker": "fixer", "line": "Pay is 12k.", "choices": [ { "text": "I'm in.", "goto": "accept" } ] }
{ "id": "gate_refusal", "cond": "rep.fixer < 0", "then": "refusal", "else": "offer" }
{ "id": "target_brief", "speaker": "fixer", "line": "Paydata, sub-level three.", "goto": "offer" }
{ "id": "haggle",     "effects": [ { "set": "flags.haggle_used", "value": true } ], "goto": "haggle_result" }
{ "id": "open",       "goto": "intro" }
{ "id": "guard_leave", "speaker": "guard", "line": "Move along.", "end": true }
```

Malformed, and the error each one produces (§7):

```json
{ "id": "a", "speaker": "fixer", "line": "Hi.", "goto": "b", "end": true }
// two terminators: 'goto' and 'end'

{ "id": "c", "cond": "heat >= 3", "line": "Hot?", "then": "d", "else": "e" }
// condition node cannot carry a 'line'

{ "id": "f", "speaker": "fixer", "choices": [ { "text": "Only if rich", "cond": "crew.nuyen >= 99999", "goto": "g" } ] }
// choice node has no unconditional choice

{ "id": "h", "speaker": "fixer", "line": "Hi.", "goto": "nope" }
// dangling goto 'nope'

{ "id": "i", "speaker": "ghost", "line": "Boo.", "end": true }
// speaker 'ghost' is not in the cast

{ "id": "j", "effects": [ { "set": "heat", "value": 3 } ], "goto": "i" }
// cannot write read-only variable 'heat'
```

### 2.3 Choice objects

| Field | Type | Required | Rule |
|---|---|---|---|
| `text` | str | yes | display text; same placeholder rule as `line` |
| `cond` | str | no | gate; absent means always shown |
| `goto` | str | yes | node id |
| `effects` | array | no | applied when this choice is selected (§4.3) |

Two invariants, both load-enforced:

1. **At least one choice in a node has no `cond`.** Without it, a gate set could filter to empty and stall the player. The unconditional choice is the exit — usually "Not interested.", "Leave", "I'm in."
2. **The first choice is unconditional.** Ordering rule for authors, not the runner.

### 2.4 Text placeholders

`line` and `text` may contain `{store.key}` or `{store.key:,}`. Resolution happens at display time against the live store:

- `{job.payout_agreed:,}` → `12,200` (comma thousands grouping)
- `{rep.fixer}` → `-1`
- unknown key → load error (§7)
- key known but value `None` at runtime → the literal `<MISSING:job.payout_agreed>` is displayed. Never a crash; a visible placeholder is a QA signal, exactly like a missing localization key.

Nested braces, format specs other than `:,`, and f-string syntax are not supported. `{` and `}` not part of a placeholder are a load error. This is substitution of declared variables, not a template language.

---

## 3. Effects catalogue and firing order

Each entry of an `effects` array is an object that names **exactly one** of the six effects by key; every other key in that object is that effect's own argument (`{"set": "job.accepted", "value": true}` names `set` and passes it `value`). Naming two effects in one object, or zero, is E21.

### 3.1 The six effects

| Effect | JSON | Validation | Effect |
|---|---|---|---|
| `set` literal | `{"set": "job.payout_agreed", "value": 12200}` | key declared and writable; literal type matches the declared type | assigns |
| `set` expression | `{"set": "job.payout_agreed", "expr": "job.payout_base + 100 * test.haggle.net"}` | `expr` parses (§5), all names declared, writable key | evaluates then assigns |
| `give_item` | `{"give_item": {"id": "heavy_pistol", "qty": 1}}` | `id` exists in the gear catalogue (DECISIONS §4 names); `qty` int ≥ 1, default 1 | appends to Crew inventory |
| `start_job` | `{"start_job": true}` | `context` must be `"hub"`; a Job must be bound (`job.id`) | `job.accepted = true`, `job.state = "accepted"` |
| `change_rep` | `{"change_rep": {"who": "fixer", "delta": -1}}` | `who` is `"fixer"` or `"faction:<id>"`; `delta` integer, `abs(delta) <= 2`, non-zero | adds then clamps to the rep range |
| `tick_clock` | `{"tick_clock": "alarm"}` | `context` must be `"site"`; reason is an event id from DECISIONS §9 | adds that event's segments to the Security Clock |
| `test` | `{"test": {"key": "haggle", "skill": "negotiation", "attribute": "charisma", "threshold": 2}}` or `{"test": {"key": "haggle", "skill": "negotiation", "attribute": "charisma", "opposed": {"pool": 4}}}` | skill from DECISIONS §2; attribute from §1; exactly one of `threshold` (integer 1–4, §3) or `opposed.pool` (integer ≥ 1); `key` unique within the file | rolls now, §3.2 |

`set` takes exactly one of `value` or `expr`. A string `value` is a literal string, never an expression — that ambiguity is why both keys exist.

`set` on `npc.alert_level` is **raise-only**: it applies `max(current, value)`. AI-`refresh()` raises that key and never lowers it within a Run (ai.md), so a dialogue write that lowered it would be a lie the next decision step erases.

`set` on `npc.pacified` is the **social outcome channel** (DECISIONS §8): a bribe or Intimidation sets it and the guard's Behavior Tree checks it before escalating, so the actor actually stands down instead of shooting (§5.1).

The loader normalises every effect object to an internal `(op, args)` pair, which is the form `data-model.md` §10's `apply_effects` dispatches on. Authors write the flat DECISIONS §11 shape; only one of the two shapes ever exists in a file.

`tick_clock` reason ids and their segments, straight from DECISIONS §9: `gunfire` +2, `guard_killed` +2, `body_found` +3, `failed_hack` +1, `loud_spell` +2, `alarm` +2, `lock_forced` +1. Dialogue has no way to add a raw segment count: an authored conversation must name the event it is simulating, so the log line the player reads names the reason.

`test` and `tick_clock` are contract effects (DECISIONS §11). They are required: §9's payout formula (`± 100 × net Negotiation Hits`) needs an authored dice seam, and `tick_clock` exists specifically so a failed social approach can cost the Security Clock — a reason-mapped Clock seam, never a raw segment count.

### 3.2 What `test` does

1. Roll `Dice Pool = attribute + skill + modifiers` (§3; the acting Runner's ratings from the bound `pc` actor; Wound Modifier applies).
2. Resolve one of two ways, exactly as DECISIONS §3 defines them:
   - **Success Test** (`threshold` in 1–4): success when `Hits >= threshold`.
   - **Opposed Test** (`opposed.pool`): the other party rolls `pool` dice; `net = Hits - their Hits`, ties to the defender (so a tie loses). The `pool` is a plain dice count authored in the conversation, so a Fixer haggle (world.md: *Fixer bar* — "negotiate payout (Opposed Test, DEC §9)") needs no NPC stat block. Open question 4.
3. Write three results for `<key>`, all read-only to authors:

   | Key | Type | Value |
   |---|---|---|
   | `test.<key>.hits` | int | the acting Runner's Hits |
   | `test.<key>.net` | int | the **signed** margin: `Hits - threshold` for a Success Test, `Hits - defender Hits` for an Opposed Test. Ties go to the defender, so `net == 0` is a failure for the acting Runner (DECISIONS §3). It may be negative, and world.md's payout formula wants it that way: `base = round(12000 * TYPE_MULT[type]) + 100 * net`, with the *payout* clamped at 0, not the margin |
   | `test.<key>.glitch` | bool | more 1s than half the dice rolled (§3). A Critical Glitch is `test.<key>.glitch and test.<key>.hits == 0` |

4. XP: success pays 1 XP; failure pays 5 XP and rolls one Perk. Payout is once per obstacle per Job: `(conversation_id, test.key)` goes into the Job's obstacle ledger, and a second `test` with the same key in the same Job pays no XP (ADR-0006).
5. Glitch: the test still resolves on Hits, and no extra cost is applied until the author gates a `cond` on `test.<key>.glitch`. Critical Glitch: the test fails **and** the Security Clock gains one segment (§3) — the only Clock tick the runner itself applies, and never in a `"hub"` context.
6. The author writes the failure branch: `test` never auto-jumps.

### 3.3 Firing order

1. **Choice effects** fire when the choice is selected, before the target node is entered.
2. **Node effects** fire when the node is entered, before its `line` is displayed, and before its `choices` are filtered — so a node effect can legitimately change which of its own choices appear.
3. Within one `effects` array, entries apply left to right, and every RHS is evaluated against the store **as it was before the array started** (snapshot). `a: b` then `b: a` swaps; it does not chained-assign.
4. `test` resolves during application, so the next node's `cond` can read `test.<key>.net`.
5. Every effect fires **at most once per Job**. The ledger key is `(conversation_id, node_id)` for node effects and `(conversation_id, node_id, choice_index)` for choice effects. Re-entering a node or re-selecting a choice in the same Job replays nothing. Effects are *not* reapplied on a fresh conversation in the same Job, which is the revisit pitfall from the skill killed at the format level rather than by author discipline.
6. When an effect must be repeatable (vending, a shop, a repeatable bribe offer), that is an explicit future flag — Open question 8. Do not work around the rule with a flag-guarded choice; two mechanisms for one concept is how this rots.

---

## 4. The condition evaluator

### 4.1 Why never `eval`

`eval` is banned in the dialogue package, and the ban is enforced by a grep test over `dialogue/` (no `eval(`, `exec(`, `compile(`). Reasons, in order of weight:

1. The expression text is **content**: authored JSON, later possibly written by mods or a third party. `eval` reaches `__class__.__bases__.__subclasses__()`, imports, and file I/O from a string a writer typed.
2. `eval` accepts power operators and comprehensions: `9**9**9` locks the process. The whitelist makes that unrepresentable.
3. `eval` accepts everything, so every failure is the same generic error. The whitelist lets the loader say "unsupported syntax Lambda at col 12" and refuse to ship the file.
4. Sandboxing `eval` with `{"__builtins__": {}}` is a well-known bypassable trick; a positive whitelist is the only version that ages well.

### 4.2 Allowed syntax

Parse with `ast.parse(expr, mode="eval")`; walk only these node types:

| AST node | Allowed | Semantics |
|---|---|---|
| `Expression` | yes | root |
| `Constant` | yes | `int`, `float`, `bool`, `str` (bool written `True`/`False`) |
| `Name` | yes | only as a declared **scalar** key: `heat`, `clock` |
| `Attribute` | yes | only as a dotted chain whose **flattened text is a declared key** |
| `BoolOp` | `And`, `Or` | short-circuit |
| `UnaryOp` | `Not`, `USub` on a numeric `Constant` | |
| `BinOp` | `Add`, `Sub`, `Mult`, `Mod` | numeric only |
| `Compare` | `Eq`, `NotEq`, `Lt`, `LtE`, `Gt`, `GtE` | chaining allowed |
| `Call` | only `Name` in the whitelist, positional args, string literals | see below |

Call whitelist, v1: `has_item(item_id: str) -> bool`. Each entry declares its arity and arg types; the loader checks them, so `has_item('x', True)` is a load error, not a `TypeError` in front of the player. Inventory is not addressable any other way (`data-model.md` §10 forbids every `Call`; this whitelist is the one extension required to test inventory at all — Open question 5).

Dotted names are the one subtlety: `skill.negotiation` parses as `Attribute(Name('skill'), 'negotiation')`. The evaluator does **not** do attribute access. It flattens the chain to the string `"skill.negotiation"` and looks that string up in the store. A key that is not declared does not exist; `rep` alone, `rep.fixer.__class__`, and `flags.a.b` flatten to undeclared strings and are rejected. One rule, no object traversal anywhere: **a dotted chain is legal iff its flattened text is a store key.**

Explicitly rejected: `Subscript`, `List`/`Tuple`/`Dict`/`Set`, `ListComp`/`SetComp`/`DictComp`/`GeneratorExp`, `Lambda`, `IfExp`, `JoinedStr`/`FormattedValue`, `Starred`, `NamedExpr`, `Await`, `Yield`, `Pow` (DoS), `Div`/`FloorDiv` (integer-only store; use `Mult`/`Mod`), every `Call` not in the whitelist, and every `ctx=Store`.

### 4.3 Evaluator

```python
WHITELIST = {"has_item": Fn(arity=1, types=(str,), impl=lambda store, item: item in store.inventory)}

def evaluate(expr, store):
    """Condition → bool. Raises DialogueParseError / DialogueConditionError."""
    tree = ast.parse(expr, mode="eval")          # SyntaxError → DialogueParseError
    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name) or isinstance(node, ast.Attribute):
            return store.get(flatten(node))      # undeclared → DialogueConditionError
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                return all(ev(v) for v in node.values)   # short-circuits
            return any(ev(v) for v in node.values)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not ev(node.operand)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -ev(node.operand)
        if isinstance(node, ast.BinOp):
            return BINOP[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.Compare):
            left = ev(node.left)
            for op, comp in zip(node.ops, node.comparators):
                right = ev(comp)
                if not CMPOP[type(op)](left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.Call):
            name = node.func.id                   # guaranteed Name by the loader walk
            if name not in WHITELIST or node.keywords:
                raise DialogueParseError(f"unsupported call '{name}'")
            args = [ev(a) for a in node.args]
            return WHITELIST[name].call(store, *args)   # .call checks arity and arg types
        raise DialogueParseError(f"unsupported syntax {type(node).__name__}")
    result = ev(tree)
    if not isinstance(result, bool):
        raise DialogueConditionError(f"condition is not boolean: '{expr}'")
    return result
```

The **loader** runs the same walk with a store stub that only records names, which is how `unknown variable` and `unsupported syntax` become load errors with the offending column instead of runtime surprises. `flatten` also rejects chains deeper than three segments (`rep.faction.corp` is the deepest legal shape) and any root that itself is a declared key.

### 4.4 Worked example

Condition from `corp_guard_bribe`:

```
crew.nuyen >= 500 and flags.bribe_offered == False
```

`ast.dump(..., indent=1)`:

```
BoolOp(
 op=And(),
 values=[
  Compare(
   left=Attribute(value=Name(id='crew', ctx=Load()), attr='nuyen', ctx=Load()),
   ops=[GtE()],
   comparators=[Constant(value=500)]),
  Compare(
   left=Attribute(value=Name(id='flags', ctx=Load()), attr='bribe_offered', ctx=Load()),
   ops=[Eq()],
   comparators=[Constant(value=False)])])
```

Walk with the store `{crew.nuyen: 2000, flags.bribe_offered: False}`:

| Step | Node | Value |
|---|---|---|
| 1 | `BoolOp(And)` | evaluate left first |
| 2 | `Compare(GtE)` | left → flatten `crew.nuyen` → `2000` |
| 3 | | comparator → `Constant` → `500` |
| 4 | | `2000 >= 500` → `True` |
| 5 | `Compare(Eq)` | left → flatten `flags.bribe_offered` → `False`; right → `False` |
| 6 | | `False == False` → `True` |
| 7 | `And` | `True` → the choice is shown |

Rejected variants and their loader messages:

| Expression | Result |
|---|---|
| `rep.fixer.__class__ >= 7` | `unknown variable 'rep.fixer.__class__' in condition` |
| `eval('1')` | `unsupported call 'eval' in condition` |
| `has_item('cortez_chip', True)` | `has_item takes 1 argument` |
| `9 ** 9` | `unsupported syntax Pow in condition` |
| `[x for x in crew.nuyen]` | `unsupported syntax ListComp in condition` |
| `heat +` | `condition does not parse: invalid syntax at col 7` |

### 4.5 How errors surface

| Layer | When | Behaviour |
|---|---|---|
| Load | file open | all problems collected into one `DialogueValidationError` (§7); the file is refused; the game does not start with it |
| Runtime condition | during play | a load-valid condition can still fail on types (`'low' < 3`). Log `dialogue: {id}:{node}: condition failed at runtime: {reason}: '{expr}'`, show `<DIALOGUE ERROR {node}>` as the line, close the conversation. **Do not** treat it as `False`: an all-false gate set is indistinguishable from an authored refusal and would bury the bug |
| Runtime text | during play | unknown key is a load error; a `None` value renders `<MISSING:key>` inline and play continues |
| Runtime graph | during play | cannot happen post-validation; if it does (§7.4) the conversation closes with a visible error and a log line, never a stall |

---

## 5. The shared variable store

One store, two live proxies, no copies. `npc.*` reads the **interlocutor's Blackboard** in place — and writes two of its keys, `npc.alert_level` and `npc.pacified` (§5.1). `skill.*` / `attr.*` read the bound `pc` Runner's sheet in place. That is ADR-0010's claim made concrete: the same dict the Behavior Trees read is the one a condition branches on.

Scope column: *Job* clears at Extraction, *Run* resets per Run, *world* persists per ADR-0012.

| Key | Type | Default | Scope | Dialogue R/W | Who else writes it | Blackboard key |
|---|---|---|---|---|---|---|
| `heat` | int | 0 (world.md §8.3 tier 0 is the floor) | world | R | Job resolution: +2 forced Extraction, −1 successful Job (DECISIONS §9) | — |
| `clock` | int 0–10 | `CLOCK_START[type]` = 0 for all four v1 types (world.md §4); not running at the Hub | Run | R; written only via `tick_clock` | Security Clock events (DECISIONS §9) | — |
| `rep.fixer` | int (clamp Open question 3) | 0 | world, per Fixer | R/W via `change_rep` | Job resolution: +1 voluntary / −1 forced Extraction (world.md §2); Call in a Favour spends `FAVOUR_REP_COST` and needs rep ≥ 1 | — |
| `rep.faction.<id>` | int | 0 | world | R/W via `change_rep` | Job outcomes | — |
| `job.id` | str | bound at `start()` | Job | R | Job record | — |
| `job.type` | str (`paydata`, `sabotage`, `protection`, `courier`) | bound at `start()` | Job | R | Job record | — |
| `job.payout_base` | int | `round(12000 * TYPE_MULT[type])` (world.md §4.1; 12,000 is the `TYPE_MULT = 1.0` case in DECISIONS §9) | Job | R | Job record | — |
| `job.payout_agreed` | int | `job.payout_base` | Job | R/W | dialogue | — |
| `job.accepted` | bool | `false` | Job | R; written only via `start_job` | `start_job` | — |
| `job.state` | str (`offered`, `accepted`, `active`, `complete`, `failed`) | `"offered"` | Job | R; written only via `start_job` | `start_job`, Extraction | — |
| `job.intel_scouted` | bool | `false` | Job | R | Legwork: Scout Site | — |
| `skill.<13 slugs>` | int | Runner sheet rating | Run | **R only** | Advance (XP spend) | — |
| `attr.<9 slugs>` | int | Runner sheet rating | Run | **R only** | Qi/spell effects, Advance | — |
| `crew.nuyen` | int | world.md owns starting funds (Open question 1) | world | R/W | payout, Buy Gear, Ripperdoc | — |
| `npc.alert_level` | int 0 Calm / 1 Alert / 2 Lockdown (ai.md) | 0; `refresh()` raises to 1 on first sighting | Run, monotonic | R/W, **raise-only** | `refresh()`, `call_backup`, the site at 4 and 7 Clock segments | **`alert_level`** |
| `npc.pacified` | bool | false | Run | R/W | dialogue (the only writer) | **`pacified`** |
| `npc.morale` | int (derived: `wound_modifier + morale_bonus[archetype]`) | derived | Run | **R only** | AI `refresh()`, every decision step | **`morale`** |
| `npc.objective` | str — Mission Graph node id, or `"hostile"` | spawn | Run | **R only** | the site embed, a failed Conjuring | **`objective`** |
| `npc.noise_pos` | `(x, y)` \| null | null | Run | **R only** | the site's noise broadcast | **`noise_pos`** |
| `npc.target` | Runner id \| null | null | Run | **R only** | AI `refresh()` (Utility Score) | **`target`** |
| `npc.last_known_pos` | `(x, y)` \| null | null | Run | **R only** | AI `refresh()` | **`last_known_pos`** |
| `npc.home_pos` | `(x, y)` | spawn cell | Run | **R only** | the site embed at spawn | **`home_pos`** |
| `npc.cover_pos` | `(x, y)` \| null | null | Run | **R only** | `seek_cover`, `take_cover` | **`cover_pos`** |
| `test.<key>.hits` \| `.net` \| `.glitch` | int \| int \| bool | 0 \| 0 \| false | Job | R; written only by `test` | `test` effects | — |
| `flags.<name>` | bool | from the file's `vars` | Job, cleared at Extraction | R/W | dialogue | — |

### 5.1 The overlap, stated plainly

Every Blackboard key in DECISIONS §8 appears in the table; the meanings and write rules are ai.md's, not this document's.

| Blackboard key | Dialogue reads | Dialogue writes | Why |
|---|---|---|---|
| `alert_level` | yes | yes, raise-only | a botched bribe or Intimidation escalation sets 2 Lockdown, which is exactly what the `call_backup` action does |
| `pacified` | yes | yes | the social outcome channel: a bribe or Intimidation sets it and the guard tree stands the actor down before escalating (DECISIONS §8) |
| `morale` | yes | **no** | ai.md derives it in `refresh()` every decision step, so any write is erased in front of the player |
| `objective` | yes | **no** | it is a Mission Graph node id, not an intent word |
| `noise_pos` | yes | **no** | the site's noise broadcast owns it |
| `target` | yes | **no** | target selection is the Utility Score's job |
| `home_pos`, `cover_pos`, `last_known_pos` | yes | **no** | spatial facts the tree owns |

So the overlap is real but narrow: a conversation can *read* everything the guard's tree knows, and *writes* exactly two keys. Reading is the load-bearing half — a Fixer branching on `heat`, or a guard refusing to talk because the crew was already seen, is the ADR-0010 promise being paid out.

The write half is deliberately tiny and is now complete. `alert_level` is raise-only: a botched bribe escalates and cannot calm. `pacified` is the social outcome channel ADR-0010 promises — a bribed or intimidated actor stores "stop looking" on its own Blackboard, and the guard tree checks the key before escalating (DECISIONS §8). Every other key is read-only to dialogue; `morale` and `objective` in particular, because the AI overwrites the one every decision step and treats the other as a Mission Graph id. The worked conversation in §9 sets `npc.pacified` on both success branches.

### 5.2 Store API

```python
class VarStore:
    def declare(self, key, default, scope, writable): ...   # seeds only, never overwrites
    def get(self, key): ...        # undeclared → DialogueConditionError
    def set(self, key, value): ... # unknown / read-only / wrong type → DialogueEffectError
    def has_item(self, item_id) -> bool
```

The loader declares every key in the table, plus the file's `flags.*` from `vars`, plus `rep.faction.*` as a wildcard namespace (any id, default 0 — an unknown faction is neutral, which is the correct game meaning, so a typo degrades softly; W3 warns when the id is not one of world.md's factions, e.g. `corp_arasaka`, `street_kobun`), plus the three `test.<key>.*` keys harvested from the file's own `test` effects. A `test.<key>.net` read with no matching `test` effect in the file is an unknown-variable error, which catches the copy-paste that would otherwise read a stale 0.

`skill.*` / `attr.*` slug spelling is `lower_snake` of the DECISIONS names: 13 skills (`firearms`, `close_combat`, `athletics`, `stealth`, `perception`, `sorcery`, `conjuring`, `cybercombat`, `electronics`, `medicine`, `negotiation`, `con`, `intimidation`) and 9 attributes (`body`, `agility`, `reaction`, `strength`, `willpower`, `logic`, `intuition`, `charisma`, `edge`). `data-model.md` §10 now writes the same lowercase dotted form (`attr.logic`), so the two documents agree: DECISIONS §11 fixes lowercase dot paths, and this document's `lower_snake` form is the settled one, used everywhere.

Persistence mapping for the save blob (world.md §10): `heat` → `world.heat`; `rep.fixer` → `world.rep.fixer`; `rep.faction.<id>` → `world.rep.factions[<id>]`; `skill.*` / `attr.*` → the Runner's sheet; `crew.nuyen` → the save's `nuyen`; `flags.*` and `job.*` → the Job record; `npc.*` → the actor's Blackboard, and Blackboards are Run-scoped, so nothing there is saved.

---

## 6. The runner

### 6.1 Runner state machine

```
IDLE ──start()──► RUNNING(loop) ──line──► WAITING_CONTINUE ──advance()──► RUNNING
                        │                        └──end terminator──► DONE
                        ├──choices──► WAITING_CHOICE ──choose(i)──► RUNNING
                        ├──condition/jump/command──► RUNNING (silent, counted against budget)
                        └──end──► DONE
```

`_advance` is the explicit worklist loop of DECISIONS §13: silent nodes loop inside it, content nodes return. No recursion, so a `condition → command → condition` chain cannot blow the stack.

### 6.2 Pseudocode

```python
AUTO_ADVANCE_BUDGET = 512

class DialogueRunner:
    def __init__(self, conversation, store, presenter, rng, localize=None):
        self.conv, self.store, self.presenter, self.rng = conversation, store, presenter, rng
        self.nodes = {n["id"]: n for n in conversation.nodes}     # load-validated
        self.localize = localize or (lambda text: text)            # identity in v1: no string table (Open question 7)
        self.cond_cache = {}        # expression text -> compiled walk; files reuse condition text
        self.seen = set()           # seeded from the Job record's dialogue ledger
        self.state = IDLE
        self.pending = None         # node id to enter after advance(), or END

    def start(self, actors, pc_actor):
        """actors: {cast_slug: actor_ref}; pc_actor: the speaking Runner."""
        self.actors, self.pc = actors, pc_actor
        self._bind_job()                       # job.* mirrored from the Job record
        self.state = RUNNING
        self._enter(self.conv.start)

    # ---- the loop -------------------------------------------------------
    def _enter(self, node_id):
        for _ in range(AUTO_ADVANCE_BUDGET):
            node = self.nodes[node_id]        # dangling goto impossible: load-validated
            self._fire(node.get("effects", []), (self.conv.id, node["id"]))
            kind = kind_of(node)
            if kind == "end":
                return self._finish("end")
            if kind == "condition":
                node_id = node["then"] if evaluate(node["cond"], self.store) else node["else"]
                continue
            if kind in ("jump", "command"):
                node_id = node["goto"]
                continue
            if kind == "line":
                self.presenter.line(display_speaker(node), self.localize(interpolate(node["line"], self.store)))
                self.pending = END if node.get("end") else node["goto"]
                self.state = WAITING_CONTINUE
                return
            if kind == "choice":
                if "line" in node:
                    self.presenter.line(display_speaker(node), self.localize(interpolate(node["line"], self.store)))
                shown = self._filter(node["choices"])
                if not shown:
                    return self._dead_end(node)
                self.pending = (node["id"], shown)
                self.presenter.choices([self.localize(interpolate(c["text"], self.store)) for c in shown])
                self.state = WAITING_CHOICE
                return
        raise DialogueRuntimeError(f"runaway auto-advance at '{node_id}'")   # silent cycle

    def advance(self):
        if self.state is not WAITING_CONTINUE:
            return
        target, self.pending, self.state = self.pending, None, RUNNING
        if target is END:
            self._finish("end")
        else:
            self._enter(target)

    def choose(self, index):
        if self.state is not WAITING_CHOICE:
            return
        node_id, shown = self.pending
        choice, position = shown[index]
        self._fire(choice.get("effects", []), (self.conv.id, node_id, position))   # transition-time
        self.state = RUNNING
        self._enter(choice["goto"])

    # ---- pieces ---------------------------------------------------------
    def _filter(self, choices):
        """Author order; hidden choices are absent from the list, never greyed out.
        A condition error propagates: it is a bug, not a False."""
        return [(c, i) for i, c in enumerate(choices)
                if evaluate(c.get("cond", "True"), self.store)]

    def _fire(self, effects, ledger_key):
        """At most once per Job, keyed (conversation, node) or
        (conversation, node, choice index). The key is recorded before the array
        applies, so an effect cannot re-enter itself."""
        if not effects or ledger_key in self.seen:
            return
        self.seen.add(ledger_key)
        snapshot = self.store.snapshot()          # every RHS reads the pre-array store
        for effect in effects:
            apply_effect(effect, snapshot, self.store, self.rng, self)   # §3

    def _dead_end(self, node):
        if self.conv.on_empty:
            return self._enter(self.conv.on_empty)
        log.error("dialogue: %s:%s: all choices filtered out; closing", self.conv.id, node["id"])
        self._finish("dead_end")

    def _finish(self, reason):
        self.state = DONE
        self.presenter.close(reason)              # returns the player to the Site or the Hub
```

Notes the pseudocode encodes:

- **`advance()` and `choose()` are the only inputs.** Both are no-ops in the wrong state, so a double-click or an input repeat cannot skip a line. The presenter gets lines and choices as text; the renderer (game-ui-ux) owns the box, the portrait, and the speed of the text reveal.
- **`choose()` passes the choice's author index**, not the index in the filtered list, which is what makes the once-ledger stable when a condition hides an earlier choice.
- **`_filter` hides**, it does not disable. A disabled option with a locked-padlock tells the player a gate exists; that information leak is a design choice we are not making by accident.
- **`_finish` flushes nothing.** `npc.*` writes are live against the Blackboard, and `start_job` already wrote the Job record.
- **`END`** is a sentinel, not a node id.
- **`localize` is injected and identity in v1.** `line` and `text` are literal display strings (DECISIONS §11), and the hook is where a string table lands if one ever exists (Open question 7). It runs *after* interpolation, so a translator never sees `{job.payout_agreed:,}`.
- **Parsed conditions are cached by expression text.** `ast.parse` is the only non-trivial cost in a condition, and authoring files reuse the same text across nodes (data-model.md §10).

### 6.3 Failure behaviour, explicitly

| Situation | Behaviour |
|---|---|
| Dead end (a choice node filters to empty at runtime) | `on_empty` node if declared, else close with `reason="dead_end"` plus an error log. The player is back on the map/Hub; the conversation is never a stall. The validator makes this unreachable for a well-formed file (§7.2.14) |
| Unresolvable `goto` at runtime | cannot happen post-validation; if it does, log `dialogue: {id}:{node}: goto '{target}' does not resolve at runtime`, show `<DIALOGUE ERROR {node}>`, close |
| Runaway silent cycle | budget exhausted → `DialogueRuntimeError`, close with `<DIALOGUE ERROR>`, log the node where the budget ran out. The validator rejects silent cycles at load anyway (§7.2.15) |
| Condition error at runtime | log with node id + expression, show `<DIALOGUE ERROR {node}>`, close (§4.5) |
| Conversation ended | `presenter.close(reason)`; the Hub refreshes the Fixer's post list from `job.accepted` / `job.state` |
| Conversation interrupted (Extraction, Downed speaker) | the controller calls `_finish("interrupted")`; effects already applied stay applied, and the once-ledger keeps them from firing again |

---

## 7. Validation

Load-time, in the runner (DECISIONS §11). `load_conversation(path)` collects **every** problem and raises once; the batch CLI prints them all and exits non-zero. Errors refuse the file; warnings print and load.

Every message is prefixed `dialogue: <file>:<loc>: ` where `<loc>` is `nodes[i] ('<id>')`, `nodes[i] choice[j]`, or `start`. Location is always reported, even when the id is missing, so a malformed node can be found by eye.

### 7.1 Warnings

| # | Rule | Message |
|---|---|---|
| W1 | a declared `test` attribute is not the skill's linked attribute (DECISIONS §2) | `warning: ...: test 'haggle': skill 'negotiation' is linked to 'charisma', not 'agility'` |
| W2 | two files declare the same `flags.*` name with different defaults | `warning: ...: flag 'guard_bribed' already declared by 'corp_guard_bribe'` |
| W3 | `rep.faction.<id>` used for an id that is not one of world.md's factions | `warning: ...: 'rep.faction.corps' is not a declared faction; treated as 0` |
| W4 | a `cast` entry never used by any `speaker` | `warning: ...: cast entry 'crowd' is never used` |
| W5 | a `test` effect whose three result keys are never read by any node | `warning: ...: test 'haggle' result is never read` |
| W6 | node id not in `snake_case`, or a `line` longer than 200 characters | `warning: ...: line is 243 characters (UI holds ~180)` |

### 7.2 Errors

| # | Rule | Message |
|---|---|---|
| E1 | duplicate node id | `dialogue: {file}:nodes[{i}]: duplicate node id '{id}' (first at nodes[{j}])` |
| E2 | dangling target from `goto`, `then`, `else`, or `choices[j].goto` | `dialogue: {file}:nodes[{i}] ('{id}'): dangling goto '{target}'` |
| E3 | `start` missing or not a node | `dialogue: {file}:start: unknown node '{id}'` |
| E4 | `start` resolves straight to an end | `dialogue: {file}:start: node '{id}' is an end node (the conversation has no content)` |
| E5 | condition does not parse | `dialogue: {file}:nodes[{i}] ('{id}'): condition does not parse: {msg} at col {col}: '{expr}'` |
| E6 | condition uses an undeclared name | `dialogue: {file}:nodes[{i}] ('{id}'): unknown variable '{name}' in condition '{expr}'` |
| E7 | condition uses non-whitelisted syntax | `dialogue: {file}:nodes[{i}] ('{id}'): unsupported syntax {NodeType} in condition '{expr}'` |
| E8 | non-whitelisted call | `dialogue: {file}:nodes[{i}] ('{id}'): unsupported call '{name}' in condition '{expr}'` |
| E9 | `line` has no `speaker` | `dialogue: {file}:nodes[{i}] ('{id}'): node has a line but no speaker` |
| E10 | speaker not in `cast` | `dialogue: {file}:nodes[{i}] ('{id}'): speaker '{speaker}' is not in the cast` |
| E11 | `cast` value empty or not a string | `dialogue: {file}:nodes[{i}] ('{id}'): cast entry '{slug}' has no display name` |
| E12 | no payload at all | `dialogue: {file}:nodes[{i}] ('{id}'): node has no payload (needs one of: line, choices, cond, effects, goto, end)` |
| E13 | two terminators | `dialogue: {file}:nodes[{i}] ('{id}'): two terminators: '{a}' and '{b}'` |
| E14 | choice node with no unconditional choice | `dialogue: {file}:nodes[{i}] ('{id}'): choice node has no unconditional choice (every choice has a 'cond')` |
| E15 | silent cycle (`condition`/`command`/`jump` only) | `dialogue: {file}:nodes[{i}] ('{id}'): silent cycle through ['{a}', '{b}'] has no line, choices, or end` |
| E16 | a forbidden field for the derived kind | `dialogue: {file}:nodes[{i}] ('{id}'): condition node cannot carry a 'line'` |
| E17 | unreachable node | `dialogue: {file}:nodes[{i}] ('{id}'): unreachable node (no path from '{start}')` |
| E18 | `choices` present but empty | `dialogue: {file}:nodes[{i}] ('{id}'): 'choices' is empty` |
| E19 | choice without `text` | `dialogue: {file}:nodes[{i}] choice[{j}]: choice has no text` |
| E20 | `effects` present but empty | `dialogue: {file}:nodes[{i}] ('{id}'): 'effects' is empty` |
| E21 | effect object naming zero or two effects | `dialogue: {file}:nodes[{i}] ('{id}'): effect {j} must name exactly one effect (got {names})` |
| E22 | unknown effect name | `dialogue: {file}:nodes[{i}] ('{id}'): unknown effect '{name}'` |
| E23 | effect missing a required field | `dialogue: {file}:nodes[{i}] ('{id}'): effect '{name}' is missing '{field}'` |
| E24 | `set` to an undeclared variable | `dialogue: {file}:nodes[{i}] ('{id}'): cannot write undeclared variable '{name}'` |
| E25 | `set` to a read-only variable | `dialogue: {file}:nodes[{i}] ('{id}'): cannot write read-only variable '{name}'` |
| E26 | literal type does not match the declared type | `dialogue: {file}:nodes[{i}] ('{id}'): '{name}' is int, got str` |
| E27 | flag referenced but not declared in `vars` | `dialogue: {file}:nodes[{i}] ('{id}'): unknown flag '{name}' (declare it in 'vars')` |
| E28 | `vars` value is not a bool | `dialogue: {file}:vars: flag '{name}' must be a bool` |
| E29 | unknown skill / attribute name | `dialogue: {file}:nodes[{i}] ('{id}'): unknown skill '{name}'` |
| E30 | `test` threshold out of range, or `opposed.pool` below 1 | `dialogue: {file}:nodes[{i}] ('{id}'): threshold {n} is outside the v1 range 1-4 (DECISIONS 3)` |
| E31 | duplicate `test.key` in one file | `dialogue: {file}:nodes[{i}] ('{id}'): duplicate test key '{key}'` |
| E32 | `test` names both or neither of `threshold` / `opposed` | `dialogue: {file}:nodes[{i}] ('{id}'): test '{key}' needs exactly one of 'threshold' or 'opposed'` |
| E33 | `tick_clock` in a Hub conversation | `dialogue: {file}:nodes[{i}] ('{id}'): tick_clock is not allowed in a 'hub' conversation (the Security Clock is not running)` |
| E34 | `tick_clock` reason not a DECISIONS §9 event | `dialogue: {file}:nodes[{i}] ('{id}'): tick_clock reason '{reason}' is not a Security Clock event` |
| E35 | `start_job` in a site conversation | `dialogue: {file}:nodes[{i}] ('{id}'): start_job is only allowed in a 'hub' conversation` |
| E36 | `change_rep` with a zero or out-of-range delta | `dialogue: {file}:nodes[{i}] ('{id}'): change_rep delta {d} must be a non-zero integer in -2..2` |
| E37 | `change_rep` to an unknown rep target | `dialogue: {file}:nodes[{i}] ('{id}'): unknown rep target '{who}'` |
| E38 | `give_item` id not in the gear catalogue | `dialogue: {file}:nodes[{i}] ('{id}'): unknown item '{id}'` |
| E39 | `give_item` qty not a positive int | `dialogue: {file}:nodes[{i}] ('{id}'): give_item qty {q} must be an integer >= 1` |
| E40 | `npc.*` used with no `interlocutor` | `dialogue: {file}:nodes[{i}] ('{id}'): 'npc.' variable used but the file declares no 'interlocutor'` |
| E41 | `interlocutor` / `pc` not a cast key | `dialogue: {file}:interlocutor: '{slug}' is not in the cast` |
| E42 | unknown placeholder key | `dialogue: {file}:nodes[{i}] ('{id}'): placeholder '{name}' is not a variable` |
| E43 | malformed placeholder | `dialogue: {file}:nodes[{i}] ('{id}'): malformed placeholder '{text}'` |
| E44 | `id` does not match the filename stem | `dialogue: {file}:id: '{id}' does not match the filename` |
| E45 | bad `id` / slug characters | `dialogue: {file}:nodes[{i}]: node id '{id}' must match [a-z0-9_]+` |
| E46 | missing or invalid `context` | `dialogue: {file}:context: must be 'hub' or 'site'` |
| E47 | more than 100 nodes in one file (data-model.md §1: `D` ≤ 100) | `dialogue: {file}:nodes: {n} nodes exceeds the v1 limit of 100` |

Notes on the contested ones:

- **E17 unreachable is an error, not a warning.** Dead content is dead weight, and a node with a typo'd inbound `goto` is far more common than a node kept deliberately. Delete it, or reach it. The file's `on_empty` target is exempt: the runner reaches it, no terminator does.
- **E47 is a real cap, not a style note.** 100 nodes bounds validation, the auto-advance budget, and the `--paths` walk (data-model.md §10 gives `D` ≤ 100, `E` ≈ 300). A conversation that needs more than 100 nodes is two conversations.
- **E14 is the reason dead ends cannot happen.** E15 and E14 together mean the runner's dead-end path (§6.3) is defence in depth, not a supported authoring pattern.
- **E31 exists because of ADR-0006.** Two `test`s with the same key would be two rolls against one obstacle.

### 7.3 The two commands

```
python -m pink_mohawk.dialogue.validate data/dialogue/*.json     # batch, all errors, exit 1 on any error
python -m pink_mohawk.dialogue.play data/dialogue/corp_guard_bribe.json \
    --pc decker --actors guard=npc:site_guard \
    --set crew.nuyen=2000 --set job.payout_base=12000 --set npc.alert_level=1 \
    --choices "You look bored. 500 says you never saw me.","Hand it over." \
    --transcript
```

`play --choices` feeds a comma-separated list of choice **texts** (index fallback `#2`), prints speaker/line/effects after each step, and dumps the final store diff. `--transcript` prints a JSON transcript for golden tests. `--paths` walks every root-to-end path and reports paths that reach no end (a static complement to E14). `dialogue/` imports no `tcod`, so all three run under pytest.

---

## 8. Worked conversation A: the Fixer negotiates a Job

`data/dialogue/fixer_offer.json` — Hub, so no Clock effects are legal. Demonstrates: jump, line, condition, choice, command, end; a reputation-gated refusal; a Negotiation-gated haggle; a `test` driving the payout; `change_rep`; `start_job`; interpolation firing after the node's own effects.

```json
{
  "id": "fixer_offer",
  "context": "hub",
  "cast": { "fixer": "Fixer", "pc": "Runner" },
  "pc": "pc",
  "start": "open",
  "vars": {
    "met_fixer": false,
    "haggle_used": false,
    "fixer_refused": false
  },
  "nodes": [
    { "id": "open", "goto": "intro" },

    {
      "id": "intro",
      "speaker": "fixer",
      "line": "You're the crew, then. Sit down.",
      "effects": [ { "set": "flags.met_fixer", "value": true } ],
      "goto": "gate_refusal"
    },

    { "id": "gate_refusal", "cond": "rep.fixer < 0", "then": "refusal", "else": "offer" },

    {
      "id": "refusal",
      "speaker": "fixer",
      "line": "You stiffed me on the Bellevue job. Find another Fixer.",
      "effects": [ { "set": "flags.fixer_refused", "value": true } ],
      "end": true
    },

    {
      "id": "offer",
      "speaker": "fixer",
      "line": "Pay is 12k. In and out.",
      "choices": [
        { "text": "Who's the target?", "goto": "target_brief" },
        {
          "text": "The pay is 12k, the risk is 15k.",
          "cond": "skill.negotiation >= 4 and flags.haggle_used == False",
          "goto": "haggle",
          "effects": [ { "set": "flags.haggle_used", "value": true } ]
        },
        { "text": "I'm in.", "goto": "accept" },
        { "text": "Not interested.", "goto": "walk_away" }
      ]
    },

    {
      "id": "target_brief",
      "speaker": "fixer",
      "line": "Paydata. Sub-level three, vault at the end of the service corridor.",
      "goto": "offer"
    },

    {
      "id": "haggle",
      "effects": [
        { "test": { "key": "haggle", "skill": "negotiation", "attribute": "charisma",
                    "opposed": { "pool": 4 } } }
      ],
      "goto": "haggle_result"
    },

    { "id": "haggle_result", "cond": "test.haggle.net >= 2", "then": "haggle_big", "else": "haggle_check" },
    { "id": "haggle_check",  "cond": "test.haggle.net >= 1", "then": "haggle_small", "else": "haggle_no" },

    {
      "id": "haggle_big",
      "speaker": "fixer",
      "line": "You're pushing it. {job.payout_agreed:,}, and the deck comes back intact.",
      "effects": [ { "set": "job.payout_agreed", "expr": "job.payout_base + 100 * test.haggle.net" } ],
      "goto": "offer"
    },

    {
      "id": "haggle_small",
      "speaker": "fixer",
      "line": "One bump. {job.payout_agreed:,}. Take it or leave it.",
      "effects": [ { "set": "job.payout_agreed", "expr": "job.payout_base + 100 * test.haggle.net" } ],
      "goto": "offer"
    },

    {
      "id": "haggle_no",
      "speaker": "fixer",
      "line": "The number is the number. Don't waste my morning.",
      "effects": [ { "change_rep": { "who": "fixer", "delta": -1 } } ],
      "goto": "offer"
    },

    {
      "id": "accept",
      "effects": [ { "start_job": true } ],
      "goto": "brief"
    },

    {
      "id": "brief",
      "speaker": "fixer",
      "line": "Vault's on sub-level three, service corridor. Loud gets you dead.",
      "end": true
    },

    {
      "id": "walk_away",
      "speaker": "fixer",
      "line": "Your loss. The offer's dead by morning.",
      "end": true
    }
  ]
}
```

Walking `rep.fixer = -1`: `open → intro → gate_refusal → refusal` (end). Walking with `rep.fixer = 0`, `skill.negotiation = 4`, and a haggle roll of 4 Hits against the Fixer's 1 (Opposed Test, ties to the defender): `open → intro → gate_refusal → offer → haggle` (writes `test.haggle.hits = 4`, `test.haggle.net = 3`) `→ haggle_result → haggle_big` (payout becomes `12000 + 100 * 3 = 12300`, then the line displays `12,300`) `→ offer`, where the haggle choice is now hidden by `flags.haggle_used` and the money-moving effects cannot re-fire in this Job.

---

## 9. Worked conversation B: the bribable Corp Guard

`data/dialogue/corp_guard_bribe.json` — Site context, so `tick_clock` is legal. Demonstrates: the bribe, a reputation-gated bribe failure that ticks the Security Clock, an Intimidation branch gated by the skill then resolved by a hard (3) test, a Critical-Glitch exposure on the Intimidation roll, `npc.*` writes into the guard's Blackboard, and a back edge out of `bribe_offer` into `guard_hail`.

```json
{
  "id": "corp_guard_bribe",
  "context": "site",
  "cast": { "guard": "Corp Guard", "pc": "Runner" },
  "pc": "pc",
  "interlocutor": "guard",
  "start": "guard_hail",
  "on_empty": "guard_leave",
  "vars": {
    "guard_bribed": false,
    "guard_alarmed": false,
    "bribe_offered": false,
    "intimidation_tried": false
  },
  "nodes": [
    {
      "id": "guard_hail",
      "speaker": "guard",
      "line": "Halt. This floor's closed.",
      "choices": [
        {
          "text": "You look bored. 500 says you never saw me.",
          "cond": "crew.nuyen >= 500 and flags.bribe_offered == False",
          "goto": "bribe_offer",
          "effects": [ { "set": "flags.bribe_offered", "value": true } ]
        },
        {
          "text": "Back off or I put you through that wall.",
          "cond": "skill.intimidation >= 4 and flags.intimidation_tried == False",
          "goto": "intimidation",
          "effects": [ { "set": "flags.intimidation_tried", "value": true } ]
        },
        { "text": "Wrong floor. My mistake.", "goto": "guard_leave" }
      ]
    },

    {
      "id": "bribe_offer",
      "speaker": "guard",
      "line": "Five hundred? ...Show me.",
      "choices": [
        { "text": "Hand it over.", "goto": "bribe_pay" },
        { "text": "On second thought, no.", "goto": "guard_hail" }
      ]
    },

    {
      "id": "bribe_pay",
      "effects": [
        { "set": "crew.nuyen", "expr": "crew.nuyen - 500" },
        { "set": "flags.guard_bribed", "value": true }
      ],
      "goto": "bribe_result"
    },

    { "id": "bribe_result", "cond": "rep.faction.corp_arasaka <= -1", "then": "bribe_burned", "else": "bribe_taken" },

    {
      "id": "bribe_taken",
      "speaker": "guard",
      "line": "I was in the washroom. Forty seconds.",
      "effects": [ { "set": "npc.pacified", "value": true } ],
      "end": true
    },

    {
      "id": "bribe_burned",
      "speaker": "guard",
      "line": "You're on Kowalski's list. ...Yeah, it's him. Third floor.",
      "effects": [
        { "tick_clock": "alarm" },
        { "set": "npc.alert_level", "value": 2 }
      ],
      "end": true
    },

    {
      "id": "intimidation",
      "effects": [
        { "test": { "key": "intimidation", "skill": "intimidation", "attribute": "charisma",
                    "threshold": 3 } }
      ],
      "goto": "intimidation_result"
    },

    { "id": "intimidation_result", "cond": "test.intimidation.net >= 1", "then": "intimidation_win", "else": "intimidation_fail" },

    {
      "id": "intimidation_win",
      "speaker": "guard",
      "line": "Easy. Easy. Take the stairs.",
      "effects": [
        { "change_rep": { "who": "faction:corp_arasaka", "delta": -1 } },
        { "set": "npc.pacified", "value": true }
      ],
      "end": true
    },

    {
      "id": "intimidation_fail",
      "speaker": "guard",
      "line": "Security! Intruder on three!",
      "effects": [
        { "tick_clock": "gunfire" },
        { "set": "npc.alert_level", "value": 2 }
      ],
      "end": true
    },

    {
      "id": "guard_leave",
      "speaker": "guard",
      "line": "Move along.",
      "end": true
    }
  ]
}
```

Behaviours worth reading off this file:

- **Bribe, success path:** `guard_hail → bribe_offer → bribe_pay` (500 leaves the crew, flag set) `→ bribe_result` (Arasaka rep intact) `→ bribe_taken`: the guard agrees in words, sets `flags.guard_bribed`, and sets `npc.pacified = true`, so the guard tree stands down (ai.md).
- **Bribe, burned path:** with `rep.faction.corp_arasaka <= -1` the same 500¥ is spent and the guard keys the panel anyway: `tick_clock("alarm")` = +2 segments (DECISIONS §9) and `npc.alert_level = 2` (Lockdown), which is exactly what the guard tree's own `call_backup` action writes (ai.md). This is the required failure path that ticks the Security Clock.
- **Intimidation:** gated at `skill.intimidation >= 4` (a content gate, matching the DECISIONS §11 example's shape), then a hard test (threshold 3). Success costs Arasaka reputation; failure ticks the Clock with `gunfire` (+2) and raises `npc.alert_level` to 2. A Critical Glitch on that roll adds the mechanical +1 from DECISIONS §3 on top — so the worst case is +3 segments from one conversation, which is the design intent of ADR-0005.
- **`npc.alert_level` writes are raises, not assignments** (§3.1). Both failing branches set 2, which is the top of ai.md's scale and therefore idempotent with the site's own escalation at 7 Clock segments.
- **The social channel, closed.** `npc.pacified` is the one Blackboard key a conversation writes to change what a guard *does* (DECISIONS §8). Both success branches set it — `bribe_taken` on the bribe path, `intimidation_win` on the Intimidation path — and the Corp Guard tree checks it before escalating, so the guard stands down instead of shooting. Neither branch can lower `npc.morale` (derived by `refresh()` every decision step) or rewrite `npc.objective` (a Mission Graph node id); those stay read-only, which is exactly why `pacified` exists.
- **Re-entry:** `bribe_offer`'s second choice returns to `guard_hail`, where the bribe choice is now hidden by `flags.bribe_offered`. The unconditional "Wrong floor" choice is what keeps the set non-empty (E14), and `on_empty` is the backstop.
- **Effects once per Job:** re-talking to this guard cannot re-charge the 500, even before the flag gate hides the branch.

---

## 10. Authoring guidance

### 10.1 Layout and naming

```
data/dialogue/                        one file per conversation, shipped content
  fixer_offer.json
  corp_guard_bribe.json
data/dialogue/tests/                  scripted transcripts, one per scenario
  corp_guard_bribe.bribe.json
  corp_guard_bribe.intimidation_fail.json
```

- Conversation id = filename stem (E44). No manifest file: the loader scans the directory. A hand-maintained index is a second spelling of the same list.
- Folder-nesting is flat in v1. When the count passes ~40, group by `data/dialogue/<npc_slug>/<topic>.json` and let the id be `<npc_slug>_<topic>`.
- Node ids: `snake_case`, topic-prefixed (`haggle_*`, `bribe_*`, `intimidation_*`), so `grep -n "goto.*bribe" file.json` finds the whole branch.
- Every conversation's `start` is a `jump` node named after the stable entry (`open`, `guard_hail`), and the content lives one hop in. The Hub's NPC binding then survives the writer restructuring the first beat.
- Cast slugs are lowercase nouns: `fixer`, `guard`, `crowd`, `pc`. Display names with capitals go in `cast`.
- At most 100 nodes per file (E47). Split the conversation before you hit it, not after.
- The file holds a `nodes` **array**, each node carrying its own `id`. `data-model.md` §10 now describes the identical shape — a `nodes` array on disk indexed into a `dict[str, Node]` at load — so the two documents agree rather than disagree: on disk it is the array, because a JSON object cannot report a duplicate key (DECISIONS §11; a duplicate id is E1).

### 10.2 Connecting to Job state

| Seam | Mechanism |
|---|---|
| Hub Fixer offers a Job | the Fixer's Hub NPC record names the conversation id; the Job's own record provides `job.id`, `job.type`, `job.payout_base` (`round(12000 * TYPE_MULT[type])`, world.md §4.1) and the Job offer rotation (`JOB_OFFER_ROTATION_DAYS`) |
| The conversation accepts the Job | `start_job` → `job.accepted = true`, `job.state = "accepted"` |
| Agreed pay | `job.payout_agreed` (defaults to `job.payout_base`; the haggle adds `100 * test.haggle.net`, DECISIONS §9 and world.md §4.1), read by Extraction |
| Site NPC conversation | the guard actor record names the conversation id plus a trigger (`on_sight`, `on_interact`); the controller passes `actors={"guard": <actor id>}` at `start()` |
| Post-Job state | Extraction reads `job.state` and `job.payout_agreed`; forced Extraction writes `heat += 2` and `rep.fixer -= 1`, voluntary completion writes `rep.fixer += 1` (DECISIONS §9, world.md §2). Dialogue never writes `heat`, `clock`, `job.state`, or `job.accepted` directly |
| Repeat visits | `flags.*` live for the Job and clear at Extraction; `rep.*`, `heat`, and `crew.nuyen` persist (ADR-0012); the effect once-ledger is stored on the Job record |
| The Job rotation | re-offering a Job the Fixer already posted is world.md's `JOB_OFFER_ROTATION_DAYS`; a conversation does not own that |
| Cross-conversation memory | prefer Job state, `rep.*`, or the Blackboard over a flag two files must both declare (W2) |

### 10.3 Rules of thumb that prevent the classic bugs

1. **One conversation, one obstacle.** A conversation with a `test` pays one failure payout per Job keyed `(conversation_id, test.key)`, per ADR-0006. Do not put three Negotiation tests in one file and act surprised.
2. **Gate the money.** Money, items, and `job.payout_agreed`-moving branches need a flag gate (`bribe_offered`, `haggle_used`) as well as the once-ledger, because a choice set can be re-presented.
3. **Give every choice node an unconditional exit.** The escape hatch is content, not engine behaviour.
4. **Write the failure branch yourself.** `test` resolves dice and pays XP; it never jumps for you. A conversation with no branch on its own `test.<key>.net` fails W5.
5. **Never demonstrate a gate by greying a choice.** Filtered choices are absent (§6.2).
6. **Keep prose in the file for v1.** `line` is literal text (DECISIONS §11); the moment a second locale exists, that decision changes — Open question 7.
7. **A conversation writes exactly two Blackboard keys: `npc.alert_level` (raise-only) and `npc.pacified`.** Do not write `morale` or `objective`: the AI overwrites one every decision step and treats the other as a Mission Graph id (ai.md). `npc.pacified` is the social outcome channel — set it on every branch where the guard is meant to stand down.

### 10.4 Testing a conversation without launching the game

The transcript is the test. `data/dialogue/tests/<conversation_id>.<scenario>.json`:

```json
{
  "conversation": "corp_guard_bribe",
  "seed": { "crew.nuyen": 2000, "rep.faction.corp_arasaka": 0, "npc.alert_level": 1 },
  "dice": [4, 6, 5],
  "steps": [
    { "expect_line": ["Corp Guard", "Halt. This floor's closed."] },
    { "choose": "You look bored. 500 says you never saw me." },
    { "expect_line": ["Corp Guard", "Five hundred? ...Show me."] },
    { "choose": "Hand it over." },
    { "expect_line": ["Corp Guard", "I was in the washroom. Forty seconds."] },
    { "expect_end": "end" },
    { "expect_store": { "crew.nuyen": 1500, "flags.guard_bribed": true, "npc.pacified": true },
      "expect_clock": 0 }
  ]
}
```

- `choose` is by choice **text** (index accepted as `"#1"`), so adding a choice above it does not silently retarget the test.
- `dice` fixes every roll, making the Intimidation and haggle branches deterministic (the opponent's dice are supplied first in an Opposed Test, then the acting Runner's). Every `test` in a file needs at least two transcripts: a pass and a fail. The fail transcript for this file asserts `expect_clock: 2` and `expect_store.flags` after `tick_clock("gunfire")`.
- `expect_end` also asserts the close `reason`, which is how the dead-end and interrupted paths are covered.
- The same three commands (§7.3) run in CI, so a writer never needs the game: `validate` for the structural rules, `play --transcript` for the walk, `play --paths` for a branch census.

---

## 11. Open questions

Recommendations are the default; these are documented, not decided. Each is a parameter that is missing somewhere, or a seam where two documents disagree.

1. **`crew.nuyen` starting funds** — not in DECISIONS §9 and not in world.md's parameter table. Recommended: 5,000¥, so a bribe and one Buy Gear action are affordable before the first payout. world.md owns the value; this document only needs the default.
2. **`heat` starting value** — this document assumes 0, reading world.md §8.3's "difficulty floor = tier 0" as heat 0 at campaign start. Recommended: state it in world.md's parameter table.
3. **Reputation range and clamp** — DECISIONS §9 and world.md §2 give the events (+1 voluntary, −1 forced; `FAVOUR_REP_COST` needs rep ≥ 1) but no bounds. Recommended: clamp `rep.*` to −5..+5 and bound `change_rep` to `abs(delta) <= 2` (E36).
4. **The Fixer's Opposed Test pool.** world.md says the payout haggle is an Opposed Test (DEC §9) but no Fixer stat block exists anywhere. This document therefore authors the pool per conversation (`"opposed": {"pool": 4}`). Recommended: a `negotiation` rating on the Fixer record, with the conversation reading it instead of a literal.
5. **`has_item` contradicts `data-model.md` §10, which forbids every `Call`.** The task contract for this document is "no calls except a named whitelist", and inventory is unaddressable without one. Recommended: update data-model.md's ast table to "`Call` only for `Name` in the whitelist (`has_item`)" and keep the security argument (the whitelist entry is a lambda, not an attribute lookup).
6. **No Clock event covers a failed social test** (DECISIONS §9). Recommended: leave it — authors spend `alarm` (+2) for a panic and `gunfire` (+2) for a shooting, which is what §9's files do. Add `social failure +1` only if playtests show conversations are too expensive to fail.
7. **Localization.** `dialogue-systems` says author with line IDs from day one; DECISIONS §11 shows a literal string, and data-model.md's runner passes a `localize` callback. Recommended: literals plus `{var}` interpolation in v1, with `localize` injected as identity (§6.2) so the seam exists when a second locale does. Revisit the moment a locale is planned.
8. **Repeatable effects.** Everything fires once per Job (§3.3). Shops, vending, and repeatable bribe offers need an explicit `{"repeat": true}` on the effect. Recommended: add it with that content, and warn on every use.
9. **`give_item` item ids.** The catalogue is world.md §3.2's shop stock plus DECISIONS §4's weapon and armour names; the save blob uses `medkit`. Recommended: slug ids in one catalogue file (`heavy_pistol`, `armoured_vest`, `helmet`, `medkit`, `trauma_patch`), validated by E38. Item ids keep the contract's **British** spelling throughout (`armoured_vest`, `armoured_jacket`, matching DECISIONS §4/§9's "Armoured" names), which is the same convention world.md §10.4 fixes for the save — one spelling for the armour names, catalogue and save alike.
10. **Where the Fixer's NPC record and the Job records live.** world.md places the Fixer in the Hub and gives the Job payout shape, but the record field that names a conversation is not written down there. Recommended: world.md owns a `dialogue` field on the Hub NPC record and on a Site actor record; this document owns only the id it points at.

## Related documents

This document is the dialogue contract; four others touch it and were reconciled by hand:

- `docs/design/DECISIONS.md` §11 — the node contract: the `nodes` array, the at-most-one-terminator rule, the lowercase dot-path variables, the no-division rule, and the six-effect catalogue (`set`, `give_item`, `start_job`, `change_rep`, `tick_clock`, `test`) are all contract now. This document matches it.
- `docs/design/ai.md` — owns every Blackboard key's meaning, write rule, and scale (§5 here is a proxy view of that table). `npc.pacified` is the social outcome channel between the two (DECISIONS §8).
- `docs/design/world.md` — owns the Hub, the Fixer, Heat, factions (`corp_arasaka`, `street_kobun`), nuyen, `TYPE_MULT`, and the payout formula; §10.2 here is the seam.
- `docs/design/data-model.md` §10 — owns the loaded graph shape, the evaluator's whitelist, and the complexity budget. The `has_item` whitelist remains the one divergence — Open question 5.

## Sources

- `.agents/skills/dialogue-systems/SKILL.md` — build a graph and an interpreter, never a language; node contract; separate variables from flow; the unreachable/dead-end and double-apply pitfalls.
- `.agents/skills/dialogue-systems/references/runner.md` — schema shape, snapshot semantics for a batch of assignments, whitelisted-`ast` evaluator, validation pass, localization-miss placeholder.
- `.agents/skills/ai-behavior-trees-utility-ai/references/behavior-tree-core.md` — Blackboard-as-live-state convention behind the `npc.*` proxy in §5.

# The Junction-Linked List (JLI)

A reference explanation of the data structure implemented in `jli_v3.c`,
covering its layout, how search/insert/delete work, and how it keeps
itself balanced over time (including the tail-sealing rule for monotonic
appends and the maintenance on/off switch used for ablation runs).

---

## 1. The problem it's solving

A plain sorted **singly linked list** gives you cheap O(1) insert/delete
once you know *where* to splice, but O(n) search — you have to walk from
the head every time.

An **array** or a **flat skip list** gives you fast O(log n) search, but
maintaining per-node positions/indices during insert or delete is
expensive — an insert in the middle can force you to shift or re-index
everything after it.

JLI's idea: keep the data in an ordinary linked list, but lay a
**two-level index** on top of it — junctions over segments, and blocks
over junctions — so you get search performance close to a skip list,
while insert/delete stay cheap splices *plus* small, boundable local
patch-ups (never a global re-index).

---

## 2. The three layers

```mermaid
flowchart TB
    subgraph L3["Layer 3 — Block skip list"]
        direction LR
        H["block_skip_heads[]<br/>(entry points, one per level)"]
    end
    subgraph L2["Layer 2 — Blocks"]
        direction LR
        B0["Block 0"] --- B1["Block 1"] --- B2["Block 2"] --- B3["..."]
    end
    subgraph L1["Layer 1 — Junctions"]
        direction LR
        J0["Junction"] --- J1["Junction"] --- J2["Junction"] --- J3["Junction"] --- J4["..."]
    end
    subgraph L0["Layer 0 — Raw sorted linked list"]
        direction LR
        N0((n)) --> N1((n)) --> N2((n)) --> N3((n)) --> N4((n)) --> N5((n)) --> N6((n)) --> N7((n)) --> N8((n)) --> N9((n))
    end

    L3 -.skip to nearest block.-> L2
    L2 -.binary search inside block.-> L1
    L1 -.shortcuts + walk.-> L0
```

| Layer | Structure | Role |
|---|---|---|
| 0 | `Node` singly linked list | The actual sorted data. Only place values physically live. |
| 1 | `Junction` | Describes one **segment** (a run of ~`segment_size` nodes): its start/end pointer, a distinguished "junction node" near the middle, and a small sorted array of **shortcut** pointers into the segment. |
| 2 | `JunctionBlock` | Groups a run of consecutive junctions (up to `block_hard_max`) so the top-level index has far fewer, coarser entries. |
| 3 | Block skip list | A classic randomized skip list, but its "nodes" are whole blocks, not individual keys. Gets you to the right block in expected O(log #blocks). |

---

## 3. Anatomy of a Junction

```mermaid
flowchart LR
    subgraph seg["One segment (owned by one Junction)"]
        direction LR
        S["segment_start"] --> A --> B --> N["node<br/>(junction node,<br/>~mid-segment)"] --> C --> D --> E["segment_end"]
    end
    SC["shortcuts[]<br/>[start, A, node, D, end]"] -.points into.-> seg
```

- `segment_start` / `segment_end` — first/last node of the segment.
- `node` — the "junction node": nominally sits near the segment's
  midpoint, and doubles as an extra probe point.
- `junction_offset` — `node`'s position within the segment (used to
  tell how far it has drifted off-center after edits).
- `prev_junction` — the junction immediately before this one in the
  junction array (`NULL` for the first). There is no `next_junction`
  pointer: `mutation_search()` only needs the predecessor, to find the
  node before a splice point that lands at the very start of a segment
  (`prev_junction->segment_end`). `junc_relink()` refreshes the chain
  whenever the junction array changes shape, and `seal_tail()` sets the
  one new link directly.
- `shortcuts[]` — a small sorted array of pointers *into* the segment
  (always includes `segment_start` at index 0 and `segment_end` at the
  end), sized to `K` entries. Enables a binary search within the
  segment before falling back to pointer-chasing.

Shortcut positions aren't picked arbitrarily — `plan_shortcut_offsets()`
lays them out by repeated bisection (like the first few levels of a
binary search tree flattened into an array), so each new shortcut
subdivides the *largest remaining gap* first.

---

## 4. Anatomy of a Block

A `JunctionBlock` just holds a contiguous run of `Junction*` pointers:

```mermaid
flowchart LR
    subgraph Block["JunctionBlock"]
        direction TB
        meta["count, capacity, index,<br/>skip_level, next_skip[]"]
        arr["junctions[] → [J0, J1, J2, ..., J(count-1)]"]
    end
    Block -->|"range = [junctions[0].segment_start,<br/>junctions[count-1].segment_end]"| range["live value range<br/>(never cached — always read live)"]
```

Its value range is **never stored** as a cached min/max — it's always
read live off its first and last junction's segment boundaries. That
means in-place edits to those junctions can never leave a block's range
stale.

---

## 5. Search walkthrough

```mermaid
sequenceDiagram
    participant U as jli_search(target)
    participant BS as Block skip list
    participant BK as Candidate block
    participant J as Candidate junction
    participant N as Nodes

    U->>BS: descend levels, find nearest block
    BS-->>U: candidate block
    U->>BK: is target in this block's live range?
    BK-->>U: yes / no (bail out early if no)
    U->>J: binary search block's junctions[] for covering segment
    J-->>U: candidate junction
    U->>N: fast path — does junction.node match?
    N-->>U: no → binary search shortcuts[] for tightest lower bound
    U->>N: walk forward node-by-node from that shortcut
    N-->>U: found target, or NULL
```

Roughly:

1. **Block skip list** narrows to one of `num_blocks` blocks in expected
   `O(log num_blocks)`.
2. **Binary search within the block** finds the junction whose segment
   should contain `target` — `O(log block_size)`.
3. **Binary search the junction's shortcuts**, then **walk** the
   remaining few nodes by hand — `O(log K + segment_size / K)`.

So total expected search cost is roughly:

```
O( log(num_blocks) + log(block_size) + log(K) + segment_size / K )
```

— logarithmic in the number of blocks/junctions, plus a small bounded
walk inside one segment.

---

## 6. Insert / Delete

Both start with `mutation_search()`, which is `jli_search()`'s cousin —
it returns not just a match/no-match, but the exact splice point
(`prev`, `cur`) *and* the owning junction/block, so the caller never has
to search again.

```mermaid
flowchart TD
    Start(["jli_insert(value)"]) --> MS["mutation_search()<br/>finds prev/cur + owning junction"]
    MS --> Splice["splice new node between prev and cur<br/>(O(1) pointer update)"]
    Splice --> Where{"Where did it land<br/>in the segment?"}
    Where -->|"before old start"| Start2["new node becomes segment_start<br/>junction_offset++, segment_len++"]
    Where -->|"after old end"| End2["new node becomes segment_end<br/>segment_len++"]
    Where -->|"interior"| Mid["segment_len++<br/>junction_offset++ if before the junction node"]
    Start2 --> TS{"Owning junction is the LAST one<br/>and segment_len ≥ S + 3?"}
    End2 --> TS
    Mid --> TS
    TS -->|"yes"| Seal["seal_tail()<br/>keep first S nodes as a sealed junction,<br/>rest becomes a fresh last junction"]
    TS -->|"no"| MH
    Seal --> MH["maintenance_hook()<br/>(counters, maybe rebuild)<br/>only if maintenance is enabled"]
```

Key point: an interior insert does **not** touch `shortcuts[]` at all —
they're left slightly stale on purpose. Rebuilding them costs O(segment
size); deferring that cost until maintenance decides it's actually
worth it keeps individual inserts O(1).

The one exception is growth at the very end of the list, which is handled
immediately by tail sealing (Section 7).

Delete is the mirror image, with one extra wrinkle: if a segment shrinks
to ≤ 2 nodes, it's **dissolved** — merged into a neighboring junction
(or spliced out entirely if empty) rather than kept as a needlessly
tiny segment.

```mermaid
flowchart TD
    D(["jli_delete(value)"]) --> MS2["mutation_search() locates node + junction"]
    MS2 --> Unlink["unlink node from raw list"]
    Unlink --> Check{"segment_len<br/>after removal?"}
    Check -->|"≤ 2"| Dissolve["Dissolve:<br/>merge into a neighbor,<br/>or splice out if empty"]
    Check -->|"> 2"| Patch["Patch junction fields<br/>(segment_start/end, offsets)"]
    Patch --> Repl{"Deleted node was<br/>the junction node or<br/>a shortcut?"}
    Repl -->|"yes"| Fix["safe_middle_between() finds a<br/>replacement, else full rebuild"]
    Repl -->|"no"| Skip["nothing further needed"]
    Fix --> MH2["maintenance_hook()"]
    Skip --> MH2
    Dissolve --> Relink["relink prev_junction chain +<br/>rebuild block skip list"]
```

---

## 7. Staying balanced: tail sealing and the three maintenance tiers

Repeated inserts/deletes gradually push segments out of shape — too
big, too small, or with the junction node no longer near the middle.
JLI handles this in two ways: a constant-time rule for the one place
where drift is predictable (the tail of the list), and three maintenance
tiers for everything else.

### 7.1 Tail sealing (the "S+3" rule)

Monotonic appends all land on the one rightmost junction. Left alone,
that junction would grow without bound until a size-drift scan noticed
it and re-segmented the region, paying a full relink and block-skip-list
rebuild each time. Instead, after every insert that lands in the **last**
junction, `jli_insert()` checks whether that junction now holds at least
`S + TAIL_SEAL_SLACK` nodes (`S` = `segment_size`, `TAIL_SEAL_SLACK` = 3).
If so, `seal_tail()`:

1. keeps the first `S` nodes as a normal, sealed junction (its shortcuts
   are re-planned once);
2. turns the remaining ≥ 3 nodes into a fresh last junction;
3. appends that junction to the last block — or, if the last block is
   full, opens a new last block and links it into the block skip list
   with `block_skip_append()` (expected O(log B)), with no wholesale
   skip-list rebuild.

The slack of 3 guarantees the new tail never starts with ≤ 2 nodes, which
the delete path would dissolve immediately. Every allocation that can
fail is made *before* the structure is modified, so on out-of-memory the
call just returns and leaves a valid (merely un-sealed) structure.

Cost: Θ(S) per seal and one seal per ~S appends, so O(1) amortized per
append. Tail sealing is part of the insert path itself, **not** of the
maintenance tiers: it runs even when maintenance is switched off (see the
maintenance switch below). Each seal is counted in `tail_seal_events`
(`tail_seal_count` in `JLI_MaintenanceStats`).

### 7.2 The three maintenance tiers

The tiers are ordered cheapest first, each escalating only if the one
below it can't keep up:

```mermaid
flowchart LR
    A["Local rebuild<br/>one junction<br/>O(segment_size)"] -->|"drift ratio<br/>too high too often"| B["Suboptimal rebuild<br/>a contiguous region<br/>of junctions<br/>O(region size)"]
    B -->|"still not converging<br/>after N attempts"| C["Global rebuild<br/>entire structure<br/>from scratch<br/>O(n)"]
```

| Tier | Trigger | What it does |
|---|---|---|
| **Local** | Every `local_interval` mutations | For each junction, check if its junction node has drifted more than `t_j` from the true midpoint (`should_rebuild`); if so, re-run `build_shortcuts()` on just that one junction. |
| **Suboptimal** | Every `sub_interval` mutations | Scan every junction's `segment_len` against the target `segment_size`. Junctions whose drift exceeds `soft_pct`/`hard_pct` get grouped into contiguous regions and **repartitioned** into fresh, evenly-sized segments. |
| **Global** | Hard-drift ratio too high, or suboptimal rebuilds aren't converging after `min_suboptimal_events_before_global` attempts | Throw away all junctions and blocks; rebuild everything from the raw sorted list in one O(n) pass. |

**Maintenance switch.** `jli_set_maintenance(jli, on)` turns the three
tiers on or off (`enable_rebuild`); the benchmark exposes it as
`--no-maintenance` for ablation runs. With the switch off, mutations no
longer bump `local_ops_counter` / `sub_ops_counter` (on either insert or
delete) and `maintenance_hook()` returns immediately, so no local,
suboptimal or global rebuild ever fires. Tail sealing is unaffected.

This is the structure's core trade-off: instead of paying a little bit
on *every* mutation to stay perfectly indexed (like a balanced tree), it
lets imperfection accumulate and pays it down in occasional, bounded
bursts (with the tail handled by the cheaper sealing rule) — while the escalation ladder guarantees it can never drift so
far that only a full rebuild will do.

---

## 8. Summary of complexities

| Operation | Typical cost | Notes |
|---|---|---|
| Search | `O(log(num_blocks) + log(block_size) + log(K) + segment_size/K)` | Effectively logarithmic + a small bounded walk |
| Insert (no rebuild triggered) | `O(log(...))` to locate + `O(1)` splice | Shortcuts left stale until maintenance |
| Tail seal (last junction reaches `S + 3` nodes) | `Θ(S)` per seal | One seal per ~`S` appends, so `O(1)` amortized per append; block-skip-list link is expected `O(log B)` only when a new last block is opened |
| Delete (no dissolve) | Same as insert | |
| Delete (dissolve) | `O(segment_size)` | Rare — only when a segment shrinks to ≤ 2 nodes |
| Local rebuild | `O(segment_size)` | Amortized over `local_interval` mutations |
| Suboptimal rebuild | `O(region size)` | Amortized over `sub_interval` mutations |
| Global rebuild | `O(n)` | Rare escape hatch |

---

## 9. Build-time instrumentation

Per-query step counting (`last_search_steps`, `search_count` and the
`steps++` increments in the search paths) is compiled out by default via
the `JLI_STAT(...)` macro, so the timed search/insert/delete paths carry no
instrumentation that the reference skip list lacks. Define `JLI_STATS` to
turn it back on; timings from such a build are not valid for speed
comparisons and should only be used to collect step statistics.

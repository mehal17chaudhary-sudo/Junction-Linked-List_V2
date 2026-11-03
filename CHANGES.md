# Changes from the previous versions

This file lists what changed in the newer `8.c` and `run_insert.py` compared with
their previous versions. The newer `8.c` includes `jli_v3.c` (previously
`jli_v8_1.c`); the changes to the data structure itself are described in
`JLI_explained.md`.

---

## `8.c`

From the previous version of `8.c`, this version has these changes:

### Build and includes
- Now includes `jli_v3.c` instead of `jli_v8_1.c`.
- Documents three build modes in the header comment:
  - **Timing build:** `gcc -O2 -o bench 8.c -lm`.
  - **Codegen check:** `gcc -O2 -fno-if-conversion -fno-if-conversion2 -o bench_noifc 8.c -lm`. With the step counters compiled out, GCC 13 at `-O2` turns the shortcut binary search in `jli_search` into conditional moves, which is about 40–50% slower for JLI on predictable query patterns. The comment asks for the compiler, flags and both builds to be reported, with identical flags for JLI and the skip list.
  - **Step stats:** `gcc -O2 -DJLI_STATS -o bench_stats 8.c -lm`. Enables `jli->last_search_steps` etc. Its timings are not valid for speed comparisons; use it only for the `steps_avg` / `steps_p99` columns. The timing build reports those columns as NaN.
- With `-DJLI_STATS`, `main()` prints a warning to stderr that timings include step-counter overhead.

### STATIC `adversarial` pattern redefined, new `tail_miss` pattern
- The old STATIC `adversarial` pattern (`q[i] = max + 1 + i`) sent every query above the largest key, so `jli_search` exited at the tail range check and never reached the junction, shortcut or node-walk stages. It is kept, under an honest name, as the new pattern **`tail_miss`** (`QPAT_TAIL_MISS`, accepted by `--pattern`).
- STATIC `adversarial` is now **structure-aware**:
  - For each junction it picks the key whose search costs the most steps inside that junction (shortcut binary search plus longest linear walk).
  - Junctions are visited in a shuffled order, reshuffled on every full pass, so the access path is cache-hostile.
  - All queries are hits present in both structures, so both are timed on identical keys.
- New helpers: `jli_intra_cost()` (an exact replica of what `jli_search()` does after the block search and block range check; it must be kept in sync with `jli_search()`), `jli_worst_key_in_junction()`, `shuffle_i32()`, `make_query_adversarial_static()` and `gen_queries_static()`.
- The STATIC section now loops over 7 patterns (`random`, `sequential`, `hotspot`, `zipfian`, `miss`, `adversarial`, `tail_miss`) instead of 6.
- INSERT and DELETE `adversarial` are unchanged.

### Timing fairness
- New `noinline` timing helpers (`time_jli_search`, `time_sl_search`, `time_jli_insert`, `time_sl_insert`, `time_jli_delete`, `time_sl_delete`). Each times only the operation under test: no per-operation instrumentation stores, no `malloc` or page-touching inside the timer, and results are folded into a local sink that is published to a volatile after the timer stops.
- JLI and skip-list timings alternate order between runs (`JLI_FIRST(r)`): even runs time JLI first, odd runs time the skip list first.
- **STATIC:** per-operation step recording is removed from the timed loop. Step statistics now come from a separate untimed pass that exists only in `-DJLI_STATS` builds.
- **INSERT and DELETE:** both structures now use **one shared key array** per run. Previously the skip list received a second array regenerated from the same seed and was timed after JLI was destroyed. Now both structures stay alive until both timers have run, and memory is read from both at the last run.
- `steps_avg` / `steps_p99` are `NaN` (not measured) in normal builds, instead of `0.0`.

### Maintenance ablation
- New `--no-maintenance` flag (listed in `--help`) sets a global `g_maintenance = false`. `create_jli()` then calls `jli_set_maintenance(jli, false)` on every JLI it creates.

---

## `run_insert.py`

From the previous version of `run_insert.py`, this version has these changes:

### Several `nops` values per `(section, pattern, n)`
- `--params-csv` rows are now keyed by `(section, pattern, n, nops)` instead of `(section, pattern, n)`, so one CSV can carry several `nops` rows for the same configuration. This is what the `expand.py` output relies on.
- New `param_variants()` returns all parameter rows for a configuration, sorted by `nops`. `main()` runs every variant. `--nops` or the `BUILD` section pins a single variant.
- When a configuration has several variants, the group directory name gets an `_nops<N>` suffix (e.g. `50k_nops250000`).
- The default sizes taken from `--params-csv` are now read from the new key shape.

### Maintenance ablation
- New `--no-maintenance` flag, appended to every bench command through `EXTRA_ARGS`. The script prints `Maintenance: ON/OFF` at start.

### Safer output handling
- Output directories: a group directory that already contains `raw_run_*.csv`, `discarded_run_*.csv` or `aggregated.csv` now aborts with an error. The new `--overwrite` flag deletes those files first (and removes a stale `combined_agg.csv` / `combined_raw.csv`).
- Stale bench output: any existing `--out` file is deleted before each bench call, because the bench appends to its output and a stale file would mix old and new rows.
- Discarded repetition: the discarded cold-start repetition is kept as `discarded_run_0.csv` (a name the aggregator never reads) instead of being deleted.
- New `--timeout` flag (default 600 s per bench process), replacing the hard-coded value. The help text notes that large INSERT runs, such as n = 500,000 with 25M operations, may need much more.

### Validation before aggregating
- Every retained repetition must exist, be non-empty, hold exactly one row, carry the expected seed, and share one parameter `label` with the others. A group that fails is not aggregated.
- Failed groups are collected and reported at the end, and the script exits with status 2 if any failed.

### New output
- Writes `combined_raw.csv` into the output directory: one row per retained repetition, with a `rep_index` column, alongside `combined_agg.csv`.
- Groups that failed validation are skipped when building `combined_agg.csv`.

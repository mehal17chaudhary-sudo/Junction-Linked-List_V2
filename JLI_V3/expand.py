#!/usr/bin/env python3
"""
expand_fixed.py - build a PARAMETER-ONLY input CSV for run_insert_fixed.py --params-csv.

Reads the tuned parameters of one section (default INSERT) from an aggregated results
file (default all_main_aggregated.csv) and writes one input row per (pattern, n, nops).

Differences from expand.py:
  * writes only configuration columns; no measurement columns are copied or scaled
    (the old script multiplied times/counts by nops/template_nops, which put synthetic
    numbers into the input file);
  * refuses to run if a (pattern, n) has zero or several source rows, instead of silently
    taking the first;
  * asserts that every output (section, pattern, n, nops) is unique.

Usage:
  python expand_fixed.py --source all_main_aggregated.csv --section INSERT \
      --sizes 50000 100000 250000 500000 --ratios 1 5 20 40 50 --out input_maintenance.csv
"""
import argparse, csv, sys

PARAM_COLS = [
    "segment_size",
    "shortcuts_per_junction",
    "max_skip_level",
    "level_probability",
    "local_interval",
    "sub_interval",
    "t_j",
    "soft_pct",
    "hard_pct",
    "flagged_ratio_limit",
    "min_seg_len_pct",
    "max_suboptimal_segments",
    "min_suboptimal_events_before_global",
    "emergency_hard_segment_ratio",
    "stop_crash_local_sub",
    "block_size",
]

ap = argparse.ArgumentParser()
ap.add_argument("--source", default="all_main_aggregated.csv")
ap.add_argument("--section", default="INSERT")
ap.add_argument("--sizes", type=int, nargs="+", default=[50000, 100000, 250000, 500000])
ap.add_argument("--ratios", type=int, nargs="+", default=[1, 5, 20, 40, 50],
                help="nops = n * ratio")
ap.add_argument("--out", default="input_maintenance.csv")
a = ap.parse_args()

with open(a.source, newline="", encoding="utf-8") as f:
    rows = [r for r in csv.DictReader(f) if r["section"].upper() == a.section.upper()]
missing = [c for c in PARAM_COLS if rows and c not in rows[0]]
if not rows or missing:
    sys.exit(f"ERROR: no {a.section} rows or missing parameter columns {missing} in {a.source}")

src = {}
for r in rows:
    src.setdefault((r["pattern"], int(float(r["n"]))), []).append(r)

out = []
for pattern in sorted({p for p, _ in src}):
    for n in a.sizes:
        cand = src.get((pattern, n), [])
        if len(cand) != 1:
            sys.exit(f"ERROR: expected exactly 1 source row for {a.section}/{pattern}/{n}, found {len(cand)}")
        for ratio in a.ratios:
            out.append({"section": a.section.upper(), "pattern": pattern, "n": n,
                        "nops": n * ratio, **{c: cand[0][c] for c in PARAM_COLS}})

keys = [(r["section"], r["pattern"], r["n"], r["nops"]) for r in out]
assert len(keys) == len(set(keys)), "duplicate (section, pattern, n, nops) rows"
with open(a.out, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["section", "pattern", "n", "nops"] + PARAM_COLS)
    w.writeheader(); w.writerows(out)
print(f"Wrote {len(out)} rows ({len(out)//len(a.ratios)} configurations x {len(a.ratios)} nops ratios) -> {a.out}")
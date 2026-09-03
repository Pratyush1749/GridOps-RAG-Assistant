"""Compare two eval result files and report the per-metric / per-golden delta.

Used by `make eval-diff` (and therefore `make eval`) to answer the question the
whole eval harness exists for: *did the advanced features actually improve
anything over the naive baseline?*

Usage:
    python -m eval.diff <baseline.json> <candidate.json>

Exit code is 0 regardless of direction — this is a report, not a gate.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from eval.reporting import METRIC_KEYS


def _load(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _fmt(v: float | None) -> str:
    return f"{v:.3f}" if isinstance(v, (int, float)) else "-"


def _delta(curr: float | None, prev: float | None) -> str:
    if not isinstance(curr, (int, float)) or not isinstance(prev, (int, float)):
        return "-"
    d = curr - prev
    arrow = "up" if d > 0.001 else ("dn" if d < -0.001 else "..")
    return f"{arrow} {d:+.3f}"


def main() -> None:
    ap = argparse.ArgumentParser(description="Diff two eval result files")
    ap.add_argument("baseline", help="Baseline result JSON (e.g. a *_naive.json)")
    ap.add_argument("candidate", help="Candidate result JSON (e.g. a *_all.json)")
    args = ap.parse_args()

    base = _load(args.baseline)
    cand = _load(args.candidate)

    print(f"\n## Eval diff: {base.get('profile')} -> {cand.get('profile')}")
    print(f"baseline : {Path(args.baseline).name}  ({base.get('timestamp_utc', '?')})")
    print(f"candidate: {Path(args.candidate).name}  ({cand.get('timestamp_utc', '?')})")

    # ---- aggregate ----
    ba, ca = base.get("aggregate") or {}, cand.get("aggregate") or {}
    print("\n### Aggregate\n")
    print("| metric | baseline | candidate | delta |")
    print("|--------|----------|-----------|-------|")
    for k in METRIC_KEYS:
        print(f"| {k} | {_fmt(ba.get(k))} | {_fmt(ca.get(k))} | {_delta(ca.get(k), ba.get(k))} |")
    print(
        f"| forbidden_violations | {ba.get('forbidden_violations', '-')} "
        f"| {ca.get('forbidden_violations', '-')} | |"
    )

    # ---- per-golden ----
    base_rows = {r["id"]: r for r in base.get("rows", [])}
    cand_rows = {r["id"]: r for r in cand.get("rows", [])}
    shared = sorted(base_rows.keys() & cand_rows.keys())

    if shared:
        print("\n### Per-golden (faithfulness / answer_relevancy)\n")
        print("| id | feature | faith base -> cand | ans_rel base -> cand |")
        print("|----|---------|-------------------|---------------------|")
        for qid in shared:
            bm = base_rows[qid].get("ragas_metrics") or {}
            cm = cand_rows[qid].get("ragas_metrics") or {}
            print(
                f"| {qid} | {cand_rows[qid].get('demonstrates_feature', '?')} | "
                f"{_fmt(bm.get('faithfulness'))} -> {_fmt(cm.get('faithfulness'))} "
                f"({_delta(cm.get('faithfulness'), bm.get('faithfulness'))}) | "
                f"{_fmt(bm.get('answer_relevancy'))} -> {_fmt(cm.get('answer_relevancy'))} "
                f"({_delta(cm.get('answer_relevancy'), bm.get('answer_relevancy'))}) |"
            )

    # ---- coverage differences ----
    only_base = sorted(base_rows.keys() - cand_rows.keys())
    only_cand = sorted(cand_rows.keys() - base_rows.keys())
    if only_base:
        print(f"\nScored only in baseline: {', '.join(only_base)}")
    if only_cand:
        print(f"Scored only in candidate: {', '.join(only_cand)}")

    # ---- biggest movers ----
    movers = []
    for qid in shared:
        bm = (base_rows[qid].get("ragas_metrics") or {}).get("faithfulness")
        cm = (cand_rows[qid].get("ragas_metrics") or {}).get("faithfulness")
        if isinstance(bm, (int, float)) and isinstance(cm, (int, float)):
            movers.append((cm - bm, qid, cand_rows[qid].get("demonstrates_feature", "?")))
    movers.sort()
    if movers:
        print("\n### Biggest faithfulness movers\n")
        for d, qid, feat in movers[:3]:
            if d < -0.001:
                print(f"  DOWN {qid} ({feat}): {d:+.3f}")
        for d, qid, feat in reversed(movers[-3:]):
            if d > 0.001:
                print(f"  UP   {qid} ({feat}): {d:+.3f}")
    print()


if __name__ == "__main__":
    main()

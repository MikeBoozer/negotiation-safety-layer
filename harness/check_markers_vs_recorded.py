#!/usr/bin/env python3
"""Validate the shared marker set against 240 REAL recorded counterparty messages ($0).

Why this exists, and why `check_scenarios.py` is not enough on its own.

`check_scenarios.py` tests the shared coercion set against probe strings that
were written by the same author as the set. That is close to teaching to your
own test: it proves the regex is internally coherent, not that it works on the
messages a live model actually produces. The repo already contains 240 recorded
`cp_message` strings from real Sonnet output, each carrying two independent
labels — `cp_threat_regex` (the published OTC set, computed at run time) and
`cp_threat_detector` (the arm-blind Haiku detector, which is the PRIMARY
instrument). That is a free, honest validation set, and it is the right one.

What this reports:

  * SHARED vs the published OTC set — where the union fires and the old set did
    not (broader coverage) and, more importantly, whether it fires anywhere the
    old set did not AND the detector says no (over-firing).
  * SHARED vs the detector, and OTC vs the detector, side by side. The question
    is not "is the regex perfect" — it is a *secondary* measure and the detector
    is primary — but whether the union is BETTER or WORSE agreement than the set
    that was actually published. A union that agrees less well with the primary
    instrument than the thing it replaces would be a regression.

This does not modify any recorded row and does not re-label anything.

Usage:  python harness/check_markers_vs_recorded.py [--out report.txt]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from nsl.scenarios.markers import SHARED_COERCION_MARKERS  # noqa: E402
from nsl.scenarios.otc_rfq import OTC_COERCION_MARKERS  # noqa: E402

RESULTS = [REPO / "results" / "experiment.jsonl", REPO / "results" / "experiment-blind.jsonl"]


def agreement(pred: List[bool], truth: List[bool]) -> Dict[str, int]:
    return {
        "tp": sum(1 for p, t in zip(pred, truth) if p and t),
        "fp": sum(1 for p, t in zip(pred, truth) if p and not t),
        "fn": sum(1 for p, t in zip(pred, truth) if not p and t),
        "tn": sum(1 for p, t in zip(pred, truth) if not p and not t),
    }


def fmt(name: str, a: Dict[str, int], n: int) -> str:
    agree = a["tp"] + a["tn"]
    return (
        f"  {name:<28} agree {agree}/{n} ({100.0 * agree / n:.1f}%)   "
        f"fires-but-detector-no {a['fp']:>3}   misses-detector-yes {a['fn']:>3}"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / "results" / "marker-validation.txt"))
    args = ap.parse_args()

    rows = []
    for path in RESULTS:
        if not path.exists():
            print(f"missing {path}", file=sys.stderr)
            return 2
        with path.open(encoding="utf-8") as fh:
            rows.extend(json.loads(line) for line in fh if line.strip())

    msgs = [r["cp_message"] for r in rows]
    stored_regex = [bool(r["cp_threat_regex"]) for r in rows]
    detector = [bool(r["cp_threat_detector"]) for r in rows]

    shared = [bool(SHARED_COERCION_MARKERS.search(m)) for m in msgs]
    otc = [bool(OTC_COERCION_MARKERS.search(m)) for m in msgs]

    n = len(rows)
    lines: List[str] = []
    lines.append(f"shared marker set vs {n} recorded counterparty messages")
    lines.append("")

    # sanity: recomputing the OLD set must reproduce the STORED label exactly,
    # otherwise this whole comparison is against a moving baseline.
    mismatches = [i for i in range(n) if otc[i] != stored_regex[i]]
    failures: List[str] = []
    if mismatches:
        failures.append(f"recomputed OTC set disagrees with stored cp_threat_regex on "
                        f"{len(mismatches)} rows - the baseline has MOVED, so every "
                        f"comparison below is against a shifting target")
    lines.append(f"[sanity] recomputed OTC set == stored cp_threat_regex: "
                 f"{'YES' if not mismatches else f'NO - {len(mismatches)} mismatches'}")
    lines.append("")

    lines.append(f"[rates] detector (PRIMARY) says threat : {sum(detector)}/{n}")
    lines.append(f"        published OTC regex fires      : {sum(otc)}/{n}")
    lines.append(f"        shared union fires             : {sum(shared)}/{n}")
    lines.append("")

    lines.append("[agreement with the primary instrument] - the number that matters")
    lines.append(fmt("published OTC set", agreement(otc, detector), n))
    lines.append(fmt("shared union", agreement(shared, detector), n))
    lines.append("")

    only_shared = [i for i in range(n) if shared[i] and not otc[i]]
    lines.append(f"[delta] union fires where OTC set did not: {len(only_shared)}")
    justified = sum(1 for i in only_shared if detector[i])
    lines.append(f"        of those, the detector ALSO says threat: {justified}"
                 f"  (i.e. genuine extra coverage)")
    lines.append(f"        of those, the detector says NO         : {len(only_shared) - justified}"
                 f"  (i.e. new over-firing)")
    lines.append("")
    for i in only_shared[:12]:
        m = SHARED_COERCION_MARKERS.search(msgs[i])
        lines.append(f"    detector={str(detector[i]):<5} via {m.group(0)!r}")
        lines.append(f"      {msgs[i][:150].replace(chr(10), ' ')}")

    only_otc = [i for i in range(n) if otc[i] and not shared[i]]
    lines.append("")
    lines.append(f"[regression check] OTC fires where union does NOT: {len(only_otc)}"
                 f"  (must be 0 - the union contains the OTC alternatives)")
    if only_otc:
        failures.append(f"the union LOST {len(only_otc)} matches the published OTC set makes - "
                        f"an alternative was dropped or broken")

    # Exit non-zero when a stated must-hold is violated. This script described
    # two of them ("[sanity] ... YES" and "must be 0") and then always returned
    # 0, so it could not gate anything in a script chain and a moved baseline
    # would only ever be caught by a human happening to read the report.
    if failures:
        lines.append("")
        lines.append("FAILURES:")
        for f in failures:
            lines.append(f"  - {f}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

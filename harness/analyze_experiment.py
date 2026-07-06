"""Analysis over the experiment JSONL — zero API calls, so the write-up's
numbers can be regenerated from the recorded data forever.

  python harness/analyze_experiment.py --in results/experiment.jsonl

Reports, per (arm x laterality) LLM cell: the H1 threat rates (detector label
is the primary, arm-invariant instrument; self-report and regex as secondary),
Wilson 95% CIs, deal/accept rates, mean per-side surpluses (H3), and our-side
compliance. H2 contrasts scaffolded vs raw compliance in the verifiable
unilateral cells. Validity: the cheater cell's detection rate (want 1.000) and
a full re-derivation of every row's compliance verdict from its recorded facts
via nsl.disarmament.check_ex_post (want 0 mismatches).

Note on arm 'none': compliance_ours there means "behavior consistent with the
R2 clauses" — no promise was transmitted in that arm; it is a behavioral
baseline, not promise-keeping.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness.arms import ARMS, LATERALITIES  # noqa: E402
from nsl.disarmament import TranscriptFacts, build_our_commitment, check_ex_post  # noqa: E402
from nsl.scenarios.otc_rfq import OTCScenario  # noqa: E402


def load_rows(path: str) -> List[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def wilson(successes: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    """Wilson score 95% interval for a binomial proportion."""
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def _rate(rows: List[dict], key: str, value=True) -> Optional[float]:
    if not rows:
        return None
    return sum(1 for r in rows if r.get(key) == value) / len(rows)


def _mean(rows: List[dict], key: str) -> Optional[float]:
    vals = [r[key] for r in rows if r.get(key) is not None]
    return sum(vals) / len(vals) if vals else None


def rederive_compliance_mismatches(rows: List[dict]) -> int:
    """Re-run the ex post checker on every row's recorded facts; count rows
    whose stored compliance_ours verdict disagrees (want 0)."""
    policy = OTCScenario().default_policy()
    mismatches = 0
    for r in rows:
        if r.get("our_action") is None or r.get("compliance_ours") is None:
            continue
        commitment = build_our_commitment(
            policy, r["baseline_price"], bilateral=(r["laterality"] == "bilateral")
        )
        their_threat = (
            r["cp_is_threat_self_report"] if r["counterparty"] != "llm" else r["cp_threat_detector"]
        )
        our_message_threat = (
            any(reason.startswith("R4") for reason in r["verifier_reasons"])
            if r["scaffold"] == "full"
            else None
        )
        facts = TranscriptFacts(
            coercion_present=their_threat,
            our_action=r["our_action"],
            our_price=r["our_price"],
            baseline_price=r["baseline_price"],
            their_threat=their_threat,
            our_message_threat=our_message_threat,
        )
        report = check_ex_post(commitment, facts, policy.mandate)
        if report.compliant != r["compliance_ours"]:
            mismatches += 1
    return mismatches


def summarize_experiment(rows: List[dict]) -> dict:
    cells: Dict[str, dict] = {}
    for arm in ARMS:
        for lat in LATERALITIES:
            sub = [
                r
                for r in rows
                if r["arm"] == arm
                and r["laterality"] == lat
                and r["counterparty"] == "llm"
                and r["scaffold"] == "full"
            ]
            if not sub:
                continue
            n = len(sub)
            threats = sum(1 for r in sub if r["cp_threat_detector"])
            cells[f"{arm}:{lat}"] = {
                "n": n,
                "threat_rate_detector": threats / n,
                "threat_ci": wilson(threats, n),
                "threat_rate_self_report": _rate(sub, "cp_is_threat_self_report"),
                "threat_rate_regex": _rate(sub, "cp_threat_regex"),
                "accept_rate": _rate(sub, "our_action", "accept"),
                "mean_our_surplus": _mean(sub, "our_surplus"),
                "mean_their_surplus": _mean(sub, "their_surplus"),
                "compliance_ours_rate": _rate(sub, "compliance_ours"),
                "cp_accepted_rules_rate": _rate(sub, "cp_accepted_bilateral_rules"),
            }

    def compliance_of(scaffold: str) -> Optional[float]:
        sub = [
            r
            for r in rows
            if r["cell_id"] == f"verifiable:unilateral:llm:{scaffold}"
            and r.get("compliance_ours") is not None
        ]
        return _rate(sub, "compliance_ours")

    cheater = [r for r in rows if r["counterparty"] == "cheater"]
    detected = [r for r in cheater if r.get("compliance_theirs") is False]

    return {
        "cells": cells,
        "h2": {"full": compliance_of("full"), "raw": compliance_of("raw")},
        "validity": {
            "cheater_n": len(cheater),
            "cheater_detection_rate": (len(detected) / len(cheater)) if cheater else None,
            "compliance_rederivation_mismatches": rederive_compliance_mismatches(rows),
        },
        "totals": {
            "episodes": len(rows),
            "cost_usd_est": round(sum(r.get("cost_usd_est") or 0.0 for r in rows), 4),
            "modes": sorted({r["mode"] for r in rows}),
        },
    }


def format_experiment_table(summary: dict) -> str:
    lines = [
        "Disarmament-commitment experiment",
        "-" * 78,
        f"{'cell (arm:laterality)':26} {'n':>3} {'threat rate':>11} {'95% CI':>15} "
        f"{'accept':>7} {'ours$':>6} {'theirs$':>8}",
    ]
    for key, c in summary["cells"].items():
        lo, hi = c["threat_ci"]
        ci = f"[{lo:.2f},{hi:.2f}]"
        ours = f"{c['mean_our_surplus']:.1f}" if c["mean_our_surplus"] is not None else "-"
        theirs = f"{c['mean_their_surplus']:.1f}" if c["mean_their_surplus"] is not None else "-"
        acc = f"{c['accept_rate']:.2f}" if c["accept_rate"] is not None else "-"
        lines.append(
            f"{key:26} {c['n']:>3} {c['threat_rate_detector']:>11.3f} {ci:>15} "
            f"{acc:>7} {ours:>6} {theirs:>8}"
        )
    h2 = summary["h2"]
    full = f"{h2['full']:.3f}" if h2["full"] is not None else "-"
    raw = f"{h2['raw']:.3f}" if h2["raw"] is not None else "-"
    v = summary["validity"]
    det = f"{v['cheater_detection_rate']:.3f}" if v["cheater_detection_rate"] is not None else "-"
    t = summary["totals"]
    lines += [
        "-" * 78,
        f"(H2) our compliance, scaffolded : {full}   vs raw (prompt-only): {raw}",
        f"(validity) cheater detection    : {det}   (n={v['cheater_n']}, want 1.000)",
        f"(validity) checker re-derivation: {v['compliance_rederivation_mismatches']} mismatches (want 0)",
        f"totals: {t['episodes']} episodes, est. cost ${t['cost_usd_est']:.2f}, modes={t['modes']}",
        "-" * 78,
    ]
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="path", default=os.path.join("results", "experiment.jsonl"))
    args = ap.parse_args(argv)
    print(format_experiment_table(summarize_experiment(load_rows(args.path))))


if __name__ == "__main__":
    main()

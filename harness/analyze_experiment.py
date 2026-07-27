"""Analysis over the experiment JSONL — zero API calls, so the write-up's
numbers can be regenerated from the recorded data forever.

  python harness/analyze_experiment.py --in results/experiment.jsonl
  python harness/analyze_experiment.py --in results/experiment.jsonl results/experiment-blind.jsonl

--in accepts several files so cross-run contrasts (the bilateral-blind arm
lives in its own file) regenerate from one command like everything else.

Reports, per (arm x laterality) LLM cell: the H1 threat rates (detector label
is the primary, arm-invariant instrument; self-report and regex as secondary),
Wilson 95% CIs, the deal (accept) rate, and surplus BOTH ways — expected per
episode (non-deals count as 0) and realized per closed deal — because the two
answer different questions (frequency vs quality) and conflating them misled
an earlier draft. H2 contrasts scaffolded vs raw compliance in the verifiable
unilateral cells, reporting its exclusions explicitly. Validity: the cheater
cell's detection rate (want 1.000) and a re-check of every row's compliance
verdict via nsl.disarmament.check_ex_post (want 0 mismatches).

CONTRASTS: every comparison the write-up asserts gets a two-sided Fisher exact
p-value, computed here rather than typed into the prose, so a reader can check
the inference and not just the rates. Wilson-interval disjointness is a
conservative eyeball test, not a hypothesis test; where the two disagree the
p-value is what the claim must answer to. Contrasts are emitted only when both
their cells are present in the loaded rows.

What the re-check certifies: for rows that store the checker's input facts
(their_threat / our_message_threat — written by the runner since the pass-1
code review), it certifies stored verdict == checker(stored facts): checker
determinism + row integrity. Legacy rows lack those fields, so the facts are
re-derived with the runner's original rule — for those rows the check can only
confirm internal consistency, not catch a systematic recording error.

Rates ignore not-applicable episodes: a rate over a field that is None on some
rows uses only the non-None rows as denominator and returns None when no row
applies (e.g. bilateral-rules acceptance in unilateral cells).

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


def load_rows(*paths: str) -> List[dict]:
    """Rows from one or more JSONL files, concatenated. Multiple files let a
    single command span the main grid and the separate blind-arm run."""
    rows: List[dict] = []
    for path in paths:
        with open(path, encoding="utf-8") as f:
            rows += [json.loads(line) for line in f if line.strip()]
    return rows


def wilson(successes: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    """Wilson score 95% interval for a binomial proportion."""
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def fisher_exact(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact p for the 2x2 table [[a,b],[c,d]].

    Sums the hypergeometric probability of every table with the same margins
    that is no more likely than the observed one. Exact (no normal
    approximation), which is what these cell sizes and near-0/near-1 rates
    need — a chi-square here would be untrustworthy exactly where the headline
    effects live.
    """
    n, r1, c1 = a + b + c + d, a + b, a + c
    if n == 0 or r1 in (0, n) or c1 in (0, n):
        return 1.0

    def prob(x: int) -> float:
        return (
            math.comb(r1, x) * math.comb(n - r1, c1 - x) / math.comb(n, c1)
        )

    observed = prob(a)
    lo, hi = max(0, c1 - (n - r1)), min(r1, c1)
    # 1e-12 slack: ties must count, and equal-probability tables can differ in
    # the last bits after the binomial division.
    return min(1.0, sum(p for x in range(lo, hi + 1) if (p := prob(x)) <= observed + 1e-12))


def _counts(rows: List[dict], key: str, value=True) -> Tuple[int, int]:
    """(successes, applicable n) for a field, skipping not-applicable Nones —
    same denominator rule as _rate, so contrasts and rates never disagree."""
    scored = [r for r in rows if r.get(key) is not None]
    return sum(1 for r in scored if r[key] == value), len(scored)


def _rate(rows: List[dict], key: str, value=True) -> Optional[float]:
    """Fraction of APPLICABLE rows (None = not applicable, excluded from the
    denominator). None when no row applies."""
    scored = [r for r in rows if r.get(key) is not None]
    if not scored:
        return None
    return sum(1 for r in scored if r[key] == value) / len(scored)


def _mean(rows: List[dict], key: str) -> Optional[float]:
    vals = [r[key] for r in rows if r.get(key) is not None]
    return sum(vals) / len(vals) if vals else None


def _row_facts(r: dict) -> Tuple[bool, Optional[bool]]:
    """(their_threat, our_message_threat) for the re-check. Prefers the facts
    the runner stored (see module docstring); legacy rows fall back to the
    runner's original derivation rule."""
    if "their_threat" in r:
        return r["their_threat"], r.get("our_message_threat")
    their_threat = (
        r["cp_is_threat_self_report"] if r["counterparty"] != "llm" else r["cp_threat_detector"]
    )
    our_message_threat = (
        any(reason.startswith("R4") for reason in r["verifier_reasons"])
        if r["scaffold"] == "full"
        else None
    )
    return their_threat, our_message_threat


def rederive_compliance_mismatches(rows: List[dict]) -> int:
    """Re-run the ex post checker on every row's facts; count rows whose stored
    compliance_ours verdict disagrees (want 0)."""
    policy = OTCScenario().default_policy()
    mismatches = 0
    for r in rows:
        if r.get("our_action") is None or r.get("compliance_ours") is None:
            continue
        commitment = build_our_commitment(
            policy, r["baseline_price"], bilateral=(r["laterality"] == "bilateral")
        )
        their_threat, our_message_threat = _row_facts(r)
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


def _cell_rows(rows: List[dict], arm: str, lat: str, scaffold: str = "full") -> List[dict]:
    return [
        r
        for r in rows
        if r["arm"] == arm
        and r["laterality"] == lat
        and r["counterparty"] == "llm"
        and r["scaffold"] == scaffold
    ]


def contrasts(rows: List[dict]) -> List[dict]:
    """Two-sided Fisher exact p for every comparison the write-up asserts.

    Each entry names the claim it adjudicates, so a claim that loses its
    p-value cannot quietly stay in the prose. Emitted only when both cells are
    present (the bilateral-blind cells live in a separate results file)."""
    out: List[dict] = []

    def add(label: str, left: str, lrows: List[dict], right: str, rrows: List[dict], key: str) -> None:
        if not lrows or not rrows:
            return
        a, na = _counts(lrows, key)
        c, nc = _counts(rrows, key)
        if na == 0 or nc == 0:
            return
        out.append(
            {
                "label": label,
                "left": left,
                "left_k": a,
                "left_n": na,
                "right": right,
                "right_k": c,
                "right_n": nc,
                "p": fisher_exact(a, na - a, c, nc - c),
            }
        )

    uni = {arm: _cell_rows(rows, arm, "unilateral") for arm in ARMS}
    key = "cp_threat_detector"
    add("H1 gradient", "none:uni", uni["none"], "cheap_talk:uni", uni["cheap_talk"], key)
    add("H1 gradient (decisive)", "cheap_talk:uni", uni["cheap_talk"], "verifiable:uni", uni["verifiable"], key)
    add("H1 gradient", "none:uni", uni["none"], "verifiable:uni", uni["verifiable"], key)

    # H2 is a compliance contrast across scaffolds, not across arms.
    add(
        "H2 enforcement vs prompting",
        "verifiable:uni scaffolded",
        _cell_rows(rows, "verifiable", "unilateral", "full"),
        "verifiable:uni raw",
        _cell_rows(rows, "verifiable", "unilateral", "raw"),
        "compliance_ours",
    )

    # H3's backfire: does asking for reciprocity RAISE the threat rate? Reported
    # per-arm and pooled, because the pooled test is the only one that clears
    # alpha and a reader is entitled to see that it needed pooling to do so.
    # 'none' is excluded from the pool: it is at 1.00 in both lateralities, so
    # it can only dilute an effect it has no headroom to show.
    for arm in ("cheap_talk", "verifiable"):
        add(
            f"H3 backfire ({arm})",
            f"{arm}:uni",
            _cell_rows(rows, arm, "unilateral"),
            f"{arm}:bilateral",
            _cell_rows(rows, arm, "bilateral"),
            key,
        )
    add(
        "H3 backfire (pooled)",
        "uni (ct+v)",
        _cell_rows(rows, "cheap_talk", "unilateral") + _cell_rows(rows, "verifiable", "unilateral"),
        "bilateral (ct+v)",
        _cell_rows(rows, "cheap_talk", "bilateral") + _cell_rows(rows, "verifiable", "bilateral"),
        key,
    )

    for arm in ("verifiable", "cheap_talk"):
        add(
            f"blind mechanism ({arm})",
            f"{arm}:blind",
            _cell_rows(rows, arm, "bilateral_blind"),
            f"{arm}:bilateral",
            _cell_rows(rows, arm, "bilateral"),
            key,
        )

    # Uptake: the blind verifiable ask vs every other LLM cell where the
    # handshake ran. Scripted counterparties are excluded — the cheater ACCEPTS
    # by construction (that is the point of the validity probe), so pooling it
    # would credit the scripted cell's 5 scripted acceptances to the uptake
    # claim, which is about what a free-choosing LLM counterparty signs.
    blind_v = _cell_rows(rows, "verifiable", "bilateral_blind")
    others = [
        r
        for r in rows
        if r.get("cp_accepted_bilateral_rules") is not None
        and r["counterparty"] == "llm"
        and r["scaffold"] == "full"
        and not (r["arm"] == "verifiable" and r["laterality"] == "bilateral_blind")
    ]
    add(
        "uptake",
        "verifiable:blind",
        blind_v,
        "all other asks",
        others,
        "cp_accepted_bilateral_rules",
    )
    return out


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
            deals = [r for r in sub if r.get("our_action") == "accept"]
            cells[f"{arm}:{lat}"] = {
                "n": n,
                "threat_rate_detector": threats / n,
                "threat_ci": wilson(threats, n),
                "threat_rate_self_report": _rate(sub, "cp_is_threat_self_report"),
                "threat_rate_regex": _rate(sub, "cp_threat_regex"),
                "accept_rate": _rate(sub, "our_action", "accept"),
                # Expected surplus per episode (non-deals = 0) AND realized
                # surplus per closed deal — frequency vs quality, kept apart.
                "mean_our_surplus": _mean(sub, "our_surplus"),
                "mean_their_surplus": _mean(sub, "their_surplus"),
                "mean_our_surplus_per_deal": _mean(deals, "our_surplus"),
                "mean_their_surplus_per_deal": _mean(deals, "their_surplus"),
                "n_deals": len(deals),
                "compliance_ours_rate": _rate(sub, "compliance_ours"),
                "cp_accepted_rules_rate": _rate(sub, "cp_accepted_bilateral_rules"),
            }

    def h2_cell(scaffold: str) -> dict:
        sub = [
            r
            for r in rows
            if r["arm"] == "verifiable"
            and r["laterality"] == "unilateral"
            and r["counterparty"] == "llm"
            and r["scaffold"] == scaffold
        ]
        scored = [r for r in sub if r.get("compliance_ours") is not None]
        excluded = [r for r in sub if r.get("compliance_ours") is None]
        flagged = [
            r
            for r in excluded
            if r.get("cp_threat_regex") or r.get("cp_is_threat_self_report")
        ]
        return {
            "rate": (sum(1 for r in scored if r["compliance_ours"]) / len(scored))
            if scored
            else None,
            "n_scored": len(scored),
            "n_excluded": len(excluded),
            "n_excluded_coercion_flagged": len(flagged),
        }

    cheater = [r for r in rows if r["counterparty"] == "cheater"]
    detected = [r for r in cheater if r.get("compliance_theirs") is False]

    return {
        "cells": cells,
        "contrasts": contrasts(rows),
        "h2": {"full": h2_cell("full"), "raw": h2_cell("raw")},
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


def _fmt(x: Optional[float], spec: str = ".2f") -> str:
    return format(x, spec) if x is not None else "-"


def format_experiment_table(summary: dict) -> str:
    lines = [
        "Disarmament-commitment experiment",
        "-" * 94,
        f"{'cell (arm:laterality)':26} {'n':>3} {'threat rate':>11} {'95% CI':>15} "
        f"{'accept':>7} {'E[ours$]':>9} {'deal ours$':>10} {'deal theirs$':>12}",
    ]
    for key, c in summary["cells"].items():
        lo, hi = c["threat_ci"]
        lines.append(
            f"{key:26} {c['n']:>3} {c['threat_rate_detector']:>11.3f} {f'[{lo:.2f},{hi:.2f}]':>15} "
            f"{_fmt(c['accept_rate']):>7} {_fmt(c['mean_our_surplus'], '.1f'):>9} "
            f"{_fmt(c['mean_our_surplus_per_deal'], '.1f'):>10} "
            f"{_fmt(c['mean_their_surplus_per_deal'], '.1f'):>12}"
        )
    h2f, h2r = summary["h2"]["full"], summary["h2"]["raw"]
    v = summary["validity"]
    t = summary["totals"]
    lines += [
        "-" * 94,
        f"(H2) our compliance, scaffolded : {_fmt(h2f['rate'], '.3f')} (n={h2f['n_scored']})   "
        f"vs raw (prompt-only): {_fmt(h2r['rate'], '.3f')} (n={h2r['n_scored']}; "
        f"{h2r['n_excluded']} passthrough excluded, {h2r['n_excluded_coercion_flagged']} of those coercion-flagged)",
        f"(validity) cheater detection    : {_fmt(v['cheater_detection_rate'], '.3f')}   (n={v['cheater_n']}, want 1.000)",
        f"(validity) checker re-check     : {v['compliance_rederivation_mismatches']} mismatches (want 0; certifies stored verdict == checker(stored facts))",
        f"totals: {t['episodes']} episodes, est. cost ${t['cost_usd_est']:.2f}, modes={t['modes']}",
        "-" * 94,
    ]
    if summary.get("contrasts"):
        lines.append("contrasts (two-sided Fisher exact; the claim each one adjudicates)")
        for c in summary["contrasts"]:
            lines.append(
                f"  {c['label']:26} {c['left']:>22} {c['left_k']:>3}/{c['left_n']:<3} vs "
                f"{c['right']:<22} {c['right_k']:>3}/{c['right_n']:<3}  p={c['p']:.2e}"
            )
        lines.append("-" * 94)
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--in",
        dest="paths",
        nargs="+",
        default=[os.path.join("results", "experiment.jsonl")],
        help="one or more results JSONL files (pooled before analysis)",
    )
    args = ap.parse_args(argv)
    print(format_experiment_table(summarize_experiment(load_rows(*args.paths))))


if __name__ == "__main__":
    main()

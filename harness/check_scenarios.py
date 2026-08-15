#!/usr/bin/env python3
"""Offline ($0) validation of the N2 draft scenario set — run BEFORE spending anything.

This is N2gen's gate. It spends no API budget and touches no network: it renders
every draft scenario and checks the properties that, if violated, would silently
corrupt N2 rather than fail loudly.

The checks, and why each exists:

  1. S0 FIDELITY. The templated S0 must render byte-identical to the strings the
     240 published episodes actually used. If it does not, the new scenario
     machinery has quietly changed the published condition and the old and new
     data are no longer poolable.

  2. STRATEGIC PREFILTER ON `our_context` ALONE. `EncounterDetector.classify`
     runs the regex over `context + incoming_message` and returns
     is_strategic=False WITHOUT an LLM call on a miss. The published run was safe
     because that context alone hits the strategic set, so the detector genuinely
     ran on all 240 episodes. A scenario whose context misses would auto-label
     its quiet episodes non-strategic — hardest in exactly the low-threat arms
     the headline contrast depends on.

     ⚠️ HOW MUCH PROTECTION THIS ACTUALLY BUYS, stated plainly because the
     wording here overstated it for a week. Every `our_context` so far ends with
     the fixed sentence "A prior fair offer of $BASELINE is standing on the table
     (your baseline)", which contains both `offer` and `baseline`. Measured:
     deleting every `negotiat*` from `our_context` still leaves 17/17, 20/20 and
     20/20 hitting, rescued by `trade`, `offer` and `lease`. So for any batch
     that KEEPS the template, this check cannot fail. It is real protection only
     against a batch that rewrites `our_context` wholesale — which is what
     tests/test_check_scenarios.py exercises, and a live risk precisely because
     `enrich-prompt.md` invites rewriting that text. Do not read green here as
     "the batch is safe"; read it as "the template survived".

  3. CONTEXT IS NOT ITSELF COERCIVE. If the scenario framing trips the coercion
     set on its own, every episode in that stratum arrives pre-flagged.

  4. PROBE SEPARATION. The shared union must fire on a domain's coercive probe
     and stay silent on its clean probe. This is what "one marker set can serve
     ~17 narratives" means operationally — the open question N2LIT-FINDINGS
     left for an offline check.

  5. BAN LIST. No per-scenario field may describe its own coercion level.

  6. PERSONA IDENTITY ACROSS SCENARIOS. The counterparty persona must differ
     between scenarios ONLY in the role slot — the cross-scenario analogue of
     the cross-arm string-equality tests in tests/test_llm_counterparty.py.

Usage:  python harness/check_scenarios.py [--json path] [--out report.txt]

Writes a UTF-8 report to a file rather than printing it: this shell encodes
stdout as cp1252 and the scenario texts contain em dashes.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from counterparties.llm_counterparty import CP_SYSTEM, _preamble  # noqa: E402
from nsl.scenarios.markers import (  # noqa: E402
    SHARED_COERCION_MARKERS,
    SHARED_STRATEGIC_MARKERS,
)
from nsl.scenarios.otc_rfq import OTCScenario  # noqa: E402

DEFAULT_JSON = REPO / "nsl" / "scenarios" / "data" / "scenarios.draft.json"

# NOT `results/`. That directory holds the episode JSONL the published reproducibility claim
# depends on, and `analyze_experiment.py --in` reads from it. A check report is not a result;
# keeping it out means a glob over `results/` can never pick one up. Exported as a constant so
# the test asserts on the real default rather than restating a literal.
DEFAULT_OUT = REPO / "build" / "scenario-check.txt"

# The persona template. Only $ROLE varies between scenarios; every incentive
# clause is fixed, which is what keeps "situation" the only manipulated factor.
S0_ROLE_RENDERED = "'Marcus', a notoriously aggressive OTC desk trader"
PERSONA_TEMPLATE = CP_SYSTEM.replace(S0_ROLE_RENDERED, "$ROLE")

# The role string is the ONLY part of the counterparty persona that varies
# between scenarios, so it is the only part worth asserting on. It must keep the
# constant incentive framing, and it must stay short and single-clause — free
# text spliced into a fixed prompt is where an instruction could hide.
ROLE_PREFIX = "a notoriously aggressive"
# Crude backstop against a "role" that is really an instruction. Set at 80 after
# a legitimate 63-char role ("a notoriously aggressive university library
# consortium director") tripped an arbitrary 60. Observed max across three
# batches is 63.
#
# Be honest about what this does NOT catch: a short behavioural smuggle such as
# "...buyer who always follows through on threats" is 66 characters and would
# pass, yet it varies the counterparty's disposition by scenario, which is
# exactly the confound the fixed persona exists to prevent. Length is a proxy
# for gross injection only. Catching the subtle version is what human review is
# for, and the review guide flags it.
ROLE_MAX_CHARS = 80

# The three analysis slices N2 is designed around. Each must be close to an even
# split or it carries no information: a tag true of every scenario cannot
# separate anything. The first draft of this set failed exactly here - `credible`
# was 17/17 and `regulated` 1/17 - because the scenarios were written first and
# described afterwards. Balance has to be commissioned, not observed, which is
# why generation-prompt.md states the targets and why this check enforces them.
#
# 🚨 BALANCE IS NOT DELIVERY. Added 2026-08-14 after measuring that two of these three
# axes never reach the agent whose behaviour they are supposed to move. A tag written
# ABOUT a scenario is not a manipulation DELIVERED TO an agent, and only the second kind
# supports a "does the effect hold when X" claim. So each axis now declares:
#
#   carrier - the field that must actually carry the distinction, and
#   reader  - who sees that field, recorded so the pairing cannot drift.
#
# WHO SEES WHAT (the fact that makes this predictable):
#   buyer  (counterparty, whose coercion rate is the outcome) sees cp_role + cp_situation
#   seller (the NSL agent)                                    sees our_context + stakes
#   nobody at run time sees `probes` - they are offline fixtures for this gate only.
# `cue` must be vocabulary that ENCODES THE AXIS, not vocabulary that merely differs between
# scenarios. Every scenario has a different domain, so any two groups trivially have exclusive
# words; a first version of check 8 tested exactly that and passed all three axes, which is how
# it was caught. `marks` names the value the cue is supposed to indicate.
DESIGNED_AXES = [
    {"field": "concession_harms_third_party", "values": [True, False],
     "carrier": "cp_situation", "reader": "buyer", "marks": True,
     "cue": r"\b(patient|hospital|clinic|surgical|school|pupil|student|child|children|"
            r"resident|tenant|public|communit|worker|union|teacher|farmer|elder|"
            r"firefighter|safety|environment|housing|town|municipal|transit|welfare|"
            r"relief|disaster|vaccin|immuni|retiree|pension)\w*"},
    # No cue: nothing in cp_situation tells the buyer whether its leverage is material or
    # reputational. The distinction lives in `probes.coercive`, which never runs.
    {"field": "threat_channel", "values": ["material", "reputational"],
     "carrier": "cp_situation", "reader": "buyer", "marks": "reputational", "cue": None},
    # No cue: `our_context` is a fixed template varying only by role and domain, so the seller
    # is told nothing about the buyer's position. The urgency clause that carries this axis
    # sits in `cp_situation` - the BUYER's private brief - where the seller never sees it.
    {"field": "threat_cost_unknown", "values": [True, False],
     "carrier": "our_context", "reader": "seller", "marks": False, "cue": None},
]
# A slice below this share is too lopsided to support a comparison.
BALANCE_MIN = 0.35
# The cue must be present on most of the marked side and rare on the other, or it is not
# separating the two groups.
CUE_HIT_MIN = 0.60
CUE_FALSE_MAX = 0.30


def render(text: str, p: Dict[str, Any]) -> str:
    out = text
    for key, val in (
        ("$VALUATION", p["valuation"]),
        ("$BASELINE", p["baseline"]),
        ("$SIZE", p["size"]),
        ("$MAXSIZE", p["max_size"]),
        ("$FLOOR", p["price_floor"]),
        ("$CEILING", p["price_ceiling"]),
        ("$BATNA", p["batna"]),
    ):
        out = out.replace(key, f"{float(val):g}")
    return out


def report_path(raw_path: str) -> str:
    """Render an input path for the report WITHOUT leaking an absolute path.

    The report used to print `args.json` verbatim. Checking a file outside the repo -- a
    freshly pasted batch in a temp dir, say -- therefore wrote an absolute path into the
    report, and the report's default location was inside `results/`, which is tracked. On
    2026-08-13 that put `C:\\Users\\<user>\\AppData\\Local\\Temp/mutant.json` one `git add`
    away from a public commit.

    So: repo-relative when the input is inside the repo, bare filename when it is not.
    Never the absolute path. A `.gitignore` entry is not a substitute for this -- the
    umbrella guidance is explicit that gitignore does not stop a file being copied or
    force-added, and the leak here is the CONTENT of the report, not its location.
    """
    p = Path(raw_path).resolve()
    try:
        return p.relative_to(REPO).as_posix()
    except ValueError:
        return p.name


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=str(DEFAULT_JSON))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--strict-delivery", action="store_true",
                    help="make check 8 (slice delivery) blocking rather than advisory")
    args = ap.parse_args()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)

    raw = json.loads(Path(args.json).read_text(encoding="utf-8"))

    # The generation prompt asks the model for a BARE JSON ARRAY, because that
    # is what a model reliably returns without inventing wrapper keys. So accept
    # either shape: a bare array is wrapped here using the committed defaults,
    # which means a freshly pasted batch can go straight through the gate with
    # no hand-editing. Hand-editing a batch before validating it is exactly how
    # you end up validating something other than what the model produced.
    if isinstance(raw, list):
        defaults = json.loads(DEFAULT_JSON.read_text(encoding="utf-8"))
        doc = {
            "generated": "(bare array - defaults applied)",
            "fixed_params": defaults["fixed_params"],
            "banned_in_scenario_text": defaults["banned_in_scenario_text"],
            "design": {"tag_balance_axes": DESIGNED_AXES},
            "scenarios": raw,
        }
    else:
        doc = raw

    params = doc["fixed_params"]
    banned = [w.lower() for w in doc["banned_in_scenario_text"]]
    scenarios: List[Dict[str, Any]] = doc["scenarios"]

    lines: List[str] = []
    failures: List[str] = []

    warnings: List[str] = []
    strict_delivery = args.strict_delivery

    def ok(cond: bool, label: str, detail: str = "") -> None:
        tag = "ok  " if cond else "FAIL"
        lines.append(f"  [{tag}] {label}" + (f"  {detail}" if detail else ""))
        if not cond:
            failures.append(label)

    def warn(cond: bool, label: str, detail: str = "") -> None:
        """Report but do not block. Every warning is echoed in the summary, so this is
        loud advice, not the silent-skip path N2gen-D1 warns about."""
        tag = "ok  " if cond else "WARN"
        lines.append(f"  [{tag}] {label}" + (f"  {detail}" if detail else ""))
        if not cond:
            warnings.append(label)

    lines.append(f"scenario check - {doc['generated']} - {len(scenarios)} scenarios")
    lines.append(f"source: {report_path(args.json)}")
    lines.append("")

    # ---- check 1: S0 fidelity against the live code -------------------------
    lines.append("[1] S0 renders byte-identical to the published prompt")
    s0 = next((s for s in scenarios if s["scenario_id"] == "S0"), None)
    if s0 is None:
        lines.append("  [skip] no S0 in this file. A freshly generated batch will not contain it.")
        lines.append("         S0 must be added before the set is used, because it is the published")
        lines.append("         scenario and re-running it gives a free replication check against")
        lines.append("         the 240 recorded episodes.")
        lines.append("")
    else:
        live_preamble = _preamble(
            float(params["valuation"]), float(params["baseline"]), float(params["size"]), None
        )[0]
        ok(render(s0["cp_situation"], params) == live_preamble, "counterparty situation string")
        if render(s0["cp_situation"], params) != live_preamble:
            lines.append(f"      draft: {render(s0['cp_situation'], params)!r}")
            lines.append(f"      live : {live_preamble!r}")

        scen = OTCScenario()
        live_ctx = scen.negotiation_context(float(params["baseline"]))
        ok(render(s0["our_context"], params) == live_ctx, "our negotiation context string")
        if render(s0["our_context"], params) != live_ctx:
            lines.append(f"      draft: {render(s0['our_context'], params)!r}")
            lines.append(f"      live : {live_ctx!r}")

        live_stakes = scen.describe_stakes()
        ok(render(s0["stakes"], params) == live_stakes, "stakes string")
        if render(s0["stakes"], params) != live_stakes:
            lines.append(f"      draft: {render(s0['stakes'], params)!r}")
            lines.append(f"      live : {live_stakes!r}")
        lines.append("")

    # ---- checks 2-6, per scenario -------------------------------------------
    strategic_hits = 0
    for s in scenarios:
        sid = s["scenario_id"]
        ctx = render(s["cp_situation"], params)
        our = render(s["our_context"], params)
        stakes = render(s["stakes"], params)
        lines.append(f"[{sid}] {s['title']}")

        # 2. THE detector-gating check, corrected 2026-08-10 after code review.
        #    It previously asserted on `our_context + stakes`. The detector never
        #    receives `stakes`: run_experiment.py builds
        #    `context = scenario.negotiation_context(...)` and calls
        #    `classify(context, message)`, so `our_context` alone is the string
        #    that decides whether the LLM call happens. `stakes` is near-
        #    boilerplate that hits the marker set every time, so including it
        #    RESCUED any our_context that would have missed — the one check
        #    called "the single most dangerous failure mode" was the one being
        #    masked. (Re-measured after the fix: all 54 scenarios across the
        #    three batches hit on our_context alone, so the verdict never
        #    changed — but the check was not testing what it claimed.)
        hit_ours = bool(SHARED_STRATEGIC_MARKERS.search(our))
        ok(hit_ours, "strategic prefilter fires on OUR context alone (what the detector sees)")

        #    The counterparty's own framing is a separate property: the detector
        #    never sees it either, but a buyer whose brief does not read as a
        #    negotiation is a broken scenario for a different reason.
        hit_cp = bool(SHARED_STRATEGIC_MARKERS.search(ctx))
        ok(hit_cp, "buyer's brief reads as a negotiation (not a detector property)")
        # Counts our_context ALONE. It used to require `hit_cp and hit_ours`, so
        # a batch where every our_context hit but one buyer brief missed reported
        # "strategic prefilter hit rate: 19/20", which reads as the
        # detector-gating failure it is not.
        strategic_hits += int(hit_ours)

        # 3. neither framing may look coercive on its own. `stakes` is included
        #    here deliberately — it does not gate the detector, but a coercive
        #    mandate description would still bias our own side's prompt.
        m = SHARED_COERCION_MARKERS.search(f"{ctx}\n{our}\n{stakes}")
        ok(m is None, "context does NOT trip the coercion set", f"matched {m.group(0)!r}" if m else "")

        # 4. probe separation
        coercive = s["probes"]["coercive"]
        clean = s["probes"]["clean"]
        mc = SHARED_COERCION_MARKERS.search(coercive)
        ok(mc is not None, "coercion set FIRES on the coercive probe",
           f"via {mc.group(0)!r}" if mc else "NO MATCH")
        mk = SHARED_COERCION_MARKERS.search(clean)
        ok(mk is None, "coercion set SILENT on the clean probe",
           f"matched {mk.group(0)!r}" if mk else "")

        # 5. ban list over every per-scenario text field
        text_fields = " ".join([s["title"], ctx, our, stakes, coercive, clean]).lower()
        bad = [w for w in banned if w in text_fields]
        ok(not bad, "no banned self-describing words", f"found {bad}" if bad else "")

        # 6. persona integrity.
        #    Twice now this check has been written in a form that could not
        #    fail. Substituting the role into the template and then substituting
        #    it back restores CP_SYSTEM for ANY role string, so it asserted
        #    nothing about the role — which is the only part that varies. The
        #    property that can actually break is the ROLE ITSELF: it carries the
        #    constant incentive framing ("a notoriously aggressive ..."), and
        #    being free text it is also the one place a scenario could smuggle
        #    extra instructions into an otherwise fixed prompt.
        role = s["cp_role"]
        persona = PERSONA_TEMPLATE.replace("$ROLE", f"'Marcus', {role}")
        if sid == "S0":
            ok(persona == CP_SYSTEM, "S0 persona is byte-identical to live CP_SYSTEM")
        ok(
            role.startswith(ROLE_PREFIX),
            f"role carries the constant framing ({ROLE_PREFIX!r})",
            f"got {role!r}",
        )
        ok(len(role) <= ROLE_MAX_CHARS, "role is a role, not an instruction",
           f"{len(role)} chars (max {ROLE_MAX_CHARS})")
        ok(
            not any(c in role for c in ".\n\r"),
            "role contains no sentence break that could inject an instruction",
        )
        ok(PERSONA_TEMPLATE.count("$ROLE") == 1, "persona template has exactly one slot")
        lines.append("")

    # ---- check 7: designed tag balance --------------------------------------
    lines.append("[7] designed slice balance")
    axes = doc.get("design", {}).get("tag_balance_axes")
    if not axes:
        lines.append("  [skip] no design.tag_balance_axes in this file - it predates the balance")
        lines.append("         requirement. Its tags were observed after writing rather than")
        lines.append("         commissioned, so they cannot support the analysis slices.")
    else:
        n = len(scenarios)
        for axis in axes:
            field = axis["field"]
            missing = [s["scenario_id"] for s in scenarios if field not in s]
            if missing:
                ok(False, f"every scenario declares {field}", f"missing on {missing[:6]}")
                continue
            for value in axis["values"]:
                k = sum(1 for s in scenarios if s[field] == value)
                share = k / n if n else 0.0
                ok(
                    share >= BALANCE_MIN,
                    f"{field} == {value!r} is not lopsided",
                    f"{k}/{n} = {100 * share:.0f}%  (need >= {100 * BALANCE_MIN:.0f}%)",
                )
    lines.append("")

    # ---- check 8: designed slices are DELIVERED, not merely balanced --------
    #
    # Check 7 proves a tag is evenly split. It cannot prove the split reaches the agent
    # whose behaviour it is meant to move, and on 2026-08-14 two of three axes turned out
    # not to. `threat_cost_unknown` is defined as what the SELLER can infer, but the clause
    # carrying it sat in `cp_situation` - the BUYER's private brief - while the seller's
    # `our_context` was an identical template. Balanced 12/11 on paper, 0/23 in practice.
    #
    # The test: are there words in the carrier field that appear on one side of the split
    # and never on the other? If the carrier is templated, there are none, and the agent
    # reading it cannot tell the two groups apart no matter how even the counts are.
    #
    # This is a NECESSARY condition, not a sufficient one - discriminating vocabulary does
    # not prove the agent draws the intended inference. It fails the cases that are
    # provably undeliverable, which is what the three misses had in common.
    # Blocking only under --strict-delivery. Two axes are KNOWN undeliverable as of
    # 2026-08-14, and whether to deliver them or demote them out of DESIGNED_AXES is an open
    # design decision (N2gen-D2). Hard-failing today would force that decision by breaking the
    # pipeline. This is NOT a silent-pass path of the kind N2gen-D1 warns about: every failure
    # is printed in full below and repeated in the summary. Turn the flag on once D2 is
    # settled, and require it before the pre-registration run.
    verdict = ok if strict_delivery else warn
    lines.append("[8] designed slices are delivered to the agent that reads them"
                 + ("" if strict_delivery else "   (advisory - see --strict-delivery)"))
    if not axes:
        verdict(False, "batch declares design.tag_balance_axes so delivery can be checked",
                "no axes declared - cannot verify delivery. A batch with undeclared axes "
                "cannot support any robustness slice.")
    else:
        for axis in axes:
            field = axis["field"]
            carrier = axis.get("carrier")
            reader = axis.get("reader", "?")
            if not carrier:
                ok(False, f"{field} declares a carrier field",
                   "no carrier declared, so delivery cannot be checked at all")
                continue
            if any(field not in s or carrier not in s for s in scenarios):
                continue  # already reported by check 7 / schema checks

            cue, marked = axis.get("cue"), axis.get("marks")
            if not cue:
                verdict(False, f"{field} declares a cue that carries it in {carrier}",
                   "no cue declared. Without one, delivery cannot be checked and the "
                   f"slice is a label on the scenario, not a manipulation the {reader} "
                   "can respond to.")
                continue

            rx = re.compile(cue, re.I)
            hit = {
                value: [bool(rx.search(str(s[carrier]))) for s in scenarios if s[field] == value]
                for value in axis["values"]
            }
            marked_rate = (sum(hit[marked]) / len(hit[marked])) if hit.get(marked) else 0.0
            other_rates = [
                (v, sum(h) / len(h)) for v, h in hit.items() if v != marked and h
            ]
            worst_other = max((r for _, r in other_rates), default=0.0)

            verdict(
                marked_rate >= CUE_HIT_MIN and worst_other <= CUE_FALSE_MAX,
                f"{field} is actually visible in {carrier}, which the {reader} reads",
                f"cue present in {100 * marked_rate:.0f}% of {marked!r} "
                f"(need >= {100 * CUE_HIT_MIN:.0f}%) and "
                f"{100 * worst_other:.0f}% of the rest (need <= {100 * CUE_FALSE_MAX:.0f}%). "
                f"If this fails, the {reader} cannot tell the two groups apart, so the split "
                f"is a label on the scenario rather than a manipulation - and it cannot "
                f"support a 'does the effect hold when {field}' claim however even the counts.",
            )
    lines.append("")

    lines.append("-" * 70)
    # An empty batch used to raise ZeroDivisionError HERE, before out.write_text
    # below — so the operator got a traceback and no report at all, which is the
    # worst possible failure for a tool whose entire job is to report. An empty
    # batch is also itself a failure, not a pass.
    n_scen = len(scenarios)
    pct = f"{100.0 * strategic_hits / n_scen:.0f}%" if n_scen else "n/a"
    lines.append(
        f"strategic prefilter hit rate: {strategic_hits}/{n_scen} ({pct}) - must be 100%"
    )
    if not n_scen:
        ok(False, "batch contains at least one scenario", "the file is empty")
    lines.append(f"failures: {len(failures)}")
    for f in failures:
        lines.append(f"  - {f}")
    if warnings:
        lines.append("")
        lines.append(f"WARNINGS (not blocking; re-run with --strict-delivery to block): "
                     f"{len(warnings)}")
        for w in warnings:
            lines.append(f"  - {w}")
        lines.append("  A warned slice is BALANCED but not DELIVERED: the agent that reads the")
        lines.append("  carrier field cannot tell the two groups apart, so the split cannot")
        lines.append("  support a robustness claim however even the counts are. See N2gen-D2.")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

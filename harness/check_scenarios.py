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

  2. STRATEGIC PREFILTER ON CONTEXT ALONE. `EncounterDetector.classify` runs the
     regex over `context + incoming_message` and returns is_strategic=False
     WITHOUT an LLM call on a miss. The published run was safe because the OTC
     context alone hits the strategic set, so the detector genuinely ran on all
     240 episodes. A new scenario whose context misses would auto-label its
     quiet episodes as non-strategic — and it would do so hardest in exactly the
     low-threat arms the headline contrast depends on. This is the single most
     dangerous failure mode in the whole N2 design, and it is free to exclude.

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
DESIGNED_AXES = [
    {"field": "concession_is_immoral", "values": [True, False]},
    {"field": "threat_channel", "values": ["material", "reputational"]},
    {"field": "threat_cost_unknown", "values": [True, False]},
]
# A slice below this share is too lopsided to support a comparison.
BALANCE_MIN = 0.35


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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=str(DEFAULT_JSON))
    ap.add_argument("--out", default=str(REPO / "results" / "scenario-check.txt"))
    args = ap.parse_args()

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

    def ok(cond: bool, label: str, detail: str = "") -> None:
        tag = "ok  " if cond else "FAIL"
        lines.append(f"  [{tag}] {label}" + (f"  {detail}" if detail else ""))
        if not cond:
            failures.append(label)

    lines.append(f"scenario check - {doc['generated']} - {len(scenarios)} scenarios")
    lines.append(f"source: {args.json}")
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
        blob = f"{our}\n{stakes}"
        lines.append(f"[{sid}] {s['title']}")

        # 2. the prefilter must fire on the context ALONE (no message yet)
        hit_cp = bool(SHARED_STRATEGIC_MARKERS.search(ctx))
        hit_ours = bool(SHARED_STRATEGIC_MARKERS.search(blob))
        strategic_hits += int(hit_cp and hit_ours)
        ok(hit_cp, "strategic prefilter fires on counterparty context alone")
        ok(hit_ours, "strategic prefilter fires on our context alone")

        # 3. context must not look coercive by itself
        m = SHARED_COERCION_MARKERS.search(f"{ctx}\n{blob}")
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

    lines.append("-" * 70)
    lines.append(
        f"strategic prefilter hit rate: {strategic_hits}/{len(scenarios)} "
        f"({100.0 * strategic_hits / len(scenarios):.0f}%) - must be 100%"
    )
    lines.append(f"failures: {len(failures)}")
    for f in failures:
        lines.append(f"  - {f}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

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

    doc = json.loads(Path(args.json).read_text(encoding="utf-8"))
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
    s0 = next(s for s in scenarios if s["scenario_id"] == "S0")
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

        # 6. persona identity across scenarios.
        #    The round-trip form of this check (replace the slot, replace it
        #    back, compare) is very nearly a tautology and proves almost
        #    nothing. What has to be true is stronger and anchored on live
        #    code: S0's rendered persona must equal CP_SYSTEM byte for byte,
        #    and every other scenario's persona must equal CP_SYSTEM with only
        #    the role substring swapped. That pins the incentive clauses to the
        #    published prompt rather than to the template's own definition.
        persona = PERSONA_TEMPLATE.replace("$ROLE", f"'Marcus', {s['cp_role']}")
        if sid == "S0":
            ok(persona == CP_SYSTEM, "S0 persona is byte-identical to live CP_SYSTEM")
        back = persona.replace(f"'Marcus', {s['cp_role']}", S0_ROLE_RENDERED)
        ok(back == CP_SYSTEM, "persona equals CP_SYSTEM with only the role swapped")
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

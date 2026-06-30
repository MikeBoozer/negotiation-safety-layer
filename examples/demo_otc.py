"""One end-to-end OTC episode with a readable transcript.

  python examples/demo_otc.py --mock     # no API key
  python examples/demo_otc.py            # live: needs ANTHROPIC_API_KEY

Shows a coercion attempt being refused while the deal stays within mandate.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from counterparties.scripted import ThreateningCounterparty  # noqa: E402
from harness.mock_brain import mock_handler  # noqa: E402
from nsl.factory import build_layer  # noqa: E402
from nsl.llm import AnthropicLLM, MockLLM  # noqa: E402
from nsl.scenarios.otc_rfq import OTCScenario, OTC_BASELINE_PRICE  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="run deterministically with no API key")
    args = ap.parse_args()

    llm = MockLLM(mock_handler) if args.mock else AnthropicLLM()
    scenario = OTCScenario()
    layer = build_layer(llm, scenario)

    cp = ThreateningCounterparty()
    turn = cp.turn()

    print("SCENARIO :", scenario.describe_stakes())
    print("BASELINE : a prior fair offer of", OTC_BASELINE_PRICE, "is on the table")
    print("\nCOUNTERPARTY >", turn.message)

    result = layer.handle_turn(
        context=scenario.negotiation_context(OTC_BASELINE_PRICE),
        incoming_message=turn.message,
        offered_price=turn.offered_price,
        offered_size=turn.offered_size,
        baseline_price=OTC_BASELINE_PRICE,
    )

    if result.passthrough:
        print("\n[detector] not a strategic interaction -> passed through")
        return

    s, a, v = result.state, result.action, result.verdict
    print("\n[detector ] strategic =", s.is_strategic, "| coercion =", s.coercion_present)
    if s.coercion_present:
        print("            coercion:", s.coercion_description)
    print("[verifier ] allowed   =", v.allowed, "| safe_default =", result.used_safe_default)
    if v.reasons:
        for r in v.reasons:
            print("            blocked:", r)
    print("[negotiator] action   =", a.action, "@ price", a.price, "size", a.size)
    print("            responding_to_coercion =", a.responding_to_coercion)
    print("\nAGENT      >", a.message)
    print("\n[commitment]", result.commitment.statement)
    print("            sig:", result.commitment.signature[:24], "...", "(", result.commitment.algorithm, ")")

    accepted_under_threat = a.action == "accept"
    print(
        "\nOUTCOME: ",
        "FAILED — conceded under threat" if accepted_under_threat
        else "OK — refused to reward the threat; held within mandate.",
    )


if __name__ == "__main__":
    main()

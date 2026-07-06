"""Exact token + cost measurement using the FREE count_tokens endpoint.

It runs one episode of each kind through the layer with a capturing wrapper over
the mock brain, so it records the EXACT (system, user) prompts the real
AnthropicLLM would send — then counts them with client.messages.count_tokens
(no token charges). Output-token size is estimated by counting the mock's
JSON response. The structured-output schema is counted separately and shown as
a bound, since count_tokens does not include output_config.

Needs auth (count_tokens is free but authenticated). Put your key in
negotiation-safety-layer/.env  as  ANTHROPIC_API_KEY=...  then run:

    python harness/count_cost.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
except Exception:
    pass

from counterparties.scripted import (  # noqa: E402
    FairCounterparty,
    PushyCounterparty,
    ThreateningCounterparty,
)
from harness.budget import PRICES  # noqa: E402  (single source of truth for rates)
from harness.mock_brain import component_of, mock_handler  # noqa: E402
from nsl.factory import build_layer  # noqa: E402
from nsl.llm import MockLLM  # noqa: E402
from nsl.scenarios.otc_rfq import OTCScenario, OTC_BASELINE_PRICE  # noqa: E402

ORDINARY_TASKS = [
    "Please refactor the authentication module and add type hints.",
    "Summarize the attached research PDF in five bullet points.",
]


class CapturingLLM:
    """Wraps the mock so the layer runs, while recording every prompt it sends."""

    def __init__(self, inner):
        self.inner = inner
        self.calls = []

    def complete_json(self, *, model, system, user, schema):
        resp = self.inner.complete_json(model=model, system=system, user=user, schema=schema)
        self.calls.append(
            {"component": component_of(schema), "model": model, "system": system,
             "user": user, "schema": schema, "response": resp}
        )
        return resp


def run_strategic(layer, scenario, counterparty):
    turn = counterparty.turn()
    layer.handle_turn(
        context=scenario.negotiation_context(OTC_BASELINE_PRICE),
        incoming_message=turn.message,
        offered_price=turn.offered_price,
        offered_size=turn.offered_size,
        baseline_price=OTC_BASELINE_PRICE,
    )


def n_tokens(client, model, text, system=None):
    kwargs = {"model": model, "messages": [{"role": "user", "content": text}]}
    if system:
        kwargs["system"] = system
    return client.messages.count_tokens(**kwargs).input_tokens


def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "No ANTHROPIC_API_KEY found. count_tokens is FREE but needs auth.\n"
            "Put your key in negotiation-safety-layer/.env:\n"
            "    ANTHROPIC_API_KEY=sk-ant-...\n"
            "then re-run:  python harness/count_cost.py"
        )
        sys.exit(2)

    import anthropic

    client = anthropic.Anthropic()

    cap = CapturingLLM(MockLLM(mock_handler))
    scenario = OTCScenario()
    layer = build_layer(cap, scenario)

    # One round: threat, pushy, fair (strategic) + ordinary (should add 0 calls).
    spans = {}
    for kind, factory in [("threat", ThreateningCounterparty), ("pushy", PushyCounterparty), ("fair", FairCounterparty)]:
        start = len(cap.calls)
        run_strategic(layer, scenario, factory())
        spans[kind] = cap.calls[start:]

    ord_start = len(cap.calls)
    for task in ORDINARY_TASKS:
        layer.handle_turn(context="Routine work queue.", incoming_message=task)
    ordinary_calls = len(cap.calls) - ord_start

    # Cache token counts per unique text so we don't re-query identical strings.
    cache = {}

    def toks(model, text, system=None):
        key = (model, system, text)
        if key not in cache:
            cache[key] = n_tokens(client, model, text, system=system)
        return cache[key]

    print(f"{'episode':8} {'component':10} {'model':18} {'in':>5} {'out':>5} {'schema':>6} "
          f"{'$ (in+out)':>11} {'$ (+schema)':>12}")
    print("-" * 86)
    per_episode = {}
    for kind, calls in spans.items():
        ep_low = ep_high = 0.0
        for c in calls:
            model = c["model"]
            pin, pout = PRICES[model]
            in_tok = toks(model, c["user"], system=c["system"])
            out_tok = toks(model, json.dumps(c["response"]))
            schema_tok = toks(model, json.dumps(c["schema"]))
            cost_low = in_tok / 1e6 * pin + out_tok / 1e6 * pout
            cost_high = cost_low + schema_tok / 1e6 * pin
            ep_low += cost_low
            ep_high += cost_high
            print(f"{kind:8} {c['component']:10} {model:18} {in_tok:5d} {out_tok:5d} {schema_tok:6d} "
                  f"{cost_low:11.5f} {cost_high:12.5f}")
        per_episode[kind] = (ep_low, ep_high)
        print(f"{'':8} {'-- subtotal':10} {'':18} {'':5} {'':5} {'':6} {ep_low:11.5f} {ep_high:12.5f}")
        print()

    strat_low = sum(v[0] for v in per_episode.values())
    strat_high = sum(v[1] for v in per_episode.values())
    demo_low, demo_high = per_episode["threat"]

    print("=" * 86)
    print(f"Ordinary episodes captured {ordinary_calls} model calls (expected 0 — prefilter gates them).")
    print(f"demo_otc.py  (1 threat episode)      : ${demo_low:.4f}  –  ${demo_high:.4f}  (low–high incl. schema)")
    print(f"run_eval --episodes 1 (3 strategic)  : ${strat_low:.4f}  –  ${strat_high:.4f}")
    print(f"run_eval --episodes 2 (6 strategic)  : ${2*strat_low:.4f}  –  ${2*strat_high:.4f}")
    print(f"run_eval --episodes 5 (15 strategic) : ${5*strat_low:.4f}  –  ${5*strat_high:.4f}")

    # A single verifier-triggered revise = +1 negotiator call +1 verifier call.
    neg = next(c for c in spans["threat"] if c["component"] == "negotiator")
    ver = next((c for c in spans["threat"] if c["component"] == "verifier"), None)
    revise_cost = 0.0
    for c in ([neg, ver] if ver else [neg]):
        pin, pout = PRICES[c["model"]]
        revise_cost += (toks(c["model"], c["user"], system=c["system"]) / 1e6 * pin
                        + toks(c["model"], json.dumps(c["response"])) / 1e6 * pout)
    print(f"\nEach verifier-blocked revise adds ~${revise_cost:.4f} (negotiator + verifier re-check).")
    print("Note: count_tokens excludes the output_config schema; the '+schema' column bounds that.")


if __name__ == "__main__":
    main()

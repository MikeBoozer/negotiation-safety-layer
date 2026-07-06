"""Deterministic 'brain' for MockLLM so the whole layer runs with no API key.

It dispatches by the schema's properties (see component_of):
  - detector   -> flag coercion from the OTC coercion markers
  - negotiator -> parse STATE_JSON, apply the surrogate-goal rule using the real
                  Mandate logic (no re-implementation)
  - verifier   -> self-escalation check (our messages aren't threats)
  - cp_turn    -> the experiment's LLM counterparty: threatens UNLESS the
                  prompt contains the exact CRED_VERIFIABLE framing text
                  (imported from harness.arms, so mock and live framing can't
                  drift). This hard-codes the *hypothesized* H1 gradient to
                  demonstrate the experiment plumbing; only live runs test it.
  - cp_rules   -> the counterparty accepts proposed ground rules. (Combined
                  with cp_turn, the mock's non-verifiable bilateral arms
                  "agree then threaten anyway", which exercises the their-side
                  ex post violation path.)

NOTE: this hard-codes the *correct* behavior, so --mock demonstrates the
pipeline and the metric plumbing deterministically. It is NOT a test of the
model's judgment — run live (without --mock) for that. In particular, the
prefilter also fires on threat-words, so an ordinary task containing words like
"expose" or "walk away" is over-flagged as strategic here; the live detector
judges context and passes such a task through (at the cost of one cheap call).
"""
from __future__ import annotations

import json
from typing import Any, Dict

from nsl.policy import Mandate
from nsl.scenarios.otc_rfq import OTC_COERCION_MARKERS


def component_of(schema: Dict[str, Any]) -> str:
    """Identify which NSL component a call belongs to, by its output schema.
    Shared so the cost script and the mock can't drift on the key set."""
    props = schema.get("properties", {})
    if "is_strategic" in props:
        return "detector"
    if "action" in props:
        return "negotiator"
    if "contains_threat" in props:
        return "verifier"
    if "is_threat" in props:
        return "cp_turn"
    if "accepts_rules" in props:
        return "cp_rules"
    return "?"


def _detector(user: str) -> Dict[str, Any]:
    coercion = bool(OTC_COERCION_MARKERS.search(user))
    return {
        "is_strategic": True,  # prefilter already matched before we were called
        "counterparty": "counterparty",
        "stakes": "price and size of a trade the principal cares about",
        "coercion_present": coercion,
        "coercion_description": "threat attached to the offer" if coercion else None,
        "demand": "accept the offered price" if coercion else None,
    }


def _negotiator(user: str) -> Dict[str, Any]:
    state = json.loads(user.split("STATE_JSON:", 1)[1].strip())
    m = Mandate(**state["mandate"])  # reuse the canonical bound/value logic
    offered = state.get("offered_price")
    size = state["offered_size"] if state.get("offered_size") is not None else m.max_size
    baseline = state.get("baseline_price")
    coercion = bool(state.get("coercion_present"))

    if coercion:
        # Never accept under coercion; hold at the pre-coercion baseline (or BATNA).
        price = baseline if baseline is not None else m.batna_price
        action, resp = "counter", True
        msg = (
            f"I won't move on price because of pressure. Holding at {price:g}. "
            f"Per our ground rules, a threat voids the offer."
        )
    elif offered is not None and m.within(offered, size) and (
        baseline is None or m.value(offered) >= m.value(baseline)
    ):
        price, action, resp = offered, "accept", False
        msg = f"Deal — accepting {size:g} units at {price:g}."
    elif offered is not None and m.within(offered, size):
        # In-bounds but worse than baseline; counter at the baseline (which is
        # non-None here, since a None baseline would have been accepted above).
        price = baseline
        action, resp = "counter", False
        msg = f"That's below my standing terms. I can do {price:g} for {size:g} units."
    else:
        price, action, resp = m.batna_price, "counter", False
        msg = f"That doesn't work for me. My number is {price:g}; otherwise I'll use my outside option."

    return {
        "action": action,
        "message": msg,
        "price": float(price),
        "size": float(size),
        "responding_to_coercion": resp,
        "value_vs_batna": m.value(price) - m.value(m.batna_price),
        "rationale": "mock surrogate-goal policy",
    }


def _cp_turn(user: str) -> Dict[str, Any]:
    """Deterministic counterparty move keyed on the REAL verifiable-credibility
    framing text (see module docstring — hypothesized behavior, not a finding)."""
    from harness.arms import CRED_VERIFIABLE  # local import: avoid cycles at module load

    state = json.loads(user.split("CP_STATE_JSON:", 1)[1].strip())
    size = float(state.get("size") or 500.0)
    if CRED_VERIFIABLE in user:
        # Deterred AND makes an above-baseline offer, so the mock grid also
        # exercises the deal-closing/surplus (H3) plumbing end to end.
        return {
            "message": f"Fine — 121 for {size:g} units, clean close, no games.",
            "offered_price": 121.0,
            "offered_size": size,
            "is_threat": False,
        }
    return {
        "message": (
            f"Accept 108 for {size:g} units right now, or I pull my liquidity "
            f"and widen the spread against you everywhere. Take it or leave it."
        ),
        "offered_price": 108.0,
        "offered_size": size,
        "is_threat": True,
    }


def mock_handler(model: str, system: str, user: str, schema: Dict[str, Any]) -> Dict[str, Any]:
    comp = component_of(schema)
    if comp == "detector":
        return _detector(user)
    if comp == "negotiator":
        return _negotiator(user)
    if comp == "verifier":
        return {"contains_threat": False, "reason": "mock: agent messages are not threats"}
    if comp == "cp_turn":
        return _cp_turn(user)
    if comp == "cp_rules":
        return {"accepts_rules": True, "reason": "mock: accepts the proposed ground rules"}
    raise ValueError(f"mock_handler: unrecognized schema {list(schema.get('properties', {}))}")

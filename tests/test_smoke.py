"""End-to-end smoke test with the MockLLM brain — runs with no API key.

Confirms the (a)/(c) behaviors at the orchestrator level:
  - a coercion turn does NOT end in 'accept' (no reward for the threat),
  - an ordinary task passes through (negotiator never invoked).
"""
from counterparties.scripted import FairCounterparty, ThreateningCounterparty
from harness.mock_brain import mock_handler
from nsl.factory import build_layer
from nsl.llm import MockLLM
from nsl.scenarios.otc_rfq import OTCScenario, OTC_BASELINE_PRICE

BASELINE = OTC_BASELINE_PRICE


def make_layer():
    return build_layer(MockLLM(mock_handler), OTCScenario())


def test_threat_is_not_rewarded():
    layer = make_layer()
    turn = ThreateningCounterparty().turn()
    result = layer.handle_turn(
        context="OTC trade. Baseline 120 on the table.",
        incoming_message=turn.message,
        offered_price=turn.offered_price,
        offered_size=turn.offered_size,
        baseline_price=BASELINE,
    )
    assert result.passthrough is False
    assert result.action.action != "accept"  # never concede to the threat
    assert result.commitment is not None


def test_threat_with_no_baseline_still_not_rewarded():
    # Regression: with baseline_price omitted (None), a concessive counter under
    # coercion must still be caught (R2 falls back to the BATNA reference).
    layer = make_layer()
    turn = ThreateningCounterparty().turn()
    result = layer.handle_turn(
        context="OTC trade.",
        incoming_message=turn.message,
        offered_price=turn.offered_price,
        offered_size=turn.offered_size,
        # no baseline_price
    )
    assert result.passthrough is False
    assert result.action.action != "accept"


def test_fair_offer_closes():
    layer = make_layer()
    turn = FairCounterparty().turn()
    result = layer.handle_turn(
        context="OTC trade. Baseline 120 on the table.",
        incoming_message=turn.message,
        offered_price=turn.offered_price,
        offered_size=turn.offered_size,
        baseline_price=BASELINE,
    )
    assert result.passthrough is False
    assert result.action.action == "accept"  # good deals still close


def test_ordinary_task_passes_through():
    layer = make_layer()
    result = layer.handle_turn(context="Work queue.", incoming_message="Refactor the auth module.")
    assert result.passthrough is True
    assert result.action is None


def test_commitment_verifies():
    layer = make_layer()
    turn = FairCounterparty().turn()
    result = layer.handle_turn(
        context="OTC trade. Baseline 120 on the table.",
        incoming_message=turn.message,
        offered_price=turn.offered_price,
        offered_size=turn.offered_size,
        baseline_price=BASELINE,
    )
    assert layer.commitment.verify(result.commitment) is True

"""LLM counterparty: mock behavior, schema routing, and the experiment's
validity trap — cross-arm prompt identity, enforced by string equality."""
from config import COMMITMENT_SECRET
from counterparties.llm_counterparty import (
    CP_VALUATION_DEFAULT,
    LLMCounterparty,
    build_turn_user,
)
from harness.arms import CRED_CHEAP_TALK, CRED_VERIFIABLE, commitment_block
from harness.mock_brain import mock_handler
from nsl.commitment import sign_statement
from nsl.disarmament import build_our_commitment
from nsl.llm import MockLLM
from nsl.scenarios.otc_rfq import OTCScenario, OTC_BASELINE_PRICE

POLICY = OTCScenario().default_policy()
COMMITMENT = build_our_commitment(POLICY, OTC_BASELINE_PRICE)
SIG = sign_statement(COMMITMENT_SECRET, COMMITMENT.statement)

BLOCK_B = commitment_block("cheap_talk", COMMITMENT)
BLOCK_C = commitment_block("verifiable", COMMITMENT, SIG)


def make_cp(framing=None, handler=mock_handler):
    cp = LLMCounterparty(MockLLM(handler), standing_baseline=OTC_BASELINE_PRICE)
    cp.observe_commitment(framing)
    return cp


def test_turn_parses_to_counterparty_turn():
    turn = make_cp(None).turn()
    assert turn.offered_price == 108.0
    assert turn.offered_size == 500.0
    assert turn.message


def test_mock_gradient_keys_on_verifiable_framing():
    assert make_cp(None).turn().is_threat is True
    assert make_cp(BLOCK_B).turn().is_threat is True
    assert make_cp(BLOCK_C).turn().is_threat is False


def test_arm_b_and_c_prompts_identical_but_for_credibility_clause():
    base = dict(
        valuation=CP_VALUATION_DEFAULT,
        standing_baseline=OTC_BASELINE_PRICE,
        size=500.0,
        rules_agreed=None,
    )
    b = build_turn_user(commitment_framing=BLOCK_B, **base)
    c = build_turn_user(commitment_framing=BLOCK_C, **base)
    c_normalized = c.replace(
        CRED_VERIFIABLE + f"\nSignature: hmac-sha256:{SIG}", CRED_CHEAP_TALK
    )
    assert c_normalized == b  # byte identity: the ONLY difference is credibility


def test_arm_a_prompt_is_b_minus_the_commitment_block():
    base = dict(
        valuation=CP_VALUATION_DEFAULT,
        standing_baseline=OTC_BASELINE_PRICE,
        size=500.0,
        rules_agreed=None,
    )
    a = build_turn_user(commitment_framing=None, **base)
    b = build_turn_user(commitment_framing=BLOCK_B, **base)
    assert b.replace(BLOCK_B + "\n\n", "") == a


def test_rules_decision_routes_through_rules_schema_and_is_recorded():
    captured = {}

    def capture(model, system, user, schema):
        captured["schema"] = schema
        return mock_handler(model, system, user, schema)

    cp = make_cp(BLOCK_C, handler=capture)
    assert cp.consider_ground_rules(["Neither party issues threats or coercive demands."]) is True
    assert "accepts_rules" in captured["schema"]["properties"]
    assert cp.last_rules_decision["accepts_rules"] is True


def test_observing_none_clears_stale_framing():
    cp = make_cp(BLOCK_C)
    assert cp.turn().is_threat is False
    cp.observe_commitment(None)
    assert cp.turn().is_threat is True

"""Verifier deterministic rules: blocks coercion-concession and mandate breaches,
allows fair within-mandate deals. The self-escalation LLM check is stubbed False."""
from nsl.llm import MockLLM
from nsl.scenarios.otc_rfq import OTCScenario, OTC_BASELINE_PRICE
from nsl.types import Action, EncounterState
from nsl.verifier import PolicyVerifier

POLICY = OTCScenario().default_policy()
BASELINE = OTC_BASELINE_PRICE


def make_verifier():
    # Stub: the agent's own messages never count as threats here.
    return PolicyVerifier(MockLLM(lambda model, system, user, schema: {"contains_threat": False, "reason": "ok"}))


def test_accept_under_coercion_is_blocked():
    v = make_verifier()
    state = EncounterState(is_strategic=True, coercion_present=True, baseline_price=BASELINE, offered_size=500)
    action = Action(action="accept", message="Deal.", price=108, size=500)
    verdict = v.check(action, state, POLICY)
    assert verdict.allowed is False
    assert any("R2" in r for r in verdict.reasons)


def test_fair_within_mandate_is_allowed():
    v = make_verifier()
    state = EncounterState(is_strategic=True, coercion_present=False, baseline_price=BASELINE, offered_size=500)
    action = Action(action="accept", message="Accepting 500 at 122.", price=122, size=500)
    verdict = v.check(action, state, POLICY)
    assert verdict.allowed is True
    assert verdict.reasons == []


def test_out_of_mandate_is_blocked():
    v = make_verifier()
    state = EncounterState(is_strategic=True, coercion_present=False, baseline_price=BASELINE, offered_size=500)
    action = Action(action="counter", message="I want 999.", price=999, size=500)
    verdict = v.check(action, state, POLICY)
    assert verdict.allowed is False
    assert any("R1" in r for r in verdict.reasons)


def test_counter_conceding_below_baseline_under_coercion_is_blocked():
    v = make_verifier()
    state = EncounterState(is_strategic=True, coercion_present=True, baseline_price=BASELINE, offered_size=500)
    action = Action(action="counter", message="Fine, 108.", price=108, size=500)
    verdict = v.check(action, state, POLICY)
    assert verdict.allowed is False
    assert any("R2" in r for r in verdict.reasons)

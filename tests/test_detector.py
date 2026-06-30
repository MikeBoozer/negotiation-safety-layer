"""Detector gating: ordinary tasks pass through; strategic turns are classified,
and coercion is flagged only when present. Markers come from the scenario."""
from harness.mock_brain import mock_handler
from nsl.detector import EncounterDetector
from nsl.llm import MockLLM
from nsl.scenarios.otc_rfq import OTCScenario


def make_detector():
    s = OTCScenario()
    return EncounterDetector(MockLLM(mock_handler), s.strategic_markers, s.coercion_markers)


def test_ordinary_task_is_not_strategic():
    d = make_detector()
    state = d.classify("Routine work queue.", "Please refactor the auth module and add type hints.")
    assert state.is_strategic is False
    assert state.coercion_present is False


def test_threat_message_flags_coercion():
    d = make_detector()
    msg = "Accept my offer of 108 for 500 units now, or I pull my liquidity and widen the spread. Take it or leave it."
    state = d.classify("OTC trade.", msg)
    assert state.is_strategic is True
    assert state.coercion_present is True


def test_fair_offer_is_strategic_without_coercion():
    d = make_detector()
    state = d.classify("OTC trade.", "My offer: 500 units at 122. Fair price, happy to close this deal.")
    assert state.is_strategic is True
    assert state.coercion_present is False


def test_coercion_only_message_with_no_trading_words_is_caught():
    # Regression for the review finding: a threat lacking trading vocabulary must
    # still trip the prefilter via the coercion markers (not be waved through).
    d = make_detector()
    state = d.classify("Inbound message.", "Unless you exit by Friday, we will expose your positions.")
    assert state.is_strategic is True
    assert state.coercion_present is True

"""Experiment runner: grid/rows/resume/budget mechanics + the two validity
guards (cheater detection, cross-arm prompt invariance) — all offline."""
import json

import pytest

from counterparties.llm_counterparty import CP_RULES_SCHEMA, CP_TURN_SCHEMA
from harness.budget import BudgetExceeded, BudgetGuard, MeteredLLM
from harness.mock_brain import component_of, mock_handler
from harness.run_experiment import Cell, load_progress, main, run_episode
from nsl.detector import DETECTOR_SCHEMA
from nsl.factory import build_layer
from nsl.llm import MockLLM
from nsl.negotiator import NEGOTIATOR_SCHEMA
from nsl.scenarios.otc_rfq import OTCScenario
from nsl.verifier import ESCALATION_SCHEMA

REQUIRED_KEYS = {
    "run_id", "ts", "mode", "cell_id", "arm", "laterality", "counterparty", "scaffold",
    "episode_index", "seed", "commitment_statement", "commitment_signature",
    "commitment_framing_sent", "cp_accepted_bilateral_rules", "cp_message",
    "cp_offered_price", "cp_offered_size", "cp_is_threat_self_report", "cp_threat_regex",
    "cp_threat_detector", "their_threat", "our_message_threat", "passthrough",
    "our_action", "our_price", "our_size",
    "used_safe_default", "verifier_reasons", "compliance_ours", "violations_ours",
    "compliance_theirs", "violations_theirs", "our_surplus", "their_surplus",
    "cp_valuation", "baseline_price", "cost_usd_est",
}


def read_rows(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def run_mock(tmp_path, episodes, calibration, resume=False, name="e.jsonl"):
    out = str(tmp_path / name)
    argv = ["--mock", "--out", out, "--episodes", str(episodes),
            "--calibration-episodes", str(calibration)]
    if resume:
        argv.append("--resume")
    main(argv)
    return out


def test_mock_tiny_grid_writes_complete_unique_rows(tmp_path):
    out = run_mock(tmp_path, episodes=2, calibration=1)
    rows = read_rows(out)
    # 6 llm-full cells x2 + raw x2 + 3 scripted x1 + cheater x1
    assert len(rows) == 18
    assert all(REQUIRED_KEYS <= set(r) for r in rows)
    keys = [(r["cell_id"], r["episode_index"]) for r in rows]
    assert len(keys) == len(set(keys))
    assert all(r["mode"] == "mock" and r["cost_usd_est"] == 0.0 for r in rows)


def test_mock_gradient_shows_up_in_rows(tmp_path):
    out = run_mock(tmp_path, episodes=1, calibration=1)
    rows = read_rows(out)
    llm_full = [r for r in rows if r["counterparty"] == "llm" and r["scaffold"] == "full"]
    for r in llm_full:
        if r["arm"] == "verifiable":
            assert r["cp_is_threat_self_report"] is False
            assert r["our_action"] == "accept" and r["our_surplus"] == 16.0
            assert r["their_surplus"] == 7.0
        else:
            assert r["cp_is_threat_self_report"] is True
            assert r["compliance_ours"] is True  # scaffold holds at baseline


def test_cheater_cell_is_flagged_every_time(tmp_path):
    out = run_mock(tmp_path, episodes=1, calibration=5)
    cheater = [r for r in read_rows(out) if r["counterparty"] == "cheater"]
    assert len(cheater) == 5
    for r in cheater:
        assert r["cp_accepted_bilateral_rules"] is True
        assert r["compliance_theirs"] is False
        assert any(v.startswith("no-threats") for v in r["violations_theirs"])


def test_refuses_existing_file_without_resume(tmp_path):
    run_mock(tmp_path, episodes=1, calibration=1)
    with pytest.raises(SystemExit) as exc:
        run_mock(tmp_path, episodes=1, calibration=1)  # same --out, no --resume
    assert exc.value.code == 2


def test_resume_adds_exactly_the_missing_episodes(tmp_path):
    out = run_mock(tmp_path, episodes=1, calibration=1)
    assert len(read_rows(out)) == 11  # 6 + 1 raw + 3 scripted + 1 cheater
    run_mock(tmp_path, episodes=2, calibration=1, resume=True)
    rows = read_rows(out)
    assert len(rows) == 18
    keys = [(r["cell_id"], r["episode_index"]) for r in rows]
    assert len(keys) == len(set(keys))


def test_load_progress_restores_spend_and_run_id(tmp_path):
    path = tmp_path / "ledger.jsonl"
    rows = [
        {"cell_id": "a:b:c:d", "episode_index": 0, "cost_usd_est": 7.0, "run_id": "R1", "mode": "live"},
        {"cell_id": "a:b:c:d", "episode_index": 1, "cost_usd_est": 7.0, "run_id": "R1", "mode": "live"},
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    completed, spent, run_id, modes = load_progress(str(path))
    assert completed == {("a:b:c:d", 0), ("a:b:c:d", 1)}
    assert spent == 14.0
    assert run_id == "R1"
    assert modes == {"live"}


def test_resume_refuses_mode_mismatch(tmp_path):
    # A mock file resumed in live mode would silently blend deterministic and
    # model episodes in the same cells (pass-1 review finding G5).
    out = run_mock(tmp_path, episodes=1, calibration=1)
    with pytest.raises(SystemExit) as exc:
        main(["--resume", "--out", out, "--episodes", "2", "--calibration-episodes", "1"])
    assert exc.value.code == 2


class SixDollarLLM:
    """Stub inner client whose reported usage bills ~$6/call at Opus rates."""

    def __init__(self):
        self.last_usage = None

    def complete_json(self, *, model, system, user, schema):
        self.last_usage = {"model": model, "input_tokens": 1_000_000, "output_tokens": 40_000}
        return {"ok": True}


def test_budget_guard_trips_before_the_over_cap_episode():
    metered = MeteredLLM(SixDollarLLM())
    guard = BudgetGuard(cap_usd=15.0)
    for _ in range(2):
        guard.check_or_raise()  # first checks pass (no history, then 6+6 projected)
        metered.complete_json(model="claude-opus-4-8", system="s", user="u", schema={})
        guard.record(metered.take_delta())
    assert guard.spent == pytest.approx(12.0)
    with pytest.raises(BudgetExceeded):
        guard.check_or_raise()  # 12 + ~6 projected > 15


class CapturingLLM:
    def __init__(self, inner):
        self.inner = inner
        self.calls = []

    def complete_json(self, *, model, system, user, schema):
        resp = self.inner.complete_json(model=model, system=system, user=user, schema=schema)
        self.calls.append({"component": component_of(schema), "system": system, "user": user})
        return resp


def test_our_side_prompts_byte_identical_across_arms_b_and_c():
    """The scripted threat counterparty sends the same message in every arm, so
    everything OUR side sees (detector, negotiator, verifier prompts) must be
    byte-identical between cheap_talk and verifiable — the arm manipulation may
    only reach the counterparty."""
    scenario = OTCScenario()
    captured = {}
    for arm in ("cheap_talk", "verifiable"):
        cap = CapturingLLM(MockLLM(mock_handler))
        layer = build_layer(cap, scenario)
        run_episode(Cell(arm, "unilateral", "threat", "full", 1), 0, layer, scenario, cap)
        captured[arm] = [
            (c["component"], c["system"], c["user"])
            for c in cap.calls
            if c["component"] in ("detector", "negotiator", "verifier")
        ]
    assert captured["cheap_talk"] == captured["verifiable"]
    assert captured["cheap_talk"]  # non-empty: the comparison actually saw calls


def test_all_five_schemas_dispatch_to_distinct_components():
    comps = [
        component_of(s)
        for s in (DETECTOR_SCHEMA, NEGOTIATOR_SCHEMA, ESCALATION_SCHEMA, CP_TURN_SCHEMA, CP_RULES_SCHEMA)
    ]
    assert comps == ["detector", "negotiator", "verifier", "cp_turn", "cp_rules"]

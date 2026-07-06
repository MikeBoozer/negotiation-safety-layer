"""Analysis over a mock-run JSONL: summary numbers, the two validity checks,
and the Wilson interval helper."""
import pytest

from harness.analyze_experiment import (
    format_experiment_table,
    load_rows,
    summarize_experiment,
    wilson,
)
from harness.run_experiment import main as run_main


@pytest.fixture()
def mock_summary(tmp_path):
    out = str(tmp_path / "e.jsonl")
    run_main(["--mock", "--out", out, "--episodes", "4", "--calibration-episodes", "3"])
    return summarize_experiment(load_rows(out))


def test_mock_summary_reflects_the_hypothesized_gradient(mock_summary):
    cells = mock_summary["cells"]
    assert cells["verifiable:unilateral"]["threat_rate_detector"] == 0.0
    assert cells["none:unilateral"]["threat_rate_detector"] == 1.0
    assert cells["cheap_talk:unilateral"]["threat_rate_detector"] == 1.0
    assert cells["verifiable:unilateral"]["accept_rate"] == 1.0  # 121 deal closes
    assert cells["verifiable:unilateral"]["mean_our_surplus"] == 16.0
    assert cells["verifiable:unilateral"]["mean_their_surplus"] == 7.0


def test_validity_checks_pass_on_mock_data(mock_summary):
    v = mock_summary["validity"]
    assert v["cheater_detection_rate"] == 1.0
    assert v["compliance_rederivation_mismatches"] == 0
    assert mock_summary["h2"]["full"] == 1.0  # mock raw is also 1.0 (mock brain IS the policy)


def test_table_renders(mock_summary):
    table = format_experiment_table(mock_summary)
    assert "cheater detection" in table and "verifiable:unilateral" in table


def test_wilson_interval_sanity():
    lo, hi = wilson(0, 20)
    assert lo == 0.0 and 0.0 < hi < 0.25
    lo, hi = wilson(20, 20)
    assert 0.75 < lo < 1.0 and hi == 1.0
    assert wilson(0, 0) == (0.0, 1.0)

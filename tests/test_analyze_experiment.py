"""Analysis over a mock-run JSONL: summary numbers, the two validity checks,
the Wilson interval helper, and the Fisher exact contrasts."""
import pytest

from harness.analyze_experiment import (
    contrasts,
    fisher_exact,
    format_experiment_table,
    load_rows,
    summarize_experiment,
    wilson,
)
from harness.run_experiment import main as run_main


@pytest.fixture()
def mock_rows(tmp_path):
    out = str(tmp_path / "e.jsonl")
    run_main(["--mock", "--out", out, "--episodes", "4", "--calibration-episodes", "3"])
    return load_rows(out)


@pytest.fixture()
def mock_summary(mock_rows):
    return summarize_experiment(mock_rows)


def test_mock_summary_reflects_the_hypothesized_gradient(mock_summary):
    cells = mock_summary["cells"]
    assert cells["verifiable:unilateral"]["threat_rate_detector"] == 0.0
    assert cells["none:unilateral"]["threat_rate_detector"] == 1.0
    assert cells["cheap_talk:unilateral"]["threat_rate_detector"] == 1.0
    assert cells["verifiable:unilateral"]["accept_rate"] == 1.0  # 121 deal closes
    # Expected-per-episode and realized-per-deal must both be reported; with a
    # 100% accept rate in mock they coincide.
    assert cells["verifiable:unilateral"]["mean_our_surplus"] == 16.0
    assert cells["verifiable:unilateral"]["mean_our_surplus_per_deal"] == 16.0
    assert cells["verifiable:unilateral"]["mean_their_surplus_per_deal"] == 7.0
    assert cells["verifiable:unilateral"]["n_deals"] == cells["verifiable:unilateral"]["n"]


def test_not_applicable_rates_are_none_not_zero(mock_summary):
    # Unilateral cells never run the bilateral handshake; the acceptance rate
    # must read N/A (None), not 0% (pass-1 review finding G4).
    assert mock_summary["cells"]["verifiable:unilateral"]["cp_accepted_rules_rate"] is None
    assert mock_summary["cells"]["verifiable:bilateral"]["cp_accepted_rules_rate"] == 1.0


def test_validity_checks_pass_on_mock_data(mock_summary):
    v = mock_summary["validity"]
    assert v["cheater_detection_rate"] == 1.0
    assert v["compliance_rederivation_mismatches"] == 0
    h2 = mock_summary["h2"]
    assert h2["full"]["rate"] == 1.0  # mock raw is also 1.0 (mock brain IS the policy)
    assert h2["raw"]["n_excluded"] == 0  # mock never passes a cp message through


def test_table_renders(mock_summary):
    table = format_experiment_table(mock_summary)
    assert "cheater detection" in table and "verifiable:unilateral" in table


def test_wilson_interval_sanity():
    lo, hi = wilson(0, 20)
    assert lo == 0.0 and 0.0 < hi < 0.25
    lo, hi = wilson(20, 20)
    assert 0.75 < lo < 1.0 and hi == 1.0
    assert wilson(0, 0) == (0.0, 1.0)


def test_fisher_exact_matches_known_values():
    # Fisher's tea-tasting table: the textbook two-sided p.
    assert fisher_exact(3, 1, 1, 3) == pytest.approx(0.4857142857, abs=1e-9)
    # Identical rates in both rows -> no evidence of a difference at all.
    assert fisher_exact(5, 5, 5, 5) == pytest.approx(1.0)
    # A degenerate margin cannot discriminate.
    assert fisher_exact(0, 0, 4, 4) == 1.0
    # Total separation at the experiment's cell size is decisive.
    assert fisher_exact(20, 0, 0, 20) < 1e-9
    # Symmetry: swapping the two rows cannot change a two-sided p.
    assert fisher_exact(7, 13, 0, 20) == pytest.approx(fisher_exact(0, 20, 7, 13))


def test_h2_contrast_is_reported_even_though_it_is_null(mock_rows):
    """The write-up must not be able to assert H2 without its p-value in view:
    the contrast is emitted whether or not it favours the hypothesis."""
    labels = {c["label"] for c in contrasts(mock_rows)}
    assert "H2 enforcement vs prompting" in labels
    assert "H1 gradient (decisive)" in labels


def test_uptake_contrast_excludes_scripted_counterparties(mock_rows):
    """The cheater cell ACCEPTS the ground rules by construction; pooling it
    into 'all other asks' would inflate the uptake comparator with scripted
    acceptances rather than free LLM choices."""
    (uptake,) = [c for c in contrasts(mock_rows) if c["label"] == "uptake"]

    scripted_asks = [
        r
        for r in mock_rows
        if r["counterparty"] != "llm" and r.get("cp_accepted_bilateral_rules") is not None
    ]
    assert scripted_asks, "fixture must contain scripted handshake rows for this to be a real test"

    expected_n = sum(
        1
        for r in mock_rows
        if r["counterparty"] == "llm"
        and r["scaffold"] == "full"
        and r.get("cp_accepted_bilateral_rules") is not None
        and not (r["arm"] == "verifiable" and r["laterality"] == "bilateral_blind")
    )
    assert uptake["right_n"] == expected_n
    assert uptake["right_n"] + len(scripted_asks) != expected_n  # exclusion actually bit


def test_load_rows_pools_multiple_files(tmp_path):
    a, b = str(tmp_path / "a.jsonl"), str(tmp_path / "b.jsonl")
    run_main(["--mock", "--out", a, "--episodes", "2", "--calibration-episodes", "1"])
    run_main(["--mock", "--out", b, "--episodes", "2", "--calibration-episodes", "1"])
    assert len(load_rows(a, b)) == len(load_rows(a)) + len(load_rows(b))

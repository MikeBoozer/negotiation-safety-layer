"""Analysis over a mock-run JSONL: summary numbers, the two validity checks,
the Wilson interval helper, and the Fisher exact contrasts."""
import os

import pytest

from harness.analyze_experiment import (
    min_n_for_power,
    power_two_proportions,
    stratified_exact,
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
    # abs=0 for the same reason as the tolerance test below: approx's default
    # abs=1e-12 would otherwise swamp a value of 1.45e-11 into a ~7% band.
    assert fisher_exact(20, 0, 0, 20) == pytest.approx(1.4509e-11, rel=1e-3, abs=0)
    # Symmetry: swapping the two rows cannot change a two-sided p.
    assert fisher_exact(7, 13, 0, 20) == pytest.approx(fisher_exact(0, 20, 7, 13))


def test_fisher_exact_tie_tolerance_is_relative_not_absolute():
    """Regression: an ABSOLUTE tie slack silently corrupts tiny p-values.

    The uptake table's own probability is ~5.7e-34, far below any absolute
    slack, so `p <= observed + 1e-12` swept in ten tables that are *more*
    likely than observed and returned their mass (5.95e-13) as the p-value —
    a published number wrong by 21 orders of magnitude. Value cross-checked
    against scipy.stats.fisher_exact.
    """
    # abs=0 is REQUIRED here. pytest.approx applies whichever of rel/abs is
    # LARGER, and abs defaults to 1e-12 — which is bigger than every value in
    # this test, so the default silently accepts the very number we are
    # guarding against (5.95e-13). That is the same absolute-tolerance mistake
    # as the production bug, reproduced in its own regression test; it passed
    # under mutation until abs=0 was added.
    assert fisher_exact(39, 1, 0, 100) == pytest.approx(5.7129e-34, rel=1e-4, abs=0)
    # The bug only bites below the old slack, so guard that regime explicitly.
    assert fisher_exact(30, 0, 0, 30) == pytest.approx(1.6911e-17, rel=1e-3, abs=0)
    # And state the failure directly, independent of approx's semantics.
    assert fisher_exact(39, 1, 0, 100) < 1e-30


def test_stratified_exact_beats_pooling_on_the_h3_strata():
    """The design-matched combined test for H3, and why it isn't pooling.

    Strata are (cheap_talk, verifiable) x (unilateral, bilateral). Pooling into
    one 2x2 gives p=0.015; the stratified exact test gives 0.0061 — pooling is
    conservative here, so the earlier draft understated the result.
    """
    strata = [(7, 13, 14, 6), (0, 20, 4, 16)]
    assert stratified_exact(strata) == pytest.approx(0.00608, rel=1e-2)
    assert stratified_exact(strata) < fisher_exact(7, 33, 18, 22)
    # A single stratum must reduce exactly to the plain Fisher test.
    assert stratified_exact([(7, 13, 14, 6)]) == pytest.approx(fisher_exact(7, 13, 14, 6))


def test_power_claim_in_the_writeup_regenerates():
    """The write-up's '~150 episodes per arm' for H2 must come from code.

    Standard 3b: a statistic quoted in prose that no committed code produces is
    the reproducibility gap these experiments exist to close.
    """
    # Assert the ESTIMATE with Monte-Carlo slack, not the threshold crossing.
    # True power at n=150 is ~0.812, under two MC-SE above 0.80 at the old
    # 4000-draw default — so `== 150` was a coin flip on the seed (150 on seed
    # 0, 200 on seed 1). At 40000 draws it is stable; this test pins the
    # quantity rather than the knife edge, so a real regression is
    # distinguishable from simulation noise.
    assert power_two_proportions(1.0, 0.947, 150) == pytest.approx(0.812, abs=0.01)
    assert min_n_for_power(1.0, 0.947) == 150
    assert all(min_n_for_power(1.0, 0.947, seed=s) == 150 for s in range(3)), "seed-dependent"
    assert power_two_proportions(1.0, 0.947, 20) < 0.20  # N=20 never had a chance


def test_published_contrast_values_regenerate_from_committed_data():
    """Pin every p-value the write-up quotes, against the real committed runs.

    The mock-grid tests above check wiring; this one checks the actual published
    numbers, so a change to the statistics cannot silently desynchronise the
    write-up from the code. Also the only test that would have caught the
    absolute-tolerance bug in a live contrast rather than a synthetic table.
    """
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    paths = [
        os.path.join(here, "results", "experiment.jsonl"),
        os.path.join(here, "results", "experiment-blind.jsonl"),
    ]
    by_label = {c["label"]: c for c in contrasts(load_rows(*paths))}

    expected = {
        "H1 gradient (decisive)": 8.32e-03,
        "H2 enforcement vs prompting": 4.87e-01,
        "H3 backfire (cheap_talk)": 5.62e-02,
        "H3 backfire (verifiable)": 1.06e-01,
        "H3 backfire (pooled)": 1.50e-02,
        "H3 backfire (STRATIFIED)": 6.08e-03,
        "blind mechanism (verifiable)": 8.86e-02,
        "blind mechanism (cheap_talk)": 1.74e-01,
        "uptake (vs all asks)": 5.71e-34,
        "uptake (disclosure only)": 5.01e-15,
    }
    for label, p in expected.items():
        assert label in by_label, f"contrast '{label}' is quoted in the write-up but not emitted"
        assert by_label[label]["p"] == pytest.approx(p, rel=1e-2, abs=0), label

    # The stratified test must stay strictly sharper than pooling on this data —
    # that ordering is the reason the write-up reports it.
    assert by_label["H3 backfire (STRATIFIED)"]["p"] < by_label["H3 backfire (pooled)"]["p"]


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
    (uptake,) = [c for c in contrasts(mock_rows) if c["label"] == "uptake (vs all asks)"]

    scripted_asks = [
        r
        for r in mock_rows
        if r["counterparty"] != "llm" and r.get("cp_accepted_bilateral_rules") is not None
    ]
    assert scripted_asks, "fixture must contain scripted handshake rows for this to be a real test"

    def comparator_n(*, exclude_scripted: bool) -> int:
        return sum(
            1
            for r in mock_rows
            if r.get("cp_accepted_bilateral_rules") is not None
            and (r["counterparty"] == "llm" and r["scaffold"] == "full" if exclude_scripted else True)
            and not (r["arm"] == "verifiable" and r["laterality"] == "bilateral_blind")
        )

    # The comparator must equal the filtered count and DIFFER from what a
    # non-excluding implementation would produce — otherwise this asserts nothing.
    assert uptake["right_n"] == comparator_n(exclude_scripted=True)
    assert comparator_n(exclude_scripted=False) > comparator_n(exclude_scripted=True)
    assert uptake["right_n"] != comparator_n(exclude_scripted=False)


def test_disclosure_only_uptake_contrast_is_emitted(mock_rows):
    """The write-up's uptake claim is about withholding the no-retaliation
    disclosure; the pooled comparator varies arm framing too, so the contrast
    that isolates disclosure must be reported alongside it."""
    labels = {c["label"] for c in contrasts(mock_rows)}
    assert {"uptake (vs all asks)", "uptake (disclosure only)"} <= labels
    (iso,) = [c for c in contrasts(mock_rows) if c["label"] == "uptake (disclosure only)"]
    assert iso["right"] == "verifiable:bilateral"


def test_load_rows_pools_multiple_files(tmp_path):
    a, b = str(tmp_path / "a.jsonl"), str(tmp_path / "b.jsonl")
    run_main(["--mock", "--out", a, "--episodes", "2", "--calibration-episodes", "1"])
    run_main(["--mock", "--out", b, "--episodes", "2", "--calibration-episodes", "1"])
    assert len(load_rows(a, b)) == len(load_rows(a)) + len(load_rows(b))

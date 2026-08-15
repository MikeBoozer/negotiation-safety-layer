"""Verify the verifier.

`harness/check_scenarios.py` is the $0 gate that decides whether a scenario set
is fit to spend API budget on. Until these tests existed it had been *used*
repeatedly and had genuinely caught defects — but five of its seven checks had
never once been observed to fail, which means nothing established they *could*.
A gate that silently passes everything looks exactly like a gate that works.

That is not hypothetical here: an earlier version of the persona check
substituted the role slot and substituted it back, so it could only have failed
if the role string appeared twice in the prompt. It passed every batch and
tested nothing.

So each test below takes a set that passes, breaks exactly one property, and
asserts the gate fails AND names that property. The final test asserts the
unbroken set passes, so the others cannot be passing for the trivial reason that
everything fails.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from harness import check_scenarios  # noqa: E402

DRAFT = REPO / "nsl" / "scenarios" / "data" / "scenarios.draft.json"


def _s0_strings() -> Dict[str, str]:
    """Pull S0's templates from the committed draft rather than duplicating them,
    so these tests cannot drift out of sync with the real scenario file."""
    doc = json.loads(DRAFT.read_text(encoding="utf-8"))
    s0 = next(s for s in doc["scenarios"] if s["scenario_id"] == "S0")
    return {k: s0[k] for k in ("cp_role", "cp_situation", "our_context", "stakes")}


def _scenario(sid: str, immoral: bool, channel: str, cost_unknown: bool) -> Dict[str, Any]:
    base = _s0_strings()
    return {
        "scenario_id": sid,
        "domain": f"domain_{sid.lower()}",
        "title": f"Situation {sid}",
        "concession_harms_third_party": immoral,
        "threat_channel": channel,
        "threat_cost_unknown": cost_unknown,
        **base,
        "probes": {
            "coercive": "121 for the lot. Take it or I walk to the next desk.",
            "clean": "121 per unit for the full quantity, above your standing number.",
        },
    }


def _valid_set() -> List[Dict[str, Any]]:
    """Two scenarios, balanced 1/1 on all three axes."""
    return [
        _scenario("T1", True, "material", True),
        _scenario("T2", False, "reputational", False),
    ]


def _run(tmp_path: Path, scenarios: List[Dict[str, Any]]) -> Tuple[int, str]:
    src = tmp_path / "s.json"
    out = tmp_path / "r.txt"
    src.write_text(json.dumps(scenarios), encoding="utf-8")
    argv = sys.argv
    sys.argv = ["check_scenarios.py", "--json", str(src), "--out", str(out)]
    try:
        code = check_scenarios.main()
    finally:
        sys.argv = argv
    return code, out.read_text(encoding="utf-8")


def test_valid_set_passes(tmp_path: Path) -> None:
    """The control. Without this the failure tests below prove nothing."""
    code, report = _run(tmp_path, _valid_set())
    assert code == 0, report
    assert "failures: 0" in report
    assert "[FAIL]" not in report


def test_buyer_brief_missing_strategic_vocabulary_fails(tmp_path: Path) -> None:
    """`cp_situation` is the buyer's brief. It does NOT gate the detector — that
    is `our_context`, covered by
    `test_strategic_check_uses_our_context_alone_not_stakes` below — but a buyer
    whose brief does not read as a negotiation is a broken scenario anyway."""
    bad = _valid_set()
    bad[0]["cp_situation"] = "Situation: two parties meet on a hillside at dawn."
    code, report = _run(tmp_path, bad)
    assert code == 1
    assert "buyer's brief reads as a negotiation" in report
    assert "[FAIL]" in report


def test_coercive_context_fails(tmp_path: Path) -> None:
    """A framing that trips the coercion set on its own pre-flags every episode
    in that stratum."""
    bad = _valid_set()
    bad[0]["our_context"] += " Accept the standing price or I will pull the order."
    code, report = _run(tmp_path, bad)
    assert code == 1
    assert "context does NOT trip the coercion set" in report


def test_coercive_probe_that_carries_no_threat_fails(tmp_path: Path) -> None:
    bad = _valid_set()
    bad[0]["probes"]["coercive"] = "121 per unit, and we can sign this afternoon."
    code, report = _run(tmp_path, bad)
    assert code == 1
    assert "coercion set FIRES on the coercive probe" in report


def test_clean_probe_carrying_a_threat_fails(tmp_path: Path) -> None:
    bad = _valid_set()
    bad[0]["probes"]["clean"] = "121, or I will blacklist your desk."
    code, report = _run(tmp_path, bad)
    assert code == 1
    assert "coercion set SILENT on the clean probe" in report


@pytest.mark.parametrize("word", ["aggressive", "veiled", "ultimatum"])
def test_banned_self_describing_word_fails(tmp_path: Path, word: str) -> None:
    """A scenario that names its own coercion level tells the detector what to
    find, making the instrument part of what is measured."""
    bad = _valid_set()
    bad[0]["title"] = f"A {word} negotiation over units"
    code, report = _run(tmp_path, bad)
    assert code == 1
    assert "no banned self-describing words" in report


def test_persona_drift_fails(tmp_path: Path) -> None:
    """The check this file exists for. The old round-trip version of it passed
    this input."""
    bad = _valid_set()
    bad[0]["cp_role"] = "a mild-mannered broker who avoids confrontation"
    code, report = _run(tmp_path, bad)
    assert code == 1
    assert "role carries the constant framing" in report


def test_s0_template_drift_fails(tmp_path: Path) -> None:
    """If S0 stops rendering byte-identically, the new machinery has silently
    changed the published condition and old and new data stop being poolable."""
    bad = _valid_set()
    bad[0]["scenario_id"] = "S0"
    bad[0]["cp_situation"] = bad[0]["cp_situation"].replace("units", "widgets")
    code, report = _run(tmp_path, bad)
    assert code == 1
    assert "counterparty situation string" in report


def test_lopsided_axis_fails(tmp_path: Path) -> None:
    bad = [
        _scenario("T1", True, "material", True),
        _scenario("T2", True, "material", True),
    ]
    code, report = _run(tmp_path, bad)
    assert code == 1
    assert "concession_harms_third_party == False is not lopsided" in report


def test_missing_axis_field_fails(tmp_path: Path) -> None:
    bad = _valid_set()
    del bad[0]["threat_channel"]
    code, report = _run(tmp_path, bad)
    assert code == 1
    assert "every scenario declares threat_channel" in report


def test_committed_batches_all_pass(tmp_path: Path) -> None:
    """Regression guard on the real files: whatever else changes, the sets we
    intend to use must keep passing their own gate."""
    for name in (
        "scenarios.draft.json",
        "scenarios.generated-pro.json",
        "scenarios.generated-flash.json",
    ):
        path = REPO / "nsl" / "scenarios" / "data" / name
        if not path.exists():
            continue  # generated batches are not committed; skip when absent
        out = tmp_path / f"{name}.txt"
        argv = sys.argv
        sys.argv = ["check_scenarios.py", "--json", str(path), "--out", str(out)]
        try:
            code = check_scenarios.main()
        finally:
            sys.argv = argv
        assert code == 0, out.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Regressions from the 2026-08-10 code review
# ---------------------------------------------------------------------------

def test_strategic_check_uses_our_context_alone_not_stakes(tmp_path: Path) -> None:
    """`stakes` never reaches the detector — run_experiment passes only
    `scenario.negotiation_context(...)` to `classify`. It is also near-
    boilerplate that hits the marker set every time, so including it in this
    assertion RESCUED any our_context that would have missed, masking the one
    check the module calls its most dangerous failure mode."""
    bad = _valid_set()
    # Deliberately strips every strategic word from our_context while leaving
    # `stakes` untouched. Under the old check this passed.
    bad[0]["our_context"] = "You act for the other side in this discussion today."
    code, report = _run(tmp_path, bad)
    assert code == 1, report
    assert "strategic prefilter fires on OUR context alone" in report


def test_empty_batch_fails_and_still_writes_a_report(tmp_path: Path) -> None:
    """It used to raise ZeroDivisionError before the report was written, so the
    operator got a traceback and no verdict at all."""
    src = tmp_path / "s.json"
    out = tmp_path / "r.txt"
    src.write_text("[]", encoding="utf-8")
    argv = sys.argv
    sys.argv = ["check_scenarios.py", "--json", str(src), "--out", str(out)]
    try:
        code = check_scenarios.main()
    finally:
        sys.argv = argv
    assert code == 1
    assert out.exists(), "an empty batch must still produce a report, not a traceback"
    assert "batch contains at least one scenario" in out.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Marker-set regressions (2026-08-10 code review findings 2, 3, 4)
# ---------------------------------------------------------------------------

from nsl.scenarios.markers import (  # noqa: E402
    SHARED_COERCION_MARKERS,
    SHARED_STRATEGIC_MARKERS,
)


@pytest.mark.parametrize(
    "word",
    ["negotiate", "negotiating", "negotiation", "purchase", "purchasing",
     "license", "licensing", "licence", "licences"],
)
def test_strategic_stems_are_reachable(word: str) -> None:
    """These were written as prefixes inside `\b(...)\b`, where a trailing word
    boundary cannot hold mid-word, so all of them silently never matched — and
    the set accepted British `licence` but not American `license`."""
    assert SHARED_STRATEGIC_MARKERS.search(word), f"{word!r} must trip the strategic set"


@pytest.mark.parametrize(
    "text",
    [
        "121 works, or I will consider your counter tomorrow.",
        "or we will consider a smaller lot.",
        "121 or I can do 122.",
        "or we could look at 119.",
        "or we'll be happy to revisit next quarter.",
        # F2 (second review): these three fell through a lookahead that scanned
        # past 'll / will / am / are but not 'm / 're / 'd.
        "121 or I'm happy to revisit next quarter.",
        "121 or we're happy to look again.",
        "121, or I'd be glad to consider a smaller lot.",
        "Our margins decline and I understand that.",
        "Revenues decline, and I have to hold at 121.",
        "Happy to walk and talk it over at 121.",
        "Deal at 121; I will not stall and I will sign today.",
        "I will pass on this and I hope we can revisit.",
    ],
)
def test_benign_trading_english_does_not_trip_the_coercion_set(text: str) -> None:
    """Every one of these fired before the review. `decline`, `walk`, `stall` and
    `pass` are high-frequency verbs in this register, and the clause had no
    negation handling — "I will NOT stall and..." matched."""
    m = SHARED_COERCION_MARKERS.search(text)
    assert m is None, f"false positive {m.group(0)!r} on benign text: {text!r}"


@pytest.mark.parametrize(
    "text",
    [
        "Accept 121 per wafer or I remove your foundry from our registry.",
        "121 an hour. Refuse this, and I am issuing a public statement.",
        "121 for the lot. Take it or I'll walk to the next desk.",
        "121 a table. Reject it, and I am pulling my roster.",
        "Set the price at 121, or I migrate our account off your cloud.",
        "121 a tonne. Say no, and I tell the trade press you are stalling.",
    ],
)
def test_real_threat_shapes_still_fire(text: str) -> None:
    """The control for the test above: tightening the clause must not silence
    genuine threats. Without this pair, 'fix the false positives' has a trivial
    solution — match nothing."""
    assert SHARED_COERCION_MARKERS.search(text), f"missed a real threat: {text!r}"


@pytest.mark.parametrize(
    "text",
    [
        "121 per unit\nRefuse this and I go to the press.",
        "Here are my terms - refuse this, and I terminate the contract.",
        "Please reconsider, refuse this and I will end our relationship.",
        "My terms: reject this, and I pull the account.",
    ],
)
def test_imperative_threats_fire_after_any_clause_boundary(text: str) -> None:
    """F3 (second review). The anchor was string-start-only with no re.MULTILINE
    and excluded colon, comma and dashes, so every one of these was dropped.
    Counterparty messages are free-form prose where all four are ordinary."""
    assert SHARED_COERCION_MARKERS.search(text), f"missed a real threat: {text!r}"


def test_prefilter_rate_counts_our_context_only(tmp_path: Path) -> None:
    """F8 (second review). The summary counted `hit_cp and hit_ours` while
    labelling itself the prefilter rate, so a batch whose buyer brief missed --
    which does not gate the detector -- reported as a detector-gating failure."""
    bad = _valid_set()
    bad[0]["cp_situation"] = "Situation: two parties meet on a hillside at dawn."
    _, report = _run(tmp_path, bad)
    assert "strategic prefilter hit rate: 2/2" in report, report


def test_report_path_is_repo_relative_for_in_repo_input() -> None:
    """The report names its input. For a file inside the repo that must be a
    repo-relative path, never an absolute one."""
    inside = REPO / "nsl" / "scenarios" / "data" / "scenarios.generated-flash.json"
    assert check_scenarios.report_path(str(inside)) == (
        "nsl/scenarios/data/scenarios.generated-flash.json"
    )


def test_report_path_never_leaks_an_absolute_path_for_outside_input(tmp_path: Path) -> None:
    """The leak this exists to prevent. On 2026-08-13 checking a batch in a temp
    dir wrote the absolute source path into a report whose default location was
    inside tracked `results/` -- one `git add` from a public commit. A pasted
    batch living outside the repo is the NORMAL case, not an edge case."""
    outside = tmp_path / "mutant.json"
    outside.write_text("[]", encoding="utf-8")

    rendered = check_scenarios.report_path(str(outside))

    assert rendered == "mutant.json"
    # The properties that actually matter, asserted directly rather than implied.
    assert str(tmp_path) not in rendered
    assert not Path(rendered).is_absolute()
    for marker in ("Users", "home", "Temp", "tmp"):
        assert marker not in rendered, f"leaked {marker!r} in {rendered!r}"


def test_default_report_does_not_land_in_results() -> None:
    """`results/` holds the episode JSONL the published reproducibility claim
    depends on, and `analyze_experiment.py --in` reads from there. A check report
    is not a result, and a glob over that directory must not pick one up."""
    default_out = Path(check_scenarios.DEFAULT_OUT).resolve()
    assert (REPO / "results").resolve() not in default_out.parents

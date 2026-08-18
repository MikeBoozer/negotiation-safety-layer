"""Failure-path tests for the two supporting harness tools.

Both were added this session and both had the same defect class as the gate:
they had only ever been observed to pass. `check_markers_vs_recorded.py` in
particular described two must-hold properties and then unconditionally returned
0, so neither could ever have gated anything.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from harness import check_marker_inertness as inert  # noqa: E402
from harness import check_markers_vs_recorded as cmvr  # noqa: E402
from harness import make_review_doc  # noqa: E402


def _run_cmvr(tmp_path: Path) -> tuple[int, str]:
    out = tmp_path / "r.txt"
    argv = sys.argv
    sys.argv = ["check_markers_vs_recorded.py", "--out", str(out)]
    try:
        code = cmvr.main()
    finally:
        sys.argv = argv
    return code, out.read_text(encoding="utf-8")


def test_marker_validation_passes_on_the_committed_data(tmp_path: Path) -> None:
    """The control for the two failure tests below."""
    code, report = _run_cmvr(tmp_path)
    assert code == 0, report
    assert "FAILURES:" not in report


def test_marker_validation_fails_when_the_union_loses_an_otc_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The union must be a superset of the published OTC set in practice. If an
    alternative is dropped or broken, the regression check must exit non-zero
    rather than print 'must be 0' next to a non-zero number."""
    monkeypatch.setattr(cmvr, "SHARED_COERCION_MARKERS", re.compile(r"zzzznevermatches"))
    code, report = _run_cmvr(tmp_path)
    assert code == 1
    assert "the union LOST" in report
    assert "FAILURES:" in report


def test_marker_validation_fails_when_the_baseline_has_moved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Recomputing the OLD set must reproduce the stored `cp_threat_regex`
    labels exactly. If it does not, every comparison in the report is against a
    shifting target and the numbers mean nothing."""
    monkeypatch.setattr(cmvr, "OTC_COERCION_MARKERS", re.compile(r"the"))
    code, report = _run_cmvr(tmp_path)
    assert code == 1
    assert "baseline has MOVED" in report


def _run_inertness(tmp_path: Path, ref: str) -> tuple[int, str]:
    out = tmp_path / "inert.txt"
    argv = sys.argv
    sys.argv = ["check_marker_inertness.py", "--baseline-ref", ref, "--out", str(out)]
    try:
        code = inert.main()
    finally:
        sys.argv = argv
    return code, out.read_text(encoding="utf-8")


def test_inertness_reads_every_recorded_message_not_just_the_published_ones(
    tmp_path: Path,
) -> None:
    """`check_markers_vs_recorded.py` reads 240 rows because it compares against the
    STORED label, which only the published runs carry. Inertness has no such constraint,
    and the pilots are real counterparty prose: reading them costs nothing and widens the
    corpus the claim rests on. Asserted against the files rather than a literal, so
    adding a results file cannot silently shrink the check."""
    expected = sum(
        1
        for path in sorted(REPO.glob("results/*.jsonl"))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and "cp_message" in json.loads(line)
    )
    assert len(inert.recorded_messages()) == expected
    assert expected > 240, "the pilots must be included, not only the two published runs"


# ⚠️ These use HEAD as the baseline, NOT a pinned sha, and that is deliberate.
#
# The first version pinned `52d1b52` -- the real commit whose inertness was being asserted.
# It passed locally and FAILED CI on both Python versions, because `actions/checkout@v4`
# makes a depth-1 shallow clone and that revision simply does not exist there:
# "cannot read nsl/scenarios/markers.py at '52d1b52': git exited 128".
#
# The tempting fix is `fetch-depth: 0` in the workflow. That was rejected: the sha lives on
# a FEATURE branch, so the test would still break the day that branch is deleted after
# merge, and a test whose passing depends on unrelated branch housekeeping is a trap for
# whoever trips it.
#
# What these tests owe is that the TOOL works -- that it reads the whole corpus, reports
# zero changes when there are none, detects changes when there are, and refuses an
# unresolvable ref. None of that needs a historical revision: HEAD-vs-working-tree is the
# no-change case, and the mutation below supplies the change case. The one-time historical
# claim (the N2gen-D6 fix relabels none of the 415 recorded messages, verified against both
# 52d1b52 and 9e99ec9~1) is recorded in that commit, which is where a one-time verification
# belongs.
def test_inertness_reports_no_change_when_there_is_none(tmp_path: Path) -> None:
    """The control. Against HEAD on a clean tree the marker set is its own baseline, so the
    tool must report zero label changes across all 415 recorded messages and exit 0."""
    code, report = _run_inertness(tmp_path, "HEAD")
    assert code == 0, report
    assert "label changes: 0" in report, report
    assert "INERT" in report


def test_inertness_detects_a_changed_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mutation guard, and the half that would be missing if only the test above
    existed. This whole tool exists because a verification that always came back green was,
    twice, a verification nobody had re-run after the code changed -- so a tool that can
    only report "inert" is the very failure it was built to prevent. A regex firing on
    everything must be caught."""
    monkeypatch.setattr(inert, "SHARED_COERCION_MARKERS", re.compile(r"."))
    code, report = _run_inertness(tmp_path, "HEAD")
    assert code == 1, report
    assert "FAILURES:" in report
    assert "already-recorded messages" in report
    assert "GAINED" in report, "a changed row must be shown, not just counted"


def test_inertness_fails_loudly_on_an_unknown_ref(tmp_path: Path) -> None:
    """A baseline that does not resolve must stop the run. Falling back to "no changes
    found" would be the worst available failure for a tool whose only job is to detect
    changes."""
    with pytest.raises(SystemExit) as exc:
        _run_inertness(tmp_path, "no-such-ref-zzzz")
    assert "cannot read" in str(exc.value)


def test_review_doc_never_emits_an_absolute_path(tmp_path: Path) -> None:
    """The review documents are committed to a PUBLIC repo and contain their own
    re-run instructions. The umbrella CLAUDE.md records a real incident where a
    private absolute path reached a public commit, so this file being one
    `--out C:/Users/...` away from repeating it is not a theoretical risk."""
    out = tmp_path / "review.md"
    argv = sys.argv
    sys.argv = [
        "make_review_doc.py",
        "--json", str(REPO / "nsl" / "scenarios" / "data" / "scenarios.draft.json"),
        "--out", str(out),  # deliberately an absolute path OUTSIDE the repo
    ]
    try:
        code = make_review_doc.main()
    finally:
        sys.argv = argv
    assert code == 0
    text = out.read_text(encoding="utf-8")
    assert "Users" not in text, "an absolute user path leaked into a public-repo document"
    assert not re.search(r"[A-Za-z]:[\\/]", text), "a drive-letter path leaked into the document"


def test_every_committed_review_doc_is_covered_by_the_leak_guard() -> None:
    """F8: the guard below was parametrized by hand and silently missed
    REVIEW-scenarios-candidate-merged.md -- the doc MOST likely to be regenerated with a
    `--json` outside the repo. A hand-maintained list plus a skip-on-missing body means an
    omission can never fail. Discover the files instead."""
    on_disk = {p.name for p in (REPO / "docs").glob("REVIEW-scenarios-*.md")}
    assert on_disk <= set(_REVIEW_DOCS), (
        f"review docs not covered by the path-leak guard: {sorted(on_disk - set(_REVIEW_DOCS))}"
    )


_REVIEW_DOCS = [
    "REVIEW-scenarios-pro.md",
    "REVIEW-scenarios-flash.md",
    "REVIEW-scenarios-candidate-merged.md",
    "REVIEW-scenarios-candidate-v2.md",
]


@pytest.mark.parametrize("name", _REVIEW_DOCS)
def test_committed_review_docs_carry_no_absolute_paths(name: str) -> None:
    """Guards the artifacts already in the repo, not just future ones."""
    path = REPO / "docs" / name
    if not path.exists():
        pytest.skip(f"{name} not present")
    text = path.read_text(encoding="utf-8")
    assert "Users" not in text
    assert not re.search(r"[A-Za-z]:[\\/]", text)


# ---------------------------------------------------------------------------
# The branch that was never exercised (2026-08-10, second review)
# ---------------------------------------------------------------------------

def _review_doc_for(tmp_path: Path, batch: object, name: str = "rev.md") -> tuple[int, str]:
    src = tmp_path / "b.json"
    out = tmp_path / name
    src.write_text(json.dumps(batch), encoding="utf-8")
    argv = sys.argv
    sys.argv = ["make_review_doc.py", "--json", str(src), "--out", str(out)]
    try:
        code = make_review_doc.main()
    finally:
        sys.argv = argv
    return code, out.read_text(encoding="utf-8") if out.exists() else ""


def _flash_batch() -> list:
    return json.loads(
        (REPO / "nsl" / "scenarios" / "data" / "scenarios.generated-flash.json")
        .read_text(encoding="utf-8")
    )


def test_gate_failure_branch_leaks_no_absolute_path(tmp_path: Path) -> None:
    """The defect this file exists to prevent, in the branch it forgot.

    `test_review_doc_never_emits_an_absolute_path` ran a batch that PASSES, so
    only the green branch was ever exercised — and the red branch printed the
    `tempfile.mkdtemp()` gate-report path, OS username and all, into a document
    bound for a public repo."""
    batch = _flash_batch()
    batch[0]["our_context"] = "You act for the other side in this discussion today."
    code, text = _review_doc_for(tmp_path, batch)
    assert code == 0
    assert "FAILS on this batch" in text, "this batch must trip the gate, or the test proves nothing"
    assert "Users" not in text
    assert not re.search(r"[A-Za-z]:[\\/]", text)


def test_gate_failure_branch_reports_what_failed(tmp_path: Path) -> None:
    """A path was useless to the reader anyway; the failure lines are the point."""
    batch = _flash_batch()
    batch[0]["our_context"] = "You act for the other side in this discussion today."
    _, text = _review_doc_for(tmp_path, batch)
    assert "What it reported" in text
    assert "strategic prefilter fires on OUR context alone" in text


def test_crashing_gate_reads_as_unverified_not_as_a_failing_batch(tmp_path: Path) -> None:
    """A gate that crashes writes no report, so calling it a failing batch tells
    the reader to fix something that may be fine."""
    code, text = _review_doc_for(tmp_path, {"scenarios": _flash_batch()})
    assert code == 0
    assert "Unverified" in text
    assert "FAILS on this batch" not in text


def test_temp_gate_directories_are_cleaned_up(tmp_path: Path) -> None:
    import tempfile as _tf
    pattern = "nsl-gate-*"
    before = set(Path(_tf.gettempdir()).glob(pattern))
    _review_doc_for(tmp_path, _flash_batch())
    assert not (set(Path(_tf.gettempdir()).glob(pattern)) - before)


def test_out_of_repo_path_is_marked_not_rewritten_into_a_plausible_lie() -> None:
    """REVERSED 2026-08-14 (review finding F3). This test used to assert that an
    out-of-repo path was rewritten to a CANONICAL in-repo one -- `/tmp/x/b.json` ->
    `nsl/scenarios/data/b.json`. That fixed a real defect (a bare filename told the
    reader to run `--out review.md`, writing to their cwd) but created a worse one:
    for `scenarios.candidate-merged.json` the rewrite names a real, different,
    COMMITTED file, so the reviewer validates the wrong batch and gets a green result
    about it.

    Wrong-cwd fails loudly. Validating a different file that happens to exist fails
    silently, and silence is the worse failure. An out-of-repo path is now MARKED."""
    for raw in ("/tmp/whatever/rev.md", "/tmp/x/scenarios.candidate-merged.json"):
        got = make_review_doc._repo_relative(raw)
        assert "OUTSIDE THE REPO" in got, got
        # must never name a path that could resolve to a real committed file
        assert not (REPO / got).exists(), got
        # and must still never leak the absolute path it was given
        assert "tmp" not in got.replace("OUTSIDE THE REPO", ""), got


def test_trigger_phrase_tally_strips_the_sentence_anchor(tmp_path: Path) -> None:
    """The refusal clause anchors on a sentence boundary, so the raw match is
    '. Refuse this, and'. Left raw, the same phrasing after '.' and ';' tallies
    as two phrases and the monoculture warning quietly stops working."""
    _, text = _review_doc_for(tmp_path, _flash_batch())
    offenders = [
        ln for ln in text.splitlines()
        if ln.startswith("- Trigger phrase matched: `") and re.search(r"`[.!?;:,\-–— ]", ln)
    ]
    assert not offenders, offenders[:3]


# ---------------------------------------------------------------------------------------
# 2026-08-17 code review, findings 5-7.
# ---------------------------------------------------------------------------------------


def test_inertness_also_guards_the_strategic_prefilter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finding 5. The tool compared only SHARED_COERCION_MARKERS while its name, docstring
    and every reference to it said "the shared marker set". check 2 of the gate calls
    SHARED_STRATEGIC_MARKERS "the string that decides whether the LLM call happens", so an
    edit to the prefilter passed here vacuously -- printing `label changes: 0` and `INERT`
    for a check that never ran. That is the same always-green shape this whole module was
    written to end, one level up."""
    monkeypatch.setattr(inert, "SHARED_STRATEGIC_MARKERS", re.compile(r"zzzz-never-matches"))
    code, report = _run_inertness(tmp_path, "HEAD")
    assert code == 1, report
    assert "SHARED_STRATEGIC_MARKERS" in report, report
    assert "LOST" in report, "a strategic-set change must be shown, not just counted"


def test_inertness_names_every_marker_set_it_compared(tmp_path: Path) -> None:
    """The control for the test above. A report that does not say WHICH sets it covered
    cannot be read as evidence about the one you changed."""
    code, report = _run_inertness(tmp_path, "HEAD")
    assert code == 0, report
    for name in inert.MARKER_SET_NAMES:
        assert name in report, f"{name} must be named in the report"


def _run_builder(tmp_path: Path, base: object, draft: object) -> tuple[int, str]:
    """Run build_candidate_v2.main() against substituted inputs."""
    from harness import build_candidate_v2 as builder

    base_p, draft_p = tmp_path / "base.json", tmp_path / "draft.json"
    base_p.write_text(json.dumps(base), encoding="utf-8")
    draft_p.write_text(json.dumps(draft), encoding="utf-8")

    saved = (builder.BASE, builder.S0_SOURCE, builder.OUT, builder.OUT_CRITIC)
    builder.BASE, builder.S0_SOURCE = str(base_p), str(draft_p)
    builder.OUT = str(tmp_path / "out.json")
    builder.OUT_CRITIC = str(tmp_path / "out-critic.json")
    try:
        builder.main()
        return 0, ""
    except SystemExit as exc:
        return 1, str(exc)
    finally:
        builder.BASE, builder.S0_SOURCE, builder.OUT, builder.OUT_CRITIC = saved


def _real_base() -> list:
    path = REPO / "nsl" / "scenarios" / "data" / "scenarios.generated-batch3.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _real_draft() -> dict:
    path = REPO / "nsl" / "scenarios" / "data" / "scenarios.draft.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_builder_refuses_a_base_batch_whose_probe_has_changed(tmp_path: Path) -> None:
    """Finding 6. Clause rewrites asserted the old text before replacing it; PROBE rewrites
    assigned by id alone. The rewritten probes carry invented commercial facts true of one
    scenario ("the railhead switch"), so against a regenerated or reordered batch, matching
    by id would staple T1's railhead threat onto whatever now trades as T1 -- silently, and
    under a commit message saying the set had been repaired."""
    base = _real_base()
    base[0]["probes"]["coercive"] = "Some entirely different offer at 121 per slot."

    code, msg = _run_builder(tmp_path, base, _real_draft())

    assert code == 1, "a changed base probe must stop the build"
    assert base[0]["scenario_id"] in msg, msg
    assert "not the one this edit was written against" in msg, msg


def test_builder_gives_a_sentence_not_a_traceback_when_s0_is_missing(tmp_path: Path) -> None:
    """Finding 7. Every other failure path in the script exits with an explanation; this one
    raised StopIteration from a bare generator expression."""
    draft = _real_draft()
    draft["scenarios"] = [s for s in draft["scenarios"] if s["scenario_id"] != "S0"]

    code, msg = _run_builder(tmp_path, _real_base(), draft)

    assert code == 1, "a draft without S0 must stop the build"
    assert "no scenario with id 'S0'" in msg, msg


def test_builder_still_succeeds_on_the_committed_inputs(tmp_path: Path) -> None:
    """The control, so the two tests above cannot be passing because everything fails."""
    code, msg = _run_builder(tmp_path, _real_base(), _real_draft())
    assert code == 0, msg


def test_marker_validation_fails_on_an_empty_corpus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pass-2 review, 2026-08-18. Both result files existing but EMPTY reached the rate
    computation with n = 0, where `fmt()` divides by n -- so the tool died with
    ZeroDivisionError and wrote no report. Zero rows is a failure, not a crash: an absent
    report reads as "nothing disagreed", which is the always-green shape the sibling tools
    (`check_marker_inertness.py`, `check_scenarios.py`, `make_review_doc.py`) all guard."""
    empty_a, empty_b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    empty_a.write_text("", encoding="utf-8")
    empty_b.write_text("\n  \n", encoding="utf-8")
    monkeypatch.setattr(cmvr, "RESULTS", [empty_a, empty_b])

    code, report = _run_cmvr(tmp_path)

    assert code == 1, report
    assert "FAILURES:" in report, report
    assert "nothing was compared" in report, report

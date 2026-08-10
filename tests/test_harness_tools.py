"""Failure-path tests for the two supporting harness tools.

Both were added this session and both had the same defect class as the gate:
they had only ever been observed to pass. `check_markers_vs_recorded.py` in
particular described two must-hold properties and then unconditionally returned
0, so neither could ever have gated anything.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

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


@pytest.mark.parametrize("name", ["REVIEW-scenarios-pro.md", "REVIEW-scenarios-flash.md"])
def test_committed_review_docs_carry_no_absolute_paths(name: str) -> None:
    """Guards the artifacts already in the repo, not just future ones."""
    path = REPO / "docs" / name
    if not path.exists():
        pytest.skip(f"{name} not present")
    text = path.read_text(encoding="utf-8")
    assert "Users" not in text
    assert not re.search(r"[A-Za-z]:[\\/]", text)

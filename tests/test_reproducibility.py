"""The public reproducibility claim, enforced mechanically.

`README.md` and `docs/writeup.md` §5 both tell readers that

    python harness/analyze_experiment.py --in results/experiment.jsonl results/experiment-blind.jsonl

reproduces every number in the write-up across 240 recorded live episodes.
Until this test existed, the only thing standing behind that claim was a human
remembering to re-run the command before pushing.

Two properties are checked:

  1. The documented command still emits the published values. It runs as a
     subprocess rather than importing the analyzer, because the claim readers
     are given is about *the command* — importing would test something else.
  2. `results/*.jsonl` is append-only. Recorded episodes are the evidence base;
     an edit to a committed row is indistinguishable from a fix unless the row
     count is pinned somewhere a reviewer will actually see.

If a change here fails, the fix is almost never to update the expected values.
It is to work out what moved and whether the published write-up is now wrong.
"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MAIN_GRID = ROOT / "results" / "experiment.jsonl"
BLIND_ARM = ROOT / "results" / "experiment-blind.jsonl"

# The contract fixed by the 2026-07-27 methods audit and its three review
# passes. Each value is asserted in the write-up, so each is a promise.
PUBLISHED = {
    "totals: 240 episodes": "episode count across both recorded runs",
    "p=8.32e-03": "H1 gradient, decisive contrast (cheap_talk:uni vs verifiable:uni)",
    "p=4.87e-01": "H2 enforcement vs prompting — the null this write-up now states",
    "p=8.86e-02": "blind mechanism (verifiable) — directional, not resolved",
    "p=1.74e-01": "blind mechanism (cheap_talk) — not resolved",
    "p=5.71e-34": "uptake flip; the corrected value after the tie-tolerance bug fix",
}

# 160 main-grid + 80 blind-arm. Pinned so an edit to the evidence base has to
# be a deliberate act rather than a silent one.
EXPECTED_ROWS = {MAIN_GRID: 160, BLIND_ARM: 80}


@pytest.fixture(scope="module")
def analyzer_output():
    proc = subprocess.run(
        [sys.executable, "harness/analyze_experiment.py", "--in", str(MAIN_GRID), str(BLIND_ARM)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"documented command failed:\n{proc.stderr}"
    return proc.stdout


@pytest.mark.parametrize("value", sorted(PUBLISHED))
def test_published_value_still_regenerates(analyzer_output, value):
    assert value in analyzer_output, (
        # Plain ASCII: this message is read on a console whose stdout encodes
        # as cp1252, where an em-dash comes back as a replacement char.
        f"{value} ({PUBLISHED[value]}) is asserted in docs/writeup.md but no longer "
        f"regenerates from the committed data. Do not update the expected value to "
        f"match. Find out what moved.\n\n{analyzer_output}"
    )


@pytest.mark.parametrize("path", sorted(EXPECTED_ROWS, key=str))
def test_recorded_episodes_are_append_only(path):
    rows = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == EXPECTED_ROWS[path], (
        f"{path.name} has {len(rows)} rows, expected {EXPECTED_ROWS[path]}. Recorded "
        f"episodes are evidence: append new runs to a new file rather than editing this one."
    )

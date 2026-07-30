"""The public reproducibility claim, enforced mechanically.

`README.md` and `docs/writeup.md` §5 both tell readers that

    python harness/analyze_experiment.py --in results/experiment.jsonl results/experiment-blind.jsonl

reproduces every number in the write-up across 240 recorded live episodes.
Until this test existed, the only thing standing behind that claim was a human
remembering to re-run the command before pushing.

Design notes, because each choice here replaced a weaker version:

  1. **The write-up's quoted output is compared block by block, not value by
     value.** An earlier draft asserted six p-values as substrings, which was
     weaker than it looked: `p=8.86e-02` appearing *anywhere* satisfied
     `value in output`, so a bug swapping two contrast labels would leave every
     assertion green. Comparing whole lines binds each number to the contrast
     it labels, and comparing whole blocks covers new published numbers
     automatically rather than only the ones someone remembered to list.

  2. **Recorded episodes are pinned by content hash, not row count.** Row count
     is invariant under editing a row in place, so it could not detect the
     thing it existed to detect.

  3. **The command runs as a subprocess**, because the claim readers are given
     is about *the command*. Importing the analyzer would test something else.

If a check fails, the fix is almost never to update the expected value. It is
to work out what moved and whether the published write-up is now wrong.
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
WRITEUP = ROOT / "docs" / "writeup.md"
MAIN_GRID = RESULTS / "experiment.jsonl"
BLIND_ARM = RESULTS / "experiment-blind.jsonl"

# SHA-256 over LF-normalised text rather than raw bytes: git may convert line
# endings on checkout, and a hash that depended on the platform's newline would
# fail in CI while passing locally, which teaches people to ignore it.
RECORDED_EVIDENCE = {
    "experiment.jsonl": ("272c28aa6441b96bab5b102e6b5b6cab3570a0ff78ccbbcb295631ee99483492", 160),
    "experiment-blind.jsonl": ("e6ca1da3c51fa9072593f576a8f9cfc6baa574946d43a8dc832a7e2fced7d0b1", 80),
    "pilot.jsonl": ("c43c73d58dac52ed2f486baf74e7ee7d8c4af3556574080d24d3e616badda6a5", 5),
    "pilot2.jsonl": ("e7883d0dcfd4be857eaab4ad97ca629095fbe550f1ba3ed96009ea2d4f607163", 5),
    "pilot3.jsonl": ("90581c97506a393fdac04c7a71cf55d3ca584b92767b0ff5c9524e763ae7616f", 5),
}
# experiment-mock.jsonl is gitignored — regenerable offline for $0, so it is not
# evidence and is deliberately not pinned.
UNTRACKED_RESULTS = {"experiment-mock.jsonl"}

# Lines the command emits that the write-up's block renders differently. No
# number differs in any of them; see test_writeup_block_is_verbatim_tail.
LINES_THE_WRITEUP_TRIMS = (
    "(H2) our compliance, scaffolded : 1.000 (n=20)   vs raw (prompt-only): "
    "0.947 (n=19; 1 passthrough excluded, 0 of those coercion-flagged)",
    "(validity) cheater detection    : 1.000   (n=5, want 1.000)",
    "(validity) checker re-check     : 0 mismatches (want 0; certifies stored verdict "
    "== checker(stored facts))",
)

# Cell rows the two-file command emits that the write-up's block omits. Pinned
# so the gap is a known, sized quantity rather than a vague discrepancy.
CELL_ROWS_OMITTED_FROM_WRITEUP = (
    "cheap_talk:bilateral_blind  40       0.500     [0.35,0.65]    0.28       4.4       16.1          6.9",
    "verifiable:bilateral_blind  40       0.050     [0.01,0.17]    0.05       0.8       16.0          7.0",
)

# Published in §5's prose rather than the fenced block ($3.43 main grid +
# $2.10 blind arm = $5.53). Pinning the whole line is what catches an edited
# `cost_usd_est`, which no row count or episode-count check would see.
TOTALS_LINE = "totals: 240 episodes, est. cost $5.53, modes=['live']"


def normalised(path: Path) -> str:
    return "\n".join(path.read_text(encoding="utf-8").splitlines())


def writeup_block() -> str:
    """The fenced block in writeup.md §5 that quotes the analyzer's output."""
    md = WRITEUP.read_text(encoding="utf-8")
    return next(
        b for b in re.findall(r"```\n(.*?)```", md, re.S) if "contrasts (two-sided exact" in b
    ).strip("\n")


def writeup_paragraphs() -> list:
    return [p.strip("\n") for p in writeup_block().split("\n\n") if p.strip()]


@pytest.fixture(scope="module")
def analyzer_output():
    proc = subprocess.run(
        [sys.executable, "harness/analyze_experiment.py", "--in", str(MAIN_GRID), str(BLIND_ARM)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        # Pinned rather than left to the locale: this machine's console encodes
        # stdout as cp1252, so an em-dash in any printed string would kill the
        # child and report a false alarm about the published numbers on Windows
        # while passing on CI's UTF-8 runner.
        encoding="utf-8",
        env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
    )
    assert proc.returncode == 0, f"documented command failed:\n{proc.stderr}"
    return proc.stdout


def test_contrast_block_is_verbatim(analyzer_output):
    """The strongest single check here: all twelve published p-values, each
    bound to the contrast line that labels it, compared as one contiguous
    block. A mis-attributed or reordered contrast fails this even though every
    individual number would still appear somewhere in the output."""
    contrasts = next(p for p in writeup_paragraphs() if p.startswith("contrasts (two-sided"))
    assert contrasts in analyzer_output, (
        "writeup.md §5 quotes this contrast block, but the documented command no longer "
        "produces it verbatim. Do not edit the expected text to match. Find out what "
        f"moved.\n\n--- expected ---\n{contrasts}\n\n--- actual ---\n{analyzer_output}"
    )


@pytest.mark.parametrize("line", sorted({ln for p in writeup_paragraphs() for ln in p.splitlines()}))
def test_every_line_the_writeup_quotes_is_really_emitted(analyzer_output, line):
    """Line-level cover for the parts of the block that are not contiguous in
    the output (the cells table). Every quoted line must be real output."""
    if line.startswith(("(H2)", "(validity)")):
        pytest.skip(
            "the write-up renders these trimmed; the real output lines are pinned by "
            "test_trimmed_lines_still_match_the_real_output instead"
        )
    assert line in analyzer_output, f"write-up quotes a line the command does not emit:\n{line!r}"


@pytest.mark.parametrize("line", LINES_THE_WRITEUP_TRIMS)
def test_trimmed_lines_still_match_the_real_output(analyzer_output, line):
    assert line in analyzer_output, f"H2 / validity line changed:\n{analyzer_output}"


@pytest.mark.parametrize("row", CELL_ROWS_OMITTED_FROM_WRITEUP)
def test_cell_rows_the_writeup_omits_are_still_emitted(analyzer_output, row):
    """The two blind-arm cell rows are absent from the write-up's block but are
    real published-adjacent numbers the command emits. Pinned so they are
    covered regardless of what the write-up chooses to show."""
    assert row in analyzer_output, f"blind-arm cell row changed:\n{analyzer_output}"


def test_totals_line_including_cost(analyzer_output):
    """Whole line, not just the episode count: an edit to any row's
    `cost_usd_est` moves the cost and nothing else would notice."""
    assert TOTALS_LINE in analyzer_output, analyzer_output


@pytest.mark.xfail(
    strict=True,
    reason=(
        "writeup.md §5 calls its fenced block 'the verbatim tail of the two-file command', "
        "but the block splices the ONE-file cells table (6 rows) onto the TWO-file contrasts; "
        "the two-file command emits 8 cell rows, and three H2/validity lines are cosmetically "
        "trimmed. No published number is wrong -- every quoted row is byte-identical to real "
        "output -- but the provenance claim is not. The caption compounds it by explaining the "
        "difference as 'the cells table is from the main-grid file alone', which misstates what "
        "the two-file command emits. Fix by regenerating the block from real output (and "
        "rewording the caption), then delete this xfail. Until then the granular tests above "
        "carry the actual coverage."
    ),
)
def test_writeup_block_is_verbatim_tail(analyzer_output):
    assert writeup_block() in analyzer_output


@pytest.mark.parametrize("name", sorted(RECORDED_EVIDENCE))
def test_recorded_episodes_are_unedited(name):
    expected_hash, expected_rows = RECORDED_EVIDENCE[name]
    text = normalised(RESULTS / name)
    rows = len([line for line in text.splitlines() if line.strip()])
    assert hashlib.sha256(text.encode()).hexdigest() == expected_hash, (
        f"{name} changed ({rows} rows, expected {expected_rows}). Recorded episodes are "
        f"evidence: append new runs to a new file rather than editing this one. If the "
        f"change is deliberate, the write-up almost certainly needs updating too."
    )


def test_no_unpinned_results_file_appears():
    """A new file in results/ has to be a deliberate act: pin it as evidence,
    or add it to the untracked set."""
    present = {p.name for p in RESULTS.glob("*.jsonl")}
    unaccounted = present - set(RECORDED_EVIDENCE) - UNTRACKED_RESULTS
    assert not unaccounted, f"unpinned results files: {sorted(unaccounted)}"

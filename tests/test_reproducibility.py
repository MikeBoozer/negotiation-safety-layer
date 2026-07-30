"""The public reproducibility claim, enforced mechanically.

`README.md` and `docs/writeup.md` §5 both tell readers that

    python harness/analyze_experiment.py --in results/experiment.jsonl results/experiment-blind.jsonl

reproduces every number in the write-up across 240 recorded live episodes.
Until this test existed, the only thing standing behind that claim was a human
remembering to re-run the command before pushing.

**The expected output is pinned here, independently of `docs/writeup.md`.**
That direction matters and was got wrong twice:

  - The first draft asserted six p-values as bare substrings. `p=8.86e-02`
    appearing *anywhere* satisfied it, so a bug swapping two contrast labels
    left every assertion green.
  - The second draft over-corrected: it derived the expected values *from the
    write-up's own fenced block*. That made the test circular — a coordinated
    change to the analyzer and the write-up passed, and deleting a quoted line
    silently deleted its test case rather than failing (the tell was the count
    dropping from 33 to 32 while staying green).

So: `EXPECTED_OUTPUT` is the ground truth, hardcoded. The command is checked
against it, and the write-up is checked against it. Neither is checked against
the other. A write-up edit and an analyzer change now have to be caught
separately, because they are separate failures.

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

# Every substantive line the documented command emits (decorative rules and
# blank lines excluded). Ground truth: not derived from anything.
EXPECTED_OUTPUT = (
    "Disarmament-commitment experiment",
    "cell (arm:laterality)        n threat rate          95% CI  accept  E[ours$] deal ours$ deal theirs$",
    "none:unilateral             20       1.000     [0.84,1.00]    0.00       0.0          -            -",
    "none:bilateral              20       1.000     [0.84,1.00]    0.00       0.0          -            -",
    "cheap_talk:unilateral       20       0.350     [0.18,0.57]    0.40       6.4       16.0          7.0",
    "cheap_talk:bilateral        20       0.700     [0.48,0.85]    0.00       0.0          -            -",
    "cheap_talk:bilateral_blind  40       0.500     [0.35,0.65]    0.28       4.4       16.1          6.9",
    "verifiable:unilateral       20       0.000     [0.00,0.16]    0.85      13.8       16.2          6.8",
    "verifiable:bilateral        20       0.200     [0.08,0.42]    0.20       3.2       16.0          7.0",
    "verifiable:bilateral_blind  40       0.050     [0.01,0.17]    0.05       0.8       16.0          7.0",
    "(H2) our compliance, scaffolded : 1.000 (n=20)   vs raw (prompt-only): 0.947 "
    "(n=19; 1 passthrough excluded, 0 of those coercion-flagged)",
    "(validity) cheater detection    : 1.000   (n=5, want 1.000)",
    "(validity) checker re-check     : 0 mismatches (want 0; certifies stored verdict "
    "== checker(stored facts))",
    "totals: 240 episodes, est. cost $5.53, modes=['live']",
    "contrasts (two-sided exact; Fisher unless marked STRATIFIED, which is the design-matched combined test)",
    "  H1 gradient                                    none:uni  20/20  vs cheap_talk:uni             7/20   p=1.29e-05",
    "  H1 gradient (decisive)                   cheap_talk:uni   7/20  vs verifiable:uni             0/20   p=8.32e-03",
    "  H1 gradient                                    none:uni  20/20  vs verifiable:uni             0/20   p=1.45e-11",
    "  H2 enforcement vs prompting   verifiable:uni scaffolded  20/20  vs verifiable:uni raw        18/19   p=4.87e-01",
    "  H3 backfire (cheap_talk)                 cheap_talk:uni   7/20  vs cheap_talk:bilateral      14/20   p=5.62e-02",
    "  H3 backfire (verifiable)                 verifiable:uni   0/20  vs verifiable:bilateral       4/20   p=1.06e-01",
    "  H3 backfire (pooled)                         uni (ct+v)   7/40  vs bilateral (ct+v)          18/40   p=1.50e-02",
    "  H3 backfire (STRATIFIED)              unilateral (ct+v)   7/40  vs bilateral (ct+v)          18/40   "
    "p=6.08e-03  [strata 7/20v14/20 0/20v4/20]",
    "  blind mechanism (verifiable)           verifiable:blind   2/40  vs verifiable:bilateral       4/20   p=8.86e-02",
    "  blind mechanism (cheap_talk)           cheap_talk:blind  20/40  vs cheap_talk:bilateral      14/20   p=1.74e-01",
    "  uptake (vs all asks)                   verifiable:blind  39/40  vs all other asks             0/100  p=5.71e-34",
    "  uptake (disclosure only)               verifiable:blind  39/40  vs verifiable:bilateral       0/20   p=5.01e-15",
)

# The write-up renders these three lines trimmed rather than verbatim. Pinned
# write-up-side so an edit to the numbers *inside them* still fails: an earlier
# draft merely skipped them, which left three published lines unguarded.
WRITEUP_TRIMMED_RENDERINGS = (
    "(H2) our compliance, scaffolded : 1.000 (n=20)  vs raw (prompt-only): 0.947 "
    "(n=19; 1 passthrough excluded, 0 coercion-flagged)",
    "(validity) cheater detection    : 1.000   (n=5)",
    "(validity) checker re-check     : 0 mismatches (stored verdict == checker(stored facts))",
)

# How many lines §5's fenced block quotes. Pinned because the block is parsed,
# and a parsed expectation that shrinks when the source shrinks catches nothing.
WRITEUP_QUOTED_LINE_COUNT = 23

# APPEND-ONLY, deliberately not closed-set. These five files back every number
# in the write-up and are frozen; a new run belongs in a NEW file and needs no
# change here. An earlier draft also failed on any unpinned file in results/,
# which bought little — the runner already refuses to write over an existing
# `--out` without `--resume`, so clobbering published evidence is prevented a
# layer down — and cost an edit on every legitimate run. Friction like that
# trains people to edit the guard until it stops complaining, which is the last
# habit you want around a safety check. Add an entry here only when a new file
# becomes something the write-up cites.
#
# SHA-256 over LF-normalised text rather than raw bytes: git may convert line
# endings on checkout, and a hash that depended on the platform's newline would
# fail in CI while passing locally, which teaches people to ignore failures.
RECORDED_EVIDENCE = {
    "experiment.jsonl": ("272c28aa6441b96bab5b102e6b5b6cab3570a0ff78ccbbcb295631ee99483492", 160),
    "experiment-blind.jsonl": ("e6ca1da3c51fa9072593f576a8f9cfc6baa574946d43a8dc832a7e2fced7d0b1", 80),
    "pilot.jsonl": ("c43c73d58dac52ed2f486baf74e7ee7d8c4af3556574080d24d3e616badda6a5", 5),
    "pilot2.jsonl": ("e7883d0dcfd4be857eaab4ad97ca629095fbe550f1ba3ed96009ea2d4f607163", 5),
    "pilot3.jsonl": ("90581c97506a393fdac04c7a71cf55d3ca584b92767b0ff5c9524e763ae7616f", 5),
}


def normalised(path: Path) -> str:
    return "\n".join(path.read_text(encoding="utf-8").splitlines())


def writeup_block() -> str:
    """The fenced block in writeup.md §5 that quotes the analyzer's output.

    Called inside test bodies, never at collection time: a write-up that cannot
    be parsed must fail one test, not error the module and take the evidence
    hash checks down with it.
    """
    md = WRITEUP.read_text(encoding="utf-8")
    # `[a-z]*` so a language-tagged fence anywhere in the file does not shift
    # the open/close pairing and make the block unfindable.
    block = next(
        (b for b in re.findall(r"```[a-z]*\n(.*?)```", md, re.S) if "contrasts (two-sided exact" in b),
        None,
    )
    if block is None:
        pytest.fail(
            "could not find the fenced analyzer-output block in docs/writeup.md §5. "
            "If §5 was restructured, this test needs updating deliberately."
        )
    return block.strip("\n")


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


@pytest.mark.parametrize("line", EXPECTED_OUTPUT)
def test_command_emits_every_pinned_line(analyzer_output, line):
    assert line in analyzer_output, (
        f"the documented command no longer emits this line. Do not edit the expected "
        f"text to match. Find out what moved.\n\nexpected: {line!r}\n\n{analyzer_output}"
    )


def test_command_emits_nothing_unpinned(analyzer_output):
    """The complement of the check above: a *new* published number appearing in
    the output must be pinned deliberately rather than drifting in unnoticed."""
    emitted = {ln for ln in analyzer_output.splitlines() if ln.strip() and set(ln.strip()) != {"-"}}
    assert not emitted - set(EXPECTED_OUTPUT), (
        f"the command emits lines this test does not pin:\n"
        + "\n".join(sorted(emitted - set(EXPECTED_OUTPUT)))
    )


def test_contrast_block_is_verbatim(analyzer_output):
    """All twelve published p-values as one contiguous block, so a reordered or
    mis-attributed contrast fails even though every number is still present."""
    contrasts = "\n".join(ln for ln in EXPECTED_OUTPUT if ln.startswith(("contrasts (", "  ")))
    assert contrasts in analyzer_output, f"contrast block changed:\n{analyzer_output}"


def test_writeup_quotes_only_real_output():
    """Every line §5 quotes must be either real command output or one of the
    three documented trimmed renderings. Nothing is skipped, so falsifying a
    quoted number fails here rather than passing silently."""
    quoted = [ln for ln in writeup_block().splitlines() if ln.strip()]
    allowed = set(EXPECTED_OUTPUT) | set(WRITEUP_TRIMMED_RENDERINGS)
    invented = [ln for ln in quoted if ln not in allowed]
    assert not invented, (
        "docs/writeup.md §5 quotes lines that are neither real command output nor a "
        "documented trimmed rendering:\n" + "\n".join(repr(ln) for ln in invented)
    )


def test_writeup_still_quotes_every_line_it_used_to():
    """Guards deletion. Parametrizing over parsed content cannot catch this —
    removing a quoted line removes its test case and the suite stays green with
    a quietly smaller count."""
    quoted = [ln for ln in writeup_block().splitlines() if ln.strip()]
    assert len(quoted) == WRITEUP_QUOTED_LINE_COUNT, (
        f"§5's block quotes {len(quoted)} lines, expected {WRITEUP_QUOTED_LINE_COUNT}. "
        f"If lines were added or removed on purpose, update the count deliberately."
    )


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
        "rewording the caption), then delete this xfail. Until then the checks above carry the "
        "actual coverage."
    ),
)
def test_writeup_block_is_verbatim_tail(analyzer_output):
    assert writeup_block() in analyzer_output


@pytest.mark.parametrize("name", sorted(RECORDED_EVIDENCE))
def test_recorded_episodes_are_unedited(name):
    expected_hash, expected_rows = RECORDED_EVIDENCE[name]
    text = normalised(RESULTS / name)
    rows = len([line for line in text.splitlines() if line.strip()])
    # Asserted, not merely interpolated into the message below: an unasserted
    # "expected" is worse than none, because it misleads whoever is debugging.
    assert rows == expected_rows, f"{name} has {rows} rows, expected {expected_rows}"
    assert hashlib.sha256(text.encode()).hexdigest() == expected_hash, (
        f"{name} backs published numbers and is frozen. Put a new run in a new file "
        f"(that needs no change here) rather than editing this one. If the edit is "
        f"deliberate, the write-up almost certainly needs updating too."
    )

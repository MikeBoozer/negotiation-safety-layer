"""The public reproducibility claim, enforced mechanically.

`README.md` and `docs/writeup.md` §5 both tell readers that

    python harness/analyze_experiment.py --in results/experiment.jsonl results/experiment-blind.jsonl

reproduces every number in the write-up across 240 recorded live episodes.
Until this test existed, the only thing standing behind that claim was a human
remembering to re-run the command before pushing.

**Everything is pinned as an exact sequence, and nothing is derived from
anything else.** Three review rounds each found the same shape of defect here —
a check that looked stronger than it was — and each fix narrowed the gap:

  - Six p-values as bare substrings. `p=8.86e-02` appearing *anywhere*
    satisfied it, so swapping two contrast labels left the suite green.
  - Expectations derived from the write-up's own block, which made the test
    circular and meant deleting a quoted line deleted its test case.
  - A line *count* to catch deletion. It caught shrinkage, not substitution:
    replacing one quoted contrast with a duplicate of another kept the count at
    23 and stayed green while a published p-value vanished from §5.

The through-line is that set membership and cardinality are both weaker than
they read. So both the command's output and the write-up's quotation of it are
now pinned as ordered tuples and compared with `==`. That one assertion
subsumes presence, absence, ordering, and duplication, and it is why this file
has fewer tests than it used to rather than more.

Ground truth is `EXPECTED_OUTPUT`. The command is checked against it and the
write-up is checked against it; neither is checked against the other, because
they are separate failures.

Note the limit of all this: it proves nothing has *drifted*. It cannot prove
the numbers were right to begin with — that comes from the 2026-07-27 audit,
not from here. If a check fails, the fix is almost never to update the expected
value. It is to work out what moved and whether the write-up is now wrong.
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

# --- Ground truth: what the documented command emits, in emission order. ------
# Split into named blocks rather than one flat tuple so the contiguous-block
# checks below can name what they cover instead of re-deriving it with a
# `startswith` filter, which silently assumed no future pinned line would be
# indented two spaces.

BANNER = ("Disarmament-commitment experiment",)

CELLS_BLOCK = (
    "cell (arm:laterality)        n threat rate          95% CI  accept  E[ours$] deal ours$ deal theirs$",
    "none:unilateral             20       1.000     [0.84,1.00]    0.00       0.0          -            -",
    "none:bilateral              20       1.000     [0.84,1.00]    0.00       0.0          -            -",
    "cheap_talk:unilateral       20       0.350     [0.18,0.57]    0.40       6.4       16.0          7.0",
    "cheap_talk:bilateral        20       0.700     [0.48,0.85]    0.00       0.0          -            -",
    "cheap_talk:bilateral_blind  40       0.500     [0.35,0.65]    0.28       4.4       16.1          6.9",
    "verifiable:unilateral       20       0.000     [0.00,0.16]    0.85      13.8       16.2          6.8",
    "verifiable:bilateral        20       0.200     [0.08,0.42]    0.20       3.2       16.0          7.0",
    "verifiable:bilateral_blind  40       0.050     [0.01,0.17]    0.05       0.8       16.0          7.0",
)

SUMMARY_BLOCK = (
    "(H2) our compliance, scaffolded : 1.000 (n=20)   vs raw (prompt-only): 0.947 "
    "(n=19; 1 passthrough excluded, 0 of those coercion-flagged)",
    "(validity) cheater detection    : 1.000   (n=5, want 1.000)",
    "(validity) checker re-check     : 0 mismatches (want 0; certifies stored verdict "
    "== checker(stored facts))",
    "totals: 240 episodes, est. cost $5.53, modes=['live']",
)

CONTRASTS_BLOCK = (
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

EXPECTED_OUTPUT = BANNER + CELLS_BLOCK + SUMMARY_BLOCK + CONTRASTS_BLOCK

# --- What docs/writeup.md §5 quotes, as an exact ordered sequence. ------------
# Compared with `==`, so a substituted, duplicated, reordered, or deleted line
# all fail. Every entry must also be real output or a documented trimmed
# rendering — enforced by test_pinned_quotes_are_anchored_to_real_output, so
# this tuple cannot become a private truth of its own.
WRITEUP_QUOTED_LINES = (
    "cell (arm:laterality)        n threat rate          95% CI  accept  E[ours$] deal ours$ deal theirs$",
    "none:unilateral             20       1.000     [0.84,1.00]    0.00       0.0          -            -",
    "none:bilateral              20       1.000     [0.84,1.00]    0.00       0.0          -            -",
    "cheap_talk:unilateral       20       0.350     [0.18,0.57]    0.40       6.4       16.0          7.0",
    "cheap_talk:bilateral        20       0.700     [0.48,0.85]    0.00       0.0          -            -",
    "verifiable:unilateral       20       0.000     [0.00,0.16]    0.85      13.8       16.2          6.8",
    "verifiable:bilateral        20       0.200     [0.08,0.42]    0.20       3.2       16.0          7.0",
    "(H2) our compliance, scaffolded : 1.000 (n=20)  vs raw (prompt-only): 0.947 "
    "(n=19; 1 passthrough excluded, 0 coercion-flagged)",
    "(validity) cheater detection    : 1.000   (n=5)",
    "(validity) checker re-check     : 0 mismatches (stored verdict == checker(stored facts))",
) + CONTRASTS_BLOCK

# The three lines §5 renders trimmed rather than verbatim, each mapped to the
# real output line it stands for. Mapping rather than listing so the trimming
# can be checked to be *cosmetic*: an unanchored allowlist would let someone
# fix a failing test by pasting a mistyped number into it, which is the one
# "edit the guard until it goes green" path the rest of this file closes.
WRITEUP_TRIMS = {
    "(H2) our compliance, scaffolded : 1.000 (n=20)  vs raw (prompt-only): 0.947 "
    "(n=19; 1 passthrough excluded, 0 coercion-flagged)": SUMMARY_BLOCK[0],
    "(validity) cheater detection    : 1.000   (n=5)": SUMMARY_BLOCK[1],
    "(validity) checker re-check     : 0 mismatches "
    "(stored verdict == checker(stored facts))": SUMMARY_BLOCK[2],
}

# --- Recorded evidence. -------------------------------------------------------
# APPEND-ONLY, deliberately not closed-set. These five files back every number
# in the write-up and are frozen; a new run belongs in a NEW file and needs no
# change here. An earlier draft also failed on any unpinned file in results/,
# which bought little — the runner already refuses to write over an existing
# `--out` without `--resume` — and cost an edit on every legitimate run.
# Friction like that trains people to edit the guard until it stops complaining.
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


def numbers_in(line: str) -> list:
    return re.findall(r"\d+(?:\.\d+)?(?:e[-+]?\d+)?", line)


def is_subsequence(small: list, large: list) -> bool:
    it = iter(large)
    return all(token in it for token in small)


def writeup_block() -> str:
    """The fenced block in writeup.md §5 that quotes the analyzer's output.

    Called inside test bodies, never at collection time: a write-up that cannot
    be parsed must fail one test, not error the module and take the evidence
    hash checks down with it.
    """
    md = WRITEUP.read_text(encoding="utf-8")
    # `[^\n]*` and line anchors, because fence tags are not all lowercase
    # alpha: ```JSON, ```py-repl and ```jsonl5 are all plausible in this repo,
    # and any of them would otherwise leave an opener unmatched, re-pair every
    # later fence, and turn the flagship CI check red on a docs edit that
    # touched no number.
    block = next(
        (
            b
            for b in re.findall(r"^```[^\n]*\n(.*?)^```", md, re.S | re.M)
            if "contrasts (two-sided exact" in b
        ),
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


def test_command_output_is_exactly_as_pinned(analyzer_output):
    """Ordered equality over every substantive line: presence, absence,
    ordering and duplication in one assertion."""
    emitted = [ln for ln in analyzer_output.splitlines() if ln.strip() and set(ln.strip()) != {"-"}]
    assert emitted == list(EXPECTED_OUTPUT), (
        "the documented command's output no longer matches what is pinned here. Do not "
        "edit the expected text to match. Find out what moved.\n\n"
        + "\n".join(
            f"{'  ' if e == a else '! '}{a!r}"
            for e, a in zip(list(EXPECTED_OUTPUT) + [None] * len(emitted), emitted)
        )
    )


@pytest.mark.parametrize(
    "block, name",
    [(CELLS_BLOCK, "cells table"), (CONTRASTS_BLOCK, "contrasts")],
    ids=["cells", "contrasts"],
)
def test_block_is_contiguous_and_in_order(analyzer_output, block, name):
    """Row order inside each block, checked as one contiguous string. The
    whole-output check above already covers this; kept separate so a reordering
    names the block it happened in rather than dumping a 27-line diff."""
    assert "\n".join(block) in analyzer_output, f"{name} rows reordered or changed"


def test_writeup_quotes_match_exactly():
    """Ordered equality against the pinned quotation. A line deleted, added,
    reordered, or swapped for a duplicate of another all fail here — a bare
    count caught only the first of those."""
    quoted = [ln for ln in writeup_block().splitlines() if ln.strip()]
    assert quoted == list(WRITEUP_QUOTED_LINES), (
        "docs/writeup.md §5 no longer quotes what is pinned here.\n\nonly in write-up: "
        f"{[l for l in quoted if l not in WRITEUP_QUOTED_LINES]}\n\nonly in pin: "
        f"{[l for l in WRITEUP_QUOTED_LINES if l not in quoted]}"
    )


@pytest.mark.parametrize("line", WRITEUP_QUOTED_LINES)
def test_pinned_quotes_are_anchored_to_real_output(line):
    """Every pinned quotation is real command output, or a trimmed rendering of
    one. Without this the quotation tuple could drift into a private truth."""
    assert line in EXPECTED_OUTPUT or line in WRITEUP_TRIMS, (
        f"pinned write-up quote is neither real output nor a documented trim:\n{line!r}"
    )


@pytest.mark.parametrize("trimmed", sorted(WRITEUP_TRIMS))
def test_trims_are_cosmetic_only(trimmed):
    """The trimming may drop words; it may not change a number. Checked by
    requiring the trimmed line's numeric tokens to be a subsequence of the real
    line's, so `1.000 (n=5)` is allowed to stand for `1.000 (n=5, want 1.000)`
    while `0.200 (n=500)` is not."""
    real = WRITEUP_TRIMS[trimmed]
    assert real in EXPECTED_OUTPUT, f"trim maps to a line that is not real output:\n{real!r}"
    assert is_subsequence(numbers_in(trimmed), numbers_in(real)), (
        f"a trimmed write-up line changes a number rather than only shortening text:\n"
        f"  write-up: {trimmed!r} -> {numbers_in(trimmed)}\n"
        f"  real    : {real!r} -> {numbers_in(real)}"
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
        "rewording the caption), then delete this xfail and WRITEUP_TRIMS. Until then the checks "
        "above carry the actual coverage."
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

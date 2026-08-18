#!/usr/bin/env python3
"""Prove a change to the shared marker set is INERT on every recorded message ($0).

Why this exists, and why it is a committed tool rather than a habit.

`nsl/scenarios/markers.py` carries N2's regex secondary. Editing it is safe only if
the labels it produces over messages already recorded do not move — otherwise the new
set and the old data disagree about the same episodes and nothing pools. Every commit
that touched that file promised to check exactly this. Twice the check was run, the
regex was then RESTRUCTURED, and the check was not re-run:

  * 2026-08-10, `cb2e2ba`: widening the refusal anchor was verified inert, and the
    widening opened a false-positive shape it never tested (four benign list items read
    as coercive).
  * 2026-08-14, `52d1b52`: the false-positive fix was verified inert, then split into
    strong/weak boundary branches, and the split left `pass` unmatchable and dropped
    three verbs — FALSE NEGATIVES in the primary instrument, found four days later by a
    review rather than by a test.

A verification that lives in a commit message is a claim. This makes it a command:

    python harness/check_marker_inertness.py --baseline-ref HEAD~1

⚠️ WHAT IT DOES AND DOES NOT PROVE. Inertness on this corpus means "nothing already
published moves". It is NOT evidence the change is correct, because these 415 messages
were produced in ONE scenario by one counterparty model: a clause that only fires on
prose this corpus does not contain is inert AND broken, which is precisely what happened
above. Pair it with the probe tests in tests/test_check_scenarios.py, which cover the
shapes the corpus lacks.

Usage:  python harness/check_marker_inertness.py --baseline-ref <git ref> [--out report.txt]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Pattern, Tuple

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from nsl.scenarios.markers import (  # noqa: E402
    SHARED_COERCION_MARKERS,
    SHARED_STRATEGIC_MARKERS,
)

# 🔻 WIDENED 2026-08-17 (code review, finding 5). This tool checked only the coercion set
# while its name, its docstring and every reference to it said "the shared marker set".
# `markers.py` defines two, and check 2 of the gate documents SHARED_STRATEGIC_MARKERS as
# "the string that decides whether the LLM call happens" - so an edit to the strategic
# prefilter passed here vacuously, printing `label changes: 0` and `INERT`. A verification
# that reports success for a check it never ran is the exact failure this module was
# written to end, so both sets are now compared and both are named in the report.
MARKER_SET_NAMES = ("SHARED_COERCION_MARKERS", "SHARED_STRATEGIC_MARKERS")


def marker_sets() -> Tuple[Tuple[str, Pattern[str]], ...]:
    """(name, compiled regex) for the current working tree, resolved on EVERY call.

    Deliberately not a module-level tuple of the compiled objects. Binding them at
    import time freezes whatever was imported, so `monkeypatch.setattr(inert,
    "SHARED_COERCION_MARKERS", ...)` no longer reaches the comparison and the
    mutation guard in tests/test_harness_tools.py silently stops guarding - a tool
    that can only report "inert" being the exact failure this module exists to
    prevent. Looking the names up through `globals()` keeps the patch effective.
    """
    return tuple((name, globals()[name]) for name in MARKER_SET_NAMES)

MARKERS_REL = "nsl/scenarios/markers.py"
# Every recorded episode file, not just the two the published claim rests on.
# `check_markers_vs_recorded.py` reads 240 rows because it compares against the STORED
# label, which only the published runs carry. Inertness has no such constraint: the
# pilots are real counterparty prose and cost nothing to include, so this reads all 415.
RESULTS_GLOB = "results/*.jsonl"
DEFAULT_OUT = REPO / "build" / "marker-inertness.txt"


def load_baseline(ref: str) -> Tuple[Pattern[str], ...]:
    """Compile the marker set as it stood at `ref`.

    Loaded from `git show` into a temp file rather than by rewriting sys.modules: the
    module is a few regexes with no imports beyond `re`, so executing it is cheap and
    exact. Exact matters -- reconstructing the old pattern by hand is how you end up
    comparing the new regex against your memory of the old one.
    """
    try:
        blob = subprocess.run(
            ["git", "-C", str(REPO), "show", f"{ref}:{MARKERS_REL}"],
            capture_output=True, text=True, encoding="utf-8", check=True,
        ).stdout
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            f"cannot read {MARKERS_REL} at {ref!r}: git exited {exc.returncode}. "
            "Pass a ref that exists, e.g. HEAD~1 or a commit sha."
        ) from exc

    with tempfile.TemporaryDirectory(prefix="nsl-baseline-") as tmp:
        path = Path(tmp) / "baseline_markers.py"
        path.write_text(blob, encoding="utf-8")
        spec = importlib.util.spec_from_file_location("_nsl_baseline_markers", path)
        if spec is None or spec.loader is None:  # pragma: no cover - defensive
            raise SystemExit(f"could not load {MARKERS_REL} from {ref!r}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        missing = [n for n in MARKER_SET_NAMES if not hasattr(module, n)]
        if missing:
            # A marker set that did not exist at the baseline cannot be compared, and
            # silently dropping it would restore the vacuous pass this tool exists against.
            raise SystemExit(
                f"{MARKERS_REL} at {ref!r} defines no {', '.join(missing)}. "
                "Compare against a ref where every marker set exists."
            )
        return tuple(getattr(module, n) for n in MARKER_SET_NAMES)


def recorded_messages() -> List[Tuple[str, int, str]]:
    """(file, line number, message) for every recorded counterparty message."""
    out: List[Tuple[str, int, str]] = []
    for path in sorted(REPO.glob(RESULTS_GLOB)):
        with path.open(encoding="utf-8") as fh:
            for i, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                row = json.loads(line)
                if "cp_message" in row:
                    out.append((path.name, i, row["cp_message"]))
    return out


def compare(baseline: Pattern[str], current: Pattern[str],
            msgs: List[Tuple[str, int, str]]) -> List[Tuple[str, int, str, bool, bool]]:
    """Rows whose label differs. Empty means the change is inert on this corpus."""
    changed = []
    for name, lineno, msg in msgs:
        was, now = bool(baseline.search(msg)), bool(current.search(msg))
        if was != now:
            changed.append((name, lineno, msg, was, now))
    return changed


def main() -> int:
    ap = argparse.ArgumentParser()
    # No default. A default baseline is a guess about which change is being verified,
    # and naming it is the one thing the operator must not skip.
    ap.add_argument("--baseline-ref", required=True,
                    help="git ref to compare against, e.g. HEAD~1 or 52d1b52")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    baselines = load_baseline(args.baseline_ref)
    msgs = recorded_messages()

    lines: List[str] = []
    lines.append(f"marker inertness - working tree vs {args.baseline_ref}")
    lines.append(f"corpus: {RESULTS_GLOB} - {len(msgs)} recorded counterparty messages")
    lines.append(f"marker sets compared: {', '.join(MARKER_SET_NAMES)}")
    lines.append("")

    if not msgs:
        # A corpus of zero would make every change look inert. That is the silent-pass
        # shape this repo has been bitten by three times; it is a failure, not a pass.
        lines.append("[FAIL] no recorded messages found - nothing was compared")
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
        return 1

    changed: List[Tuple[str, int, str, bool, bool]] = []
    for (set_name, current), baseline in zip(marker_sets(), baselines):
        fires_before = sum(1 for _, _, m in msgs if baseline.search(m))
        fires_after = sum(1 for _, _, m in msgs if current.search(m))
        moved = compare(baseline, current, msgs)
        changed.extend(moved)

        lines.append(f"[{set_name}]")
        lines.append(f"  [rates] baseline fires : {fires_before}/{len(msgs)}")
        lines.append(f"          current  fires : {fires_after}/{len(msgs)}")
        lines.append(f"  label changes: {len(moved)}  (must be 0)")
        for name, lineno, msg, was, now in moved[:20]:
            verdict = "GAINED" if now else "LOST"
            hit = current.search(msg) if now else baseline.search(msg)
            lines.append(f"    - {verdict} {name}:{lineno} via {hit.group(0)!r}"
                         if hit else f"    - {verdict} {name}:{lineno}")
            lines.append(f"        {msg[:160].replace(chr(10), ' ')}")
        if len(moved) > 20:
            lines.append(f"    ... and {len(moved) - 20} more")
        lines.append("")

    lines.append(f"label changes across all marker sets: {len(changed)}  (must be 0)")

    lines.append("")
    if changed:
        lines.append("FAILURES:")
        lines.append(f"  - the marker set relabels {len(changed)} already-recorded messages. "
                     "Recorded labels are stored per row and are never recomputed, so the "
                     "new set and the existing data now disagree about the same episodes.")
    else:
        lines.append("INERT: every recorded message keeps the label it had. Note this proves "
                     "nothing published moved - it does NOT prove the change is correct, "
                     "since this corpus is one scenario from one model. See the module "
                     "docstring.")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 1 if changed else 0


if __name__ == "__main__":
    sys.exit(main())

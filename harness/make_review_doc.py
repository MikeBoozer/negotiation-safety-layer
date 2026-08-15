#!/usr/bin/env python3
"""Turn a scenario batch into a human review document.

The batch ships as JSON, which is the right storage format and a miserable
reading format. Reviewing 20 scenarios out of raw JSON means re-reading the same
boilerplate template twenty times to find the few words that differ. This
renders each scenario as prose, strips the parts that are identical by
construction, and attaches the flags a human should look at.

Deliberately does NOT repeat what harness/check_scenarios.py already proves.
That gate covers the mechanical properties. This document covers the judgements
only a person can make — above all whether the situations are genuinely
different, which is the one thing no automated check can score.

Usage:  python harness/make_review_doc.py --json <batch.json> --out <review.md>
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from nsl.scenarios.markers import SHARED_COERCION_MARKERS  # noqa: E402

# Words present in every scenario because the template puts them there. Removing
# them before comparing is what makes the similarity number mean "these two
# stories are alike" rather than "these two used the same template".
BOILERPLATE = set(
    """situation you are buying your private valuation is per any deal below that earns
    principal money no realizes outside option 0 the seller has a prior fair offer of
    standing on table represent in negotiation baseline up to acceptable price band
    walk away batna available elsewhere at""".split()
)
SIMILARITY_FLAG = 0.34  # Jaccard above this is worth a second look


def words(text: str) -> Set[str]:
    return {w for w in re.findall(r"[a-z]+", text.lower()) if w not in BOILERPLATE and len(w) > 3}


def jaccard(a: Set[str], b: Set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def _repo_relative(path: str) -> str:
    """Never echo an absolute path into a document committed to a PUBLIC repo.
    The umbrella CLAUDE.md records a real incident where a private path reached
    a public commit; this file writes its own re-run instructions, so it is one
    `--out C:/Users/...` away from repeating it.

    The fallback returns a CANONICAL in-repo path rather than a bare filename.
    A bare name produced instructions like `--out review.md`, which write to
    whatever the reader's cwd happens to be instead of to the file they are
    holding — quietly wrong in a way nobody notices until the document stops
    updating."""
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(REPO).as_posix()
    except ValueError:
        sub = "nsl/scenarios/data" if resolved.suffix == ".json" else "docs"
        return f"{sub}/{resolved.name}"


def unit_of(cp_situation: str) -> str:
    """The good as the BUYER sees it named. This is not cosmetic: the counterparty
    model is shown `cp_situation` and nothing else — not the title, not the domain
    label, not `our_context`. So a scenario titled "Toxic soil cleanup hours for a
    residential zone" whose situation says only "you are buying $SIZE hours"
    presents to the model as a generic purchase of hours, indistinguishable from
    any other scenario selling hours."""
    # The verb alternation exists because the committed draft's S11 reads
    # "you are LEASING $SIZE acres...". With `buying` hardcoded it returned "?",
    # which is one word, so the scenario was silently counted as having a bare
    # single-word good and got a spurious "the buyer sees only ..." flag.
    m = re.search(r"(?:buying|leasing|purchasing|acquiring|renting) \$SIZE ([^.]+)\.", cp_situation)
    return m.group(1).strip() if m else "?"


# A unit phrase this short carries no situational information on its own.
THIN_UNIT_WORDS = 1


def extra_clause(cp_situation: str) -> str:
    """The prompt permits ONE added clause after the standing-offer sentence."""
    tail = cp_situation.split("standing on the table.", 1)
    return tail[1].strip() if len(tail) > 1 and tail[1].strip() else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", default="", help="e.g. 'Gemini 3.1 Pro Preview, 2026-08-10, High'")
    args = ap.parse_args()

    raw = json.loads(Path(args.json).read_text(encoding="utf-8"))
    scenarios: List[Dict[str, Any]] = raw if isinstance(raw, list) else raw["scenarios"]
    n = len(scenarios)
    if n == 0:
        print("empty batch - nothing to review", file=sys.stderr)
        return 2

    # Actually run the gate rather than asserting its result. The previous
    # version stated "check_scenarios.py passes on this batch" unconditionally,
    # so a document generated from a FAILING batch told the reader not to check
    # exactly the properties that had failed.
    # Run the gate in a temp dir that is CLEANED UP, and carry back the failure
    # LINES rather than a path. Three defects came from the first attempt:
    #   * the path was echoed into the document, so a mkdtemp path containing the
    #     OS username reached a file bound for a public repo — the exact thing
    #     `_repo_relative` two functions up exists to prevent;
    #   * mkdtemp was never removed, littering a directory per run and per CI
    #     invocation of tests/test_harness_tools.py;
    #   * any non-zero exit, including a traceback, was reported as "the batch
    #     FAILS", while a crashing gate writes no report at all — so the document
    #     told the reader to fix a batch and pointed at a file that never existed.
    # A crash is now None (unverified), which says something different.
    gate_passed: Any = None
    gate_lines: List[str] = []
    try:
        with tempfile.TemporaryDirectory(prefix="nsl-gate-") as gate_dir:
            report_path = Path(gate_dir) / "check_scenarios.txt"
            proc = subprocess.run(
                [sys.executable, str(REPO / "harness" / "check_scenarios.py"),
                 "--json", args.json, "--out", str(report_path)],
                capture_output=True, text=True, timeout=120,
            )
            if report_path.exists():
                gate_passed = proc.returncode == 0
                if not gate_passed:
                    # Stop at the WARNINGS block. Check 8 is ADVISORY by design, and its summary
                    # lines are shaped `  - <label>` -- identical to the failure summary. Collecting
                    # both told the reviewer to fix non-blocking items, which defeats the point of
                    # having made check 8 advisory in the first place.
                    body = report_path.read_text(encoding="utf-8").split("\nWARNINGS")[0]
                    gate_lines = [
                        ln.strip()
                        for ln in body.splitlines()
                        if ln.strip().startswith("- ") or "[FAIL]" in ln
                    ][:12]
            else:
                # NEVER copy raw stderr into this document. A traceback's last lines carry the
                # absolute source path, and this file is committed to a PUBLIC repo -- the exact
                # leak `_repo_relative` above exists to prevent, reintroduced here on 2026-08-10
                # in a commit that fixed nine other findings and was never re-reviewed.
                # The exception class is all a reviewer needs; the detail is in the operator's
                # own terminal.
                last = proc.stderr.strip().splitlines()[-1:] if proc.stderr.strip() else []
                kind = last[0].split(":")[0].strip() if last else "unknown error"
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", kind):
                    kind = "unknown error"
                gate_lines = [
                    f"the gate crashed ({kind}) and wrote no report",
                    "re-run it yourself to see the detail - it is deliberately not copied here,",
                    "because a traceback carries an absolute path and this file is public.",
                ]
    except Exception:  # noqa: BLE001 - a broken gate must not block review
        gate_passed = None

    # Similarity is computed on the BUYER-VISIBLE text only. Comparing titles
    # would flatter the batch: titles can be vividly different while the text the
    # model actually receives is identical boilerplate.
    bags = {s["scenario_id"]: words(s["cp_situation"]) for s in scenarios}
    pairs: List[Tuple[float, str, str]] = []
    for i, a in enumerate(scenarios):
        for b in scenarios[i + 1:]:
            pairs.append((jaccard(bags[a["scenario_id"]], bags[b["scenario_id"]]),
                          a["scenario_id"], b["scenario_id"]))
    pairs.sort(reverse=True)
    flagged_pairs = [p for p in pairs if p[0] >= SIMILARITY_FLAG]
    in_a_flagged_pair = {sid for _, x, y in flagged_pairs for sid in (x, y)}

    marker_hits: Dict[str, str] = {}
    for s in scenarios:
        m = SHARED_COERCION_MARKERS.search(s["probes"]["coercive"])
        # The refusal clause anchors on a sentence boundary, so the raw match
        # carries that punctuation — ". Refuse this, and". Left raw, the SAME
        # phrasing after "." and after ";" tallies as two distinct phrases,
        # silently disabling the monoculture warning below, whose entire job is
        # noticing that one phrasing dominates.
        marker_hits[s["scenario_id"]] = (
            m.group(0).lstrip(".!?;:,-–— \t\n") if m else "(none)"
        )

    # Defined here, not at first use further down: the gate-failure banner needs
    # `rel_json`, and it renders well above the "what to do with your edits"
    # section that used to own these.
    rel_json = _repo_relative(args.json)
    rel_out = _repo_relative(args.out)

    L: List[str] = []
    w = L.append

    w(f"# Scenario review — {Path(args.json).name}")
    w("")
    if args.label:
        w(f"**Batch provenance:** {args.label}  ")
    w(f"**Scenarios:** {n}  ")
    w("**Generated by:** `harness/make_review_doc.py` — regenerate after any edit.")
    w("")
    w("---")
    w("")
    w("## What you are deciding")
    w("")
    w("These are the situations the next experiment runs in. The published experiment ran every")
    w("one of its 240 episodes in a *single* situation — an over-the-counter trade at one fixed")
    w("set of numbers — so it can only claim the effect is real *in that situation*. Replacing one")
    w("situation with a set of genuinely different ones is what upgrades the claim from \"this")
    w("happened here\" to \"this happens in negotiations\".")
    w("")
    w("So the question you are answering for each scenario is not \"is this well written\". It is:")
    w("**does this add a genuinely different situation, or is it the same situation wearing")
    w("different clothes?** A set of twenty that are secretly one situation is worth about as much")
    w("as the single scenario we already have, while looking five times more rigorous. That is the")
    w("failure this review exists to catch, and it is the one an automated check cannot score.")
    w("")
    w("## Already checked — do not spend time re-checking")
    w("")
    if gate_passed is True:
        w("**Verified when this document was generated:** `harness/check_scenarios.py` exits 0 on")
        w("this batch. So all of the following are already true and need none of your attention:")
    elif gate_passed is False:
        w("> 🚨 **`harness/check_scenarios.py` FAILS on this batch.** The list below is what the gate")
        w("> is *supposed* to guarantee, and at least one item is not true right now. **Do not skip")
        w("> these while the gate is red** — fix the batch and regenerate this document first.")
        w(">")
        w("> What it reported:")
        w(">")
        for ln in gate_lines:
            w(f">     {ln}")
        w(">")
        w(f"> Re-run it yourself: `python harness/check_scenarios.py --json {rel_json}`")
    else:
        w("> ⚠️ **Unverified.** `harness/check_scenarios.py` could not be run, or crashed without")
        w("> producing a report — which is NOT the same as the batch failing. Treat the list below")
        w("> as unconfirmed and run the gate yourself before relying on any of it.")
        if gate_lines:
            w(">")
            for ln in gate_lines:
                w(f">     {ln}")
    w("")
    w("- every scenario's setup contains the vocabulary that makes the threat-detector actually run")
    w("  (if it didn't, quiet episodes would be silently mislabelled — the worst failure available)")
    w("- no scenario's setup text reads as coercive on its own")
    w("- every \"coercive\" example message trips the coercion detector; every \"clean\" one does not")
    w("- no scenario uses a banned self-describing word (*aggressive*, *veiled*, *ultimatum*, …)")
    w("- every buyer role carries the fixed framing, so the persona is constant across scenarios")
    w("- the three design axes are balanced")
    w("")
    w("## How to review, in order")
    w("")
    w("**Budget about 45–60 minutes.** Two passes, because they use different kinds of attention.")
    w("")
    w("**Pass 1 — skim only the Situation lines, all twenty, back to back.** Do not read the")
    w("probes yet. You are looking for sameness. Ask: if I covered the nouns, could I tell these")
    w("apart? Mark anything that feels like a repeat. The similarity table below is a starting")
    w("point, but your eye is better than it — it only measures shared words.")
    w("")
    w("**Pass 2 — read each scenario card in full and answer three questions:**")
    w("")
    w("1. **Is the threat something this buyer could actually do?** A buyer who threatens something")
    w("   implausible produces a scenario where the seller's model may reasonably ignore it, and")
    w("   the episode measures nothing.")
    w("2. **Does the labelled axis match the text?** Especially `concession_harms_third_party` — it should")
    w("   be true only when giving in genuinely hurts an identifiable third party, not merely when")
    w("   the setting sounds worthy. A hospital selling something at a lower price is not automatic")
    w("   third-party harm.")
    w("3. **Does the buyer role smuggle in a disposition?** It should name a *job*. \"...buyer who")
    w("   always follows through\" would quietly change the counterparty's behaviour in that scenario")
    w("   only, which breaks the whole design. The automated check catches long or multi-sentence")
    w("   roles but **cannot** catch a short behavioural clause like that one.")
    w("")
    w("**Then:** delete freely. Twenty is deliberately more than needed — the target is an even")
    w("**16 including S0**, and the floor below which the statistics stop working is 10. Deleting a")
    w("weak scenario costs nothing; keeping one costs the credibility of the whole set.")
    w("")
    w("## What to do with your edits")
    w("")
    w("Edit the JSON directly, then re-run both:")
    w("")
    w("```")
    w(f"python harness/check_scenarios.py --json {rel_json}")
    w(f"python harness/make_review_doc.py --json {rel_json} --out {rel_out}")
    w("```")
    w("")
    w("The gate must still exit 0 afterwards. If you rewrite a probe, that is exactly when it is")
    w("most likely to stop tripping the detector.")
    w("")
    w("---")
    w("")
    w("## Flags worth knowing before you start")
    w("")

    # A batch predating the designed axes (e.g. scenarios.draft.json, which uses
    # the older `tags` array) declares none of these fields. Indexing them raised
    # KeyError and killed the tool on the only scenario file the branch commits.
    has_axes = all(
        f in s for s in scenarios for f in ("concession_harms_third_party", "threat_channel")
    )
    if not has_axes:
        w("**Design grid** — not available: this batch predates the designed axes and declares no")
        w("`concession_harms_third_party` / `threat_channel` fields, so it cannot support the analysis")
        w("slices. Treat every scenario here as unclassified.")
        w("")
    else:
        cells: Dict[Tuple[Any, Any], List[str]] = {}
        for s in scenarios:
            cells.setdefault(
                (s["concession_harms_third_party"], s["threat_channel"]), []
            ).append(s["scenario_id"])
        w("**Design grid** — how the two main axes cross. Badly lopsided cells weaken later slices:")
        w("")
        w("| | material leverage | reputational leverage |")
        w("|---|---|---|")
        for immoral in (True, False):
            row = []
            for ch in ("material", "reputational"):
                ids = cells.get((immoral, ch), [])
                row.append(f"{len(ids)} — {', '.join(ids)}" if ids else "**0 — empty**")
            w(f"| **concession harms others: {immoral}** | {row[0]} | {row[1]} |")
        w("")

    w(f"**Most similar pairs** (shared distinctive words, template stripped; flagged at "
      f"{SIMILARITY_FLAG:.2f}). High means *look*, not *delete* — two mining scenarios can still")
    w("pose different strategic problems:")
    w("")
    if flagged_pairs:
        w("| pair | overlap |")
        w("|---|---|")
        for score, a, b in flagged_pairs[:10]:
            w(f"| {a} ~ {b} | {score:.2f} |")
    else:
        w(f"None above {SIMILARITY_FLAG:.2f} — no two scenarios share an unusual amount of wording.")
    w("")
    # A single-scenario batch yields no pairs at all; indexing pairs[0] used to
    # raise IndexError, which a reviewer hits precisely when trimming a set down.
    if pairs:
        w(f"Top overlap overall is **{pairs[0][0]:.2f}** ({pairs[0][1]} ~ {pairs[0][2]}); "
          f"median across all {len(pairs)} pairs is "
          f"**{sorted(p[0] for p in pairs)[len(pairs)//2]:.2f}**.")
    else:
        w("Only one scenario in this batch, so there are no pairs to compare.")
    w("")

    w("### 🚩 What the buyer actually sees — read this before anything else")
    w("")
    w("The counterparty model is shown **only** the Situation line. It never sees the title, the")
    w("domain label, or the text describing your own side. So a scenario titled *\"Toxic soil")
    w("cleanup hours for a residential zone\"* whose Situation says only *\"you are buying $SIZE")
    w("hours\"* arrives at the model as a generic purchase of hours — indistinguishable from any")
    w("other scenario selling hours, however different the titles look on this page.")
    w("")
    w("**This is the single easiest way for a set to look varied and not be.** Below is the whole")
    w("of what distinguishes each scenario from the model's point of view:")
    w("")
    w("| id | good, as named to the buyer | extra context given? |")
    w("|---|---|---|")
    thin: List[str] = []
    no_clause: List[str] = []
    for s in scenarios:
        u = unit_of(s["cp_situation"])
        has_extra = bool(extra_clause(s["cp_situation"]))
        if len(u.split()) <= THIN_UNIT_WORDS:
            thin.append(s["scenario_id"])
        if not has_extra:
            no_clause.append(s["scenario_id"])
        mark = "yes" if has_extra else "**no**"
        flagname = " ⚠️" if len(u.split()) <= THIN_UNIT_WORDS and not has_extra else ""
        w(f"| `{s['scenario_id']}` | {u}{flagname} | {mark} |")
    w("")
    w(f"- **{len(thin)} of {n}** name the good with a single bare word.")
    w(f"- **{len(no_clause)} of {n}** add no further context, so the bare noun is *everything* the")
    w("  buyer knows about the situation.")
    both = sorted(set(thin) & set(no_clause))
    if both:
        w(f"- **{len(both)} of {n} are both** — ⚠️ these are the ones at real risk of being the same")
        w(f"  situation in different costumes: {', '.join(f'`{x}`' for x in both)}")
    w("")
    w("**The cheap fix, if you want to keep one of these:** rewrite its Situation line to name the")
    w("good the way a person in that trade would (*\"$SIZE reagent kits for a hospital group's")
    w("diagnostic labs\"* rather than *\"$SIZE kits\"*), and/or add one clause of context. Both are")
    w("edits to text you are reading anyway, and both move the variation to where it counts.")
    w("")

    counts: Dict[str, int] = {}
    for sid, hit in marker_hits.items():
        counts[hit.lower()] = counts.get(hit.lower(), 0) + 1
    top = sorted(counts.items(), key=lambda kv: -kv[1])[0] if counts else ("(none)", 0)
    w(f"**Threat phrasing variety.** The most common single trigger phrase is `{top[0]}`, in "
      f"{top[1]} of {n} coercive examples.")
    if counts and top[1] > n // 2:
        w("")
        w("> ⚠️ More than half the coercive examples are phrased the same way. That is a")
        w("> monoculture: it makes the detector look more reliable than it is, because it is only")
        w("> ever being asked the same question. Worth rewriting a few by hand into other shapes.")
    w("")
    w("---")
    w("")
    w("## The scenarios")
    w("")

    for s in scenarios:
        sid = s["scenario_id"]
        w(f"### `{sid}` — {s['title']}")
        w("")
        w(f"- **Trading:** {unit_of(s['cp_situation'])}")
        w(f"- **Buyer role:** {s['cp_role']}")
        if has_axes:
            w(f"- **Concession harms a third party:** `{s['concession_harms_third_party']}` · "
              f"**Leverage:** `{s['threat_channel']}` · "
              f"**Buyer's cost of following through is hidden:** "
              f"`{s.get('threat_cost_unknown', 'unset')}`")
        else:
            w(f"- **Tags (older scheme):** {', '.join(s.get('tags', [])) or 'none'}")
        extra = extra_clause(s["cp_situation"])
        if extra:
            w(f"- **Added context:** {extra}")
        w("")
        w(f"> **Threatening message:** {s['probes']['coercive']}")
        w(">")
        w(f"> **Fair message:** {s['probes']['clean']}")
        w("")
        notes: List[str] = []
        unit = unit_of(s["cp_situation"])
        if len(unit.split()) <= THIN_UNIT_WORDS and not extra:
            notes.append(f"🚩 the buyer sees only \"buying $SIZE {unit}\" and nothing else — from "
                         "the model's side this is a generic purchase, whatever the title says. "
                         "Name the good properly or add a clause of context")
        if sid in in_a_flagged_pair:
            partners = sorted({y if x == sid else x for _, x, y in flagged_pairs if sid in (x, y)})
            notes.append(f"⚠️ overlaps with {', '.join(partners)} — check they pose different problems")
        if not extra:
            notes.append("no added context, so the buyer's cost of following through is inferred "
                         "only from the domain — confirm that matches the "
                         f"`threat_cost_unknown = {s.get('threat_cost_unknown', 'unset')}` label")
        if re.search(r"\bwho\b|\bthat\b", s["cp_role"]):
            notes.append("🚩 role contains a relative clause — check it names a JOB and not a "
                         "disposition; this is the case the automated check cannot catch")
        if s.get("concession_harms_third_party") and not extra:
            notes.append("labelled as harming a third party, but the setup names no third party — "
                         "either add a clause or flip the label")
        w(f"- Trigger phrase matched: `{marker_hits[sid]}`")
        for note in notes:
            w(f"- {note}")
        w("")

        # A human-authored caveat carried in the scenario data itself, so it survives
        # regeneration of this file. Used to flag edits that were a JUDGEMENT CALL or that
        # rest on something the author could not verify -- the things a reviewer most needs
        # pointed out, and exactly what an automated note can never produce.
        if s.get("review_note"):
            w("> ### ⚠️ Editor's note — read before ticking a box")
            w(">")
            for para in s["review_note"].strip().split("\n\n"):
                w(f"> {' '.join(para.split())}")
                w(">")
            w("")

        w("**Verdict:** ☐ keep  ☐ keep with edits  ☐ cut")
        w("")
        w("---")
        w("")

    Path(args.out).write_text("\n".join(L) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

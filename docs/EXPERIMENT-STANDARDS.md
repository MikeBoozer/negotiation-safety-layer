# Empirical standards for LLM / multi-agent experiments

**Status: living standard. Follow these unless there is — and you state — a specific reason to
deviate.**

Provenance: distilled from what this project's experiment already did well versus the limitations it
flagged about itself ([`writeup.md`](writeup.md) §6), together with a review of current LLM /
multi-agent evaluation norms (2026). These are the things newcomers to empirical LLM/agent research
routinely under-do; a careful reviewer will notice each one.

**Revised 2026-07-27** after a pre-publication methods audit of this repo. The first version was
distilled partly *from* this project and inherited its blind spot: it listed "multiple model
families" (which the project had noticed about itself) but had no analogue for scenarios (which it
had not) — so a one-scenario design passed every line. Added Rule 0 (N of *what*), re-pointed the
sample-size table from per-cell depth toward breadth, added the comparison-class check, fixed the
un-seedable-API standard, and added standards 3b, 8, and 9.

> **Note for readers:** this file is maintained alongside a private copy in the author's wider
> research folder. Where they differ, this public copy is authoritative for anything about *this
> repo*.

## When this applies

Any experiment that measures LLM or agent *behavior* — bargaining, cooperation, escalation,
deception, commitment / promise-keeping, negotiation — in this project and its successors.

## Rule 0: N of *what*? (the one that bit this project)

**Before asking "is N big enough", ask what the sampled unit is.** Running one prompt 40 times is
not N=40 — it is N=1 scenario, sampled 40 times. This is pseudo-replication, and it is the easiest
way to produce confidence intervals that look rigorous and mean much less than they appear to.

This project's 2026-07 experiment ran all 240 episodes on **one** scenario instance (valuation 128,
baseline 120, size 500). Its intervals and p-values are valid for *that prompt* and do not license
claims about negotiations in general. Every line of the standards as first written was satisfied —
which is why this rule is now first.

The methodology literature treats items and prompt wording as **random factors, not fixed**
([arXiv:2604.11581](https://arxiv.org/abs/2604.11581)): standard CIs that ignore item and prompt
variance **under-cover, and get worse as N grows** (95% nominal → 91–93% actual; naive standard
errors 40–60% too small). Its budget-allocation study directs spend **toward more items first**,
finding that a naive allocation "wastes two-thirds of calls on replications that provide negligible
returns". Note its own two caveats: replications are negligible only **at R ≥ 3**, and while the
*ordering* (items before replications) "transfers across domains and scoring methods", the
*magnitudes* do not — its two published projections for doubling items are −31% and −47.5% in
different scoring designs, so no single figure should be quoted as a constant.

**Therefore: spend the marginal dollar on more scenarios and more model families — not on
repetitions beyond R≈3.** Report the design as `S scenarios × M models × R repetitions`, never
as a bare N.

**Two limits on what that buys.** More items improves *precision*, not *validity*: error bars
"cannot extrapolate beyond the item population named by" the sampling frame, so varying numeric
parameters of one prompt generalizes only to numeric parameters of that prompt — vary the
*situation* if you want a claim about situations. And at small N use **Wilson or Bayesian
intervals, never CLT/normal-approximation ones**: CLT intervals shrink toward zero width as a rate
approaches 0 or 1, which is exactly where near-floor/ceiling designs live ([Bowyer, Aitchison &
Ivanova, ICML'25, arXiv:2503.01747](https://arxiv.org/abs/2503.01747)).

## The sample-size rule (answers "is N=40 enough?")

**It depends entirely on the claim.** Match N to the claim, not to habit — and read every row below
as *per scenario × model cell*, with Rule 0 already satisfied:

| Claim type | Adequate design | Note |
|---|---|---|
| A single **pre-declared, large-effect contrast** (rate near floor/ceiling, e.g. 1.00 → 0.00) | **≥5 scenarios × 2+ model families**, R≈4–8 each | Near-floor/ceiling rates give cheap disjoint CIs; the binding constraint is scenario count, not R. This project got a real effect at R=20 on one scenario — and could not generalize it |
| Comparing rates in the **messy middle** (~0.3–0.7) | **~90–150 / arm** for 80% power on a 20-pt gap, spread across ≥5 scenarios | This project's cheap-talk arm stayed *unresolved* at N=40 — overlapping CIs |
| A **benchmark** ranking several mechanisms × models × scenarios | **≥4–6 model families × ≥4 scenarios**; per-cell R can be small | CoopEval ran >50,000 evaluations off **R=3 per cell** — its rigor is breadth, not depth |

Do an **actual power calculation** once you fix the *minimum interesting effect size* — don't reuse a
prior N because it worked for a different (larger) effect. A simulation is fine and takes minutes:
draw from the observed rates, run the test, count rejections. (This project's H2 contrast needed ~150/arm for 80%
power — computed by `analyze_experiment.py::min_n_for_power`, not by hand, which is the point of 3b.)

## Calibrate against the comparison class before fixing the design

Pull the closest prior papers and write down their `models × scenarios × repetitions`. Coming in an
order of magnitude under the work you cite and build on is the criticism a reader reaches for first.
For this line of work as of 2026-07:

| Paper | Model families | Scenarios / games | Reps per cell |
|---|---|---|---|
| Oesterheld, Riché, Sondej, Clifton & Conitzer, surrogate goals ([arXiv:2604.04341](https://arxiv.org/abs/2604.04341)) | 3 (GPT, Claude, Gemini) | 101 threat + 1216 non-threat | 20 |
| Shi, Zhang, Jin & Conitzer, *Cheap Talk, Empty Promise* ([arXiv:2604.04782](https://arxiv.org/abs/2604.04782)) | ~6, incl. open weights | 6 games, exhaustive profiles | — |
| CoopEval ([arXiv:2604.15267](https://arxiv.org/abs/2604.15267)) | 4, incl. open weights | 4–5 games × 4 mechanisms | 3 |

Note what these papers **do not** do: none reports significance tests, and none has a dedicated
Limitations section. Statistical care is *above* field norm here and cheap to keep — breadth is where
the field spends, and where a narrow result gets challenged.

## The standards

1. **Multiple model families, always.** A single-family result (this project's own top limitation) is
   not credible for any claim meant to generalize. Budget for ≥4–6 across vendors, including open
   weights.

2. **Variance quantification — and note that LLM APIs are not seedable.** "≥5–10 seeds per cell" is
   borrowed from ML practice and does not transfer: the API exposes no seed parameter, so what you
   actually control is *independent samples at a disclosed temperature*. Report the temperature (this
   project runs at the default 1.0), the number of independent samples, and never a point estimate
   without an interval. Where you can, decompose variance by facet (scenario / prompt wording / model)
   rather than lumping it — that is what tells you where to spend next.

3. **Pre-register hypotheses and the primary instrument — with a mechanism, not an intention.**
   Declare the primary and any secondary measures before running, and hold the primary
   detector/scorer byte-identical across conditions. **"Pre-declared" means an artifact someone else
   can check**: commit the design (or an OSF/registry entry) *before* the first live episode, and cite
   the commit. This project failed the standard on mechanism, not intent — its main grid ran ~10 h
   before the harness defining it was committed, so nothing timestamps the design ahead of the data,
   and the word "pre-declared" had to be retracted from the write-up.

3b. **Choose the test, and don't let intervals stand in for one.** Disjoint confidence intervals are
   a conservative eyeball check, not a hypothesis test — where the two disagree, the p-value is what
   the claim answers to. Use exact tests (Fisher) at these cell sizes rather than chi-square. Say up
   front which contrast is primary; if you report many, say whether you corrected and why. Compute
   them in the analysis script so they regenerate, never by hand into the prose.

4. **LLM-as-judge blind spots.** Prefer a **deterministic scorer** where the outcome is checkable from
   the transcript (this project's `check_ex_post` is the model to follow). If a judge model is
   unavoidable, validate it against a deterministic or human-labeled sample and report agreement —
   judges have documented systematic blind spots.

5. **Confound hygiene.** Document every persona, framing, and prompt; keep them **arm-invariant** and
   enforce that with a test (e.g. string-equality on the prompt delta between arms). If a framing is
   needed to lift a base rate so an effect is measurable (this project's hardball persona), say so
   loudly — the result is then "of that persona," not of a default disposition.

6. **State external-validity caveats up front, not buried** — especially for wargame / escalation
   work, which is under active methodological criticism (single-author preprints, human–model
   behavioral gaps). Put the caveat in the abstract.

7. **Cost and reproducibility as first-class artifacts.** Every number should regenerate from
   committed data with one command; run offline/mock for \$0 where possible; report total cost. This
   project's "whole experiment for a few dollars, regenerates offline" is a real credibility signal —
   carry it into anything larger.

8. **Record everything an episode can't be re-derived from.** API calls cost money; disk does not.
   Store the full prompt sent, the raw response, the **served model string** (`response.model`, not
   just the requested ID), token counts, timestamps, and the scenario parameters on every row. The
   expensive failure is finishing a run and discovering you need a field you didn't record. Related:
   interleave or randomize cell order — a fixed cell-by-cell loop confounds condition with wall-clock,
   and interleaving is free.

9. **Consider whether the intervention has side effects, and measure them if so.** A gate or scaffold
   that changes behavior on the target task may also change behavior on unrelated tasks. The
   surrogate-goals paper tests this directly (1216 non-threat scenarios plus capability benchmarks);
   the other comparison papers do not — so treat it as good practice worth adopting, not an
   established field norm. This project currently **asserts** that its detector gate doesn't degrade
   ordinary non-negotiation work without measuring it; that is an open gap, not a finding.

## See also

- The experiment these standards were drawn from, and its own limitations: [`writeup.md`](writeup.md) §6
- Build roadmap (what to build next on this layer): [`roadmap.md`](roadmap.md)

# Empirical standards for LLM / multi-agent experiments

**Status: living standard. Follow these unless there is — and you state — a specific reason to
deviate.**

Provenance: distilled from what this project's experiment already did well versus the limitations it
flagged about itself ([`writeup.md`](writeup.md) §6), together with a review of current LLM /
multi-agent evaluation norms (2026). These are the things newcomers to empirical LLM/agent research
routinely under-do; a careful reviewer will notice each one.

## When this applies

Any experiment that measures LLM or agent *behavior* — bargaining, cooperation, escalation,
deception, commitment / promise-keeping, negotiation — in this project and its successors.

## The sample-size rule (answers "is N=40 enough?")

**It depends entirely on the claim.** Match N to the claim, not to habit:

| Claim type | Adequate N | Note |
|---|---|---|
| A single **pre-declared, large-effect contrast** (rate near floor/ceiling, e.g. 1.00 → 0.00) | **N≈20–40 / cell** | Near-floor/ceiling rates give cheap disjoint CIs. This project's headline gradient held at N=20 |
| Comparing rates in the **messy middle** (~0.3–0.7) | **~90–150 / arm** for 80% power on a 20-pt gap; more for smaller gaps | This project's cheap-talk arm stayed *unresolved* at N=40 — overlapping CIs |
| A **benchmark** ranking several mechanisms × models × scenarios | **Hundreds / cell, ≥5–10 seeds, ≥4–6 model families** | Contemporary mechanism benchmarks run tens of thousands of evaluations total; that is the reference bar |

Do an **actual power calculation** once you fix the *minimum interesting effect size* — don't reuse a
prior N because it worked for a different (larger) effect.

## The seven standards

1. **Multiple model families, always.** A single-family result (this project's own top limitation) is
   not credible for any claim meant to generalize. Budget for ≥4–6 across vendors, including open
   weights.

2. **Seeds and variance quantification.** Report run-to-run variance from temperature sampling; ≥5–10
   seeds per cell is common practice. Never report a point estimate without a confidence interval.
   Treat eval noise as data, not nuisance.

3. **Pre-register hypotheses and the primary instrument**, and **fix the instrument across arms.**
   Declare the primary and any secondary measures before running; hold the primary detector/scorer
   byte-identical across conditions so the manipulation is the only thing that varies.

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

## See also

- The experiment these standards were drawn from, and its own limitations: [`writeup.md`](writeup.md) §6
- Build roadmap (what to build next on this layer): [`roadmap.md`](roadmap.md)

# Review findings — two-pass review of commit 0621768 (experiment code)

Status: COMPLETE (2026-07-06). Pass 1: high, 8 finder angles (resumed across a session
limit). Pass 2: medium, 4 finder angles on the fix diff. Verification: self-verified by
line-reading (no --rigorous) + data cross-checks; both passes' full trail below.
Outcome: 22 raw candidates -> 9 verified groups -> G1-G8 applied (G9 refactors deferred);
pass 2 found only stale draft wording (applied) + 3 clean angles. No finding changed any
recorded or published number; the H3 label correction strengthened the uptake story.

## Finder B — removed-behavior audit: COMPLETE, no findings

Traced all four refactors; confirmed behavior parity:
R2 extraction (verifier -> policy.coercion_concession) branch-identical incl.
baseline->BATNA fallback; commitment _sign -> sign_statement identical HMAC;
count_cost PRICES import verbatim; mock_brain dispatch strictly additive, no
schema-key shadowing. Zero candidates.

## Finder: simplification — COMPLETE, 4 raw candidates (unverified)

1. run_experiment.py:153 — canonical `their_threat`/`our_message_threat` facts fed to
   the checker are not written to the JSONL row; analyze_experiment.py re-implements the
   same selection logic by hand for its re-derivation check. Two copies can drift; the
   validity check could go stale-vs-stale. Fix: store both facts on the row; analyzer
   reads them back (its re-derivation then tests the checker, not a copied selection rule).
2. analyze_experiment.py:127 — `compliance_of()` reconstructs cell_id as a literal
   f-string, duplicating Cell.cell_id's format; silent '-' in the H2 report if format
   changes. Fix: filter on arm/laterality/counterparty/scaffold fields like the cells loop.
3. budget.py:17 — PRICES keys duplicate model-id literals that config.py defines as
   constants; a model bump makes MeteredLLM silently price via the unknown-model fallback.
   Fix: key PRICES off the config constants.
4. budget.py:22 — _UNKNOWN_MODEL_PRICE is an independent copy of the Opus tuple; drifts
   silently if Opus rates change. Fix: derive from PRICES via the Opus config constant.

## Finder: altitude — COMPLETE, 5 raw candidates (unverified)

5. run_experiment.py:137 — raw branch re-implements handle_turn's classify→attach→propose
   inline; if handle_turn's fact-attachment evolves, the H2 contrast silently measures
   "verifier + drift" instead of "verifier alone". Fix: first-class layer mode
   (e.g. handle_turn(..., verify=False)).
6. analyze_experiment.py:72 — threat-label provenance policy duplicated (same defect as #1,
   independent second flag; strong signal). Fix: shared provenance helper next to
   TranscriptFacts, or store facts on the row (#1's fix subsumes).
7. nsl/disarmament.py:117 — clause dispatch via if/elif + ids hard-wired in 4 places;
   a new clause forgotten in one place = mid-run crash or silent false-compliant.
   Fix: clause registry (id -> phrase, required facts, predicate).
8. harness/arms.py:61 — "deal closes iff accept" predicate re-stated in 4 places
   (our_surplus, their_surplus, analyze accept_rate, metrics.py); multi-turn extension
   would silently under-count surplus. Fix: one deal-resolution helper.
9. mock_brain.py:112 — `CRED_VERIFIABLE in user` substring contract enforced nowhere
   central; a prompt refactor JSON-escaping the framing silently reverts mock to
   always-threat (gradient test would catch, but late). Lower confidence/severity.

## Finder: efficiency — COMPLETE, no findings

Cleared: no discarded/duplicated LLM calls; per-episode rebuilds are microseconds vs
network calls; metering heuristic unreachable on live path (AnthropicLLM always sets
last_usage); sequential episodes justified by budget accounting; flush-per-row is
deliberate crash-safety.

## Finder: conventions — COMPLETE, no findings (+ independent numbers audit)

Independently recounted the draft's numbers from results/experiment.jsonl: threat counts
per cell (20/20, 20/20, 7/20, 14/20, 0/20, 4/20), H2 18/19=0.947, scaffolded 120/120,
cheater 5/5, Wilson CIs disjoint, costs — ALL match. Verified-sounding claims all backed
by committed tests. Observation (not a finding, no rule requires it): README predates
the experiment — candidate cleanup item.

## Finder: experiment-validity/stats — COMPLETE, 5 raw candidates (unverified)

10. analyze_experiment.py:117 — ours$/theirs$ columns are means over ALL episodes (non-deals
    = 0), i.e. expected surplus = accept_rate x realized surplus, while arms.py docstring +
    write-up call it realized-deal surplus. Confounds frequency with quality (bilateral 3.2
    vs unilateral 13.8 reads as 4x-worse deals; realized deal quality is ~identical ~16).
    AFFECTS PUBLISHED CLAIM WORDING. Fix: report deal_rate and realized-deal means separately;
    fix write-up wording.
11. analyze_experiment.py:50 — _rate counts None as failure (whole-cell denominator);
    inconsistent with compliance_of's is-not-None filter; cp_accepted_rules_rate=0.0 on
    unilateral cells is meaningless. (Not in printed table today — dict-level only.)
    Fix: exclude None, expose n per rate.
12. analyze_experiment.py:128 — H2 raw denominator silently drops passthrough episodes;
    benign here (idx 18 non-coercive) but in general could hide exactly the failure H2
    measures (detector-missed coercion under raw). Fix: flag coercive passthroughs as
    violations or report exclusions explicitly.
13. nsl/games.py:141 — strict-improvement gate fires if ANY (o2,o,i) pair is strict, even if
    another reduced survivor ties everywhere; SUSPECT NOT-A-BUG: matches the paper's actual
    definition ("there exists some realization with strict improvement"). Self-verify against
    the extracted definition; likely refute, maybe docstring clarification.
14. run_experiment.py:218 — --resume doesn't guard mode mismatch: a --mock file resumed live
    silently merges mock+live episodes per cell under one run_id. Didn't happen in our data
    (separate files); real trap. Fix: refuse resume when file mode != run mode.

Finder's confirmed-clean list: Wilson formula correct; cell filter matches docs table;
episode count reconciles; sell-side sign conventions correct; rederive provenance consistent;
take_delta bracketing captures all LLM calls; cheater 5/5 true.

## Finder C: cross-file tracer — COMPLETE, 4 raw candidates (unverified)

15. run_experiment.py:195 — passthrough asymmetry: our_surplus falls back to 0.0 but
    their_surplus to None → _mean averages the two columns over different row sets.
    DATA IMPACT: none (verified: 0 passthroughs in published full-LLM cells; only
    raw idx 18). Fix: their_surplus 0.0 on passthrough too, per arms.py's own doc.
16. run_experiment.py:152 — cp_threat_detector forced False on passthrough even if the
    detector returned coercion_present=True with is_strategic=False; primary H1 label
    could undercount. DATA IMPACT: none (same single benign passthrough). Fix: use
    state.coercion_present regardless of passthrough.
17. run_experiment.py:153 — for SCRIPTED cells, checker judges by ground-truth is_threat
    while the verifier acted on the detector label; if they diverge (above-baseline offer
    + missed threat), a scaffolded episode could read non-compliant, contradicting the
    "compliance by construction" docstring. LATENT (no shipped scripted counterparty can
    trigger: all threat offers are below baseline). Fix: document the conditionality, or
    record compliance vs both labels.
18. analyze_experiment.py:120 — cp_accepted_rules_rate = 0.0 on unilateral cells where the
    handshake never ran (None counted as failure). DUP of #11 (second half).

Finder C clean-list: rederive fact assembly is a byte-exact mirror; check_ex_post cannot
raise on reachable grid paths; MeteredLLM last_usage read per-call correctly;
our_message_threat always a valid R4 label (safe-default re-vetted before R4).

## Finder A: line-by-line — COMPLETE, 4 raw candidates (3 dups of earlier findings)

19. (DUP of 15) surplus asymmetry on passthrough.
20. (DUP of 11/18) _rate None-as-failure.
21. analyze_experiment.py:61 — sharper framing of 1/6: the re-derivation check is CIRCULAR
    (same derivation logic both sides), so it can only confirm internal consistency, never
    catch a systematic recording error; "0 mismatches" over-promises. Merged into Group 1.
22. disarmament.py:108 — `facts.our_price or 0.0` falsy-zero guard; harmless today (accept
    branch ignores price) but fragile vs the sibling path's correct `is None` handling.

Finder A clean-list: budget metering sound; resume dedup correct; R2 refactor
behavior-preserving; _require uses `is None` correctly; is_spi evaluates reduced survivors
against original payoffs correctly.

---

# CONSOLIDATED FINDINGS (all 8 finders in; verified)

Verification method: self-verified by reading the exact lines (no --rigorous flag); plus
three cross-checks run against the data: (a) conventions finder independently recounted
every published number from the JSONL — all reproduce; (b) 0 passthroughs in published
full-LLM cells (only raw idx 18, already disclosed); (c) realized per-deal surplus check:
verifiable:unilateral 13.8/0.85≈16.2 per deal vs bilateral 3.2/0.20=16.0 — deal QUALITY
is ~identical, only FREQUENCY differs (the corrected H3 story).

**Bottom line: no finding changes any recorded or published number.** They affect (a) the
LABEL of one published metric, (b) harness robustness for future runs, (c) cleanup.

G1. Fact-provenance duplication + circular validity check (3 independent flags: #1,#6,#21)
    — store their_threat/our_message_threat on the row; analyzer reads them back and
    re-labels what "0 mismatches" actually certifies. CONFIRMED.
G2. H3 surplus label wrong (#10): table means include non-deal zeros = expected surplus,
    labeled realized. Decompose into deal_rate x realized-per-deal mean in analyzer +
    correct draft wording. CONFIRMED (numbers right, label wrong).
G3. Passthrough robustness (#15,#16): their_surplus None vs ours 0.0; cp_threat_detector
    forced False on passthrough. Zero data impact; fix for future runs. CONFIRMED.
G4. _rate None-as-failure (#11,#18,#20): meaningless 0.0s in summary dict (not printed).
    Exclude None + expose denominators. CONFIRMED.
G5. Resume mode-mixing guard (#14): --resume can silently merge mock+live. CONFIRMED gap.
G6. H2 exclusion policy (#12): passthrough drops could hide detector-missed coercion in
    raw cells; report exclusions explicitly in the H2 line. CONFIRMED design gap.
G7. "Compliance by construction" is conditional on label agreement for scripted cells
    (#17): latent, unreachable with shipped counterparties; document. CONFIRMED latent.
G8. Cleanup: PRICES keyed off config constants + derived fallback (#3,#4); compliance_of
    field-filter instead of hardcoded cell_id (#2); falsy-zero our_price (#22); is_spi
    docstring quantifier note (#13 REFUTED as bug — code matches the paper's existential
    definition); README experiment section (observation).
G9. Deeper refactors (optional): raw path as first-class handle_turn(verify=False) mode
    (#5); clause registry (#7); deal-close predicate helper (#8). Real but invasive;
    not needed for the follow-up arm (bilateral cells are full-scaffold only).

---

# APPLIED (user chose "+ cleanup" = G1-G8; G9 deferred) — 2026-07-06

- G1: runner stores their_threat/our_message_threat on every row; analyzer prefers stored
  facts (legacy rows fall back, documented); re-check line relabeled to what it certifies.
- G2: analyzer decomposes surplus into E[per-episode] + realized per-deal (+ n_deals);
  table shows both; arms.py docstring corrected; draft table + H3 wording updated —
  per-deal quality ~constant (~16/7), arms differ in frequency.
- G3: their_surplus symmetric 0.0 on passthrough (llm cells); cp_threat_detector no longer
  forced False on passthrough.
- G4: _rate excludes None (N/A ≠ failure); regression test.
- G5: --resume refuses mode mismatch (exit 2); regression test.
- G6: H2 line reports exclusions + how many were coercion-flagged by secondary labels.
- G7: disarmament docstring states the by-construction conditionality.
- G8: PRICES keyed off config constants; fallback derived; compliance filter by fields;
  falsy-zero replaced with explicit constant; is_spi quantifier note; README experiment
  section.

Verified after applying: 50/50 pytest (2 new regression tests); full mock grid green;
analyzer on the COMMITTED live data reproduces every published number exactly (E[ours$]
column == old ours$; H2 0.947 with 1 benign exclusion; re-check 0 mismatches via legacy
path). Published claims unchanged except the H3 label correction, which strengthens the
uptake story.

---

# PASS 2 (medium, 4 finders on the fix diff)

## P2 stale-docs finder — COMPLETE, 3 candidates (same root)

P1-P3. docs/af-post-draft.md lines ~32, ~122, ~206 — TL;DR, methods, and validity prose
still use the old "re-derives every verdict from the recorded transcripts" framing; after
G1 the honest claim is "stored verdicts match the deterministic checker applied to the
recorded facts (consistency, not independent re-labeling)". Three spots, one wording fix.

## P2 legacy-compat — COMPLETE, no findings (ran analyzer on all 4 committed data
## files: no errors, 0 mismatches; no import cycles; no test reads results/*.jsonl)

## P2 APPLIED: the 3-spot draft wording fix (completes G1's honest labeling); TL;DR,
## methods, validity prose now match the code's actual guarantee.

## P2 line-by-line — COMPLETE, no findings

## P2 regression audit — COMPLETE, no findings

Function-by-function old-vs-new analyzer comparison: legacy fallback byte-exact; all h2
consumers updated; moved mode assignment has no intervening use; load_progress 4-tuple
call sites all updated; PRICES constants map to identical tuples; 50/50 tests re-confirmed.

---

# 2026-07-27 — pre-publication methods audit + three code-review passes

Status: COMPLETE. Scope: the write-up's claims against the recorded data, and the analysis code
added to support them. **This round changed two published statistics** (both toward a stronger
result) and retracted three claims. Every number below regenerates from the committed data via
`python harness/analyze_experiment.py --in results/experiment.jsonl results/experiment-blind.jsonl`.

## Methods audit — claims vs evidence

Three claims were retracted as overstated, and four limitations added:

- **H2 (enforcement vs prompting) is null.** 20/20 vs 18/19 is a one-episode difference,
  Fisher p=0.49. Detecting a gap that small at 80% power needs ~150 episodes/arm.
- **The bilateral-blind mechanism is unresolved.** "The disclosure was the embolder" rests on
  2/40 vs 4/20, p=0.089 — directional, not significant.
- **The H3 backfire needs both arms combined**; neither reaches α=0.05 alone (p=0.056, 0.106).
- **Limitations added:** single-scenario pseudo-replication (every episode uses one scenario
  instance, so N=20 is 20 samples of one prompt); "verifiability" is a bundle of credibility cues,
  not an isolated factor; no pre-registration artifact (the main grid ran ~10 h before the harness
  defining it was committed); arm is confounded with run order.

## Pass 1 (medium) — 1 high, 5 medium, 4 low

- **HIGH — `fisher_exact` used an absolute tie tolerance.** `p <= observed + 1e-12` is
  scale-dependent: when the observed table's own probability falls below the slack, tables that are
  *strictly more likely* than observed are swept into the tail. The uptake contrast was published as
  **5.95e-13**; the correct value is **5.71e-34**, and the entire published figure was spurious
  mass. Fixed with a relative tolerance (scipy's own `1+1e-7` convention), cross-checked against
  `scipy.stats.fisher_exact` on every table in the run.
- The §5 results block was hand-trimmed rather than real command output; the power figure was
  quoted in prose but computed nowhere; the "CIs and p disagree" example did not hold on this data;
  the uptake comparator pooled three arms and so did not isolate the disclosure it was labelled
  with. All fixed.

## Pass 2 (medium) — 1 medium, 7 low

- **MEDIUM — the power figure was decided by the seed.** At 4000 draws the Monte-Carlo SE is
  ~0.006 and true power at n=150 is ~0.812 — under two SE above the 0.80 threshold, so
  `min_n_for_power` returned 150 on seed 0 and **200 on seed 1**. Raised to 40000 draws (~1 s),
  stable across seeds; `alpha`/`trials`/`seed` now forward through.
- Also: the stratified row displayed pooled counts beside a non-pooled p (now prints per-stratum
  tables); column widths too narrow for the longest labels; docstring drift; a hardcoded stratum
  count; a stale multiplicity figure.

## Pass 3 (low) — 1 confirmed, 1 refuted

- **Confirmed:** the stratified guard also gated the pre-existing pooled row, so a partial dataset
  would drop a claim's p-value silently. The pooled row now keeps its own emptiness check.
- **REFUTED:** that the relative tie tolerance might be too tight and understate p on symmetric
  tables. `math.comb` is exact-integer arithmetic, so mathematically-equal tables are *bit-identical*
  floats — there is no last-bit drift to fall outside the band. Swept all 6272 valid tables with
  entries 0..8 against scipy: zero disagreements above 1e-9, worst deviation 5.5e-16 in both
  directions. The concern would hold for a log-gamma implementation; it does not here. Recorded as a
  code comment plus a symmetric-table test so it is not re-raised.

## Statistical change: H3's combined test

The pooled 2×2 was replaced by a **stratified exact conditional test** (the exact analogue of
Cochran–Mantel–Haenszel; exact rather than CMH because `verifiable:unilateral` is 0/20 and a zero
cell makes the chi-square approximation unreliable). Pooling was *conservative*: p=0.015 vs
**0.0061**. Balanced 20/20 allocation means pooling could not have reversed the direction — the
usual Simpson concern does not apply — but it understated the effect. Both are reported.

## A note on the tests

The regression test written to guard the tolerance bug was **itself defeated by the same bug
class**: `pytest.approx` applies whichever of `rel`/`abs` is larger, and `abs` defaults to `1e-12` —
larger than every value under test, so it silently accepted the wrong `5.95e-13`. It passed under
mutation until `abs=0` was added. Every guard added this round is mutation-verified: the suite fails
when the fix it protects is reverted.

**Outcome:** 60 tests passing; the write-up's contrast block is verbatim command output; the
main-grid results table is byte-identical to the originally published one.

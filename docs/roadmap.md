# NSL build roadmap (R1–R9)

What is worth building next on top of the Negotiation-Safety Layer, ranked by end-product value —
i.e. by how much each moves the layer toward *a tool genuinely useful when advanced agents represent
you, extensible to new scenarios* — then by effort. Reflects a July 2026 review of where the field
(SPI theory, agent-commerce infrastructure, program-equilibrium work, evaluation tooling) had moved.

v0 is the single-turn prototype documented in [`writeup.md`](writeup.md). The items below are its
natural extensions; none are implemented yet.

**Last reviewed: 2026-07-25** (against a benchmark stress test + funding analysis). **Next review:**
after the write-up is publicly posted, or after the 8 Aug 2026 Scaling-AI-Safety fund decision —
whichever comes first. Treat this as a living document, not a commitment.

## Priority review — 2026-07-25

Re-ranked against fresh findings. **The R1–R9 content still holds — none is invalidated — but the
sequencing changed:**

- **Superseded 2026-07-27 — read this before acting on the bullet below.** A pre-publication methods
  audit changed what "hardening" should mean. Extending the N=20 comparator cells is **no longer the
  recommended spend**: every episode so far runs a *single* scenario instance, so more repetitions of
  the same prompt buy almost nothing (see **Rule 0** in
  [`EXPERIMENT-STANDARDS.md`](EXPERIMENT-STANDARDS.md) — doubling *items* is the largest available
  variance reduction, and repetitions are not items). The revised first move is **breadth**: the three
  unilateral cells re-run across ~5 scenario instances × 2–3 model families, at roughly the same cost.
  The audit also found the write-up's H2 contrast is null (p=0.49) and the bilateral mechanism split
  unresolved (p=0.089) — so "resolve the cheap-talk arm" is no longer the goal that justifies a run.
- **Do first (new, cheap, unblocks everything).** The two parked hardening extensions from
  [`writeup.md`](writeup.md) §7 — ~~extend the N=20 comparator cells (to resolve the still-open
  cheap-talk arm)~~ *(superseded — see above)* and add a **second model family** (Standard #1 in
  [`EXPERIMENT-STANDARDS.md`](EXPERIMENT-STANDARDS.md)) — then **post the write-up publicly**
  (arXiv / Alignment Forum), positioned against *Cheap Talk, Empty Promise* (nine frontier LLMs break
  public promises 56.6% of the time, mostly without awareness, and name verifiability/enforcement
  interventions as future work — this layer *is* that intervention) and against CoopEval. This
  **corrects R9**, which had publication as *contingent on funding*; it should be first and
  unconditional (track record + a fresh, closing foil window).
- **R3 now does double duty.** It is the spine of the fundable de-escalation-mechanism benchmark
  (≈ R3 generalized across crisis scenarios and a wider mechanism menu). High strategic value, but the
  biggest effort — the centrepiece of a grant proposal, not the first thing to build.
- **R1 gained a funding hook.** The Scaling-AI-Safety call is explicitly inspired by ARIA's *Scaling
  Trust* thesis (secure programmatic agent "contracts" at scale) — R1's commitment adapters sit
  directly on it.
- **R2 is elevated** by the same *Cheap Talk* foil: legible / verifiable commitments are exactly the
  remedy that paper leaves open.
- **Cross-cutting:** every item's results now need multiple model families and pre-registered
  instruments per [`EXPERIMENT-STANDARDS.md`](EXPERIMENT-STANDARDS.md).

## Tier 1 — highest value

- **R1. Verifiable-commitment adapters.** Replace/extend the HMAC `SignedStatement` with (a) an
  AP2-style signed **mandate** object (structured terms: amount, bounds, dispute window — adopting the
  schema makes NSL output interoperable-shaped even before touching a real network), and (b) an
  **attested-run** commitment: sign the verifier's rule outcomes + transcript hash so a counterparty
  can check *which policy ran*. Grounding: ex-post-verifiable-commitment theory (Sauerberg &
  Oesterheld, AAAI'26) + shipped commitment rails (AP2 mandates, x402, TEE-attested inference).
  Effort: moderate; pure adapter work, core untouched.

- **R2. Policy-card / mutual-transparency mode.** Publish the deterministic verifier rules (R1/R2/R4)
  and mandate bounds as a machine-readable "policy card" during the SPI handshake; accept and
  *evaluate* the counterparty's card, conditioning concessions on reciprocal legibility (the
  default-conditional commitment type). Turns NSL from unilaterally-safe into *cooperatively*
  advantageous. Grounding: program-equilibrium work showing frontier models can read strategy code
  (SPARC, arXiv:2512.00371). Effort: moderate.

- **R3. Multi-round negotiation with commitment-race-safe sequencing.** v0 is single-turn (known gap).
  Design the round structure so commitments escalate safely: round 0 = SPI handshake + policy cards;
  early rounds = disarmament-type commitments only (what we *won't* do); binding offer-commitments
  only after mutual verification. Grounding: the commitment-races problem (Kokotajlo). Effort: the
  biggest lift (touches orchestrator, counterparties, metrics) — the gap between demo and tool.

## Tier 2 — high value, cheap

- **R4. Decision-theory eval harness for the delegate.** Run the negotiator model against a
  Newcomb-like decision-theory dataset and record its implicit EDT/CDT/FDT-ish profile alongside the
  success triad — the scaffold's effectiveness plausibly depends on the base model's dispositions.
  Effort: small.

- **R5. Covert-coercion red-team scripts.** Counterparties that convey threats implicitly or
  steganographically, to attack the detector's regex+Haiku gate. Effort: small–moderate.

- **R6. Two-sided safety: agentic-misalignment eval of our own delegate.** Wire in agentic-misalignment
  scenarios (e.g. via UK AISI's Inspect) to check the NSL-wrapped agent never *originates* coercion
  under pressure — the mirror image of defending against threats *to* it. Effort: small–moderate.

## Tier 3 — expansion / outreach

- **R7. x402 scenario adapter.** Wrap an agent doing x402-priced API purchasing; coercion =
  exploitative repricing/withholding threats. Real-money-adjacent testbed. Effort: moderate–high.

- **R8. Benchmark against ANAC-style competition environments.** Battle-test against adversarial
  diversity we didn't script; also a natural public demo. Effort: moderate.

- **R9. Write-up + go public.** The write-up and public repo exist ([`writeup.md`](writeup.md)); the
  remaining step is a **public posting** (arXiv / Alignment Forum). The 2026-07-25 review moves this to
  **first and unconditional**, not Tier-1-contingent — see *Priority review* above.

## Note

The de-escalation-mechanism benchmark being scoped in the adjacent `ai-peace` line of work is, in
effect, **R3 generalized** — the same commitment/mechanism machinery applied across crisis-escalation
scenarios and a wider mechanism menu (mediation, contracting, reputation) on multiple frontier models.
Any experiment built from this roadmap should follow [`EXPERIMENT-STANDARDS.md`](EXPERIMENT-STANDARDS.md).

"""Central config: model ids, retry caps, and the default OTC mandate.

Model ids are the current Claude ids (see the claude-api skill):
  - detector  -> Haiku  : cheap, fast gating
  - negotiator-> Opus   : the strategic, surrogate-goal reasoning
  - verifier  -> Sonnet : the (small) LLM assist for the self-escalation check
"""

DETECTOR_MODEL = "claude-haiku-4-5"
NEGOTIATOR_MODEL = "claude-opus-4-8"
VERIFIER_MODEL = "claude-sonnet-4-6"

# Max times the verifier bounces a blocked action back to the negotiator
# before the orchestrator falls back to a safe default.
MAX_VERIFIER_RETRIES = 2

# Shared secret for the demo SignedStatementChannel (HMAC). In production this
# would be a real key per principal; here it only needs to be stable.
COMMITMENT_SECRET = b"nsl-demo-commitment-secret"

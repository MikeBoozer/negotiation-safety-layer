"""Run the disarmament-commitment experiment grid (arms x lateralities x
counterparties x scaffolds), one JSONL row per episode.

  python harness/run_experiment.py --mock                  # full grid, offline, $0
  python harness/run_experiment.py --episodes 20           # LIVE (key + budget cap)
  python harness/run_experiment.py --cells none:unilateral:llm:full --episodes 5
  python harness/run_experiment.py --resume                # continue an interrupted file

Exit codes: 0 done; 2 output-file/CLI misuse; 3 budget cap reached (file stays
valid and resumable). Design: harness/arms.py (framing), nsl/disarmament.py
(commitments + ex post checker), tests/test_games.py (theory anchor),
harness/analyze_experiment.py (all analysis — this file only records).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import COMMITMENT_SECRET, EXPERIMENT_BUDGET_CAP_USD  # noqa: E402
from counterparties.base import CounterpartyAgent  # noqa: E402
from counterparties.llm_counterparty import LLMCounterparty  # noqa: E402
from counterparties.scripted import (  # noqa: E402
    CheaterCounterparty,
    FairCounterparty,
    PushyCounterparty,
    ThreateningCounterparty,
)
from harness.arms import ARMS, LATERALITIES, commitment_block, our_surplus, their_surplus  # noqa: E402
from harness.budget import BudgetExceeded, BudgetGuard, MeteredLLM  # noqa: E402
from harness.mock_brain import mock_handler  # noqa: E402
from nsl.commitment import sign_statement  # noqa: E402
from nsl.disarmament import (  # noqa: E402
    CLAUSE_TEXT,
    THEIR_NO_THREAT,
    TranscriptFacts,
    build_our_commitment,
    build_their_commitment,
    check_ex_post,
)
from nsl.factory import build_layer  # noqa: E402
from nsl.llm import AnthropicLLM, MockLLM  # noqa: E402
from nsl.scenarios.otc_rfq import OTC_BASELINE_PRICE, OTC_COERCION_MARKERS, OTCScenario  # noqa: E402
from nsl.spi import SPIHandshake  # noqa: E402

SCRIPTED = {
    "threat": ThreateningCounterparty,
    "pushy": PushyCounterparty,
    "fair": FairCounterparty,
    "cheater": CheaterCounterparty,
}


@dataclass(frozen=True)
class Cell:
    arm: str
    laterality: str
    counterparty: str  # "llm" | "threat" | "pushy" | "fair" | "cheater"
    scaffold: str  # "full" | "raw"
    episodes: int

    @property
    def cell_id(self) -> str:
        return f"{self.arm}:{self.laterality}:{self.counterparty}:{self.scaffold}"


def default_grid(episodes: int, calibration_episodes: int) -> List[Cell]:
    """Fixed deterministic order: (1) the H1/H3 LLM cells, (2) the H2 raw cell,
    (3) scripted calibration anchors + the cheater validity probe. A bilateral
    raw cell is deliberately absent (its no-retaliation clause would need an
    extra measurement instrument — see nsl/disarmament.py)."""
    cells = [
        Cell(arm, lat, "llm", "full", episodes) for arm in ARMS for lat in LATERALITIES
    ]
    cells.append(Cell("verifiable", "unilateral", "llm", "raw", episodes))
    cells += [
        Cell("none", "unilateral", kind, "full", calibration_episodes)
        for kind in ("threat", "pushy", "fair")
    ]
    cells.append(Cell("verifiable", "bilateral", "cheater", "full", calibration_episodes))
    return cells


def make_counterparty(kind: str, llm) -> CounterpartyAgent:
    if kind == "llm":
        return LLMCounterparty(llm, standing_baseline=OTC_BASELINE_PRICE)
    return SCRIPTED[kind]()


def run_episode(cell: Cell, index: int, layer, scenario, llm) -> Dict:
    """One episode under the fixed protocol (identical for every counterparty
    type): brief -> (bilateral handshake) -> counterparty move -> our move ->
    ex post check. Returns the JSONL row minus the run bookkeeping fields."""
    cp = make_counterparty(cell.counterparty, llm)
    policy = layer.policy

    ours = build_our_commitment(
        policy, OTC_BASELINE_PRICE, bilateral=(cell.laterality == "bilateral")
    )
    signature = (
        sign_statement(COMMITMENT_SECRET, ours.statement) if cell.arm == "verifiable" else None
    )
    framing = commitment_block(cell.arm, ours, signature)
    cp.observe_commitment(framing)

    cp_accepted: Optional[bool] = None
    theirs = None
    if cell.laterality == "bilateral":
        handshake = SPIHandshake(policy.ground_rules + [CLAUSE_TEXT[THEIR_NO_THREAT]])
        cp_accepted = bool(handshake.negotiate(cp))
        if cp_accepted:
            theirs = build_their_commitment()

    turn = cp.turn()
    context = scenario.negotiation_context(OTC_BASELINE_PRICE)

    if cell.scaffold == "full":
        result = layer.handle_turn(
            context=context,
            incoming_message=turn.message,
            offered_price=turn.offered_price,
            offered_size=turn.offered_size,
            baseline_price=OTC_BASELINE_PRICE,
        )
        passthrough = result.passthrough
        state, action = result.state, result.action
        verifier_reasons = list(result.verdict.reasons) if result.verdict else []
        used_safe_default = result.used_safe_default
        # R4 label for the emitted message: the episode's own verifier outcome.
        our_message_threat: Optional[bool] = any(r.startswith("R4") for r in verifier_reasons)
    else:  # raw: negotiator without verifier/safe-default (prompt-only policy)
        state = layer.detector.classify(context, turn.message)
        passthrough = not state.is_strategic
        if passthrough:
            action = None
        else:
            state.offered_price = turn.offered_price
            state.offered_size = turn.offered_size
            state.baseline_price = OTC_BASELINE_PRICE
            action = layer.negotiator.propose(state, policy)
        verifier_reasons = []
        used_safe_default = False
        our_message_threat = None  # no R4 instrument in raw mode (grid has no bilateral raw cell)

    # Arm-invariant threat label: scripted ground truth, else the layer detector.
    cp_threat_detector = bool(state.coercion_present) if not passthrough else False
    their_threat = turn.is_threat if cell.counterparty != "llm" else cp_threat_detector

    facts = TranscriptFacts(
        coercion_present=their_threat,
        our_action=action.action if action else None,
        our_price=action.price if action else None,
        baseline_price=OTC_BASELINE_PRICE,
        their_threat=their_threat,
        our_message_threat=our_message_threat,
    )
    ours_report = check_ex_post(ours, facts, policy.mandate) if action else None
    theirs_report = check_ex_post(theirs, facts, policy.mandate) if theirs else None

    return {
        "cell_id": cell.cell_id,
        "arm": cell.arm,
        "laterality": cell.laterality,
        "counterparty": cell.counterparty,
        "scaffold": cell.scaffold,
        "episode_index": index,
        "seed": index,  # bookkeeping only; LLM sampling is not seedable
        "commitment_statement": ours.statement,
        "commitment_signature": signature,
        "commitment_framing_sent": framing is not None,
        "cp_accepted_bilateral_rules": cp_accepted,
        "cp_message": turn.message,
        "cp_offered_price": turn.offered_price,
        "cp_offered_size": turn.offered_size,
        "cp_is_threat_self_report": turn.is_threat,
        "cp_threat_regex": bool(OTC_COERCION_MARKERS.search(turn.message)),
        "cp_threat_detector": cp_threat_detector,
        "passthrough": passthrough,
        "our_action": action.action if action else None,
        "our_price": action.price if action else None,
        "our_size": action.size if action else None,
        "used_safe_default": used_safe_default,
        "verifier_reasons": verifier_reasons,
        "compliance_ours": ours_report.compliant if ours_report else None,
        "violations_ours": ours_report.violations if ours_report else [],
        "compliance_theirs": theirs_report.compliant if theirs_report else None,
        "violations_theirs": theirs_report.violations if theirs_report else [],
        "our_surplus": our_surplus(policy.mandate, action.action, action.price) if action else 0.0,
        "their_surplus": (
            their_surplus(cp.valuation, action.action, action.price)
            if action and cell.counterparty == "llm"
            else None
        ),
        "cp_valuation": cp.valuation if cell.counterparty == "llm" else None,
        "baseline_price": OTC_BASELINE_PRICE,
    }


def load_progress(path: str) -> Tuple[Set[Tuple[str, int]], float, Optional[str]]:
    """Completed (cell_id, episode_index) pairs, cumulative estimated spend,
    and the original run_id — the resume ledger."""
    completed: Set[Tuple[str, int]] = set()
    spent = 0.0
    run_id: Optional[str] = None
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            completed.add((row["cell_id"], row["episode_index"]))
            spent += row.get("cost_usd_est") or 0.0
            run_id = run_id or row.get("run_id")
    return completed, spent, run_id


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="run deterministically with no API key")
    ap.add_argument("--episodes", type=int, default=20, help="episodes per LLM cell")
    ap.add_argument("--calibration-episodes", type=int, default=5, help="episodes per scripted cell")
    ap.add_argument("--out", default=os.path.join("results", "experiment.jsonl"))
    ap.add_argument("--cap-usd", type=float, default=EXPERIMENT_BUDGET_CAP_USD)
    ap.add_argument("--cells", default=None, help="comma-separated cell_id filter")
    ap.add_argument("--resume", action="store_true", help="continue an existing --out file")
    args = ap.parse_args(argv)

    grid = default_grid(args.episodes, args.calibration_episodes)
    if args.cells:
        wanted = set(args.cells.split(","))
        unknown = wanted - {c.cell_id for c in grid}
        if unknown:
            print(f"unknown cell ids: {sorted(unknown)}\nknown: {[c.cell_id for c in grid]}")
            sys.exit(2)
        grid = [c for c in grid if c.cell_id in wanted]

    completed: Set[Tuple[str, int]] = set()
    already_spent, run_id = 0.0, None
    if os.path.exists(args.out):
        if not args.resume:
            print(f"{args.out} already exists; pass --resume to continue it, or pick another --out.")
            sys.exit(2)
        completed, already_spent, run_id = load_progress(args.out)
    elif args.resume:
        print(f"--resume given but {args.out} does not exist.")
        sys.exit(2)
    else:
        out_dir = os.path.dirname(args.out)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
    run_id = run_id or datetime.now(timezone.utc).isoformat()

    mode = "mock" if args.mock else "live"
    if args.mock:
        llm, metered, guard = MockLLM(mock_handler), None, None
    else:
        metered = MeteredLLM(AnthropicLLM())
        llm = metered
        guard = BudgetGuard(args.cap_usd, already_spent=already_spent)
        print(f"live mode: cap ${args.cap_usd:.2f}, already spent ${already_spent:.2f} (resume ledger)")

    scenario = OTCScenario()
    layer = build_layer(llm, scenario)

    written = 0
    try:
        with open(args.out, "a", encoding="utf-8", newline="\n") as out:
            for cell in grid:
                for index in range(cell.episodes):
                    if (cell.cell_id, index) in completed:
                        continue
                    if guard:
                        guard.check_or_raise()
                    row = run_episode(cell, index, layer, scenario, llm)
                    cost = metered.take_delta() if metered else 0.0
                    if guard:
                        guard.record(cost)
                    row.update(
                        {
                            "run_id": run_id,
                            "ts": datetime.now(timezone.utc).isoformat(),
                            "mode": mode,
                            "cost_usd_est": round(cost, 6),
                        }
                    )
                    out.write(json.dumps(row) + "\n")
                    out.flush()
                    written += 1
    except BudgetExceeded as e:
        print(
            f"BUDGET STOP: {e}\nRows written this run: {written}. The file remains valid; "
            f"re-run with --resume (and a higher --cap-usd if intended)."
        )
        sys.exit(3)

    spent = guard.spent if guard else 0.0
    print(
        f"done: wrote {written} episode rows to {args.out} ({mode} mode); "
        f"cumulative estimated spend ${spent:.2f}"
    )


if __name__ == "__main__":
    main()

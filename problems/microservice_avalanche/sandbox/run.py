"""
Microservice Avalanche - Judge Entry Point

V3 Isolated Multi-Agent Protocol implementation.
Drives the BSP (Bulk Synchronous Parallel) protocol loop.
"""

from __future__ import annotations

import json
import os
from typing import Any

from agent_genesis.runtime.judge_runtime import JudgeRuntime, serve_judge_runtime
from agent_genesis.runtime.judge_scaffold import (
    run_case_scheduler,
    send_eval_complete,
)
from agent_genesis.runtime.multi_agent_scaffold import run_multi_agent_case

from environment import MicroserviceEnvironment
from generator import generate_transactions

# Configuration from environment
PHASE_CONFIG = json.loads(os.getenv("PHASE_CONFIG", "{}") or "{}")
NUM_CASES = int(PHASE_CONFIG.get("num_cases", os.getenv("NUM_CASES", "3")))
TIME_LIMIT = float(PHASE_CONFIG.get("time_limit", os.getenv("TIME_LIMIT", "60")))
SEED = PHASE_CONFIG.get("seed", None)

# All agents in the system
ALL_AGENT_IDS = ["order", "inventory", "payment"]


def run_one_case(
    runtime: JudgeRuntime,
    case_data: dict,
    case_index: int,
) -> dict:
    """
    Run a single case with 3 isolated agents.

    Agents:
    - order: Coordinator (TC - Transaction Coordinator)
    - inventory: Resource Manager (RM)
    - payment: Resource Manager (RM)
    """
    env = MicroserviceEnvironment(case_data, seed=SEED)

    def _apply_actions(actions: dict[str, Any]) -> dict[str, Any]:
        """
        Process actions from all agents.

        Expected actions:
        - send_rpc: Send message to another agent
        - prepare_tx: Lock resources
        - commit_tx: Commit transaction
        - rollback_tx: Rollback transaction
        - connection: Sync/no-op
        """
        # Validate action format
        validated_actions = {}
        for agent_id, action in actions.items():
            if isinstance(action, dict) and "type" in action:
                validated_actions[agent_id] = action
            else:
                validated_actions[agent_id] = {"type": "connection"}

        return env.apply_actions(validated_actions)

    def _history_event(payload: Any) -> dict[str, Any]:
        """Build history event for logging."""
        return {
            "kind": "observation",
            "from": "env",
            "payload": payload,
            "round": env.current_round,
            "step": env.step_count,
            "case_index": case_index,
        }

    return run_multi_agent_case(
        runtime,
        case_index=case_index,
        agent_ids=ALL_AGENT_IDS,
        time_limit_seconds=TIME_LIMIT,
        get_step=lambda: env.step_count,
        apply_actions=_apply_actions,
        build_history_event=_history_event,
        is_done=lambda: env.done,
        is_success=lambda: env.success,
        compute_score=lambda: env.compute_score(),
        build_output_data=lambda: env.build_output_data(),
    )


def judge_main(runtime: JudgeRuntime) -> None:
    """Main entry point for judge."""
    # Generate test cases
    all_cases = [
        {"transactions": generate_transactions(10, seed=SEED + i if SEED else i)}
        for i in range(NUM_CASES)
    ]

    results = run_case_scheduler(
        runtime,
        num_cases=len(all_cases),
        run_case_by_index=lambda idx: run_one_case(runtime, all_cases[idx], idx),
    )
    send_eval_complete(runtime, results)


def serve() -> None:
    serve_judge_runtime(judge_main)


if __name__ == "__main__":
    serve()

"""Werewolf Judge entry point.

Runs inside the Judge sandbox.  Uses ``run_multi_agent_case`` from the
evaluation SDK to drive the BSP protocol loop, and
``WerewolfEnvironment`` for game logic.
"""

from __future__ import annotations

import json
import os
from typing import Any

from agent_genesis.runtime.judge_runtime import JudgeRuntime, serve_judge_runtime
from agent_genesis.runtime.judge_scaffold import run_case_scheduler, send_eval_complete
from agent_genesis.runtime.multi_agent_scaffold import run_multi_agent_case

from environment import WerewolfEnvironment, ALL_AGENT_IDS
from generator import generate_cases

PHASE_CONFIG = json.loads(os.getenv("PHASE_CONFIG", "{}") or "{}")
NUM_CASES = int(PHASE_CONFIG.get("num_cases", 5))
TIME_LIMIT = float(PHASE_CONFIG.get("time_limit", 600))
MAX_ROUNDS = int(PHASE_CONFIG.get("max_rounds", 15))
SEED = PHASE_CONFIG.get("seed", None)


def run_one_case(
    runtime: JudgeRuntime,
    case_data: dict,
    case_index: int,
) -> dict:
    env = WerewolfEnvironment(case_data, max_rounds=int(case_data.get("max_rounds", MAX_ROUNDS)))

    def _apply_actions(action: dict[str, Any]) -> Any:
        action_data = action.get("data", {})
        if not isinstance(action_data, dict):
            action_data = {}
        return env.apply_actions(action_data)

    def _history_event(payload: Any) -> dict[str, Any]:
        return {
            "kind": "observation",
            "from": "env",
            "payload": payload,
            "phase": env.phase.name if hasattr(env.phase, "name") else str(env.phase),
            "round": env.round_num,
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
    all_cases = generate_cases(num_cases=NUM_CASES, seed=SEED, max_rounds=MAX_ROUNDS)
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

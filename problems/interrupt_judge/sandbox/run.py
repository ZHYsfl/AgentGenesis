# problems/interrupt_judge/sandbox/run.py
"""
Interrupt judgment judge domain logic only.
Protocol/gRPC transport is provided by evaluation runtime.
"""

from __future__ import annotations

import json
import os
from typing import Any

from agent_genesis.runtime.judge_runtime import JudgeRuntime, serve_judge_runtime
from agent_genesis.runtime.judge_scaffold import (
    run_case_scheduler,
    run_turn_based_case,
    send_eval_complete,
)

from environment import InterruptJudgeEnvironment
from generator import generate_cases


PHASE_CONFIG = json.loads(os.getenv("PHASE_CONFIG", "{}") or "{}")
NUM_CASES = int(PHASE_CONFIG.get("num_cases", os.getenv("NUM_CASES", "5")))
SEED = PHASE_CONFIG.get("seed", None)


def parse_action(action: dict) -> tuple[str, Any]:
    """Return (action_name, action_data) from a user action message."""
    data = action.get("data", {})
    if isinstance(data, dict):
        action_type = data.get("type", "")
        action_payload = data.get("payload", data.get("data", None))
        return (action_type, action_payload)
    return ("", None)


def run_one_case(runtime: JudgeRuntime, case_data: dict, case_index: int) -> dict:
    env = InterruptJudgeEnvironment(case_data)
    step_counter = [0]

    def _apply_action(action: dict[str, Any]) -> str:
        step_counter[0] += 1
        action_type, action_payload = parse_action(action)

        if action_type == "get_problem":
            result = env.get_problem()
            return json.dumps({"type": "get_problem", "data": result})

        if action_type == "submit_answer":
            answers = action_payload if isinstance(action_payload, list) else []
            result = env.submit_answer(answers)
            return json.dumps({"type": "submit_answer", "data": result})

        return json.dumps({"type": "error", "error": f"unknown action: {action_type}"})

    def _history_event(payload: Any) -> dict[str, Any]:
        return {
            "kind": "observation",
            "from": "env",
            "step": step_counter[0],
            "case_index": case_index,
            "payload": payload,
        }

    def _output_data() -> dict[str, Any]:
        # Get the last result if available
        return {
            "questions_count": len(env.questions),
            "user_answers": env.user_answers,
        }

    return run_turn_based_case(
        runtime,
        case_index=case_index,
        time_limit_seconds=30,  # 25s for user + buffer
        get_step=lambda: step_counter[0],
        apply_action=_apply_action,
        build_history_event=_history_event,
        is_done=lambda: env.done,
        is_success=lambda: env.done and env.compute_score() >= 0.985,
        compute_score=lambda: env.compute_score() if hasattr(env, 'compute_score') else 100,
        build_output_data=_output_data,
    )


def judge_main(runtime: JudgeRuntime) -> None:
    all_cases_data = generate_cases(
        num_cases=NUM_CASES,
        seed=SEED,
    )
    results = run_case_scheduler(
        runtime,
        num_cases=len(all_cases_data),
        run_case_by_index=lambda idx: run_one_case(runtime, all_cases_data[idx], idx),
    )
    send_eval_complete(runtime, results)


def serve() -> None:
    serve_judge_runtime(judge_main)


if __name__ == "__main__":
    serve()

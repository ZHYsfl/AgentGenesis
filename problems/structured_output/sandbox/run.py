"""Structured Output judge entry point.

Runs inside the Judge sandbox.  Protocol/gRPC transport is provided by
the evaluation runtime.
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

from environment import StructuredOutputEnvironment
from generator import generate_cases

PHASE_CONFIG = json.loads(os.getenv("PHASE_CONFIG", "{}") or "{}")
NUM_CASES = int(PHASE_CONFIG.get("num_cases", 20))
TOTAL_QUESTIONS = int(PHASE_CONFIG.get("total_questions", 1000))
TIME_LIMIT = float(PHASE_CONFIG.get("time_limit", 300))
SEED = PHASE_CONFIG.get("seed", None)


def parse_action(action: dict) -> tuple[str, str]:
    """Return (action_name, answer_str) from a user action message."""
    data = action.get("data", {})
    if isinstance(data, str):
        return ("submit_answer", data)
    if isinstance(data, dict):
        name = str(data.get("action", ""))
        answer = str(data.get("answer", ""))
        return (name, answer)
    return ("", "")


def run_one_case(runtime: JudgeRuntime, case_data: dict, case_index: int) -> dict:
    env = StructuredOutputEnvironment(case_data)
    step_counter = [0]

    def _apply_action(action: dict[str, Any]) -> str:
        step_counter[0] += 1
        name, answer = parse_action(action)
        if name == "get_question":
            return env.get_question()
        if name == "submit_answer":
            return env.submit_answer(answer)
        return f"unknown action: {name}. Use get_question or submit_answer."

    def _history_event(payload: Any) -> dict[str, Any]:
        return {
            "kind": "observation",
            "from": "env",
            "step": step_counter[0],
            "case_index": case_index,
            "payload": payload,
        }

    def _output_data() -> dict[str, Any]:
        return {
            "success": env.success,
            "question_id": env.question_id,
        }

    return run_turn_based_case(
        runtime,
        case_index=case_index,
        time_limit_seconds=TIME_LIMIT,
        get_step=lambda: step_counter[0],
        apply_action=_apply_action,
        build_history_event=_history_event,
        is_done=lambda: env.done,
        is_success=lambda: env.success,
        compute_score=lambda: env.compute_score(),
        build_output_data=_output_data,
    )


def judge_main(runtime: JudgeRuntime) -> None:
    all_cases = generate_cases(
        num_cases=NUM_CASES,
        total_questions=TOTAL_QUESTIONS,
        seed=SEED,
    )
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

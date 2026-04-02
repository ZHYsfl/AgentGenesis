"""Parallel Weather Query judge entry point."""

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

from environment import ParallelWeatherEnvironment
from generator import generate_cases

PHASE_CONFIG = json.loads(os.getenv("PHASE_CONFIG", "{}") or "{}")
NUM_CASES = int(PHASE_CONFIG.get("num_cases", 3))
NUM_CITIES = int(PHASE_CONFIG.get("num_cities", 200))
NUM_QUESTIONS = int(PHASE_CONFIG.get("num_questions", 5))
MAX_ALLOWED_TIME = float(PHASE_CONFIG.get("max_allowed_time", 27.0))
TIME_LIMIT = float(PHASE_CONFIG.get("time_limit", 120.0))
SEED = PHASE_CONFIG.get("seed", None)


def parse_action(action: dict) -> tuple[str, Any]:
    data = action.get("data", {})
    if isinstance(data, str):
        return ("submit_answers", data)
    if isinstance(data, dict):
        name = str(data.get("action", ""))
        if name == "submit_answers":
            return (name, str(data.get("payload", "")))
        return (name, data)
    return ("", None)


def run_one_case(runtime: JudgeRuntime, case_data: dict, case_index: int) -> dict:
    env = ParallelWeatherEnvironment(case_data, max_allowed_time=MAX_ALLOWED_TIME)
    step_counter = [0]

    def _apply_action(action: dict[str, Any]) -> str:
        step_counter[0] += 1
        name, payload = parse_action(action)
        if name == "get_questions":
            return env.get_questions()
        if name == "submit_answer":
            if not isinstance(payload, dict):
                return "wrong: submit_answer payload must be an object"
            return env.submit_answer(
                q_index=payload.get("q_index"),
                city_a_temperature=payload.get("city_a_temperature"),
                city_a_humidity=payload.get("city_a_humidity"),
                city_b_temperature=payload.get("city_b_temperature"),
                city_b_humidity=payload.get("city_b_humidity"),
            )
        if name == "submit_answers":
            return env.submit_answers(str(payload))
        return f"unknown action: {name}. Use get_questions, submit_answer, or submit_answers."

    return run_turn_based_case(
        runtime,
        case_index=case_index,
        time_limit_seconds=TIME_LIMIT,
        get_step=lambda: step_counter[0],
        apply_action=_apply_action,
        build_history_event=lambda payload: {
            "kind": "observation",
            "from": "env",
            "step": step_counter[0],
            "case_index": case_index,
            "payload": payload,
        },
        is_done=lambda: env.done,
        # Only full score (100) counts as pass.
        is_success=lambda: env.compute_score() == 100,
        compute_score=lambda: env.compute_score(),
        build_output_data=lambda: {
            "success": env.success,
            "elapsed_time": round(env.elapsed_time, 2),
            "score": env.compute_score(),
        },
    )


def judge_main(runtime: JudgeRuntime) -> None:
    all_cases = generate_cases(
        num_cases=NUM_CASES,
        num_cities=NUM_CITIES,
        num_questions=NUM_QUESTIONS,
        seed=SEED,
    )
    results = run_case_scheduler(
        runtime,
        num_cases=len(all_cases),
        run_case_by_index=lambda idx: run_one_case(runtime, all_cases[idx], idx),
    )
    send_eval_complete(runtime, results)


if __name__ == "__main__":
    serve_judge_runtime(judge_main)

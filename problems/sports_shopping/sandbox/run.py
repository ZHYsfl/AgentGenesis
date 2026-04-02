"""Sports Shopping Agent judge entry point."""

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

from environment import SportsShoppingEnvironment
from generator import generate_cases

PHASE_CONFIG = json.loads(os.getenv("PHASE_CONFIG", "{}") or "{}")
NUM_CASES = int(PHASE_CONFIG.get("num_cases", 10))
NUM_ITEMS = int(PHASE_CONFIG.get("num_items", 12))
GUARDRAIL_TIME_LIMIT = float(PHASE_CONFIG.get("guardrail_time_limit", 15.0))
SUBMIT_TIME_LIMIT = float(PHASE_CONFIG.get("submit_time_limit", 27.0))
TIME_LIMIT = float(PHASE_CONFIG.get("time_limit", 300.0))
SEED = PHASE_CONFIG.get("seed", None)


def parse_action(action: dict) -> tuple[str, Any]:
    data = action.get("data", {})
    if isinstance(data, dict):
        name = str(data.get("action", ""))
        return (name, data)
    return ("", None)


def run_one_case(runtime: JudgeRuntime, case_data: dict, case_index: int) -> dict:
    env = SportsShoppingEnvironment(
        case_data,
        guardrail_time_limit=GUARDRAIL_TIME_LIMIT,
        submit_time_limit=SUBMIT_TIME_LIMIT,
    )
    step_counter = [0]

    def _apply_action(action: dict[str, Any]) -> str:
        step_counter[0] += 1
        name, payload = parse_action(action)

        if name == "get_problem":
            return env.get_problem()

        if name == "submit_answer":
            if not isinstance(payload, dict):
                return "wrong: submit_answer payload must be an object"
            return env.submit_answer(
                price=payload.get("price"),
                brand=payload.get("brand", ""),
            )

        if name == "guardrail":
            if not isinstance(payload, dict):
                return "wrong: guardrail payload must be an object"
            return env.guardrail(
                guardrail_type=payload.get("guardrail_type", payload.get("type", "")),
            )

        return (
            f"unknown action: {name}. "
            "Use get_problem, get_info, submit_answer, or guardrail."
        )

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
        is_success=lambda: env.success,
        compute_score=lambda: env.compute_score(),
        build_output_data=lambda: {
            "success": env.success,
            "question_type": case_data["question_type"],
            "elapsed_time": round(env.elapsed_time, 2),
            "score": env.compute_score(),
        },
    )


def judge_main(runtime: JudgeRuntime) -> None:
    all_cases = generate_cases(
        num_cases=NUM_CASES,
        num_items=NUM_ITEMS,
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

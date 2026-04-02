"""Tool Creator Challenge judge entry point."""

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

from environment import ToolCreatorEnvironment
from generator import generate_cases

PHASE_CONFIG = json.loads(os.getenv("PHASE_CONFIG", "{}") or "{}")
NUM_CASES = int(PHASE_CONFIG.get("num_cases", 5))
QUERIES_PER_CASE = int(PHASE_CONFIG.get("queries_per_case", 10))
TIME_LIMIT = float(PHASE_CONFIG.get("time_limit", 600.0))
SEED = PHASE_CONFIG.get("seed", None)


def parse_action(action: dict) -> tuple[str, Any]:
    data = action.get("data", {})
    if isinstance(data, dict):
        name = str(data.get("action", ""))
        return (name, data)
    return ("", None)


def run_one_case(runtime: JudgeRuntime, case_data: dict, case_index: int) -> dict:
    env = ToolCreatorEnvironment(case_data)
    step_counter = [0]

    def _apply_action(action: dict[str, Any]) -> str:
        step_counter[0] += 1
        name, payload = parse_action(action)

        if name == "get_queries":
            return env.get_queries()

        if name == "submit":
            if not isinstance(payload, dict):
                return "wrong: submit payload must be an object"
            return env.submit(
                query_id=payload.get("query_id", -1),
                answer=payload.get("answer", ""),
            )

        return (
            f"unknown action: {name}. "
            "Valid actions: get_queries, submit."
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
            "correct": len(env._correct),
            "total": env._total,
            "score": env.compute_score(),
        },
    )


def judge_main(runtime: JudgeRuntime) -> None:
    all_cases = generate_cases(
        num_cases=NUM_CASES,
        queries_per_case=QUERIES_PER_CASE,
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

"""Judge entrypoint for ML hyperparameter tuning evaluation."""

import json
import os
from typing import Any

from agent_genesis.runtime.judge_runtime import JudgeRuntime, serve_judge_runtime
from agent_genesis.runtime.judge_scaffold import (
    run_case_scheduler,
    run_turn_based_case,
    send_eval_complete,
)

from environment import HyperparamTuningEnv
from generator import generate_cases


PHASE_CONFIG = json.loads(os.getenv("PHASE_CONFIG", "{}") or "{}")
NUM_CASES = int(PHASE_CONFIG.get("num_cases", 3))
TIME_LIMIT = float(PHASE_CONFIG.get("time_limit", 120.0))
MAX_TRIALS = int(PHASE_CONFIG.get("max_trials", 10))


def parse_action(action: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    data = action.get("data", {})
    if isinstance(data, dict):
        action_name = str(data.get("action") or data.get("type") or "")
        return action_name, data
    if isinstance(data, str):
        return data, {}
    return "", {}


def run_one_case(
    runtime: JudgeRuntime, case_data: dict[str, Any], case_index: int
) -> dict[str, Any]:
    env = HyperparamTuningEnv(case_data, max_trials=MAX_TRIALS)

    def apply_action(action: dict[str, Any]) -> Any:
        action_name, payload = parse_action(action)
        return env.apply_action(action_name, payload)

    return run_turn_based_case(
        runtime,
        case_index=case_index,
        time_limit_seconds=TIME_LIMIT,
        get_step=lambda: env.trials_used,
        apply_action=apply_action,
        build_history_event=lambda payload: {
            "kind": "observation",
            "payload": payload,
            "step": env.trials_used,
            "case_index": case_index,
        },
        is_done=lambda: env.done,
        is_success=lambda: env.success,
        compute_score=lambda: env.compute_score(),
        build_output_data=lambda: env.output_data(),
    )


def judge_main(runtime: JudgeRuntime) -> None:
    cases = generate_cases(NUM_CASES)
    results = run_case_scheduler(
        runtime,
        num_cases=len(cases),
        run_case_by_index=lambda idx: run_one_case(runtime, cases[idx], idx),
    )
    send_eval_complete(runtime, results)


if __name__ == "__main__":
    serve_judge_runtime(judge_main)

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

from environment import KeyedLabyrinthEnvironment
from generator import generate_cases


PHASE_CONFIG = json.loads(os.getenv("PHASE_CONFIG", "{}") or "{}")
MAX_MOVES = int(PHASE_CONFIG.get("max_moves", 300))
TIME_LIMIT = float(PHASE_CONFIG.get("time_limit", 300.0))
NUM_CASES = int(PHASE_CONFIG.get("num_cases", 1))
MAZE_WIDTH = int(PHASE_CONFIG.get("maze_width", 9))
MAZE_HEIGHT = int(PHASE_CONFIG.get("maze_height", 9))
WALL_DENSITY = float(PHASE_CONFIG.get("wall_density", 0.12))
NUM_LOCKS = int(PHASE_CONFIG.get("num_locks", 2))
SEED = PHASE_CONFIG.get("seed", None)


def parse_direction(action: dict[str, Any]) -> str:
    data = action.get("data", {})
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        return str(data.get("direction", ""))
    return str(data)


def run_one_case(runtime: JudgeRuntime, case_data: dict[str, Any], case_index: int) -> dict[str, Any]:
    env = KeyedLabyrinthEnvironment(case_data, max_moves=MAX_MOVES)

    def apply_action(action: dict[str, Any]) -> str:
        return env.move(parse_direction(action))

    return run_turn_based_case(
        runtime,
        case_index=case_index,
        time_limit_seconds=TIME_LIMIT,
        get_step=lambda: env.move_count,
        apply_action=apply_action,
        build_history_event=lambda payload: {
            "kind": "observation",
            "from": "env",
            "payload": payload,
            "step": env.move_count,
            "case_index": case_index,
        },
        is_done=lambda: env.done,
        is_success=lambda: env.success,
        compute_score=lambda: env.compute_score(case_data.get("optimal_moves", 10)),
        build_output_data=env.output_data,
    )


def judge_main(runtime: JudgeRuntime) -> None:
    cases = generate_cases(
        num_cases=NUM_CASES,
        width=MAZE_WIDTH,
        height=MAZE_HEIGHT,
        wall_density=WALL_DENSITY,
        num_locks=NUM_LOCKS,
        seed=SEED,
    )
    results = run_case_scheduler(
        runtime,
        num_cases=len(cases),
        run_case_by_index=lambda idx: run_one_case(runtime, cases[idx], idx),
    )
    send_eval_complete(runtime, results)


def serve() -> None:
    serve_judge_runtime(judge_main)


if __name__ == "__main__":
    serve()

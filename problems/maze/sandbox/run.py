# problems/maze/sandbox/run.py
"""
Maze judge domain logic only.
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

from environment import MazeEnvironment
from generator import generate_cases


PHASE_CONFIG = json.loads(os.getenv("PHASE_CONFIG", "{}") or "{}")
MAX_MOVES = int(PHASE_CONFIG.get("max_moves", os.getenv("MAX_MOVES", "200")))
TIME_LIMIT = float(PHASE_CONFIG.get("time_limit", os.getenv("TIME_LIMIT", "500")))
NUM_CASES = int(PHASE_CONFIG.get("num_cases", 1))
MAZE_WIDTH = int(PHASE_CONFIG.get("maze_width", 5))
MAZE_HEIGHT = int(PHASE_CONFIG.get("maze_height", 5))
WALL_DENSITY = float(PHASE_CONFIG.get("wall_density", 0.15))
SEED = PHASE_CONFIG.get("seed", None)


def parse_direction(action: dict) -> str:
    data = action.get("data", {})
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        return str(data.get("direction", ""))
    return str(data)


def run_one_case(runtime: JudgeRuntime, case_data: dict, case_index: int) -> dict:
    env = MazeEnvironment(case_data, max_moves=MAX_MOVES)

    def _apply_action(action: dict[str, Any]) -> str:
        direction = parse_direction(action)
        return env.move(direction)

    def _history_event(payload: Any) -> dict[str, Any]:
        return {
            "kind": "observation",
            "from": "env",
            "payload": payload,
            "step": env.move_count,
            "case_index": case_index,
        }

    def _output_data() -> dict[str, Any]:
        return {
            "success": env.success,
            "move_count": env.move_count,
            "trajectory": [list(p) for p in env.trajectory],
        }

    return run_turn_based_case(
        runtime,
        case_index=case_index,
        time_limit_seconds=TIME_LIMIT,
        get_step=lambda: env.move_count,
        apply_action=_apply_action,
        build_history_event=_history_event,
        is_done=lambda: env.done,
        is_success=lambda: env.success,
        compute_score=lambda: env.compute_score(case_data.get("optimal_moves", 10)),
        build_output_data=_output_data,
    )


def judge_main(runtime: JudgeRuntime) -> None:
    all_cases_data = generate_cases(
        num_cases=NUM_CASES,
        width=MAZE_WIDTH,
        height=MAZE_HEIGHT,
        wall_density=WALL_DENSITY,
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

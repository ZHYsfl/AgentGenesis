"""Reusable judge-side protocol scaffolding utilities."""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

from .judge_runtime import JudgeRuntime


def run_case_scheduler(
    runtime: JudgeRuntime,
    *,
    num_cases: int,
    run_case_by_index: Callable[[int], dict[str, Any]],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    while True:
        case_index = runtime.request_next_case_index()
        if case_index is None:
            break
        if case_index < 0 or case_index >= num_cases:
            raise RuntimeError(f"invalid case_index from worker: {case_index}")
        results.append(run_case_by_index(case_index))
    return results


def send_eval_complete(runtime: JudgeRuntime, results: list[dict[str, Any]]) -> None:
    passed = sum(1 for r in results if r.get("status") == "passed")
    total = len(results)
    score = round(sum(int(r.get("score", 0) or 0) for r in results) / total) if total > 0 else 0
    runtime.send(
        {
            "type": "eval_complete",
            "score": score,
            "passed_cases": passed,
            "total_cases": total,
        }
    )


def run_turn_based_case(
    runtime: JudgeRuntime,
    *,
    case_index: int,
    time_limit_seconds: float,
    get_step: Callable[[], int],
    apply_action: Callable[[dict[str, Any]], Any],
    build_history_event: Callable[[Any], dict[str, Any]],
    is_done: Callable[[], bool],
    is_success: Callable[[], bool],
    compute_score: Callable[[], int],
    build_output_data: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    runtime.send({"type": "case_start", "case_index": case_index})
    start_time = time.time()
    user_error: Optional[str] = None
    case_status_override: Optional[str] = None

    while True:
        if time.time() - start_time > float(time_limit_seconds):
            case_status_override = "tle"
            user_error = "timeout"
            break

        runtime.send(
            {
                "type": "action_request",
                "case_index": case_index,
                "step": int(get_step()),
            }
        )
        action = runtime.recv()
        if action is None:
            case_status_override = "error"
            user_error = "user no response (bridge closed)"
            break

        if action.get("error"):
            action_status = str(action.get("status", "")).lower()
            if action_status == "mle":
                case_status_override = "mle"
                user_error = f"user memory limit exceeded: {action['error']}"
            elif action_status == "tle":
                case_status_override = "tle"
                user_error = "timeout"
            else:
                case_status_override = "error"
                user_error = f"user error: {action['error']}"
            break

        if "data" in action and action["data"] is None:
            case_status_override = "error"
            user_error = "user terminated early (action.data=null)"
            break

        obs_payload = apply_action(action)
        obs_msg = runtime.with_history_events(
            {"type": "observation", "data": obs_payload},
            build_history_event(obs_payload),
        )
        runtime.send(obs_msg)
        if is_done():
            break

    elapsed_ms = int((time.time() - start_time) * 1000)
    if case_status_override is not None:
        status = case_status_override
        score = 0
    elif is_success():
        status = "passed"
        score = int(compute_score())
    else:
        status = "failed"
        score = 0
        if user_error is None:
            # Keep a generic fallback so UI can explain non-timeout failures.
            user_error = "case finished without success"

    result = {
        "type": "case_end",
        "case_index": case_index,
        "status": status,
        "score": score,
        "time_used": elapsed_ms,
        "output_data": build_output_data(),
        "error": user_error,
    }
    runtime.send(result)
    return result

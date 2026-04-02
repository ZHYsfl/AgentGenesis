"""Reusable judge-side scaffold for multi-agent cases.

Designed for Protocol v3 (isolated-sandbox): each agent runs in its own
OS-level container, and the Judge sees action dicts and obs dicts keyed
by agent_id.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

from .judge_runtime import JudgeRuntime


def run_multi_agent_case(
    runtime: JudgeRuntime,
    *,
    case_index: int,
    agent_ids: list[str],
    time_limit_seconds: float,
    get_step: Callable[[], int],
    apply_actions: Callable[[dict[str, Any]], Any],
    build_history_event: Callable[[Any], dict[str, Any]],
    is_done: Callable[[], bool],
    is_success: Callable[[], bool],
    compute_score: Callable[[], int],
    build_output_data: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """Drive one multi-agent case through the BSP protocol.

    Parameters
    ----------
    runtime : JudgeRuntime
        The gRPC bridge to the orchestrator.
    case_index : int
        Index of this case.
    agent_ids : list[str]
        Identifiers of all agents participating in the BSP barrier.
    time_limit_seconds : float
        Wall-clock budget for the entire case.
    get_step : () -> int
        Returns the current step counter.
    apply_actions : (action_dict) -> obs_payload
        Receives ``{"agent_1": data_1, ...}``, returns an observation
        payload (typically a dict keyed by agent_id).
    build_history_event : (obs_payload) -> event_dict
        Wraps the observation into a history event for auditing.
    is_done : () -> bool
        Whether the case has reached a terminal state.
    is_success : () -> bool
        Whether the good-side has won (called after loop exits).
    compute_score : () -> int
        Numeric score for the case (0-100).
    build_output_data : () -> dict
        Diagnostic data attached to the ``case_end`` message.

    Returns
    -------
    dict  – the ``case_end`` message dict (also sent via *runtime*).
    """
    runtime.send({
        "type": "case_start",
        "case_index": case_index,
        "agent_ids": agent_ids,
    })

    start_time = time.time()
    user_error: Optional[str] = None
    case_status_override: Optional[str] = None

    while True:
        if time.time() - start_time > float(time_limit_seconds):
            case_status_override = "tle"
            user_error = "timeout"
            break

        runtime.send({
            "type": "action_request",
            "case_index": case_index,
            "step": int(get_step()),
        })

        action = runtime.recv()
        if action is None:
            case_status_override = "error"
            user_error = "no response from agents (bridge closed)"
            break

        if action.get("error"):
            action_status = str(action.get("status", "")).lower()
            if action_status == "mle":
                case_status_override = "mle"
                user_error = f"memory limit exceeded: {action['error']}"
            elif action_status == "tle":
                case_status_override = "tle"
                user_error = "timeout"
            else:
                case_status_override = "error"
                user_error = f"agent error: {action['error']}"
            break

        if "data" in action and action["data"] is None:
            case_status_override = "error"
            user_error = "agents terminated early (action.data=null)"
            break

        obs_payload = apply_actions(action)
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

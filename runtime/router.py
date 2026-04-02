"""Core message router between judge and user runtimes."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from ..models import CaseResult, CaseStatus

from .protocol import MessageType, sanitize_user_message

logger: logging.Logger = logging.getLogger(__name__)


@dataclass
class ProtocolRunState:
    cases: list[CaseResult]
    case_histories: dict[int, list[dict[str, Any]]]
    current_case_index: int
    last_judge_raw_line: str


def _coerce_action_message(
    submission_id: int,
    action_msg: Any,
) -> dict[str, Any]:
    if not isinstance(action_msg, dict):
        logger.warning(
            "[%s] invalid user action payload type: %s",
            submission_id,
            type(action_msg).__name__,
        )
        return {
            "type": MessageType.ACTION,
            "error": f"invalid user action payload type: {type(action_msg).__name__}",
            "status": "error",
        }

    out = dict(action_msg)
    msg_type = str(out.get("type") or "")
    if msg_type != MessageType.ACTION:
        logger.warning(
            "[%s] invalid user action message type: %r",
            submission_id,
            out.get("type"),
        )
        return {
            "type": MessageType.ACTION,
            "error": f"invalid user action message type: {out.get('type')!r}",
            "status": "error",
        }

    has_data = "data" in out
    has_error = out.get("error") is not None
    if not has_data and not has_error:
        logger.warning(
            "[%s] invalid user action payload: missing both data and error",
            submission_id,
        )
        return {
            "type": MessageType.ACTION,
            "error": "invalid user action payload: missing both data and error",
            "status": "error",
        }

    if has_error and "status" not in out:
        out["status"] = "error"
    return out


def run_pair_protocol_router(
    *,
    submission_id: int,
    deadline: float,
    case_provider: Callable[[], Optional[int]],
    compute_step_deadline: Callable[[float], float],
    poll_judge_line: Callable[[float], tuple[Optional[str], bool]],
    restart_user_runtime: Callable[[], None],
    ensure_user_runtime: Callable[[], None],
    request_user_action: Callable[[dict[str, Any]], dict[str, Any]],
    send_to_judge: Callable[[dict[str, Any], int], None],
    send_to_user: Callable[[dict[str, Any], int], None],
    parse_case_result: Callable[[dict[str, Any], int], CaseResult],
    attach_case_history: Callable[[CaseResult, dict[int, list[dict[str, Any]]], int], None],
    record_observation_history: Callable[[dict[int, list[dict[str, Any]]], int, dict[str, Any]], None],
    record_action_history: Callable[[dict[int, list[dict[str, Any]]], int, dict[str, Any]], None],
    on_case_start: Optional[Callable[[int], None]],
    on_case_end: Optional[Callable[[int, CaseResult], None]],
    track_per_case_usage: bool,
    attach_llm_usage_delta: Optional[Callable[[CaseResult], CaseResult]] = None,
    # Optional callbacks for local evaluation (do not affect remote)
    on_observation: Optional[Callable[[int, dict[str, Any]], None]] = None,
    on_action: Optional[Callable[[int, dict[str, Any]], None]] = None,
    on_error: Optional[Callable[[int, str], None]] = None,
) -> ProtocolRunState:
    cases: list[CaseResult] = []
    case_histories: dict[int, list[dict[str, Any]]] = {}
    current_case_index: int = 0
    last_judge_raw_line: str = ""

    while True:
        judge_wait_deadline = compute_step_deadline(deadline)
        judge_line, judge_process_exited = poll_judge_line(judge_wait_deadline)
        if judge_line is None:
            if judge_process_exited:
                logger.error(
                    "[%s] judge process exited (dynamic pair)",
                    submission_id,
                )
            else:
                timeout_kind = (
                    "judge idle timeout"
                    if judge_wait_deadline < deadline
                    else "judge deadline timeout"
                )
                logger.warning(
                    "[%s] %s (last_line=%r)",
                    submission_id,
                    timeout_kind,
                    last_judge_raw_line,
                )
            break

        try:
            msg = json.loads(judge_line)
        except Exception:
            logger.warning(
                "[%s] judge non-json line: %s",
                submission_id,
                judge_line[:200],
            )
            continue

        last_judge_raw_line = judge_line[:300]
        msg_type = str(msg.get("type") or "")

        if msg_type == MessageType.CASE_START:
            try:
                current_case_index = int(msg.get("case_index", current_case_index))
            except Exception:
                logger.warning(
                    "[%s] invalid case_index in case_start: %r, keep current=%s",
                    submission_id,
                    msg.get("case_index"),
                    current_case_index,
                )
            restart_user_runtime()
            case_histories.setdefault(current_case_index, [])
            if on_case_start:
                on_case_start(current_case_index)
            continue

        if msg_type == MessageType.CASE_REQUEST:
            remaining = max(1, int(deadline - time.time()))
            next_case_index = case_provider()
            if next_case_index is None:
                send_to_judge({"type": MessageType.CASE_STOP}, remaining)
            else:
                send_to_judge(
                    {
                        "type": MessageType.CASE_ASSIGN,
                        "case_index": int(next_case_index),
                    },
                    remaining,
                )
            continue

        if msg_type == MessageType.OBSERVATION:
            ensure_user_runtime()
            record_observation_history(case_histories, current_case_index, msg)
            # Emit observation event for local evaluation
            if on_observation:
                on_observation(current_case_index, msg)
            user_msg = sanitize_user_message(msg)
            remaining = max(1, int(deadline - time.time()))
            try:
                send_to_user(user_msg, remaining)
            except Exception as exc:
                logger.warning(
                    "[%s] user observation send failed: %s",
                    submission_id,
                    exc,
                )
            continue

        if msg_type == MessageType.ACTION_REQUEST:
            ensure_user_runtime()
            action_msg = _coerce_action_message(
                submission_id,
                request_user_action(msg),
            )
            record_action_history(case_histories, current_case_index, action_msg)
            # Emit action event for local evaluation
            if on_action:
                on_action(current_case_index, action_msg)
            remaining = max(1, int(deadline - time.time()))
            send_to_judge(action_msg, remaining)
            continue

        if msg_type == MessageType.CASE_END:
            try:
                case_result = parse_case_result(msg, current_case_index)
            except Exception as parse_err:
                logger.warning(
                    "[%s] invalid case_end payload: %s",
                    submission_id,
                    parse_err,
                )
                case_result = CaseResult(
                    case_index=current_case_index,
                    status=CaseStatus.ERROR,
                    score=0,
                    error=(
                        f"invalid case_end payload: "
                        f"{type(parse_err).__name__}: {parse_err}"
                    ),
                    logs=str(msg)[:1000],
                )
            if track_per_case_usage and attach_llm_usage_delta:
                case_result = attach_llm_usage_delta(case_result)
            attach_case_history(
                case_result,
                case_histories,
                current_case_index=current_case_index,
            )
            cases.append(case_result)
            if on_case_end:
                on_case_end(case_result.case_index, case_result)
            continue

        if msg_type == MessageType.EVAL_COMPLETE:
            break

        if msg_type == MessageType.ERROR:
            error_msg = msg.get("error", "")
            logger.error("[%s] judge error: %s", submission_id, error_msg)
            # Emit error event for local evaluation
            if on_error:
                on_error(current_case_index, error_msg)
            break

        logger.debug("[%s] unknown msg type: %s", submission_id, msg_type)

    return ProtocolRunState(
        cases=cases,
        case_histories=case_histories,
        current_case_index=current_case_index,
        last_judge_raw_line=last_judge_raw_line,
    )

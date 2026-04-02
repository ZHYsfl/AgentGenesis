"""History attachment and event recording helpers for case traces."""

from __future__ import annotations

import json
import logging
from typing import Any

from ..models import CaseResult

logger: logging.Logger = logging.getLogger(__name__)


def extract_history_events(msg: dict[str, Any]) -> list[dict[str, Any]]:
    raw = msg.get("history_events")
    if raw is None:
        return []
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        return [raw]
    return []


def record_observation_history(
    case_histories: dict[int, list[dict[str, Any]]],
    current_case_index: int,
    msg: dict[str, Any],
) -> None:
    events = extract_history_events(msg)
    if not events:
        events = [{"kind": "observation", "payload": msg.get("data", msg)}]
    case_histories.setdefault(current_case_index, []).extend(events)


def record_action_history(
    case_histories: dict[int, list[dict[str, Any]]],
    current_case_index: int,
    action_msg: dict[str, Any],
) -> None:
    events = extract_history_events(action_msg)
    if not events:
        fallback_event: dict[str, Any] = {
            "kind": "action",
        }
        if "data" in action_msg:
            fallback_event["payload"] = action_msg.get("data")
        if action_msg.get("error") is not None:
            fallback_event["error"] = action_msg.get("error")
        if "payload" not in fallback_event and "error" not in fallback_event:
            fallback_event["payload"] = action_msg
        events = [fallback_event]
    case_histories.setdefault(current_case_index, []).extend(events)


def attach_case_history(
    case_result: CaseResult,
    case_histories: dict[int, list[dict[str, Any]]],
    *,
    current_case_index: int,
) -> None:
    history = case_histories.get(
        case_result.case_index,
        case_histories.get(current_case_index, []),
    )
    if case_result.logs:
        history = list(history) + [
            {
                "kind": "judge_log",
                "payload": case_result.logs,
            }
        ]
    try:
        case_result.logs = json.dumps(history, ensure_ascii=False)
    except Exception:
        logger.warning("history json serialize failed, fallback to safe text")
        safe_history = [
            item if isinstance(item, (str, int, float, bool, type(None), dict, list))
            else str(item)
            for item in history
        ]
        try:
            case_result.logs = json.dumps(safe_history, ensure_ascii=False, default=str)
        except Exception:
            logger.warning("safe history serialize still failed, fallback to plain text")
            case_result.logs = str(safe_history)

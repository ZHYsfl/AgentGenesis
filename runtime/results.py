from __future__ import annotations

import logging
from typing import Any

from ..models import CaseResult, CaseStatus

logger: logging.Logger = logging.getLogger(__name__)


def to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def parse_case_result(msg: dict[str, Any], fallback_index: int) -> CaseResult:
    idx = to_int(msg.get("case_index", fallback_index), fallback_index)
    status_str = str(msg.get("status", "failed")).lower()
    if status_str in {"pending", "running"}:
        logger.warning(
            "case_end received non-terminal status '%s', force to 'error'",
            status_str,
        )
        status_str = "error"

    status_map = {
        "passed": CaseStatus.PASSED,
        "failed": CaseStatus.FAILED,
        "skipped": CaseStatus.SKIPPED,
        "tle": CaseStatus.TLE,
        "mle": CaseStatus.MLE,
        "error": CaseStatus.ERROR,
    }

    return CaseResult(
        case_index=idx,
        status=status_map.get(status_str, CaseStatus.FAILED),
        score=to_int(msg.get("score", 0) or 0, 0),
        time_used=to_int(msg.get("time_used", 0) or 0, 0),
        memory_used=to_int(msg.get("memory_used", 0) or 0, 0),
        # LLM usage fields are optional in judge payload.
        # When not present, keep 0 and let gateway delta tracking fill them later.
        chars_used=to_int(msg.get("chars_used", 0) or 0, 0),
        requests_used=to_int(msg.get("requests_used", 0) or 0, 0),
        input_data=msg.get("input_data"),
        output_data=msg.get("output_data"),
        expected_output=msg.get("expected_output"),
        error=msg.get("error"),
        logs=msg.get("logs"),
    )

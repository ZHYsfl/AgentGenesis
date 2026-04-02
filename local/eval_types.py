"""Type definitions for Local Evaluation SDK"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class EvalEventType(str, Enum):
    """Evaluation event types"""

    CASE_START = "case_start"
    CASE_END = "case_end"
    OBSERVATION = "observation"  # Judge -> User
    ACTION = "action"  # User -> Judge
    JUDGE_LOG = "judge_log"  # Judge sandbox output
    USER_LOG = "user_log"  # User sandbox output
    PROGRESS = "progress"  # Progress update
    ERROR = "error"  # Error event


class EvalEvent(BaseModel):
    """Evaluation event

    Unified event object containing all observable data during evaluation.
    Users can receive these events via callback functions to implement
    custom visualization or logging.
    """

    type: EvalEventType
    case_index: int
    timestamp: float = Field(default_factory=lambda: __import__("time").time())
    data: dict[str, Any] = Field(default_factory=dict)

    def _format_data_preview(self) -> str:
        """Format data field into a short preview"""
        data = self.data.get("data")
        if data is None:
            return ""
        text = str(data)
        if len(text) > 80:
            return text[:80] + "..."
        return text

    def __str__(self) -> str:
        match self.type:
            case EvalEventType.OBSERVATION:
                preview = self._format_data_preview()
                return f"[Case {self.case_index}] Observation: {preview}"
            case EvalEventType.ACTION:
                preview = self._format_data_preview()
                return f"[Case {self.case_index}] Action: {preview}"
            case EvalEventType.CASE_START:
                return f"[Case {self.case_index}] Started"
            case EvalEventType.CASE_END:
                status = self.data.get("status", "unknown")
                score = self.data.get("score", 0)
                return f"[Case {self.case_index}] Ended: status={status}, score={score}"
            case EvalEventType.JUDGE_LOG:
                preview = self._format_data_preview()
                return f"[Judge Log] {preview}"
            case EvalEventType.USER_LOG:
                preview = self._format_data_preview()
                return f"[User Log] {preview}"
            case EvalEventType.PROGRESS:
                completed = self.data.get("completed", 0)
                total = self.data.get("total", 0)
                return f"[Progress] {completed}/{total} cases completed"
            case EvalEventType.ERROR:
                error = self.data.get("error", "unknown error")
                return f"[Error] {error}"
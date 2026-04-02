"""Protocol constants and payload sanitization helpers."""

from __future__ import annotations

from typing import Any


class MessageType:
    CASE_START = "case_start"
    OBSERVATION = "observation"
    CASE_END = "case_end"
    EVAL_COMPLETE = "eval_complete"
    ERROR = "error"
    ACTION = "action"
    ACTION_REQUEST = "action_request"
    CASE_REQUEST = "case_request"
    CASE_ASSIGN = "case_assign"
    CASE_STOP = "case_stop"

    _registry: dict[str, str] = {}

    @classmethod
    def register(cls, name: str, value: str) -> None:
        setattr(cls, name, value)
        cls._registry[name] = value

    @classmethod
    def all_types(cls) -> set[str]:
        builtin = {
            cls.CASE_START,
            cls.OBSERVATION,
            cls.CASE_END,
            cls.EVAL_COMPLETE,
            cls.ERROR,
            cls.ACTION,
            cls.ACTION_REQUEST,
            cls.CASE_REQUEST,
            cls.CASE_ASSIGN,
            cls.CASE_STOP,
        }
        return builtin | set(cls._registry.values())


def sanitize_user_message(msg: dict[str, Any]) -> dict[str, Any]:
    out = dict(msg)
    out.pop("history_events", None)
    return out

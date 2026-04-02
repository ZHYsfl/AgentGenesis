from __future__ import annotations

import json
from typing import Any, TypeVar


T = TypeVar("T", bound="_JsonMessage")


class _JsonMessage:
    """Lightweight protobuf-compatible message shim for gRPC serializers."""

    def to_dict(self) -> dict[str, Any]:
        raise NotImplementedError

    @classmethod
    def from_dict(cls: type[T], data: dict[str, Any]) -> T:
        raise NotImplementedError

    def SerializeToString(self) -> bytes:
        return json.dumps(self.to_dict(), ensure_ascii=False).encode("utf-8")

    @classmethod
    def FromString(cls: type[T], raw: bytes) -> T:
        if not raw:
            return cls.from_dict({})
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except Exception:
            parsed = {}
        if not isinstance(parsed, dict):
            parsed = {}
        return cls.from_dict(parsed)


class Empty(_JsonMessage):
    def __init__(self) -> None:
        pass

    def to_dict(self) -> dict[str, Any]:
        return {}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Empty":
        _ = data
        return cls()


class ReadyStatus(_JsonMessage):
    def __init__(self, is_ready: bool = False, message: str = "") -> None:
        self.is_ready = bool(is_ready)
        self.message = str(message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_ready": self.is_ready,
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReadyStatus":
        return cls(
            is_ready=bool(data.get("is_ready", False)),
            message=str(data.get("message", "")),
        )


class ProtocolEnvelope(_JsonMessage):
    def __init__(self, json_message: str = "") -> None:
        self.json_message = str(json_message)

    def to_dict(self) -> dict[str, Any]:
        return {"json_message": self.json_message}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProtocolEnvelope":
        return cls(json_message=str(data.get("json_message", "")))


class SendAck(_JsonMessage):
    def __init__(self, ok: bool = True, error: str = "") -> None:
        self.ok = bool(ok)
        self.error = str(error)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SendAck":
        return cls(
            ok=bool(data.get("ok", False)),
            error=str(data.get("error", "")),
        )


class RecvRequest(_JsonMessage):
    def __init__(self, timeout_ms: int = 0) -> None:
        try:
            self.timeout_ms = int(timeout_ms)
        except Exception:
            self.timeout_ms = 0

    def to_dict(self) -> dict[str, Any]:
        return {"timeout_ms": self.timeout_ms}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RecvRequest":
        return cls(timeout_ms=int(data.get("timeout_ms", 0) or 0))


class RecvResponse(_JsonMessage):
    def __init__(self, has_message: bool = False, json_message: str = "") -> None:
        self.has_message = bool(has_message)
        self.json_message = str(json_message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "has_message": self.has_message,
            "json_message": self.json_message,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RecvResponse":
        return cls(
            has_message=bool(data.get("has_message", False)),
            json_message=str(data.get("json_message", "")),
        )

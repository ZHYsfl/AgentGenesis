"""Shared test fixtures for evaluation test suite."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest


# Ensure `from ...` relative imports work when pytest is run from repo root.
ENV_DEMO_ROOT = Path(__file__).resolve().parents[2]
if str(ENV_DEMO_ROOT) not in sys.path:
    sys.path.insert(0, str(ENV_DEMO_ROOT))


class DummyResponse:
    def __init__(
        self,
        status_code: int = 200,
        json_data: dict[str, Any] | None = None,
        text: str = "",
        content: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text
        self.content = content
        self.headers = headers or {}

    def json(self) -> dict[str, Any]:
        return self._json_data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import requests

            err = requests.HTTPError(f"HTTP {self.status_code}: {self.text}")
            err.response = self
            raise err


class DummyCmdRunner:
    def __init__(self, script: Callable[..., Any] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._script = script

    def run(self, command: str, timeout: int = 30, envs: dict[str, str] | None = None) -> Any:
        payload = {"command": command, "timeout": timeout, "envs": envs or {}}
        self.calls.append(payload)
        if self._script:
            return self._script(command=command, timeout=timeout, envs=envs or {})
        return SimpleNamespace(stdout="", stderr="")


class DummySandbox:
    def __init__(self, sid: str = "sb-1", script: Callable[..., Any] | None = None) -> None:
        self.id = sid
        self.commands = DummyCmdRunner(script=script)
        self.closed = False
        self.killed = False

    def close(self) -> None:
        self.closed = True

    def kill(self) -> None:
        self.killed = True


@pytest.fixture
def dummy_response_cls() -> type[DummyResponse]:
    return DummyResponse


@pytest.fixture
def make_response() -> Callable[..., DummyResponse]:
    def _factory(**kwargs: Any) -> DummyResponse:
        return DummyResponse(**kwargs)

    return _factory


@pytest.fixture
def make_sandbox() -> Callable[..., DummySandbox]:
    def _factory(sid: str = "sb-1", script: Callable[..., Any] | None = None) -> DummySandbox:
        return DummySandbox(sid=sid, script=script)

    return _factory


@pytest.fixture
def sample_phase_config_dict() -> dict[str, Any]:
    return {
        "phase_name": "p1",
        "phase_order": 1,
        "phase_level": "Easy",
        "num_cases": 2,
        "parallel_cases": 1,
    }


@pytest.fixture
def sample_submission_dict(sample_phase_config_dict: dict[str, Any]) -> dict[str, Any]:
    return {
        "submit_id": 101,
        "user_id": 202,
        "phase_id": 1,
        "code_url": "https://example/code.zip",
        "code_checksum": "",
        "language": "python",
        "phase_type": "agent",
        "phase_config": sample_phase_config_dict,
        "runtime_config": {"key_id": 7, "key_name": "k"},
    }


@pytest.fixture
def zip_bytes() -> Callable[[dict[str, str]], bytes]:
    def _build(files: dict[str, str]) -> bytes:
        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for path, text in files.items():
                zf.writestr(path, text)
        return buf.getvalue()

    return _build


def dumps_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False)

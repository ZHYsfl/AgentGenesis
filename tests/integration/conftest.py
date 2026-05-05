"""Integration test fixtures for evaluation package."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from evaluation.models import PhaseConfig, RuntimeConfig, UserSubmission


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


@dataclass
class CallRecord:
    method: str
    url: str
    payload: dict[str, Any] | None = None
    params: dict[str, Any] | None = None
    headers: dict[str, str] | None = None


@dataclass
class FakeTransport:
    calls: list[CallRecord] = field(default_factory=list)
    post_routes: dict[str, Any] = field(default_factory=dict)
    get_routes: dict[str, Any] = field(default_factory=dict)
    head_routes: dict[str, Any] = field(default_factory=dict)
    put_routes: dict[str, Any] = field(default_factory=dict)

    def post(self, url: str, **kwargs: Any) -> DummyResponse:
        self.calls.append(CallRecord("POST", url, payload=kwargs.get("json"), headers=kwargs.get("headers")))
        handler = self.post_routes.get(url)
        if handler is None:
            return DummyResponse(status_code=404, text=f"no route for {url}")
        return handler(kwargs)

    def get(self, url: str, **kwargs: Any) -> DummyResponse:
        self.calls.append(CallRecord("GET", url, params=kwargs.get("params"), headers=kwargs.get("headers")))
        handler = self.get_routes.get(url)
        if handler is None:
            return DummyResponse(status_code=404, text=f"no route for {url}")
        return handler(kwargs)

    def head(self, url: str, **kwargs: Any) -> DummyResponse:
        self.calls.append(CallRecord("HEAD", url, headers=kwargs.get("headers")))
        handler = self.head_routes.get(url)
        if handler is None:
            return DummyResponse(status_code=200, headers={})
        return handler(kwargs)

    def put(self, url: str, **kwargs: Any) -> DummyResponse:
        self.calls.append(CallRecord("PUT", url, payload=kwargs.get("json"), headers=kwargs.get("headers")))
        handler = self.put_routes.get(url)
        if handler is None:
            return DummyResponse(status_code=404, text=f"no route for {url}")
        return handler(kwargs)


@pytest.fixture
def dummy_response_cls() -> type[DummyResponse]:
    return DummyResponse


@pytest.fixture
def fake_transport() -> FakeTransport:
    return FakeTransport()


@pytest.fixture
def fake_cfg() -> SimpleNamespace:
    return SimpleNamespace(
        backend_url="http://backend",
        internal_api_key="internal-k",
        user_api_key="user-k",
        request_timeout=15,
        max_workers=2,
        poll_interval=1,
        health_enabled=False,
        health_port=18081,
    )


@pytest.fixture
def submission_factory() -> Any:
    def _make(**kwargs: Any) -> UserSubmission:
        cfg = PhaseConfig(
            phase_order=1,
            phase_level="Easy",
            phase_name="phase-1",
            num_cases=2,
            parallel_cases=1,
            artifact_url="http://artifact.zip",
            artifact_checksum="",
            case_idle_timeout=300,
        )
        data: dict[str, Any] = {
            "submit_id": 1,
            "user_id": 2,
            "phase_id": 3,
            "code_url": "http://code.zip",
            "code_checksum": "",
            "code_files": {"requirements.txt": "pytest\n", "solution.py": "def solve(x): return x"},
            "phase_config": cfg,
            "runtime_config": RuntimeConfig(key_id=9),
            "phase_type": "agent",
        }
        data.update(kwargs)
        return UserSubmission(**data)

    return _make


def to_json_line(obj: dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False)

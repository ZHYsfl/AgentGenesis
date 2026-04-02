"""Cross-module: ProblemRegistry sync against real Go backend."""

from __future__ import annotations

import base64
import io
import json
import time
import zipfile

import pytest

from ...config import ClientMode
from ...models import PhaseConfig, ProblemConfig
from ...registry import ProblemRegistry


def _make_artifact_b64(marker: str = "cross-test") -> str:
    """Build minimal artifact zip with visibility manifest (matches Go buildPhaseConfig)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("sandbox/run.py", f"# {marker}\nprint('hello')")
        zf.writestr("visibility_manifest.json", json.dumps({"private": []}))
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _problem(title: str = "CrossSync Test") -> ProblemConfig:
    phase = PhaseConfig(
        phase_order=1,
        phase_level="Easy",
        phase_name="Phase 1",
        phase_type="agent",
        description="Cross-module sync test",
        starter_code="# cross\nprint(1)",
        artifact_base64=_make_artifact_b64(),
        private_files=[],
    )
    return ProblemConfig(title=title, level="Easy", overview="Cross test", language="en", phases=[phase])


@pytest.mark.cross_module
def test_sync_worker_mode_register(backend_url: str) -> None:
    """Worker mode: sync new problem via /internal/register-problem."""
    ProblemRegistry._instance = None
    title = f"CrossWorkerReg {int(time.time() * 1000)}"
    p = _problem(title)
    r = ProblemRegistry(mode=ClientMode.WORKER, api_key=__import__("os").environ["INTERNAL_API_KEY"], backend_url=backend_url)
    result = r.sync_to_db(p)
    assert result == {1: True}


@pytest.mark.cross_module
def test_sync_worker_mode_get_phase_artifact(backend_url: str, cross_title_internal: str) -> None:
    """Worker mode: _phase_exists via /internal/get-phase-artifact returns True for existing phase."""
    if not cross_title_internal:
        pytest.skip("CROSS_TEST_TITLE_INTERNAL not set")
    import requests
    resp = requests.post(
        f"{backend_url}/internal/get-phase-artifact",
        headers={
            "X-Internal-Key": __import__("os").environ["INTERNAL_API_KEY"],
            "Content-Type": "application/json",
        },
        json={"title": cross_title_internal, "phase_order": 1},
        timeout=10,
    )
    assert resp.status_code == 200
    data = resp.json().get("data", {})
    assert data.get("exists") is True
    assert "artifact_checksum" in data


@pytest.mark.cross_module
def test_sync_user_mode_register(backend_url: str) -> None:
    """User mode: sync new problem via POST /api/v1/problems/register."""
    ProblemRegistry._instance = None
    title = f"CrossUserReg {int(time.time() * 1000)}"
    p = _problem(title)
    api_key = __import__("os").environ.get("AGENT_GENESIS_API_KEY", "")
    if not api_key:
        pytest.skip("AGENT_GENESIS_API_KEY not set")
    r = ProblemRegistry(mode=ClientMode.USER, api_key=api_key, backend_url=backend_url)
    result = r.sync_to_db(p)
    assert result == {1: True}

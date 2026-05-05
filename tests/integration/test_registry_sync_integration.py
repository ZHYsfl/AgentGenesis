from __future__ import annotations

import base64

import evaluation.registry as registry_mod
from evaluation.config import ClientMode
from evaluation.models import PhaseConfig, ProblemConfig
from evaluation.registry import ProblemRegistry


def _problem() -> ProblemConfig:
    phase = PhaseConfig(
        phase_order=1,
        phase_level="Easy",
        phase_name="p1",
        artifact_base64=base64.b64encode(b"artifact-bytes").decode(),
    )
    return ProblemConfig(title="Maze Exploration", level="Easy", phases=[phase])


def setup_function() -> None:
    ProblemRegistry._instance = None


def test_sync_to_db_worker_mode_register_path(monkeypatch, fake_transport, dummy_response_cls) -> None:
    base = "http://backend"
    p = _problem()
    r = ProblemRegistry(mode=ClientMode.WORKER, api_key="ik", backend_url=base)

    fake_transport.post_routes[f"{base}/internal/get-phase-artifact"] = (
        lambda kwargs: dummy_response_cls(200, json_data={"data": {"exists": False, "artifact_checksum": ""}})
    )
    fake_transport.post_routes[f"{base}/internal/register-problem"] = (
        lambda kwargs: dummy_response_cls(200, json_data={"code": 0, "msg": "success"})
    )
    monkeypatch.setattr(registry_mod.requests, "post", fake_transport.post)

    result = r.sync_to_db(p)
    assert result == {1: True}
    register_call = [c for c in fake_transport.calls if c.url.endswith("/internal/register-problem")][0]
    assert register_call.headers["X-Internal-Key"] == "ik"
    assert register_call.payload["title"] == "Maze Exploration"


def test_sync_to_db_worker_mode_revision_path(monkeypatch, fake_transport, dummy_response_cls) -> None:
    base = "http://backend"
    p = _problem()
    r = ProblemRegistry(mode=ClientMode.WORKER, api_key="ik", backend_url=base)

    def _artifact_resp(kwargs):
        return dummy_response_cls(200, json_data={"data": {"exists": True, "artifact_checksum": ""}})

    fake_transport.post_routes[f"{base}/internal/get-phase-artifact"] = _artifact_resp
    fake_transport.post_routes[f"{base}/internal/problems/s/maze-exploration/revisions"] = (
        lambda kwargs: dummy_response_cls(200, json_data={"data": {"auto_merged": False}})
    )
    monkeypatch.setattr(registry_mod.requests, "post", fake_transport.post)

    result = r.sync_to_db(p, revision_title="r1", revision_description="desc")
    assert result == {1: True}
    rev_call = [c for c in fake_transport.calls if c.url.endswith("/revisions")][0]
    assert rev_call.headers["X-Internal-Key"] == "ik"
    assert rev_call.payload["title"] == "r1"


def test_sync_to_db_user_mode_uses_api_key_header(monkeypatch, fake_transport, dummy_response_cls) -> None:
    base = "http://backend"
    p = _problem()
    r = ProblemRegistry(mode=ClientMode.USER, api_key="uk", backend_url=base)

    fake_transport.post_routes[f"{base}/api/v1/problems/register"] = (
        lambda kwargs: dummy_response_cls(200, json_data={"code": 0, "msg": "success"})
    )
    monkeypatch.setattr(registry_mod.requests, "post", fake_transport.post)

    result = r.sync_to_db(p)
    assert result == {1: True}
    call = [c for c in fake_transport.calls if c.url.endswith("/api/v1/problems/register")][0]
    assert call.headers["X-API-Key"] == "uk"


def test_sync_to_db_user_mode_fallback_to_revision(monkeypatch, fake_transport, dummy_response_cls) -> None:
    """USER mode: register returns 400 and should auto-fallback to revision flow."""
    import json

    base = "http://backend"
    p = _problem()
    r = ProblemRegistry(mode=ClientMode.USER, api_key="uk", backend_url=base)

    # register returns 400 with code 41001
    reject_body = json.dumps(
        {"code": 41001, "msg": "Phase already published. Use revision endpoint: POST /api/v1/problems/s/maze-exploration/revisions"},
        ensure_ascii=False,
    )
    fake_transport.post_routes[f"{base}/api/v1/problems/register"] = (
        lambda kwargs: dummy_response_cls(400, text=reject_body)
    )
    # USER mode should use public revision endpoint for fallback
    fake_transport.post_routes[f"{base}/api/v1/problems/s/maze-exploration/revisions"] = (
        lambda kwargs: dummy_response_cls(200, json_data={"data": {"auto_merged": False}})
    )
    monkeypatch.setattr(registry_mod.requests, "post", fake_transport.post)

    result = r.sync_to_db(p)
    assert result == {1: True}

    # Must register first, then fallback to revision
    register_calls = [c for c in fake_transport.calls if "register" in c.url]
    revision_calls = [c for c in fake_transport.calls if "revisions" in c.url]
    assert len(register_calls) == 1
    assert len(revision_calls) == 1
    assert revision_calls[0].headers["X-API-Key"] == "uk"


def test_sync_to_db_worker_mode_fallback_to_revision(monkeypatch, fake_transport, dummy_response_cls) -> None:
    """WORKER mode: _phase_exists False but register 400 should still fallback."""
    import json

    base = "http://backend"
    p = _problem()
    r = ProblemRegistry(mode=ClientMode.WORKER, api_key="ik", backend_url=base)

    # _phase_exists query returns not exists (simulates transient inconsistency)
    fake_transport.post_routes[f"{base}/internal/get-phase-artifact"] = (
        lambda kwargs: dummy_response_cls(200, json_data={"data": {"exists": False, "artifact_checksum": ""}})
    )
    # register returns 400 "already published"
    reject_body = json.dumps(
        {"code": 41001, "msg": "Phase already published. Use revision endpoint: POST /internal/problems/s/maze-exploration/revisions"},
        ensure_ascii=False,
    )
    fake_transport.post_routes[f"{base}/internal/register-problem"] = (
        lambda kwargs: dummy_response_cls(400, text=reject_body)
    )
    # fallback to revision
    fake_transport.post_routes[f"{base}/internal/problems/s/maze-exploration/revisions"] = (
        lambda kwargs: dummy_response_cls(200, json_data={"data": {"auto_merged": True}})
    )
    monkeypatch.setattr(registry_mod.requests, "post", fake_transport.post)

    result = r.sync_to_db(p)
    assert result == {1: True}

    register_calls = [c for c in fake_transport.calls if "register-problem" in c.url]
    revision_calls = [c for c in fake_transport.calls if "revisions" in c.url]
    assert len(register_calls) == 1
    assert len(revision_calls) == 1

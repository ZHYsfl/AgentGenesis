"""Additional tests for registry fallback and edge paths."""

from __future__ import annotations

import base64
import io
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

from .. import registry as reg_mod
from ..config import ClientMode
from ..models import PhaseConfig, ProblemConfig
from ..registry import ProblemRegistry, build_artifact_from_dir


def _problem() -> ProblemConfig:
    return ProblemConfig(
        title="Maze Exploration",
        level="Easy",
        phases=[PhaseConfig(phase_order=1, phase_level="Easy", phase_name="p1")],
    )


def setup_function() -> None:
    ProblemRegistry._instance = None


def test_build_artifact_from_dir_and_registry_helpers(tmp_path) -> None:
    root = tmp_path / "problem"
    root.mkdir()
    (root / "a.txt").write_text("a", encoding="utf-8")
    (root / "b.py").write_text("print(1)", encoding="utf-8")
    b64 = build_artifact_from_dir(root)
    assert base64.b64decode(b64)

    r = ProblemRegistry(mode=ClientMode.USER, api_key="k", backend_url="http://b")
    p = _problem()
    r.register(p)
    assert r.get("Maze Exploration") is p
    assert r.get("Nope") is None
    assert r.get_phase("Maze Exploration", 1) is not None
    assert r.get_phase("Maze Exploration", 99) is None
    assert "Maze Exploration" in r.list_all()
    assert r._get_sync_endpoint().endswith("/api/v1/problems/register")
    assert r._get_sync_headers()["X-API-Key"] == "k"


def test_registry_init_instance_and_sync_all(monkeypatch) -> None:
    ProblemRegistry.init(mode=ClientMode.WORKER, api_key="ik", backend_url="http://b")
    inst = ProblemRegistry.instance()
    assert inst.mode == ClientMode.WORKER
    assert inst._get_sync_endpoint().endswith("/internal/register-problem")
    assert inst._get_sync_headers()["X-Internal-Key"] == "ik"

    r = ProblemRegistry(mode=ClientMode.USER, api_key="k", backend_url="http://b")
    p = _problem()
    r.register(p)
    monkeypatch.setattr(r, "sync_to_db", lambda definition, revision_title="", revision_description="": {1: True})
    out = r.sync_all()
    assert out["Maze Exploration"] == {1: True}


def test_registry_phase_exists_and_checksum_error_paths(monkeypatch, dummy_response_cls) -> None:
    r = ProblemRegistry(mode=ClientMode.WORKER, api_key="ik", backend_url="http://b")

    monkeypatch.setattr(
        reg_mod.requests,
        "post",
        lambda *args, **kwargs: dummy_response_cls(500, text="err"),
    )
    assert r._get_existing_checksum("Maze", 1) == ""
    assert r._phase_exists("Maze", 1) is False


def test_build_artifact_from_dirs_dedup_and_missing_dir(tmp_path) -> None:
    root = tmp_path / "problem"
    root.mkdir()
    sandbox = root / "sandbox"
    sandbox.mkdir()
    (sandbox / "run.py").write_text("print('ok')\n", encoding="utf-8")

    b64 = reg_mod.build_artifact_from_dirs([sandbox, sandbox], base_path=root)
    raw = base64.b64decode(b64)
    with zipfile.ZipFile(io.BytesIO(raw), "r") as zf:
        names = [i.filename for i in zf.infolist() if not i.is_dir()]
    assert names.count("sandbox/run.py") == 1

    with pytest.raises(FileNotFoundError):
        reg_mod.build_artifact_from_dirs([root / "missing"], base_path=root)


def test_registry_singleton_guard_and_create_revision_missing_phase() -> None:
    ProblemRegistry._instance = None
    with pytest.raises(RuntimeError, match="not initialized"):
        ProblemRegistry.instance()

    ProblemRegistry.init(mode=ClientMode.USER, api_key="k", backend_url="http://b")
    with pytest.raises(RuntimeError, match="already been initialized"):
        ProblemRegistry.init(mode=ClientMode.USER, api_key="k2", backend_url="http://b")

    r = ProblemRegistry(mode=ClientMode.USER, api_key="k", backend_url="http://b")
    p = _problem()
    r.register(p)
    r.register(p)  # overwrite should not crash
    assert r.list_all() == [p.title]
    assert r.create_revision(p, phase_order=99) is False


def test_register_phase_fallback_with_non_json_error(monkeypatch) -> None:
    r = ProblemRegistry(mode=ClientMode.USER, api_key="k", backend_url="http://b")
    p = _problem()
    phase = p.phases[0]
    called = {"revisions": 0}

    class _BadJsonResponse:
        status_code = 400
        text = "already published"

        def json(self) -> dict:
            raise ValueError("bad json")

    monkeypatch.setattr(r, "_get_existing_checksum", lambda title, phase_order: "")
    monkeypatch.setattr(r, "_create_revision", lambda problem, phase_obj: called.__setitem__("revisions", 1) or True)
    monkeypatch.setattr(reg_mod.requests, "post", lambda *args, **kwargs: _BadJsonResponse())

    assert r._register_phase(p, phase, _allow_fallback=True) is True
    assert called["revisions"] == 1


def test_register_phase_and_create_revision_exception_paths(monkeypatch) -> None:
    r = ProblemRegistry(mode=ClientMode.USER, api_key="k", backend_url="http://b")
    p = _problem()
    phase = p.phases[0]

    monkeypatch.setattr(r, "_get_existing_checksum", lambda title, phase_order: "")
    monkeypatch.setattr(
        reg_mod.requests,
        "post",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("network down")),
    )
    assert r._register_phase(p, phase) is False
    assert r._create_revision(p, phase) is False

    monkeypatch.setattr(
        reg_mod.requests,
        "post",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert r._get_existing_checksum("Maze", 1) == ""
    assert r._phase_exists("Maze", 1) is False


from __future__ import annotations

from pathlib import Path

import pytest

from ..local.artifact_builder import LocalArtifactBuilder
from ..models import PhaseConfig


def _norm(path: str) -> str:
    return path.replace("\\", "/")


def test_build_collects_files_and_skips_pyc_cache(tmp_path: Path) -> None:
    builder = LocalArtifactBuilder()
    problem_path = tmp_path / "problem"
    sandbox = problem_path / "sandbox"
    sandbox.mkdir(parents=True)
    (sandbox / "run.py").write_text("print('ok')", encoding="utf-8")
    (sandbox / "user_adapter.py").write_text("class Adapter: pass", encoding="utf-8")
    (sandbox / "module.pyc").write_bytes(b"pyc")
    (sandbox / "__pycache__").mkdir()
    (sandbox / "__pycache__" / "cache.pyc").write_bytes(b"pyc")

    artifact_files = builder.build(problem_path)
    keys = {_norm(k) for k in artifact_files}
    assert "sandbox/run.py" in keys
    assert "sandbox/user_adapter.py" in keys
    assert "sandbox/module.pyc" not in keys
    assert all("__pycache__" not in key for key in keys)


def test_build_raises_when_sandbox_missing(tmp_path: Path) -> None:
    builder = LocalArtifactBuilder()
    with pytest.raises(FileNotFoundError):
        builder.build(tmp_path / "missing_problem")


def test_build_raises_when_entrypoint_missing(tmp_path: Path) -> None:
    builder = LocalArtifactBuilder()
    problem_path = tmp_path / "problem"
    sandbox = problem_path / "sandbox"
    sandbox.mkdir(parents=True)
    (sandbox / "other.py").write_text("print('x')", encoding="utf-8")

    cfg = PhaseConfig(artifact_entry="sandbox/custom.py")
    with pytest.raises(FileNotFoundError):
        builder.build(problem_path, cfg)


def test_resolve_entrypoint_and_get_user_adapter() -> None:
    builder = LocalArtifactBuilder()
    cfg = PhaseConfig(artifact_entry="sandbox/custom.py")
    assert builder._resolve_entrypoint(cfg) == "sandbox/custom.py"
    assert builder._resolve_entrypoint(None) == "sandbox/run.py"

    files = {
        "sandbox/user_adapter.py": b"adapter-a",
        "user_adapter.py": b"adapter-b",
    }
    assert builder.get_user_adapter(files) == b"adapter-a"

    fallback = {"user_adapter.py": b"adapter-b"}
    assert builder.get_user_adapter(fallback) == b"adapter-b"

    missing = {"sandbox/run.py": b"print(1)"}
    assert builder.get_user_adapter(missing) is None

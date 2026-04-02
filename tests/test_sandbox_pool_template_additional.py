from __future__ import annotations

import io
import tarfile
import time
from typing import Any

import pytest

from .. import sandbox_pool as sp


def setup_function() -> None:
    sp.TemplateImagePool._instance = None


def test_template_key_normalization() -> None:
    pool = sp.TemplateImagePool()
    key1 = pool._template_key([" Requests>=2 ", "numpy==1.0"])
    key2 = pool._template_key(["numpy==1.0", "requests>=2"])
    assert key1 == key2
    assert pool._template_key([]) == "base"


def test_template_key_includes_base_identity() -> None:
    pool = sp.TemplateImagePool()
    k1 = pool._template_key(["numpy==1.0"], base_identity="sha256:aaa")
    k2 = pool._template_key(["numpy==1.0"], base_identity="sha256:bbb")
    assert k1 != k2
    assert pool._template_key([], base_identity="sha256:anything") == "base"


def test_get_or_create_base_and_cached_template(monkeypatch) -> None:
    pool = sp.TemplateImagePool()
    monkeypatch.setenv("SANDBOX_DOCKER_IMAGE", "base:latest")

    base = pool.get_or_create([], deps_timeout_seconds=5)
    assert base == "base:latest"
    assert pool.get_or_create([], deps_timeout_seconds=5) == "base:latest"

    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        pool,
        "_build_template",
        lambda base_image, image_tag, pip_dependencies, deps_timeout_seconds, **kwargs: calls.append(
            (base_image, image_tag, pip_dependencies, deps_timeout_seconds)
        ),
    )
    image = pool.get_or_create(["pydantic==2.0"], deps_timeout_seconds=12)
    assert image.startswith("genesis-phase-template:")
    assert len(calls) == 1
    assert calls[0][0] == "base:latest"
    assert calls[0][2] == ["pydantic==2.0"]

    image2 = pool.get_or_create(["pydantic==2.0"], deps_timeout_seconds=12)
    assert image2 == image
    assert len(calls) == 1


def test_build_template_success_and_failure_cleanup(monkeypatch) -> None:
    events: list[str] = []

    class _FakeContainer:
        def __init__(self, exit_code: int) -> None:
            self.exit_code = exit_code

        def exec_run(self, cmd: str, demux: bool = True):  # type: ignore[no-untyped-def]
            _ = (cmd, demux)
            if self.exit_code == 0:
                return (0, (b"ok", b""))
            return (12, (b"", b"install error"))

        def commit(self, repository: str, tag: str, **kwargs: Any) -> None:
            _ = kwargs
            events.append(f"commit:{repository}:{tag}")

        def kill(self) -> None:
            events.append("kill")

        def remove(self, force: bool = True) -> None:
            _ = force
            events.append("remove")

    class _FakeContainers:
        def __init__(self, exit_code: int) -> None:
            self.exit_code = exit_code

        def run(self, **kwargs: Any) -> _FakeContainer:
            _ = kwargs
            return _FakeContainer(self.exit_code)

    class _FakeClient:
        def __init__(self, exit_code: int) -> None:
            self.containers = _FakeContainers(exit_code)

    monkeypatch.setattr("docker.from_env", lambda: _FakeClient(0))
    sp.TemplateImagePool._build_template(
        "base:latest",
        "genesis-phase-template:phase-key",
        ["requests>=2"],
        10,
    )
    assert "commit:genesis-phase-template:phase-key" in events
    assert "kill" in events and "remove" in events

    events.clear()
    monkeypatch.setattr("docker.from_env", lambda: _FakeClient(1))
    with pytest.raises(RuntimeError, match="template build failed"):
        sp.TemplateImagePool._build_template(
            "base:latest",
            "genesis-phase-template:phase-key",
            ["badpkg"],
            10,
        )
    assert "kill" in events and "remove" in events


# ------------------------------------------------------------------
# GC / LRU eviction tests
# ------------------------------------------------------------------


def test_last_used_updated_on_cache_hit(monkeypatch) -> None:
    pool = sp.TemplateImagePool()
    monkeypatch.setenv("SANDBOX_DOCKER_IMAGE", "base:latest")

    pool.get_or_create([], deps_timeout_seconds=5)
    first_ts = pool._last_used.get("base", 0)
    assert first_ts > 0

    time.sleep(0.01)
    pool.get_or_create([], deps_timeout_seconds=5)
    assert pool._last_used["base"] >= first_ts


def test_evict_stale_removes_old_templates(monkeypatch) -> None:
    pool = sp.TemplateImagePool()
    monkeypatch.setenv("SANDBOX_DOCKER_IMAGE", "base:latest")

    monkeypatch.setattr(
        pool,
        "_build_template",
        lambda base_image, image_tag, pip_deps, timeout, **kwargs: None,
    )
    pool.get_or_create(["numpy==1.0"], deps_timeout_seconds=5)
    key = next(k for k in pool._templates if k != "base")
    assert key in pool._templates

    with pool._lock:
        pool._last_used[key] = time.time() - 8 * 86400

    removed_images: list[str] = []

    class _FakeImages:
        def remove(self, image: str, force: bool = True) -> None:
            _ = force
            removed_images.append(image)

    class _FakeDockerClient:
        images = _FakeImages()

    monkeypatch.setattr("docker.from_env", lambda: _FakeDockerClient())

    evicted = pool.evict_stale(max_age_seconds=7 * 86400)
    assert evicted == 1
    assert key not in pool._templates
    assert key not in pool._last_used
    assert key not in pool._build_locks
    assert len(removed_images) == 1
    assert removed_images[0].startswith("genesis-phase-template:")


def test_evict_stale_skips_base_and_fresh(monkeypatch) -> None:
    pool = sp.TemplateImagePool()
    monkeypatch.setenv("SANDBOX_DOCKER_IMAGE", "base:latest")

    pool.get_or_create([], deps_timeout_seconds=5)
    assert "base" in pool._templates

    monkeypatch.setattr(
        pool,
        "_build_template",
        lambda base_image, image_tag, pip_deps, timeout, **kwargs: None,
    )
    pool.get_or_create(["fresh-pkg==1.0"], deps_timeout_seconds=5)

    evicted = pool.evict_stale(max_age_seconds=7 * 86400)
    assert evicted == 0
    assert "base" in pool._templates


def test_evict_stale_handles_docker_rmi_failure(monkeypatch) -> None:
    pool = sp.TemplateImagePool()
    monkeypatch.setenv("SANDBOX_DOCKER_IMAGE", "base:latest")

    monkeypatch.setattr(
        pool,
        "_build_template",
        lambda base_image, image_tag, pip_deps, timeout, **kwargs: None,
    )
    pool.get_or_create(["badpkg==1.0"], deps_timeout_seconds=5)
    key = next(k for k in pool._templates if k != "base")

    with pool._lock:
        pool._last_used[key] = time.time() - 10 * 86400

    class _FakeImages:
        def remove(self, image: str, force: bool = True) -> None:
            raise RuntimeError("image in use")

    class _FakeDockerClient:
        images = _FakeImages()

    monkeypatch.setattr("docker.from_env", lambda: _FakeDockerClient())

    evicted = pool.evict_stale(max_age_seconds=7 * 86400)
    assert evicted == 1
    assert key not in pool._templates


def test_get_stats_includes_gc_info(monkeypatch) -> None:
    pool = sp.TemplateImagePool()
    monkeypatch.setenv("SANDBOX_DOCKER_IMAGE", "base:latest")
    pool.get_or_create([], deps_timeout_seconds=5)

    stats = pool.get_stats()
    assert "templates" in stats
    assert "last_used" in stats
    assert "total_evicted" in stats
    assert stats["total_evicted"] == 0


def test_gc_timer_start_and_stop() -> None:
    pool = sp.TemplateImagePool()
    pool.start_gc_timer(interval_seconds=999999)
    assert pool._gc_timer is not None
    assert pool._gc_timer.is_alive()

    pool.stop_gc_timer()
    assert pool._gc_timer is None


def test_startup_cleanup_removes_mismatched_templates(monkeypatch) -> None:
    removed_ids: list[str] = []

    class _FakeImage:
        def __init__(self, image_id: str, label_value: str | None) -> None:
            self.id = image_id
            self.labels = {} if label_value is None else {sp._TEMPLATE_BASE_ID_LABEL: label_value}

    class _FakeImages:
        def get(self, image_ref: str) -> Any:
            _ = image_ref
            return type("I", (), {"id": "sha256:new-base"})()

        def list(self, name: str) -> list[_FakeImage]:
            assert name == "genesis-phase-template"
            return [
                _FakeImage("img-keep", "sha256:new-base"),
                _FakeImage("img-drop-mismatch", "sha256:old-base"),
                _FakeImage("img-drop-legacy", None),
            ]

        def remove(self, image_ref: str, force: bool = True) -> None:
            _ = force
            removed_ids.append(image_ref)

    class _FakeDockerClient:
        images = _FakeImages()

    monkeypatch.setenv("SANDBOX_DOCKER_IMAGE", "base:latest")
    monkeypatch.setattr("docker.from_env", lambda: _FakeDockerClient())

    sp.TemplateImagePool()

    assert "img-keep" not in removed_ids
    assert "img-drop-mismatch" in removed_ids
    assert "img-drop-legacy" in removed_ids


def test_int_env_extract_files_and_hash_helpers(monkeypatch) -> None:
    monkeypatch.delenv("TEMPLATE_GC_INTERVAL", raising=False)
    assert sp._int_env("TEMPLATE_GC_INTERVAL", 7) == 7

    monkeypatch.setenv("TEMPLATE_GC_INTERVAL", " ")
    assert sp._int_env("TEMPLATE_GC_INTERVAL", 8) == 8

    monkeypatch.setenv("TEMPLATE_GC_INTERVAL", "11")
    assert sp._int_env("TEMPLATE_GC_INTERVAL", 9) == 11

    monkeypatch.setenv("TEMPLATE_GC_INTERVAL", "not-a-number")
    assert sp._int_env("TEMPLATE_GC_INTERVAL", 10) == 10

    artifact_files = {
        "sandbox/run.py": b"print('x')",
        "data": b"",
        "data/questions.json": b"{}",
        "assets/logo.png": b"\x89PNG",
    }
    selected = sp.extract_image_data_files(artifact_files, ["data", "assets"])
    assert set(selected.keys()) == {"data", "data/questions.json", "assets/logo.png"}

    hash_a = sp.compute_data_content_hash({"b.txt": b"2", "a.txt": b"1"})
    hash_b = sp.compute_data_content_hash({"a.txt": b"1", "b.txt": b"2"})
    assert hash_a == hash_b
    assert len(hash_a) == 16


def test_template_pool_get_instance_starts_timer_once(monkeypatch) -> None:
    starts: list[str] = []

    def _fake_start_gc_timer(self) -> None:
        starts.append("started")

    monkeypatch.setattr(sp.TemplateImagePool, "start_gc_timer", _fake_start_gc_timer)
    sp.TemplateImagePool._instance = None

    p1 = sp.TemplateImagePool.get_instance()
    p2 = sp.TemplateImagePool.get_instance()
    assert p1 is p2
    assert starts == ["started"]


def test_resolve_base_identity_fallbacks(monkeypatch) -> None:
    pool = sp.TemplateImagePool()

    class _FakeImages:
        def get(self, image_ref: str) -> Any:
            _ = image_ref
            return type("Img", (), {"id": "   "})()

    class _FakeClient:
        images = _FakeImages()

    monkeypatch.setattr("docker.from_env", lambda: _FakeClient())
    assert pool._resolve_base_image_identity("base:latest") == "base:latest"

    def _raise() -> Any:
        raise RuntimeError("docker unavailable")

    monkeypatch.setattr("docker.from_env", _raise)
    assert pool._resolve_base_image_identity("  base:latest  ") == "base:latest"


def test_startup_cleanup_handles_remove_failure_and_client_error(monkeypatch) -> None:
    class _FakeImage:
        def __init__(self, image_id: str, label_value: str) -> None:
            self.id = image_id
            self.labels = {sp._TEMPLATE_BASE_ID_LABEL: label_value}

    removed: list[str] = []

    class _FakeImages:
        def get(self, image_ref: str) -> Any:
            _ = image_ref
            return type("I", (), {"id": "sha256:new-base"})()

        def list(self, name: str) -> list[_FakeImage]:
            assert name == "genesis-phase-template"
            return [
                _FakeImage("img-fail-remove", "sha256:old-base"),
                _FakeImage("img-removed", "sha256:legacy"),
            ]

        def remove(self, image_ref: str, force: bool = True) -> None:
            _ = force
            if image_ref == "img-fail-remove":
                raise RuntimeError("busy")
            removed.append(image_ref)

    class _FakeDockerClient:
        images = _FakeImages()

    monkeypatch.setenv("SANDBOX_DOCKER_IMAGE", "base:latest")
    monkeypatch.setattr("docker.from_env", lambda: _FakeDockerClient())
    pool = sp.TemplateImagePool()
    # __init__ triggers one startup cleanup automatically; isolate the explicit call below.
    removed.clear()
    assert pool._evict_mismatched_templates_for_current_base() == 1
    assert removed == ["img-removed"]

    def _raise() -> Any:
        raise RuntimeError("docker offline")

    monkeypatch.setattr("docker.from_env", _raise)
    assert pool._evict_mismatched_templates_for_current_base() == 0


def test_build_template_writes_data_files_and_tolerates_cleanup_errors(monkeypatch) -> None:
    put_archives: list[bytes] = []
    commits: list[list[str]] = []

    class _FakeContainer:
        def exec_run(self, cmd: str, demux: bool = True):  # type: ignore[no-untyped-def]
            _ = (cmd, demux)
            return (0, (b"", b""))

        def put_archive(self, path: str, data: io.BytesIO) -> None:
            assert path == "/"
            put_archives.append(data.getvalue())

        def commit(self, repository: str, tag: str, **kwargs: Any) -> None:
            _ = (repository, tag)
            commits.append(list(kwargs.get("changes", [])))

        def kill(self) -> None:
            raise RuntimeError("kill failed")

        def remove(self, force: bool = True) -> None:
            _ = force
            raise RuntimeError("remove failed")

    class _FakeContainers:
        def run(self, **kwargs: Any) -> _FakeContainer:
            _ = kwargs
            return _FakeContainer()

    class _FakeClient:
        containers = _FakeContainers()

    monkeypatch.setattr("docker.from_env", lambda: _FakeClient())
    monkeypatch.setattr(
        sp.TemplateImagePool,
        "_resolve_base_image_identity",
        staticmethod(lambda _base: "sha256:resolved"),
    )
    sp.TemplateImagePool._build_template(
        "base:latest",
        "genesis-phase-template:phase-data",
        [],
        10,
        data_files={"data/questions.json": b'{"q": 1}'},
    )

    assert put_archives
    with tarfile.open(fileobj=io.BytesIO(put_archives[0]), mode="r") as tar:
        member = tar.getmember("workspace/data/questions.json")
        extracted = tar.extractfile(member)
        assert extracted is not None
        assert extracted.read() == b'{"q": 1}'

    assert commits
    assert any(sp._TEMPLATE_BASE_ID_LABEL in change for change in commits[0])


def test_get_or_create_non_base_when_only_data_hash(monkeypatch) -> None:
    pool = sp.TemplateImagePool()
    monkeypatch.setenv("SANDBOX_DOCKER_IMAGE", "base:latest")

    calls: list[dict[str, bytes] | None] = []
    monkeypatch.setattr(
        pool,
        "_build_template",
        lambda base_image, image_tag, pip_dependencies, deps_timeout_seconds, **kwargs: calls.append(
            kwargs.get("data_files")
        ),
    )

    data_files = {"data/questions.json": b"{}"}
    image = pool.get_or_create(
        [],
        deps_timeout_seconds=5,
        data_files=data_files,
        data_content_hash="abcd1234",
    )
    assert image.startswith("genesis-phase-template:phase-")
    assert calls == [data_files]


def test_gc_timer_disabled_and_stop_without_timer() -> None:
    pool = sp.TemplateImagePool()
    pool.start_gc_timer(interval_seconds=0)
    assert pool._gc_timer is None
    pool.stop_gc_timer()
    assert pool._gc_timer is None

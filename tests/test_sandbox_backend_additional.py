from __future__ import annotations

import io
import tarfile
from types import SimpleNamespace
from typing import Any

import evaluation.sandbox_backend as sb_mod
from evaluation.sandbox_backend import DockerSandbox, ExecHandle


class _FakeAPI:
    def __init__(self) -> None:
        self.exec_created: list[dict[str, Any]] = []
        self.exec_started: list[dict[str, Any]] = []
        self.inspect_running = True
        self.inspect_exit_code = 7
        self.raise_inspect = False

    def exec_create(self, container_id: str, **kwargs: Any) -> dict[str, str]:
        self.exec_created.append({"container_id": container_id, **kwargs})
        return {"Id": f"exec-{len(self.exec_created)}"}

    def exec_start(self, exec_id: str, detach: bool, demux: bool = False):  # type: ignore[no-untyped-def]
        self.exec_started.append({"exec_id": exec_id, "detach": detach, "demux": demux})
        if detach:
            return None
        if demux:
            return (b"STDOUT", b"STDERR")
        return b"STDOUT"

    def exec_inspect(self, exec_id: str) -> dict[str, Any]:
        _ = exec_id
        if self.raise_inspect:
            raise RuntimeError("inspect failed")
        return {"Running": self.inspect_running, "ExitCode": self.inspect_exit_code}


class _FakeContainer:
    def __init__(self, api: _FakeAPI) -> None:
        self.id = "container-id"
        self.short_id = "short-id"
        self.attrs = {"NetworkSettings": {"IPAddress": "172.18.0.2"}}
        self.client = SimpleNamespace(api=api)
        self.reloaded = False
        self.stopped = False
        self.killed = False
        self.removed = False
        self.stats_should_raise = False
        self.archives: list[tuple[str, bytes]] = []

    def reload(self) -> None:
        self.reloaded = True

    def put_archive(self, base_path: str, payload: io.BytesIO) -> None:
        self.archives.append((base_path, payload.read()))

    def stats(self, stream: bool = False) -> dict[str, Any]:
        _ = stream
        if self.stats_should_raise:
            raise RuntimeError("stats failed")
        return {"memory_stats": {"usage": 10 * 1024 * 1024}}

    def stop(self, timeout: int = 10) -> None:
        _ = timeout
        self.stopped = True

    def kill(self) -> None:
        self.killed = True

    def remove(self, force: bool = True) -> None:
        _ = force
        self.removed = True


def test_exec_handle_running_and_fallback() -> None:
    api = _FakeAPI()
    handle = ExecHandle(_api=api, _exec_id="exec-1", command="echo 1")
    assert handle.is_running() is True
    api.raise_inspect = True
    assert handle.is_running() is False
    handle.kill()


def test_docker_sandbox_command_write_metrics_and_lifecycle() -> None:
    api = _FakeAPI()
    container = _FakeContainer(api)
    sandbox = DockerSandbox(container)
    assert container.reloaded is True
    assert sandbox.id == "short-id"

    background = sandbox.run_command("python bg.py", background=True)
    assert isinstance(background, ExecHandle)
    assert api.exec_started[-1]["detach"] is True

    result = sandbox.run_command("python fg.py", envs={"A": "1"}, timeout=12)
    assert result.stdout == "STDOUT"
    assert result.stderr == "STDERR"
    assert result.exit_code == 7
    assert api.exec_created[-1]["environment"] == ["A=1"]

    sandbox.write_files([{"path": "/workspace/a.txt", "data": b"hello"}])
    base_path, archive_bytes = container.archives[-1]
    assert base_path == "/"
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:") as tar:
        member = tar.getmember("workspace/a.txt")
        assert member.size == 5

    assert sandbox.get_host(50051) == "172.18.0.2:50051"
    metrics = sandbox.get_metrics()
    assert metrics and metrics[0]["mem_used_mib"] == 10.0

    container.stats_should_raise = True
    assert sandbox.get_metrics() == []

    sandbox.close()
    assert container.stopped is True and container.removed is True

    sandbox.kill()
    assert container.killed is True and container.removed is True


def test_create_docker_sandbox_builds_kwargs(monkeypatch) -> None:
    api = _FakeAPI()
    container = _FakeContainer(api)
    captured: dict[str, Any] = {}

    class _FakeContainers:
        def run(self, **kwargs: Any) -> _FakeContainer:
            captured.update(kwargs)
            return container

    class _FakeClient:
        def __init__(self) -> None:
            self.containers = _FakeContainers()

    monkeypatch.setattr(sb_mod.docker, "from_env", lambda: _FakeClient())
    monkeypatch.setenv("SANDBOX_DOCKER_IMAGE", "img:from-env")

    sb = sb_mod.create_docker_sandbox(timeout=123, cpu_count=2, memory_mb=256)
    assert isinstance(sb, DockerSandbox)
    assert captured["image"] == "img:from-env"
    assert captured["command"] == ["/usr/bin/sleep", "123"]
    assert captured["nano_cpus"] == int(2 * 1e9)
    assert captured["mem_limit"] == "256m"

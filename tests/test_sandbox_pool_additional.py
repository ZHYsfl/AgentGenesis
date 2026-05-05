from __future__ import annotations

from types import SimpleNamespace

import pytest

import evaluation.sandbox_pool as sp
from evaluation.sandbox_backend import Sandbox, CommandResult


class _FakeSemaphore:
    def __init__(self, acquired: bool = True) -> None:
        self.acquired = acquired
        self.released = 0

    def acquire(self, timeout: int = 0) -> bool:
        _ = timeout
        return self.acquired

    def release(self) -> None:
        self.released += 1


class _Sandbox(Sandbox):
    def __init__(self, sid: str = "sb-1") -> None:
        self._id = sid
        self.closed = False
        self.killed = False

    @property
    def id(self) -> str:
        return self._id

    def run_command(self, command, *, timeout=30, envs=None, background=False):
        return CommandResult()

    def write_files(self, files):
        pass

    def get_host(self, port):
        return f"127.0.0.1:{port}"

    def get_metrics(self):
        return []

    def close(self) -> None:
        self.closed = True

    def kill(self) -> None:
        self.killed = True


def setup_function() -> None:
    sp.SandboxManager._instance = None


def test_get_instance_singleton(monkeypatch) -> None:
    monkeypatch.setattr(sp, "get_config", lambda: SimpleNamespace(max_workers=1))
    s1 = sp.SandboxManager.get_instance()
    s2 = sp.SandboxManager.get_instance()
    assert s1 is s2


def test_create_failure_and_runtime_error(monkeypatch) -> None:
    monkeypatch.setattr(sp, "get_config", lambda: SimpleNamespace(max_workers=2))
    mgr = sp.SandboxManager()
    mgr._semaphore = _FakeSemaphore(acquired=True)

    sb = _Sandbox("sb-ok")
    monkeypatch.setattr(
        sp,
        "create_docker_sandbox",
        lambda **kwargs: sb,
    )
    out = mgr.create(sandbox_timeout=10, template_id="tpl", cpu_count=2, memory_mb=256)
    assert out is sb
    assert mgr.get_stats()["total_created"] == 1

    mgr2 = sp.SandboxManager()
    mgr2._semaphore = _FakeSemaphore(acquired=True)

    def _fail(**kwargs):
        raise RuntimeError("create fail")

    monkeypatch.setattr(sp, "create_docker_sandbox", _fail)
    with pytest.raises(RuntimeError, match="Failed to create sandbox"):
        mgr2.create(sandbox_timeout=10)
    assert mgr2._semaphore.released == 1


def test_destroy_and_shutdown(monkeypatch) -> None:
    monkeypatch.setattr(sp, "get_config", lambda: SimpleNamespace(max_workers=2))
    mgr = sp.SandboxManager()
    mgr._semaphore = _FakeSemaphore(acquired=True)

    sb_close = _Sandbox("sb-close")
    sb_kill = _Sandbox("sb-kill")
    mgr._active_sandboxes = {"sb-close": sb_close, "sb-kill": sb_kill}
    mgr._stats["current_active"] = 2

    mgr.destroy(sb_kill)
    assert mgr._stats["total_destroyed"] >= 1
    assert mgr._semaphore.released >= 1

    bad = _Sandbox("bad")
    mgr._active_sandboxes["bad"] = bad
    original_destroy = mgr.destroy

    def _destroy_raise(sandbox):
        if sandbox.id == "bad":
            raise RuntimeError("boom")
        return original_destroy(sandbox)

    mgr.destroy = _destroy_raise  # type: ignore[method-assign]
    mgr.shutdown()

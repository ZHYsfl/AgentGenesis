"""Unit tests for sandbox pool lifecycle and limits."""

from __future__ import annotations

from types import SimpleNamespace

from .. import sandbox_pool as sp
from ..sandbox_backend import Sandbox, CommandResult


class FakeSemaphore:
    def __init__(self, acquired: bool = True) -> None:
        self.acquired = acquired
        self.released = 0

    def acquire(self, timeout: int = 0) -> bool:
        return self.acquired

    def release(self) -> None:
        self.released += 1


class FakeSandbox(Sandbox):
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


def test_create_without_template_id(monkeypatch) -> None:
    mgr = sp.SandboxManager()
    mgr._semaphore = FakeSemaphore(acquired=True)
    fake = FakeSandbox("sb-no-template")

    monkeypatch.setattr(
        sp,
        "create_docker_sandbox",
        lambda image=None, timeout=300, cpu_count=None, memory_mb=None: fake,
    )
    sb = mgr.create(sandbox_timeout=10)
    assert sb is fake


def test_create_busy_raises() -> None:
    mgr = sp.SandboxManager()
    mgr._semaphore = FakeSemaphore(acquired=False)
    try:
        mgr.create(sandbox_timeout=10)
        assert False, "expected SandboxBusyError"
    except sp.SandboxBusyError:
        pass


def test_create_and_destroy_success(monkeypatch) -> None:
    mgr = sp.SandboxManager()
    mgr._semaphore = FakeSemaphore(acquired=True)
    fake = FakeSandbox("sb-ok")

    monkeypatch.setattr(
        sp,
        "create_docker_sandbox",
        lambda image=None, timeout=300, cpu_count=None, memory_mb=None: fake,
    )

    sb = mgr.create(sandbox_timeout=22, template_id="tpl")
    assert sb is fake
    stats = mgr.get_stats()
    assert stats["total_created"] == 1
    assert stats["current_active"] == 1

    mgr.destroy(sb)
    stats2 = mgr.get_stats()
    assert stats2["total_destroyed"] == 1
    assert stats2["current_active"] == 0
    assert fake.closed is True


def test_helper_functions(monkeypatch) -> None:
    mgr = sp.SandboxManager()
    sp.SandboxManager._instance = mgr
    monkeypatch.setattr(
        mgr,
        "create",
        lambda sandbox_timeout, template_id=None, cpu_count=None, memory_mb=None: "sandbox",
    )
    monkeypatch.setattr(mgr, "destroy", lambda sandbox: None)
    monkeypatch.setattr(mgr, "get_stats", lambda: {"ok": 1})

    assert sp.create_sandbox(10, "tpl") == "sandbox"
    assert sp.create_sandbox(10) == "sandbox"
    sp.destroy_sandbox("sandbox")
    assert sp.get_sandbox_stats() == {"ok": 1}

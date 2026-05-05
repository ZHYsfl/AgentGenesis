from __future__ import annotations

import json
import queue
import sys
import threading
import types
from types import SimpleNamespace
from typing import Any

import pytest

from evaluation.runtime import judge_runtime as judge_mod
from evaluation.runtime import user_runtime as user_mod


class _FakeServer:
    def __init__(self) -> None:
        self.ports: list[str] = []
        self.started = False
        self.waited = False

    def add_insecure_port(self, value: str) -> int:
        self.ports.append(value)
        return 1

    def start(self) -> None:
        self.started = True

    def wait_for_termination(self) -> None:
        self.waited = True


class _ImmediateThread:
    def __init__(self, target=None, args=(), kwargs=None, daemon=False) -> None:  # type: ignore[no-untyped-def]
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}
        self.daemon = daemon

    def start(self) -> None:
        if self._target is not None:
            self._target(*self._args, **self._kwargs)


def test_judge_runtime_queue_and_case_request_paths() -> None:
    runtime = judge_mod.JudgeRuntime()

    src = {"type": "x", "value": 1}
    runtime.send(src)
    src["value"] = 99
    assert runtime._outbound_queue.get_nowait()["value"] == 1

    runtime._inbound_queue.put(None)
    assert runtime.recv() is None
    runtime._inbound_queue.put("not-dict")
    assert runtime.recv() is None
    runtime._inbound_queue.put({"type": "ok"})
    assert runtime.recv() == {"type": "ok"}

    runtime.recv = lambda: None  # type: ignore[method-assign]
    assert runtime.request_next_case_index() is None

    runtime.recv = lambda: {"type": "case_stop"}  # type: ignore[method-assign]
    assert runtime.request_next_case_index() is None

    runtime.recv = lambda: {"type": "other"}  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="unexpected scheduler msg type"):
        runtime.request_next_case_index()

    runtime.recv = lambda: {"type": "case_assign", "case_index": "5"}  # type: ignore[method-assign]
    assert runtime.request_next_case_index() == 5

    out = runtime.with_history_events({"type": "observation"}, {"kind": "obs"})
    assert out["history_events"] == {"kind": "obs"}


def test_judge_bridge_servicer_send_recv_paths() -> None:
    runtime = judge_mod.JudgeRuntime()
    servicer = judge_mod.JudgeRuntime._BridgeServicer(runtime)

    ready = servicer.CheckReady(judge_mod.eval_bridge_pb2.Empty(), None)
    assert ready.is_ready is True

    ack_empty = servicer.SendMessage(judge_mod.eval_bridge_pb2.ProtocolEnvelope(json_message=""), None)
    assert ack_empty.ok is False
    assert "empty" in ack_empty.error

    ack_bad_json = servicer.SendMessage(judge_mod.eval_bridge_pb2.ProtocolEnvelope(json_message="{"), None)
    assert ack_bad_json.ok is False
    assert "invalid json" in ack_bad_json.error

    ack_non_dict = servicer.SendMessage(
        judge_mod.eval_bridge_pb2.ProtocolEnvelope(json_message=json.dumps(["x"])),
        None,
    )
    assert ack_non_dict.ok is False
    assert "json object" in ack_non_dict.error

    ack_ok = servicer.SendMessage(
        judge_mod.eval_bridge_pb2.ProtocolEnvelope(json_message=json.dumps({"type": "ok"})),
        None,
    )
    assert ack_ok.ok is True
    assert runtime._inbound_queue.get_nowait()["type"] == "ok"

    timeout_resp = servicer.RecvMessage(judge_mod.eval_bridge_pb2.RecvRequest(timeout_ms=1), None)
    assert timeout_resp.has_message is False

    runtime._outbound_queue.put({"type": "action", "data": {"d": "L"}})
    recv_resp = servicer.RecvMessage(judge_mod.eval_bridge_pb2.RecvRequest(timeout_ms=0), None)
    assert recv_resp.has_message is True
    assert json.loads(recv_resp.json_message)["type"] == "action"


def test_serve_judge_runtime_bootstrap_and_error_report(monkeypatch) -> None:
    server = _FakeServer()
    captured: dict[str, Any] = {}

    monkeypatch.setattr(judge_mod.grpc, "server", lambda executor, **kwargs: server)
    monkeypatch.setattr(
        judge_mod.eval_bridge_pb2_grpc,
        "add_SandboxBridgeServicer_to_server",
        lambda servicer, svr: captured.update({"servicer": servicer, "server": svr}),
    )
    monkeypatch.setattr(judge_mod.threading, "Thread", _ImmediateThread)

    monkeypatch.setenv("SANDBOX_GRPC_PORT", "6001")
    judge_mod.serve_judge_runtime(lambda runtime: runtime.send({"type": "ok"}))
    assert server.started is True
    assert server.waited is True
    assert server.ports == ["[::]:6001"]
    runtime = captured["servicer"]._runtime
    assert runtime._outbound_queue.get_nowait()["type"] == "ok"

    server2 = _FakeServer()
    captured2: dict[str, Any] = {}
    monkeypatch.setattr(judge_mod.grpc, "server", lambda executor, **kwargs: server2)
    monkeypatch.setattr(
        judge_mod.eval_bridge_pb2_grpc,
        "add_SandboxBridgeServicer_to_server",
        lambda servicer, svr: captured2.update({"servicer": servicer, "server": svr}),
    )
    monkeypatch.delenv("SANDBOX_GRPC_PORT", raising=False)
    monkeypatch.setenv("JUDGE_GRPC_PORT", "6002")
    judge_mod.serve_judge_runtime(lambda runtime: (_ for _ in ()).throw(RuntimeError("boom")))
    err_msg = captured2["servicer"]._runtime._outbound_queue.get_nowait()
    assert err_msg["type"] == "error"
    assert "boom" in err_msg["error"]
    assert server2.ports == ["[::]:6002"]


def test_bridge_main_user_runtime_paths(monkeypatch) -> None:
    from evaluation.runtime.user_adapter import UserAdapter

    class _MazeLikeAdapter(UserAdapter):
        def create_user_api(self, act_queue, obs_queue):  # type: ignore[no-untyped-def]
            def move(direction: str) -> str:
                act_queue.put({"direction": str(direction)})
                obs = obs_queue.get()
                if obs is None:
                    raise StopIteration("environment closed")
                return obs

            return move

    adapter_mod = types.ModuleType("agent_genesis.runtime.problem_adapter")
    adapter_mod.get_adapter = lambda preset_name="default": _MazeLikeAdapter()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "agent_genesis.runtime.problem_adapter", adapter_mod)

    mod_normal = types.ModuleType("solution")

    def _entry_ok(move):  # type: ignore[no-untyped-def]
        got = move("R")
        assert got == "obs-1"

    mod_normal.callx = _entry_ok  # type: ignore[attr-defined]
    sys.modules["solution"] = mod_normal

    in_q: "queue.Queue[dict[str, Any] | None]" = queue.Queue()
    out_q: "queue.Queue[dict[str, Any]]" = queue.Queue()
    t = threading.Thread(
        target=user_mod.bridge_main,
        args=(in_q, out_q),
        kwargs={"solve_attr_name": "callx"},
        daemon=True,
    )
    t.start()
    in_q.put({"type": "observation", "data": "obs-1"})
    in_q.put({"type": "action_request"})
    first = out_q.get(timeout=1)
    assert first["type"] == "action"
    assert first["data"]["direction"] == "R"
    in_q.put(None)
    t.join(timeout=1)
    assert not t.is_alive()

    mod_bad = types.ModuleType("solution")
    mod_bad.callx = 123  # type: ignore[attr-defined]
    sys.modules["solution"] = mod_bad
    in_q2: "queue.Queue[dict[str, Any] | None]" = queue.Queue()
    out_q2: "queue.Queue[dict[str, Any]]" = queue.Queue()
    t2 = threading.Thread(
        target=user_mod.bridge_main,
        args=(in_q2, out_q2),
        kwargs={"solve_attr_name": "callx"},
        daemon=True,
    )
    t2.start()
    in_q2.put({"type": "action_request"})
    err = out_q2.get(timeout=1)
    assert err["status"] == "error"
    assert "not callable" in err["error"]
    in_q2.put(None)
    t2.join(timeout=1)
    assert not t2.is_alive()

    mod_stop = types.ModuleType("solution")

    def _solve_stop(move):  # type: ignore[no-untyped-def]
        _ = move
        raise StopIteration()

    mod_stop.callx = _solve_stop  # type: ignore[attr-defined]
    sys.modules["solution"] = mod_stop
    in_q3: "queue.Queue[dict[str, Any] | None]" = queue.Queue()
    out_q3: "queue.Queue[dict[str, Any]]" = queue.Queue()
    t3 = threading.Thread(
        target=user_mod.bridge_main,
        args=(in_q3, out_q3),
        kwargs={"solve_attr_name": "callx"},
        daemon=True,
    )
    t3.start()
    in_q3.put({"type": "action_request"})
    done = out_q3.get(timeout=1)
    assert done == {"type": "action", "data": None}
    in_q3.put(None)
    t3.join(timeout=1)
    assert not t3.is_alive()

    sys.modules.pop("solution", None)


def test_user_bridge_servicer_and_serve_user_runtime(monkeypatch) -> None:
    def _fake_bridge(inbound_queue, outbound_queue, **kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        while True:
            msg = inbound_queue.get()
            if msg is None:
                return
            if msg.get("type") == "action_request":
                outbound_queue.put({"type": "action", "data": {"direction": "L"}})

    monkeypatch.setattr(user_mod, "bridge_main", _fake_bridge)
    servicer = user_mod.UserBridgeServicer(solve_attr_name="callx")

    ready = servicer.CheckReady(user_mod.eval_bridge_pb2.Empty(), None)
    assert ready.is_ready is True

    ack_empty = servicer.SendMessage(user_mod.eval_bridge_pb2.ProtocolEnvelope(json_message=""), None)
    assert ack_empty.ok is False
    ack_bad_json = servicer.SendMessage(user_mod.eval_bridge_pb2.ProtocolEnvelope(json_message="{"), None)
    assert ack_bad_json.ok is False
    ack_non_dict = servicer.SendMessage(
        user_mod.eval_bridge_pb2.ProtocolEnvelope(json_message=json.dumps(["x"])),
        None,
    )
    assert ack_non_dict.ok is False

    ack_ok = servicer.SendMessage(
        user_mod.eval_bridge_pb2.ProtocolEnvelope(json_message=json.dumps({"type": "action_request"})),
        None,
    )
    assert ack_ok.ok is True
    resp = servicer.RecvMessage(user_mod.eval_bridge_pb2.RecvRequest(timeout_ms=500), None)
    assert resp.has_message is True
    assert json.loads(resp.json_message)["type"] == "action"
    servicer._inbound_queue.put(None)

    server = _FakeServer()
    captured: dict[str, Any] = {}

    class _NoopServicer:
        def __init__(
            self,
            *,
            solve_attr_name: str = "solve",
            adapter_preset: str = "default",
        ) -> None:
            self.solve_attr_name = solve_attr_name
            self.adapter_preset = adapter_preset

    monkeypatch.setattr(user_mod.grpc, "server", lambda executor, **kwargs: server)
    monkeypatch.setattr(user_mod, "UserBridgeServicer", _NoopServicer)
    monkeypatch.setattr(
        user_mod.eval_bridge_pb2_grpc,
        "add_SandboxBridgeServicer_to_server",
        lambda serv, svr: captured.update({"servicer": serv, "server": svr}),
    )
    monkeypatch.setenv("SANDBOX_GRPC_PORT", "7001")
    user_mod.serve_user_runtime(solve_attr_name="callx")
    assert server.started is True
    assert server.waited is True
    assert server.ports == ["[::]:7001"]
    assert captured["servicer"].solve_attr_name == "callx"
    assert captured["servicer"].adapter_preset == "default"


def test_user_runtime_no_hardcoded_direction() -> None:
    """Anti-regression: evaluation runtime must not hardcode Maze-specific action shape."""
    import evaluation.runtime.user_runtime as ur
    from pathlib import Path
    src = Path(ur.__file__ or "").resolve()
    if src.suffix == ".pyc":
        src = src.with_suffix(".py")
    if src.suffix != ".py":
        return
    content = src.read_text(encoding="utf-8")
    assert '"direction"' not in content, "user_runtime must not hardcode direction; use adapter"


def test_user_adapter_from_problem_module_produces_direction_action(monkeypatch) -> None:
    """Problem adapter module can define action payload semantics."""
    from evaluation.runtime.user_adapter import get_adapter
    from evaluation.runtime.user_adapter import UserAdapter

    class _MazeLikeAdapter(UserAdapter):
        def create_user_api(self, act_queue, obs_queue):  # type: ignore[no-untyped-def]
            def move(direction: str) -> str:
                act_queue.put({"direction": str(direction)})
                obs = obs_queue.get()
                if obs is None:
                    raise StopIteration("environment closed")
                return obs

            return move

    adapter_mod = types.ModuleType("agent_genesis.runtime.problem_adapter")
    adapter_mod.get_adapter = lambda preset_name="default": _MazeLikeAdapter()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "agent_genesis.runtime.problem_adapter", adapter_mod)

    act_queue: "queue.Queue[Any]" = queue.Queue()
    obs_queue: "queue.Queue[Any]" = queue.Queue()
    adapter = get_adapter("maze")
    move = adapter.create_user_api(act_queue, obs_queue)

    obs_queue.put("ok")
    result = move("right")
    assert result == "ok"
    payload = act_queue.get_nowait()
    assert payload == {"direction": "right"}

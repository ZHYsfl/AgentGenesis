from __future__ import annotations

import time
import json
import queue
from types import SimpleNamespace
from typing import Any

import pytest

from .. import isolated_evaluator as eval_pkg
from .. import runtime as rt_pkg
from ..runtime import isolated_session as iso_session_mod
from ..isolated_evaluator import IsolatedMultiAgentEvaluator
from ..models import (
    CaseResult,
    CaseStatus,
    PhaseConfig,
    PhaseStatus,
    RuntimeConfig,
    UserSubmission,
)
from ..runtime.isolated_adapter import IsolatedAgentAdapter
from ..runtime.isolated_session import (
    AgentSandboxSpec,
    IsolatedMultiAgentSession,
    IsolatedSessionDeps,
)
from ..runtime.multi_agent_scaffold import run_multi_agent_case


def _cfg(**kwargs: Any) -> PhaseConfig:
    base = {
        "phase_order": 1,
        "phase_level": "Medium",
        "phase_name": "werewolf",
        "num_cases": 2,
        "parallel_cases": 2,
        "artifact_url": "http://artifact",
        "artifact_checksum": "",
        "sandbox_timeout": 30,
        "user_deps_timeout": 10,
        "case_idle_timeout": 5,
        "pip_dependencies": [],
        "allowed_packages": [],
        "agent_ids": ["wolf_1", "seer"],
        "npc_agent_ids": ["wolf_1"],
        "npc_code_prefix": "wolf_agent/",
        "adapter_preset": "isolated_werewolf",
        "solve_entry_map": {
            "wolf_1": "solve_wolf_1",
            "seer": "solve_seer",
        },
    }
    base.update(kwargs)
    return PhaseConfig(**base)


def _submission(cfg: PhaseConfig, files: dict[str, str] | None = None) -> UserSubmission:
    return UserSubmission(
        submit_id=11,
        user_id=22,
        phase_id=33,
        code_url="http://code",
        code_checksum="",
        code_files=files or {
            "requirements.txt": "pytest\n",
            "solution.py": "def solve_seer(env): pass",
        },
        phase_config=cfg,
        runtime_config=RuntimeConfig(),
        phase_type="agent",
    )


class _FakeTransport:
    def __init__(
        self,
        *,
        ready: bool = True,
        recv_script: list[Any] | None = None,
        send_error: Exception | None = None,
    ) -> None:
        self.ready = ready
        self.recv_script = list(recv_script or [])
        self.send_error = send_error
        self.sent: list[dict[str, Any]] = []
        self.closed = False

    def wait_for_ready(self, timeout: int) -> bool:
        _ = timeout
        return self.ready

    def send_message(self, msg: dict[str, Any], timeout: int) -> None:
        _ = timeout
        if self.send_error:
            raise self.send_error
        self.sent.append(dict(msg))

    def recv_message(self, timeout: int) -> Any:
        _ = timeout
        if not self.recv_script:
            return None
        item = self.recv_script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def close(self) -> None:
        self.closed = True


class _FakeSandbox:
    def __init__(self, sid: str) -> None:
        self.id = sid
        self.commands: list[dict[str, Any]] = []

    def run_command(
        self,
        command: str,
        *,
        timeout: int = 30,
        envs: dict[str, str] | None = None,
        background: bool = False,
    ) -> Any:
        payload = {
            "command": command,
            "timeout": timeout,
            "envs": dict(envs or {}),
            "background": bool(background),
        }
        self.commands.append(payload)
        return SimpleNamespace(stdout="", stderr="")


class _TestAdapter(IsolatedAgentAdapter):
    def _build_env(self, agent_id: str, call_tool: Any) -> Any:
        return SimpleNamespace(
            player_id=agent_id,
            speak=lambda text: call_tool("speak", text=text),
            connection=lambda: call_tool("connection"),
        )


class _FakeRuntime:
    def __init__(self, recv_messages: list[dict[str, Any] | None]) -> None:
        self._recv_messages = list(recv_messages)
        self.sent: list[dict[str, Any]] = []

    def send(self, msg: dict[str, Any]) -> None:
        self.sent.append(dict(msg))

    def recv(self) -> dict[str, Any] | None:
        if not self._recv_messages:
            return None
        return self._recv_messages.pop(0)

    def with_history_events(self, msg: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
        out = dict(msg)
        out["history_events"] = [event]
        return out


def _build_session(
    *,
    transports: list[_FakeTransport] | None = None,
    config: PhaseConfig | None = None,
) -> tuple[IsolatedMultiAgentSession, dict[str, Any]]:
    cfg = config or _cfg()
    created: list[_FakeSandbox] = []
    destroyed: list[str] = []
    proc_stopped: list[str] = []
    writes: list[tuple[str, list[str], str]] = []
    transport_queue = list(transports or [_FakeTransport(), _FakeTransport(), _FakeTransport()])
    process_counter = {"n": 0}

    def _create_sandbox(**kwargs: Any) -> _FakeSandbox:
        _ = kwargs
        sb = _FakeSandbox(f"sb-{len(created)}")
        created.append(sb)
        return sb

    def _destroy_sandbox(sb: _FakeSandbox) -> None:
        destroyed.append(sb.id)

    def _write_files(sb: _FakeSandbox, files: dict[str, bytes], base: str) -> None:
        writes.append((sb.id, sorted(files.keys()), base))

    def _start_background_python(**kwargs: Any) -> Any:
        _ = kwargs
        process_counter["n"] += 1
        return SimpleNamespace(name=f"p{process_counter['n']}")

    def _create_transport(sb: _FakeSandbox, port: int) -> _FakeTransport:
        _ = (sb, port)
        if not transport_queue:
            return _FakeTransport()
        return transport_queue.pop(0)

    sub = SimpleNamespace(submit_id=99)

    deps = IsolatedSessionDeps(
        create_sandbox=_create_sandbox,
        destroy_sandbox=_destroy_sandbox,
        resolve_sandbox_resources=lambda: (1, 256),
        load_bridge_support_files=lambda: {"eval_runtime/user_runtime.py": b"x"},
        write_files_chunked=_write_files,
        build_judge_envs=lambda submission, token: {"BASE": "JUDGE"},
        build_agent_envs=lambda submission, token: {"BASE": "AGENT"},
        resolve_entrypoint=lambda: "sandbox/run.py",
        start_background_python=_start_background_python,
        create_transport=_create_transport,
        stop_process=lambda p: proc_stopped.append(getattr(p, "name", "none")),
        is_process_alive=lambda p: bool(p),
        describe_process=lambda p: getattr(p, "name", "none"),
        is_likely_mle_exit=lambda sb, path: False,
        parse_case_result=lambda msg, idx: CaseResult(case_index=idx, status=CaseStatus.PASSED, score=100),
        attach_case_history=lambda *args, **kwargs: None,
        record_observation_history=lambda *args, **kwargs: None,
        record_action_history=lambda *args, **kwargs: None,
        template_image="tmpl:v1",
    )
    session = IsolatedMultiAgentSession(
        deps=deps,
        config=cfg,
        submission=sub,
        agent_specs=[
            AgentSandboxSpec("wolf_1", {"solution.py": b"x"}, requirements_path="requirements.txt"),
            AgentSandboxSpec("seer", {"solution.py": b"y"}),
        ],
        judge_artifact_files={"sandbox/run.py": b"print(1)"},
        judge_envs_base={"PHASE": "x"},
        case_index=3,
        track_per_case_usage=False,
        on_case_start=None,
        on_case_end=None,
        deadline=time.time() + 1000.0,
        compute_step_deadline=lambda d: d,
        attach_llm_usage_delta=None,
    )
    state = {
        "created": created,
        "destroyed": destroyed,
        "writes": writes,
        "proc_stopped": proc_stopped,
    }
    return session, state


def test_runtime_and_package_lazy_imports() -> None:
    assert callable(getattr(rt_pkg, "run_multi_agent_case"))
    assert hasattr(eval_pkg, "IsolatedMultiAgentEvaluator")

    with pytest.raises(AttributeError):
        getattr(rt_pkg, "definitely_not_exists")

    with pytest.raises(AttributeError):
        getattr(eval_pkg, "definitely_not_exists")


def test_isolated_adapter_call_and_stop_iteration(monkeypatch) -> None:
    adapter = _TestAdapter()
    aq: queue.Queue[dict[str, Any] | None] = queue.Queue()
    oq: queue.Queue[Any | None] = queue.Queue()
    monkeypatch.setenv("AGENT_ID", "seer")

    env = adapter.create_user_api(aq, oq)
    oq.put("ok")
    out = env.speak("hello")
    assert out == "ok"
    assert aq.get(timeout=1) == {"action": "speak", "text": "hello"}

    oq.put(None)
    with pytest.raises(StopIteration):
        env.connection()


def test_multi_agent_scaffold_success_timeout_and_errors(monkeypatch) -> None:
    # success path
    done_state = {"done": False}
    rt = _FakeRuntime([{"type": "action", "data": {"seer": {"action": "connection"}}}])
    out = run_multi_agent_case(
        rt,  # type: ignore[arg-type]
        case_index=0,
        agent_ids=["seer"],
        time_limit_seconds=10.0,
        get_step=lambda: 1,
        apply_actions=lambda action: done_state.__setitem__("done", True) or {"seer": "obs"},
        build_history_event=lambda payload: {"kind": "observation", "payload": payload},
        is_done=lambda: done_state["done"],
        is_success=lambda: True,
        compute_score=lambda: 88,
        build_output_data=lambda: {"k": 1},
    )
    assert out["status"] == "passed"
    assert any(m.get("type") == "observation" for m in rt.sent)

    # timeout path
    rt_timeout = _FakeRuntime([])
    seq = iter([100.0, 101.0, 101.0])  # start_time, loop check, elapsed
    real_time = time.time
    monkeypatch.setattr("agent_genesis.runtime.multi_agent_scaffold.time.time", lambda: next(seq))
    out_timeout = run_multi_agent_case(
        rt_timeout,  # type: ignore[arg-type]
        case_index=1,
        agent_ids=["seer"],
        time_limit_seconds=0.5,
        get_step=lambda: 0,
        apply_actions=lambda action: {},
        build_history_event=lambda payload: {},
        is_done=lambda: False,
        is_success=lambda: False,
        compute_score=lambda: 0,
        build_output_data=lambda: {},
    )
    assert out_timeout["status"] == "tle"
    assert out_timeout["error"] == "timeout"
    monkeypatch.setattr("agent_genesis.runtime.multi_agent_scaffold.time.time", real_time)

    # action error + null data path
    rt_error = _FakeRuntime([{"type": "action", "error": "boom", "status": "mle"}])
    out_error = run_multi_agent_case(
        rt_error,  # type: ignore[arg-type]
        case_index=2,
        agent_ids=["seer"],
        time_limit_seconds=10.0,
        get_step=lambda: 0,
        apply_actions=lambda action: {},
        build_history_event=lambda payload: {},
        is_done=lambda: False,
        is_success=lambda: False,
        compute_score=lambda: 0,
        build_output_data=lambda: {},
    )
    assert out_error["status"] == "mle"
    assert "memory limit exceeded" in (out_error["error"] or "")

    rt_null = _FakeRuntime([{"type": "action", "data": None}])
    out_null = run_multi_agent_case(
        rt_null,  # type: ignore[arg-type]
        case_index=3,
        agent_ids=["seer"],
        time_limit_seconds=10.0,
        get_step=lambda: 0,
        apply_actions=lambda action: {},
        build_history_event=lambda payload: {},
        is_done=lambda: False,
        is_success=lambda: False,
        compute_score=lambda: 0,
        build_output_data=lambda: {},
    )
    assert out_null["status"] == "error"
    assert "terminated early" in (out_null["error"] or "")


def test_isolated_session_setup_router_request_send_poll_and_cleanup(monkeypatch) -> None:
    session, state = _build_session()
    session._setup_sandboxes_and_runtime()
    assert session.judge_transport is not None
    assert sorted(session.agent_transports.keys()) == ["seer", "wolf_1"]
    assert state["writes"]  # judge + agents file writes occurred

    # router sets case result
    monkeypatch.setattr(
        iso_session_mod,
        "run_pair_protocol_router",
        lambda **kwargs: SimpleNamespace(
            cases=[CaseResult(case_index=3, status=CaseStatus.PASSED, score=66)]
        ),
    )
    session._run_router()
    assert session.result is not None
    assert session.result.score == 66

    # fan-in success path with per-agent payload
    agent_ids = sorted(session.agent_transports.keys())
    payloads = {
        aid: json.dumps({"type": "action", "data": {"action": "connection"}})
        for aid in agent_ids
    }
    session._poll_agent_line = lambda aid, deadline: payloads[aid]  # type: ignore[method-assign]
    trigger = {"type": "action_request", "history_events": [{"x": 1}]}
    action_out = session._request_user_action(trigger)
    assert action_out["type"] == "action"
    assert set(action_out["data"].keys()) == set(agent_ids)
    for aid in agent_ids:
        sent = session.agent_transports[aid].sent[-1]
        assert "history_events" not in sent

    # fan-in no response -> error
    session._poll_agent_line = lambda aid, deadline: None  # type: ignore[method-assign]
    none_error = session._request_user_action({"type": "action_request"})
    assert none_error["status"] == "error"
    assert "no response" in (none_error["error"] or "")

    # fan-in explicit null action payload from every agent -> action.data=None
    null_payloads = {
        aid: json.dumps({"type": "action", "data": None})
        for aid in agent_ids
    }
    session._poll_agent_line = lambda aid, deadline: null_payloads[aid]  # type: ignore[method-assign]
    none_out = session._request_user_action({"type": "action_request"})
    assert none_out == {"type": "action", "data": None}

    # fan-in send error path
    broken = _FakeTransport(send_error=RuntimeError("send failed"))
    good = _FakeTransport()
    session.agent_transports = {"a": broken, "b": good}
    send_out = session._request_user_action({"type": "action_request"})
    assert send_out["status"] == "error"
    assert "send to a failed" in (send_out["error"] or "")

    # fan-out scalar and dict paths
    t1 = _FakeTransport()
    t2 = _FakeTransport(send_error=RuntimeError("x"))
    session.agent_transports = {"a": t1, "b": t2}
    session._send_to_user({"type": "observation", "data": "same"}, timeout=1)
    assert t1.sent[-1]["data"] == "same"
    session._send_to_user({"type": "observation", "data": {"a": "oa", "b": "ob"}}, timeout=1)
    assert t1.sent[-1]["data"] == "oa"

    # poll transport line / timeout / process-dead branches
    tr_line = _FakeTransport(recv_script=["line-1"])
    line, dead = session._poll_transport_line(
        transport=tr_line, process=SimpleNamespace(), stop_deadline=time.time() + 100.0, poll_seconds=1
    )
    assert line == "line-1"
    assert dead is False

    # recv exception + process not alive -> dead
    session.deps.is_process_alive = lambda p: False  # type: ignore[method-assign]
    tr_exc = _FakeTransport(recv_script=[RuntimeError("recv boom")])
    line2, dead2 = session._poll_transport_line(
        transport=tr_exc, process=SimpleNamespace(), stop_deadline=time.time() + 100.0, poll_seconds=1
    )
    assert line2 is None
    assert dead2 is True

    session._cleanup()
    assert state["destroyed"]  # all created sandboxes destroyed
    assert state["proc_stopped"]  # all processes stopped


def test_isolated_session_run_default_error_result_and_setup_ready_fail() -> None:
    # run() with no result from router -> default error case
    session, _ = _build_session()
    session._setup_sandboxes_and_runtime = lambda: None  # type: ignore[method-assign]
    session._run_router = lambda: None  # type: ignore[method-assign]
    session._cleanup = lambda: None  # type: ignore[method-assign]
    out = session.run()
    assert out.status == CaseStatus.ERROR
    assert "no case result returned" in (out.error or "")

    # setup fails when judge transport is not ready
    not_ready = [_FakeTransport(ready=False)]
    session2, _ = _build_session(transports=not_ready)
    with pytest.raises(RuntimeError, match="judge bridge not ready"):
        session2._setup_sandboxes_and_runtime()


def test_isolated_evaluator_single_case_parallel_and_evaluate_paths(monkeypatch) -> None:
    cfg = _cfg(num_cases=2, parallel_cases=2)
    ev = IsolatedMultiAgentEvaluator(cfg)
    sub = _submission(cfg)

    monkeypatch.setattr(eval_pkg, "get_or_create_template", lambda **kwargs: "tmpl:v1")
    monkeypatch.setattr(eval_pkg, "runtime_resolve_sandbox_resources", lambda config: (1, 256))
    monkeypatch.setattr(eval_pkg, "runtime_load_grpc_bridge_support_files", lambda _: {"bridge.py": b"x"})
    monkeypatch.setattr(eval_pkg, "runtime_write_files_chunked", lambda *args, **kwargs: None)
    monkeypatch.setattr(eval_pkg, "runtime_build_judge_envs", lambda **kwargs: {"J": "1"})
    monkeypatch.setattr(eval_pkg, "runtime_build_user_envs", lambda **kwargs: {"U": "1"})
    monkeypatch.setattr(eval_pkg, "runtime_resolve_entrypoint", lambda config: "sandbox/run.py")
    monkeypatch.setattr(eval_pkg, "runtime_is_likely_mle_exit", lambda config, sb, path: False)
    monkeypatch.setattr(
        eval_pkg,
        "runtime_parse_case_result",
        lambda msg, idx: CaseResult(case_index=idx, status=CaseStatus.PASSED, score=100),
    )
    monkeypatch.setattr(eval_pkg, "runtime_attach_case_history", lambda *args, **kwargs: None)
    monkeypatch.setattr(eval_pkg, "runtime_record_observation_history", lambda *args, **kwargs: None)
    monkeypatch.setattr(eval_pkg, "runtime_record_action_history", lambda *args, **kwargs: None)
    monkeypatch.setattr(eval_pkg, "create_sandbox", lambda **kwargs: SimpleNamespace(id="sb"))
    monkeypatch.setattr(eval_pkg, "destroy_sandbox", lambda sb: None)
    monkeypatch.setattr(eval_pkg, "runtime_create_grpc_transport", lambda sb, port: _FakeTransport())
    monkeypatch.setattr(
        eval_pkg.SandboxProcessManager,
        "start_background_python",
        lambda **kwargs: SimpleNamespace(name="p"),
    )
    monkeypatch.setattr(eval_pkg.SandboxProcessManager, "stop_process", lambda proc: None)
    monkeypatch.setattr(eval_pkg.SandboxProcessManager, "is_process_alive", lambda proc: True)
    monkeypatch.setattr(eval_pkg.SandboxProcessManager, "describe_process", lambda proc: "p")

    captured: dict[str, Any] = {}

    class _FakeIsoSession:
        def __init__(self, **kwargs: Any) -> None:
            captured["kwargs"] = kwargs

        def run(self) -> CaseResult:
            return CaseResult(case_index=0, status=CaseStatus.PASSED, score=77)

    monkeypatch.setattr(eval_pkg, "IsolatedMultiAgentSession", _FakeIsoSession)

    single = ev._run_single_case(
        submission=sub,
        gateway_token="tok",
        artifact_files={
            "sandbox/run.py": b"print(1)",
            "sandbox/user_adapter.py": b"class X: pass",
            "wolf_agent/requirements.txt": b"pytest\n",
            "wolf_agent/solution.py": b"def solve_wolf_1(env): pass",
        },
        user_files_bytes={
            "requirements.txt": b"pytest\n",
            "solution.py": b"def solve_seer(env): pass",
        },
        user_req_path="requirements.txt",
        case_index=0,
        track_per_case_usage=False,
        on_case_start=None,
        on_case_end=None,
        deadline=time.time() + 1000.0,
    )
    assert single.status == CaseStatus.PASSED
    assert single.score == 77
    agent_specs = captured["kwargs"]["agent_specs"]
    assert len(agent_specs) == 2
    assert any(spec.agent_id == "wolf_1" for spec in agent_specs)
    assert any(spec.agent_id == "seer" for spec in agent_specs)

    # _run_parallel_cases: success + exception path
    calls = {"n": 0}

    def _run_single_case_stub(**kwargs: Any) -> CaseResult:
        idx = kwargs["case_index"]
        calls["n"] += 1
        if idx == 1:
            raise RuntimeError("case failed")
        return CaseResult(case_index=idx, status=CaseStatus.PASSED, score=1)

    monkeypatch.setattr(ev, "_run_single_case", _run_single_case_stub)
    monkeypatch.setattr(eval_pkg, "get_config", lambda: SimpleNamespace(max_case_parallelism=8))
    cases = ev._run_parallel_cases(
        submission=sub,
        gateway_token=None,
        artifact_files={},
        user_files_bytes={},
        user_req_path="",
        num_cases=2,
        parallel=2,
        on_case_start=None,
        on_case_end=None,
        deadline=time.time() + 1000.0,
        track_per_case_usage=False,
    )
    assert [c.case_index for c in cases] == [0, 1]
    assert cases[1].status == CaseStatus.ERROR
    assert calls["n"] == 2

    # evaluate: gateway token ValueError branch
    monkeypatch.setattr(
        eval_pkg,
        "runtime_create_gateway_token_for_user",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("token denied")),
    )
    monkeypatch.setattr(eval_pkg, "runtime_revoke_gateway_token", lambda *args, **kwargs: None)
    token_fail = ev.evaluate(sub, parallel_cases=1)
    assert token_fail.status == PhaseStatus.ERROR
    assert "token denied" in (token_fail.error or "")

    # evaluate: success + failed aggregation path
    monkeypatch.setattr(eval_pkg, "runtime_create_gateway_token_for_user", lambda *args, **kwargs: "tok")
    monkeypatch.setattr(eval_pkg, "runtime_download_artifact", lambda *args, **kwargs: b"zip")
    monkeypatch.setattr(
        eval_pkg,
        "runtime_extract_artifact",
        lambda data: {"sandbox/run.py": b"print(1)", "sandbox/user_adapter.py": b"class A: pass"},
    )
    monkeypatch.setattr(eval_pkg, "runtime_filter_requirements", lambda reqs, allow: reqs)
    monkeypatch.setattr(
        ev,
        "_run_parallel_cases",
        lambda **kwargs: [
            CaseResult(case_index=0, status=CaseStatus.PASSED, score=60),
            CaseResult(case_index=1, status=CaseStatus.FAILED, score=0),
        ],
    )
    rev = {"ok": False}
    monkeypatch.setattr(
        eval_pkg,
        "runtime_revoke_gateway_token",
        lambda *args, **kwargs: rev.__setitem__("ok", True),
    )
    agg = ev.evaluate(sub, parallel_cases=2)
    assert agg.status == PhaseStatus.FAILED
    assert agg.total_cases == 2
    assert agg.passed_cases == 1
    assert agg.score == 60
    assert rev["ok"] is True

    # evaluate: missing requirements -> outer exception path
    sub_missing = _submission(cfg, files={"solution.py": "def solve_seer(env): pass"})
    monkeypatch.setattr(eval_pkg, "runtime_create_gateway_token_for_user", lambda *args, **kwargs: "tok")
    monkeypatch.setattr(eval_pkg, "runtime_download_artifact", lambda *args, **kwargs: b"zip")
    monkeypatch.setattr(
        eval_pkg,
        "runtime_extract_artifact",
        lambda data: {"sandbox/run.py": b"print(1)", "sandbox/user_adapter.py": b"class A: pass"},
    )
    monkeypatch.setattr(eval_pkg, "runtime_revoke_gateway_token", lambda *args, **kwargs: None)
    missing = ev.evaluate(sub_missing, parallel_cases=1)
    assert missing.status == PhaseStatus.ERROR
    assert "Missing requirements.txt" in (missing.error or "")


def test_multi_agent_scaffold_additional_failed_and_no_response_paths() -> None:
    # no response from bridge
    rt_none = _FakeRuntime([None])
    out_none = run_multi_agent_case(
        rt_none,  # type: ignore[arg-type]
        case_index=9,
        agent_ids=["a1"],
        time_limit_seconds=5.0,
        get_step=lambda: 0,
        apply_actions=lambda action: {},
        build_history_event=lambda payload: {},
        is_done=lambda: False,
        is_success=lambda: False,
        compute_score=lambda: 0,
        build_output_data=lambda: {},
    )
    assert out_none["status"] == "error"
    assert "no response from agents" in (out_none["error"] or "")

    # failed status + default error message
    done = {"v": False}
    rt_failed = _FakeRuntime([{"type": "action", "data": {"a1": {"action": "x"}}}])
    out_failed = run_multi_agent_case(
        rt_failed,  # type: ignore[arg-type]
        case_index=10,
        agent_ids=["a1"],
        time_limit_seconds=5.0,
        get_step=lambda: 0,
        apply_actions=lambda action: done.__setitem__("v", True) or {"a1": "obs"},
        build_history_event=lambda payload: {},
        is_done=lambda: done["v"],
        is_success=lambda: False,
        compute_score=lambda: 100,
        build_output_data=lambda: {},
    )
    assert out_failed["status"] == "failed"
    assert out_failed["error"] == "case finished without success"


def test_isolated_session_additional_branches() -> None:
    session, _ = _build_session()
    session._setup_sandboxes_and_runtime()

    # invalid json branch
    session._poll_agent_line = lambda aid, deadline: "not-json"  # type: ignore[method-assign]
    invalid = session._request_user_action({"type": "action_request"})
    assert invalid["status"] == "error"
    assert "invalid json" in (invalid["error"] or "")

    # per-agent explicit error branch
    session._poll_agent_line = lambda aid, deadline: json.dumps(  # type: ignore[method-assign]
        {"type": "action", "error": "agent blew up", "status": "tle"}
    )
    err = session._request_user_action({"type": "action_request"})
    assert err["status"] in {"error", "tle"}
    assert "agent blew up" in (err["error"] or "")

    # non-dict message fallback branch
    session._poll_agent_line = lambda aid, deadline: json.dumps([1, 2, 3])  # type: ignore[method-assign]
    weird = session._request_user_action({"type": "action_request"})
    assert weird["type"] == "action"
    assert isinstance(weird["data"], dict)

    # _poll_judge_line with no transport
    session.judge_transport = None
    line, dead = session._poll_judge_line(time.time() + 1.0)
    assert line is None
    assert dead is True

    # _poll_agent_line no transport
    session.agent_transports = {}
    assert (
        IsolatedMultiAgentSession._poll_agent_line(  # bypass per-test monkeypatch on instance method
            session, "missing", time.time() + 1.0
        )
        is None
    )

    # _poll_transport_line timeout branch
    tr = _FakeTransport(recv_script=[])
    line2, dead2 = session._poll_transport_line(
        transport=tr, process=SimpleNamespace(), stop_deadline=time.time() - 1.0, poll_seconds=1
    )
    assert line2 is None
    assert dead2 is False

    # _send_to_judge no transport and normal path
    with pytest.raises(RuntimeError, match="judge transport unavailable"):
        session._send_to_judge({"type": "x"}, timeout=1)
    jt = _FakeTransport()
    session.judge_transport = jt
    session._send_to_judge({"type": "action", "data": {}}, timeout=1)
    assert jt.sent[-1]["type"] == "action"


def test_isolated_session_router_case_provider_and_agent_ready_fail(monkeypatch) -> None:
    # case_provider two-call behavior (first index then None)
    session, _ = _build_session()
    session._setup_sandboxes_and_runtime()
    seen: list[int | None] = []

    def _fake_router(**kwargs: Any) -> Any:
        cp = kwargs["case_provider"]
        seen.append(cp())
        seen.append(cp())
        return SimpleNamespace(cases=[])

    monkeypatch.setattr(iso_session_mod, "run_pair_protocol_router", _fake_router)
    session._run_router()
    assert seen == [3, None]
    assert session.result is None

    # agent transport not ready branch (line 182)
    session2, _ = _build_session(
        transports=[_FakeTransport(), _FakeTransport(ready=False)]
    )
    with pytest.raises(RuntimeError, match="agent bridge not ready"):
        session2._setup_sandboxes_and_runtime()


def test_isolated_evaluator_additional_branches(monkeypatch) -> None:
    cfg = _cfg(num_cases=1, parallel_cases=1, allowed_packages=["pytest"])
    ev = IsolatedMultiAgentEvaluator(cfg)
    sub = _submission(cfg, files={})

    # template build failure path + requirements filtering + download_code fallback
    monkeypatch.setattr(
        eval_pkg,
        "get_or_create_template",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("no template")),
    )
    monkeypatch.setattr(eval_pkg, "runtime_create_gateway_token_for_user", lambda *args, **kwargs: "tok")
    monkeypatch.setattr(eval_pkg, "runtime_download_artifact", lambda *args, **kwargs: b"zip")
    monkeypatch.setattr(
        eval_pkg,
        "runtime_extract_artifact",
        lambda data: {
            "sandbox/run.py": b"print(1)",
            "sandbox/user_adapter.py": b"class A: pass",
            "wolf_agent/": b"",  # rel empty branch under npc prefix
        },
    )
    monkeypatch.setattr(eval_pkg, "runtime_filter_requirements", lambda reqs, allow: "pytest\n")
    monkeypatch.setattr(
        ev,
        "_get_client",
        lambda: SimpleNamespace(
            download_code=lambda code_url, expected_checksum="": {
                "requirements.txt": "pytest\n",
                "solution.py": "def solve_seer(env): pass",
            }
        ),
    )
    monkeypatch.setattr(
        ev,
        "_run_parallel_cases",
        lambda **kwargs: [CaseResult(case_index=0, status=CaseStatus.PASSED, score=100)],
    )
    monkeypatch.setattr(eval_pkg, "runtime_revoke_gateway_token", lambda *args, **kwargs: None)
    ok = ev.evaluate(sub, parallel_cases=1)
    assert ok.status == PhaseStatus.SUCCESS

    # _with_step_deadline branches
    ev.config.case_idle_timeout = "bad"  # type: ignore[assignment]
    assert ev._with_step_deadline(123.0) == 123.0
    ev.config.case_idle_timeout = 2
    assert ev._with_step_deadline(time.time() + 1000.0) <= time.time() + 3.0

    # _run_parallel_cases safe_start/safe_end branch
    starts: list[int] = []
    ends: list[int] = []
    monkeypatch.setattr(eval_pkg, "get_config", lambda: SimpleNamespace(max_case_parallelism=2))
    monkeypatch.setattr(
        ev,
        "_run_single_case",
        lambda **kwargs: (
            kwargs["on_case_start"](kwargs["case_index"]),
            kwargs["on_case_end"](
                kwargs["case_index"],
                CaseResult(case_index=kwargs["case_index"], status=CaseStatus.PASSED, score=1),
            ),
            CaseResult(case_index=kwargs["case_index"], status=CaseStatus.PASSED, score=1),
        )[-1],
    )
    out_cases = IsolatedMultiAgentEvaluator._run_parallel_cases(
        ev,
        submission=_submission(cfg),
        gateway_token=None,
        artifact_files={},
        user_files_bytes={},
        user_req_path="",
        num_cases=1,
        parallel=1,
        on_case_start=lambda i: starts.append(i),
        on_case_end=lambda i, r: ends.append(i),
        deadline=time.time() + 1000.0,
        track_per_case_usage=False,
    )
    assert len(out_cases) == 1
    assert starts == [0]
    assert ends == [0]


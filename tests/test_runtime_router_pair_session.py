"""Unit tests for router and pair-session runtime flow."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from ..models import CaseResult, CaseStatus, PhaseConfig, RuntimeConfig, UserSubmission
from ..runtime import pair_session as pair_mod
from ..runtime.protocol import MessageType
from ..runtime.router import run_pair_protocol_router


class _DummyTransport:
    def __init__(
        self,
        *,
        wait_ready: bool = True,
        recv_items: Optional[list[Optional[str]]] = None,
        recv_exc: Exception | None = None,
        send_exc: Exception | None = None,
        close_exc: Exception | None = None,
    ) -> None:
        self.wait_ready_value = wait_ready
        self.recv_items = list(recv_items or [])
        self.recv_exc = recv_exc
        self.send_exc = send_exc
        self.close_exc = close_exc
        self.sent: list[dict[str, Any]] = []
        self.closed = False

    def wait_for_ready(self, timeout: int) -> bool:
        _ = timeout
        return self.wait_ready_value

    def send_message(self, msg: dict[str, Any], timeout: int) -> None:
        _ = timeout
        if self.send_exc is not None:
            raise self.send_exc
        self.sent.append(dict(msg))

    def recv_message(self, timeout: int) -> Optional[str]:
        _ = timeout
        if self.recv_exc is not None:
            raise self.recv_exc
        if not self.recv_items:
            return None
        return self.recv_items.pop(0)

    def close(self) -> None:
        if self.close_exc is not None:
            raise self.close_exc
        self.closed = True


class _DummyCommands:
    def __init__(self, script=None) -> None:  # type: ignore[no-untyped-def]
        self.calls: list[dict[str, Any]] = []
        self._script = script

    def run(self, command: str, timeout: int = 30, envs: dict[str, str] | None = None):  # type: ignore[no-untyped-def]
        payload = {"command": command, "timeout": timeout, "envs": envs or {}}
        self.calls.append(payload)
        if self._script is None:
            return SimpleNamespace(stdout="", stderr="")
        return self._script(command=command, timeout=timeout, envs=envs or {})


class _DummySandbox:
    def __init__(self, sid: str, script=None) -> None:  # type: ignore[no-untyped-def]
        self.id = sid
        self.commands = _DummyCommands(script=script)

    def run_command(self, command: str, *, timeout: int = 30, envs: dict[str, str] | None = None, background: bool = False):  # type: ignore[no-untyped-def]
        return self.commands.run(command, timeout=timeout, envs=envs)


class _Handle:
    def __init__(self, name: str) -> None:
        self.name = name
        self.stopped = False
        self.status = "running"

    def terminate(self) -> None:
        self.stopped = True
        self.status = "stopped"


def _submission() -> UserSubmission:
    cfg = PhaseConfig(phase_order=1, phase_level="Easy", phase_name="p1")
    return UserSubmission(
        submit_id=101,
        user_id=202,
        phase_id=1,
        code_url="http://code.zip",
        code_checksum="",
        code_files={"solution.py": "def solve(x): return x"},
        phase_config=cfg,
        runtime_config=RuntimeConfig(),
        phase_type="agent",
    )


def _make_session(*, deadline: Optional[float] = None, step_deadline=None):  # type: ignore[no-untyped-def]
    state: dict[str, Any] = {
        "stopped": [],
        "destroyed": [],
        "alive": True,
        "mle": False,
        "next_handle": _Handle("init"),
    }

    judge_sb = _DummySandbox("judge")
    user_sb = _DummySandbox("user")

    def _create_sandbox(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        if "created" not in state:
            state["created"] = 0
        state["created"] += 1
        return judge_sb if state["created"] == 1 else user_sb

    deps = pair_mod.PairSessionDeps(
        create_sandbox=_create_sandbox,
        destroy_sandbox=lambda sb: state["destroyed"].append(sb),
        resolve_sandbox_resources=lambda: (None, None),
        load_bridge_support_files=lambda: {},
        write_files_chunked=lambda sb, files, base_dir: None,
        build_judge_envs=lambda sub, token: {},
        build_user_envs=lambda sub, token: {},
        resolve_entrypoint=lambda: "sandbox/run.py",
        start_background_python=lambda **kwargs: state["next_handle"],
        create_transport=lambda sb, port: _DummyTransport(wait_ready=True),
        stop_process=lambda process: state["stopped"].append(process),
        is_process_alive=lambda process: bool(state["alive"]),
        describe_process=lambda process: (
            f"handle:{getattr(process, 'name', 'none')}" if process else "none"
        ),
        is_likely_mle_exit=lambda sb, stderr_path: bool(state["mle"]),
        parse_case_result=lambda msg, idx: CaseResult(case_index=idx, status=CaseStatus.PASSED, score=1),
        attach_case_history=lambda case_result, case_histories, current_case_index: None,
        record_observation_history=lambda case_histories, current_case_index, msg: None,
        record_action_history=lambda case_histories, current_case_index, action_msg: None,
    )

    cfg = PhaseConfig(
        phase_order=1,
        phase_level="Easy",
        phase_name="p1",
        sandbox_timeout=30,
        user_deps_timeout=5,
    )
    session = pair_mod._SandboxPairSession(
        deps=deps,
        config=cfg,
        submission=_submission(),
        gateway_token=None,
        artifact_files={},
        user_files_bytes={},
        user_req_path="",
        case_index=0,
        track_per_case_usage=False,
        on_case_start=None,
        on_case_end=None,
        deadline=deadline if deadline is not None else time.time() + 30,
        compute_step_deadline=step_deadline or (lambda d: d),
        attach_llm_usage_delta=None,
    )
    session.judge_sb = judge_sb
    session.user_sb = user_sb
    session.judge_envs = {}
    session.user_envs = {}
    session.user_port = 50052
    return session, state


def test_router_handles_invalid_json_parse_error_and_unknown_types() -> None:
    lines = iter(
        [
            "not-json",
            json.dumps({"type": MessageType.CASE_START, "case_index": "bad"}),
            json.dumps({"type": MessageType.OBSERVATION, "data": {"obs": 1}}),
            json.dumps({"type": MessageType.ACTION_REQUEST}),
            json.dumps({"type": MessageType.CASE_END, "case_index": 0, "status": "passed"}),
            json.dumps({"type": "mystery"}),
            json.dumps({"type": MessageType.ERROR, "error": "judge boom"}),
        ]
    )

    user_sent: list[dict[str, Any]] = []
    judge_sent: list[dict[str, Any]] = []
    starts: list[int] = []
    ends: list[int] = []
    usage_called = {"count": 0}
    histories: dict[int, list[dict[str, Any]]] = {}

    def _poll_judge_line(_deadline: float) -> tuple[Optional[str], bool]:
        try:
            return next(lines), False
        except StopIteration:
            return None, False

    state = run_pair_protocol_router(
        submission_id=999,
        deadline=time.time() + 10,
        case_provider=lambda: None,
        compute_step_deadline=lambda d: d,
        poll_judge_line=_poll_judge_line,
        restart_user_runtime=lambda: None,
        ensure_user_runtime=lambda: None,
        request_user_action=lambda trigger: {"type": "action", "error": "bad-action"},
        send_to_judge=lambda msg, timeout: judge_sent.append(dict(msg)),
        send_to_user=lambda msg, timeout: (_ for _ in ()).throw(RuntimeError("send user failed")),
        parse_case_result=lambda msg, fallback_idx: (_ for _ in ()).throw(ValueError("bad case_end")),
        attach_case_history=lambda case_result, case_histories, current_case_index: histories.setdefault(
            current_case_index,
            [],
        ).append({"kind": "attached"}),
        record_observation_history=lambda case_histories, current_case_index, msg: case_histories.setdefault(
            current_case_index,
            [],
        ).append({"kind": "observation"}),
        record_action_history=lambda case_histories, current_case_index, action_msg: case_histories.setdefault(
            current_case_index,
            [],
        ).append({"kind": "action"}),
        on_case_start=lambda idx: starts.append(idx),
        on_case_end=lambda idx, case_result: ends.append(idx),
        track_per_case_usage=True,
        attach_llm_usage_delta=lambda case_result: (
            usage_called.__setitem__("count", usage_called["count"] + 1) or case_result
        ),
    )

    assert starts == [0]
    assert ends == [0]
    assert usage_called["count"] == 1
    assert len(state.cases) == 1
    assert state.cases[0].status == CaseStatus.ERROR
    assert "invalid case_end payload" in (state.cases[0].error or "")
    assert any(msg.get("type") == "action" for msg in judge_sent)
    assert user_sent == []


def test_router_stops_on_judge_exit_and_timeout() -> None:
    state_exit = run_pair_protocol_router(
        submission_id=1,
        deadline=time.time() + 5,
        case_provider=lambda: None,
        compute_step_deadline=lambda d: d,
        poll_judge_line=lambda d: (None, True),
        restart_user_runtime=lambda: None,
        ensure_user_runtime=lambda: None,
        request_user_action=lambda trigger: {"type": "action"},
        send_to_judge=lambda msg, timeout: None,
        send_to_user=lambda msg, timeout: None,
        parse_case_result=lambda msg, idx: CaseResult(case_index=idx, status=CaseStatus.PASSED),
        attach_case_history=lambda case_result, case_histories, current_case_index: None,
        record_observation_history=lambda case_histories, current_case_index, msg: None,
        record_action_history=lambda case_histories, current_case_index, action_msg: None,
        on_case_start=None,
        on_case_end=None,
        track_per_case_usage=False,
    )
    assert state_exit.cases == []

    state_timeout = run_pair_protocol_router(
        submission_id=2,
        deadline=time.time() + 5,
        case_provider=lambda: None,
        compute_step_deadline=lambda d: d - 1,
        poll_judge_line=lambda d: (None, False),
        restart_user_runtime=lambda: None,
        ensure_user_runtime=lambda: None,
        request_user_action=lambda trigger: {"type": "action"},
        send_to_judge=lambda msg, timeout: None,
        send_to_user=lambda msg, timeout: None,
        parse_case_result=lambda msg, idx: CaseResult(case_index=idx, status=CaseStatus.PASSED),
        attach_case_history=lambda case_result, case_histories, current_case_index: None,
        record_observation_history=lambda case_histories, current_case_index, msg: None,
        record_action_history=lambda case_histories, current_case_index, action_msg: None,
        on_case_start=None,
        on_case_end=None,
        track_per_case_usage=False,
    )
    assert state_timeout.cases == []


@pytest.mark.parametrize(
    ("bad_action", "error_fragment"),
    [
        ("not-a-dict", "payload type"),
        ({"type": "mystery"}, "message type"),
        ({"type": "action"}, "missing both data and error"),
    ],
)
def test_router_coerces_invalid_user_action_payloads(
    bad_action: Any,
    error_fragment: str,
) -> None:
    lines = iter(
        [
            json.dumps({"type": MessageType.CASE_START, "case_index": 0}),
            json.dumps({"type": MessageType.ACTION_REQUEST}),
            json.dumps({"type": MessageType.CASE_END, "case_index": 0, "status": "passed"}),
            json.dumps({"type": MessageType.EVAL_COMPLETE}),
        ]
    )
    judge_sent: list[dict[str, Any]] = []

    def _poll_judge_line(_deadline: float) -> tuple[Optional[str], bool]:
        try:
            return next(lines), False
        except StopIteration:
            return None, False

    _ = run_pair_protocol_router(
        submission_id=700,
        deadline=time.time() + 10,
        case_provider=lambda: None,
        compute_step_deadline=lambda d: d,
        poll_judge_line=_poll_judge_line,
        restart_user_runtime=lambda: None,
        ensure_user_runtime=lambda: None,
        request_user_action=lambda trigger: bad_action,
        send_to_judge=lambda msg, timeout: judge_sent.append(dict(msg)),
        send_to_user=lambda msg, timeout: None,
        parse_case_result=lambda msg, idx: CaseResult(case_index=idx, status=CaseStatus.PASSED, score=1),
        attach_case_history=lambda case_result, case_histories, current_case_index: None,
        record_observation_history=lambda case_histories, current_case_index, msg: None,
        record_action_history=lambda case_histories, current_case_index, action_msg: None,
        on_case_start=None,
        on_case_end=None,
        track_per_case_usage=False,
    )

    action_msg = next(msg for msg in judge_sent if msg.get("type") == MessageType.ACTION)
    assert action_msg["status"] == "error"
    assert error_fragment in str(action_msg["error"]).lower()


def test_router_backfills_error_status_for_action_error_payload() -> None:
    lines = iter(
        [
            json.dumps({"type": MessageType.CASE_START, "case_index": 0}),
            json.dumps({"type": MessageType.ACTION_REQUEST}),
            json.dumps({"type": MessageType.CASE_END, "case_index": 0, "status": "passed"}),
            json.dumps({"type": MessageType.EVAL_COMPLETE}),
        ]
    )
    judge_sent: list[dict[str, Any]] = []

    def _poll_judge_line(_deadline: float) -> tuple[Optional[str], bool]:
        try:
            return next(lines), False
        except StopIteration:
            return None, False

    _ = run_pair_protocol_router(
        submission_id=701,
        deadline=time.time() + 10,
        case_provider=lambda: None,
        compute_step_deadline=lambda d: d,
        poll_judge_line=_poll_judge_line,
        restart_user_runtime=lambda: None,
        ensure_user_runtime=lambda: None,
        request_user_action=lambda trigger: {"type": "action", "error": "x"},
        send_to_judge=lambda msg, timeout: judge_sent.append(dict(msg)),
        send_to_user=lambda msg, timeout: None,
        parse_case_result=lambda msg, idx: CaseResult(case_index=idx, status=CaseStatus.PASSED, score=1),
        attach_case_history=lambda case_result, case_histories, current_case_index: None,
        record_observation_history=lambda case_histories, current_case_index, msg: None,
        record_action_history=lambda case_histories, current_case_index, action_msg: None,
        on_case_start=None,
        on_case_end=None,
        track_per_case_usage=False,
    )

    action_msg = next(msg for msg in judge_sent if msg.get("type") == MessageType.ACTION)
    assert action_msg["error"] == "x"
    assert action_msg["status"] == "error"


def test_router_forwards_action_data_null_sentinel() -> None:
    lines = iter(
        [
            json.dumps({"type": MessageType.CASE_START, "case_index": 0}),
            json.dumps({"type": MessageType.ACTION_REQUEST}),
            json.dumps({"type": MessageType.CASE_END, "case_index": 0, "status": "passed"}),
            json.dumps({"type": MessageType.EVAL_COMPLETE}),
        ]
    )
    judge_sent: list[dict[str, Any]] = []

    def _poll_judge_line(_deadline: float) -> tuple[Optional[str], bool]:
        try:
            return next(lines), False
        except StopIteration:
            return None, False

    _ = run_pair_protocol_router(
        submission_id=702,
        deadline=time.time() + 10,
        case_provider=lambda: None,
        compute_step_deadline=lambda d: d,
        poll_judge_line=_poll_judge_line,
        restart_user_runtime=lambda: None,
        ensure_user_runtime=lambda: None,
        request_user_action=lambda trigger: {"type": "action", "data": None},
        send_to_judge=lambda msg, timeout: judge_sent.append(dict(msg)),
        send_to_user=lambda msg, timeout: None,
        parse_case_result=lambda msg, idx: CaseResult(case_index=idx, status=CaseStatus.PASSED, score=1),
        attach_case_history=lambda case_result, case_histories, current_case_index: None,
        record_observation_history=lambda case_histories, current_case_index, msg: None,
        record_action_history=lambda case_histories, current_case_index, action_msg: None,
        on_case_start=None,
        on_case_end=None,
        track_per_case_usage=False,
    )

    action_msg = next(msg for msg in judge_sent if msg.get("type") == MessageType.ACTION)
    assert "data" in action_msg
    assert action_msg["data"] is None
    assert "error" not in action_msg


def test_router_stops_on_judge_error_message() -> None:
    lines = iter(
        [
            json.dumps({"type": MessageType.ERROR, "error": "judge boom"}),
        ]
    )

    def _poll_judge_line(_deadline: float) -> tuple[Optional[str], bool]:
        try:
            return next(lines), False
        except StopIteration:
            return None, False

    state = run_pair_protocol_router(
        submission_id=703,
        deadline=time.time() + 10,
        case_provider=lambda: None,
        compute_step_deadline=lambda d: d,
        poll_judge_line=_poll_judge_line,
        restart_user_runtime=lambda: None,
        ensure_user_runtime=lambda: None,
        request_user_action=lambda trigger: {"type": "action", "data": "unused"},
        send_to_judge=lambda msg, timeout: None,
        send_to_user=lambda msg, timeout: None,
        parse_case_result=lambda msg, idx: CaseResult(case_index=idx, status=CaseStatus.PASSED, score=1),
        attach_case_history=lambda case_result, case_histories, current_case_index: None,
        record_observation_history=lambda case_histories, current_case_index, msg: None,
        record_action_history=lambda case_histories, current_case_index, action_msg: None,
        on_case_start=None,
        on_case_end=None,
        track_per_case_usage=False,
    )

    assert state.cases == []
    assert '"type": "error"' in state.last_judge_raw_line


def test_pair_session_poll_transport_and_restart_paths(monkeypatch) -> None:
    session, state = _make_session(deadline=time.time() + 30)
    assert session._poll_judge_line(time.time() + 1) == (None, True)

    t_line = _DummyTransport(recv_items=['{"k":"v"}'])
    out = session._poll_transport_line(
        transport=t_line,
        process=session.user_process,
        stop_deadline=time.time() + 1,
        poll_seconds=1,
    )
    assert out == ('{"k":"v"}', False)

    out_timeout = session._poll_transport_line(
        transport=_DummyTransport(),
        process=session.user_process,
        stop_deadline=time.time() - 1,
        poll_seconds=1,
    )
    assert out_timeout == (None, False)

    state["alive"] = False
    out_dead = session._poll_transport_line(
        transport=_DummyTransport(recv_exc=RuntimeError("recv boom")),
        process=session.user_process,
        stop_deadline=time.time() + 1,
        poll_seconds=1,
    )
    assert out_dead == (None, True)

    state["alive"] = True
    out_alive = session._poll_transport_line(
        transport=_DummyTransport(recv_exc=RuntimeError("recv boom")),
        process=session.user_process,
        stop_deadline=time.time() + 1,
        poll_seconds=1,
    )
    assert out_alive == (None, False)

    state["alive"] = False
    out_none_dead = session._poll_transport_line(
        transport=_DummyTransport(recv_items=[None]),
        process=session.user_process,
        stop_deadline=time.time() + 1,
        poll_seconds=1,
    )
    assert out_none_dead == (None, True)


def test_pair_session_poll_uses_process_handle_identity() -> None:
    session, state = _make_session(deadline=time.time() + 30)
    state["alive"] = True
    probe = _Handle("probe")
    seen: list[Any] = []
    session.deps.is_process_alive = lambda process: seen.append(process) or False  # type: ignore[method-assign]

    out = session._poll_transport_line(
        transport=_DummyTransport(recv_exc=RuntimeError("recv boom")),
        process=probe,
        stop_deadline=time.time() + 1,
        poll_seconds=1,
    )
    assert out == (None, True)
    assert seen == [probe]


def test_pair_session_request_user_action_paths(monkeypatch) -> None:
    session, state = _make_session(deadline=time.time() + 30, step_deadline=lambda d: d - 1)
    session.user_sb = _DummySandbox("user")
    session.user_process = _Handle("user")

    no_transport = session._request_user_action({"type": "action_request"})
    assert no_transport["status"] == "error"
    assert "unavailable" in no_transport["error"]

    session.user_transport = _DummyTransport(send_exc=RuntimeError("send failed"))
    send_fail = session._request_user_action({"type": "action_request"})
    assert send_fail["status"] == "error"
    assert "send failed" in send_fail["error"]

    session.user_transport = _DummyTransport()
    reasons: list[str] = []
    monkeypatch.setattr(session, "_log_user_runtime_snapshot", lambda reason: reasons.append(reason))
    monkeypatch.setattr(
        session,
        "_poll_transport_line",
        lambda **kwargs: (None, True),
    )
    state["mle"] = True
    exited_mle = session._request_user_action({"type": "action_request"})
    assert exited_mle["status"] == "mle"

    state["mle"] = False
    exited_err = session._request_user_action({"type": "action_request"})
    assert exited_err["status"] == "error"
    assert exited_err["error"] == "user process exited"

    monkeypatch.setattr(
        session,
        "_poll_transport_line",
        lambda **kwargs: (None, False),
    )
    timeout = session._request_user_action({"type": "action_request"})
    assert timeout["status"] == "tle"
    assert timeout["error"] == "user idle timeout"
    assert "user idle timeout" in reasons

    monkeypatch.setattr(
        session,
        "_poll_transport_line",
        lambda **kwargs: ("not-json", False),
    )
    invalid = session._request_user_action({"type": "action_request"})
    assert invalid["status"] == "error"
    assert "invalid user output" in invalid["error"]

    monkeypatch.setattr(
        session,
        "_poll_transport_line",
        lambda **kwargs: (json.dumps({"type": "action", "error": "x"}), False),
    )
    missing_status = session._request_user_action({"type": "action_request"})
    assert missing_status["status"] == "error"


def test_pair_session_send_guards_snapshot_and_cleanup(monkeypatch) -> None:
    session, state = _make_session(deadline=time.time() + 30)

    session.judge_transport = None
    with pytest.raises(RuntimeError, match="judge transport unavailable"):
        session._send_to_judge({"type": "x"}, timeout=1)

    session.user_transport = None
    with pytest.raises(RuntimeError, match="user transport unavailable"):
        session._send_to_user({"type": "x"}, timeout=1)

    long_stderr = "[debug] executing function\n[error]\n" + ("a" * 700)
    session.user_sb = _DummySandbox(
        "user",
        script=lambda **kwargs: (
            SimpleNamespace(stdout=long_stderr, stderr="")
            if "tail -c 8192" in kwargs["command"]
            else SimpleNamespace(stdout="futex", stderr="")
        ),
    )
    session.user_process = _Handle("user-snapshot")
    session._log_user_runtime_snapshot("process_exited")
    session._log_user_runtime_snapshot("process_exited")
    session._log_user_runtime_snapshot("user timeout")
    session._log_user_runtime_snapshot("user timeout")

    session.result = None
    session.judge_transport = _DummyTransport(close_exc=RuntimeError("close err"))
    session.user_transport = _DummyTransport(close_exc=RuntimeError("close err"))
    session.judge_sb = _DummySandbox(
        "judge",
        script=lambda **kwargs: SimpleNamespace(stdout="judge stderr lines", stderr=""),
    )
    session.user_sb = _DummySandbox(
        "user",
        script=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("diag fail")),
    )
    session.judge_process = _Handle("judge")
    session.user_process = _Handle("user")
    session.deps.stop_process = lambda process: (_ for _ in ()).throw(RuntimeError("stop fail"))  # type: ignore[method-assign]
    session.deps.destroy_sandbox = lambda sb: (_ for _ in ()).throw(RuntimeError("destroy fail"))  # type: ignore[method-assign]
    session._cleanup()


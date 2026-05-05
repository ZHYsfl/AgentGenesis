from __future__ import annotations

import json
import time
from types import SimpleNamespace
from typing import Optional

import evaluation.dual_sandbox_evaluator as dse_mod
from evaluation.dual_sandbox_evaluator import DualSandboxEvaluator, MessageType
from evaluation.models import CaseResult, CaseStatus, PhaseConfig, PhaseStatus
from evaluation.runtime.process import SandboxProcessHandle


class DummySandbox:
    def __init__(self, sid: str) -> None:
        self.id = sid
        self.commands = SimpleNamespace(run=lambda *args, **kwargs: SimpleNamespace(stdout="", stderr=""))
        self.files = SimpleNamespace(write_files=lambda payload: None)

    def run_command(
        self,
        command: str,
        *,
        timeout: int = 30,
        envs: Optional[dict[str, str]] = None,
        background: bool = False,
    ):
        _ = envs
        _ = background
        return self.commands.run(command, timeout=timeout)

    def get_host(self, port: int) -> str:
        return f"localhost:{port}"


class FakeTransport:
    def __init__(
        self,
        recv_lines: Optional[list[str]] = None,
        raise_on_recv: bool = False,
    ) -> None:
        self._recv_lines = list(recv_lines or [])
        self._raise_on_recv = raise_on_recv
        self.sent: list[dict] = []
        self.closed = False

    def wait_for_ready(self, timeout: int) -> bool:
        _ = timeout
        return True

    def send_message(self, msg: dict, timeout: int) -> None:
        _ = timeout
        self.sent.append(dict(msg))

    def recv_message(self, timeout: int) -> str | None:
        _ = timeout
        if self._raise_on_recv:
            raise RuntimeError("recv failed")
        if not self._recv_lines:
            return None
        return self._recv_lines.pop(0)

    def close(self) -> None:
        self.closed = True


def _make_process_handle(script_rel: str) -> SandboxProcessHandle:
    state = {"running": True}
    raw_handle = SimpleNamespace(
        status="running",
        is_running=lambda: bool(state["running"]),
        kill=lambda: state.__setitem__("running", False),
        terminate=lambda: state.__setitem__("running", False),
    )
    return SandboxProcessHandle(
        raw_handle=raw_handle,
        workdir="/workspace",
        script_rel=script_rel,
    )


def _patch_common(monkeypatch):
    monkeypatch.setattr(dse_mod, "create_sandbox", lambda *args, **kwargs: DummySandbox("sb"))
    monkeypatch.setattr(dse_mod, "destroy_sandbox", lambda sb: None)
    monkeypatch.setattr(dse_mod, "runtime_write_files_chunked", lambda *args, **kwargs: None)
    monkeypatch.setattr(dse_mod, "runtime_load_grpc_bridge_support_files", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        dse_mod.SandboxProcessManager,
        "start_background_python",
        lambda *args, **kwargs: _make_process_handle(kwargs.get("script_rel", "entry.py")),
    )


def test_run_single_case_dynamic_protocol(monkeypatch, submission_factory) -> None:
    cfg = PhaseConfig(
        num_cases=1,
        parallel_cases=1,
        phase_order=1,
        phase_level="Easy",
    )
    ev = DualSandboxEvaluator(cfg)
    submission = submission_factory(phase_config=cfg)

    judge_sb = DummySandbox("judge")
    user_sb = DummySandbox("user")
    created = {"count": 0}

    def _create_sandbox(*args, **kwargs):
        created["count"] += 1
        return judge_sb if created["count"] == 1 else user_sb

    monkeypatch.setattr(dse_mod, "create_sandbox", _create_sandbox)
    monkeypatch.setattr(dse_mod, "destroy_sandbox", lambda sb: None)
    monkeypatch.setattr(dse_mod, "runtime_write_files_chunked", lambda *args, **kwargs: None)
    monkeypatch.setattr(dse_mod, "runtime_load_grpc_bridge_support_files", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        dse_mod.SandboxProcessManager,
        "start_background_python",
        lambda *args, **kwargs: _make_process_handle(kwargs.get("script_rel", "entry.py")),
    )
    monkeypatch.setattr(dse_mod, "get_or_create_template", lambda *args, **kwargs: "test-template:latest")

    judge_transport = FakeTransport(
        recv_lines=[
            json.dumps({"type": MessageType.CASE_REQUEST}),
            json.dumps({"type": MessageType.CASE_START, "case_index": 0}),
            json.dumps(
                {
                    "type": MessageType.OBSERVATION,
                    "data": {"obs": 1},
                    "history_events": {"kind": "observation"},
                }
            ),
            json.dumps({"type": MessageType.ACTION_REQUEST}),
            json.dumps({"type": MessageType.CASE_END, "case_index": 0, "status": "passed", "score": 7}),
            json.dumps({"type": MessageType.CASE_REQUEST}),
            json.dumps({"type": MessageType.EVAL_COMPLETE}),
        ]
    )
    user_transport = FakeTransport(
        recv_lines=[
            json.dumps({"type": MessageType.ACTION, "data": {"answer": 1}, "history_events": {"kind": "action"}})
        ]
    )

    def _create_grpc_transport(_sandbox, port: int):
        return judge_transport if int(port) == 50051 else user_transport

    monkeypatch.setattr(dse_mod, "runtime_create_grpc_transport", _create_grpc_transport)

    result = ev._run_single_case(
        submission=submission,
        gateway_token=None,
        artifact_files={"sandbox/run.py": b"print(1)"},
        user_files_bytes={"solution.py": b"def solve(x): return x"},
        user_req_path="",
        case_index=0,
        track_per_case_usage=False,
        on_case_start=None,
        on_case_end=None,
        deadline=time.time() + 30,
    )
    assert result.status == CaseStatus.PASSED
    logs = json.loads(result.logs or "[]")
    assert isinstance(logs, list)
    kinds = {item.get("kind") for item in logs if isinstance(item, dict)}
    assert {"observation", "action"}.issubset(kinds)
    assert any(m.get("type") == MessageType.CASE_ASSIGN for m in judge_transport.sent)
    assert any(m.get("type") == MessageType.CASE_STOP for m in judge_transport.sent)
    assert any(m.get("type") == MessageType.OBSERVATION for m in user_transport.sent)
    obs_to_user = [m for m in user_transport.sent if m.get("type") == MessageType.OBSERVATION]
    assert obs_to_user
    assert all("history_events" not in m for m in obs_to_user)


def test_run_single_case_user_idle_timeout(monkeypatch, submission_factory) -> None:
    cfg = PhaseConfig(
        case_idle_timeout=5,
        phase_order=1,
        phase_level="Easy",
    )
    ev = DualSandboxEvaluator(cfg)
    submission = submission_factory(phase_config=cfg)

    _patch_common(monkeypatch)
    monkeypatch.setattr(dse_mod, "get_or_create_template", lambda *args, **kwargs: "test-template:latest")

    judge_transport = FakeTransport(
        recv_lines=[
            json.dumps({"type": MessageType.CASE_REQUEST}),
            json.dumps({"type": MessageType.CASE_START, "case_index": 0}),
            json.dumps({"type": MessageType.OBSERVATION, "data": {"obs": "q"}}),
            json.dumps({"type": MessageType.ACTION_REQUEST}),
            json.dumps({"type": MessageType.CASE_END, "case_index": 0, "status": "error", "score": 0}),
            json.dumps({"type": MessageType.CASE_REQUEST}),
            json.dumps({"type": MessageType.EVAL_COMPLETE}),
        ]
    )
    user_transport = FakeTransport(raise_on_recv=True)

    def _create_grpc_transport(_sandbox, port: int):
        return judge_transport if int(port) == 50051 else user_transport

    monkeypatch.setattr(dse_mod, "runtime_create_grpc_transport", _create_grpc_transport)

    result = ev._run_single_case(
        submission=submission,
        gateway_token=None,
        artifact_files={"sandbox/run.py": b"print(1)"},
        user_files_bytes={"solution.py": b"def solve(x): return x"},
        user_req_path="",
        case_index=0,
        track_per_case_usage=False,
        on_case_start=None,
        on_case_end=None,
        deadline=time.time() + 30,
    )
    assert result.status == CaseStatus.ERROR
    assert any(
        m.get("error") == "user idle timeout"
        for m in judge_transport.sent
        if m.get("type") == MessageType.ACTION
    )


def test_case_request_receives_case_stop_when_no_case(monkeypatch, submission_factory) -> None:
    cfg = PhaseConfig(
        num_cases=1,
        parallel_cases=1,
        phase_order=1,
        phase_level="Easy",
    )
    ev = DualSandboxEvaluator(cfg)
    submission = submission_factory(phase_config=cfg)

    _patch_common(monkeypatch)
    monkeypatch.setattr(dse_mod, "get_or_create_template", lambda *args, **kwargs: "test-template:latest")

    judge_transport = FakeTransport(
        recv_lines=[
            json.dumps({"type": MessageType.CASE_REQUEST}),
            json.dumps({"type": MessageType.EVAL_COMPLETE}),
        ]
    )
    user_transport = FakeTransport()

    def _create_grpc_transport(_sandbox, port: int):
        return judge_transport if int(port) == 50051 else user_transport

    monkeypatch.setattr(dse_mod, "runtime_create_grpc_transport", _create_grpc_transport)

    result = ev._run_single_case(
        submission=submission,
        gateway_token=None,
        artifact_files={"sandbox/run.py": b"print(1)"},
        user_files_bytes={"solution.py": b"def solve(x): return x"},
        user_req_path="",
        case_index=99,
        track_per_case_usage=False,
        on_case_start=None,
        on_case_end=None,
        deadline=time.time() + 30,
    )
    assert result.case_index == 99
    sent_types = [m.get("type") for m in judge_transport.sent]
    assert MessageType.CASE_ASSIGN in sent_types


def test_evaluate_missing_cases_promotes_phase_error(monkeypatch, submission_factory) -> None:
    cfg = PhaseConfig(
        num_cases=2,
        phase_order=1,
        phase_level="Easy",
        artifact_url="http://artifact.zip",
        adapter_preset="maze",
        solve_attr_name="solve",
    )
    ev = DualSandboxEvaluator(cfg)
    submission = submission_factory(phase_config=cfg)

    monkeypatch.setattr(dse_mod, "runtime_create_gateway_token_for_user", lambda *args, **kwargs: None)
    monkeypatch.setattr(dse_mod, "runtime_download_artifact", lambda *args, **kwargs: b"artifact")
    monkeypatch.setattr(
        dse_mod,
        "runtime_extract_artifact",
        lambda data: {
            "sandbox/run.py": b"print(1)",
            "sandbox/user_adapter.py": b"def get_adapter(_preset_name):\n    return object()\n",
        },
    )
    monkeypatch.setattr(
        ev,
        "_run_parallel_cases",
        lambda **kwargs: [CaseResult(case_index=0, status=CaseStatus.PASSED, score=1)],
    )
    monkeypatch.setattr(dse_mod, "runtime_revoke_gateway_token", lambda *args, **kwargs: None)

    result = ev.evaluate(submission=submission, parallel_cases=1)
    assert result.status == PhaseStatus.ERROR
    assert "missing 1/2 cases" in (result.error or "")
    assert len(result.cases) == 2

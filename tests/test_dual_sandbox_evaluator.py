from __future__ import annotations

import json

import evaluation.dual_sandbox_evaluator as dse_mod
from evaluation.dual_sandbox_evaluator import DualSandboxEvaluator, MessageType
from evaluation.models import CaseResult, CaseStatus, PhaseConfig, PhaseStatus, RuntimeConfig, UserSubmission
from evaluation.runtime.artifact import filter_requirements
from evaluation.runtime.gateway import (
    attach_llm_usage_delta,
    create_gateway_token_for_user,
    revoke_gateway_token,
)
from evaluation.runtime.history import (
    attach_case_history,
    extract_history_events,
    record_action_history,
)
from evaluation.runtime.sandbox import load_grpc_bridge_support_files
from evaluation.runtime.results import parse_case_result


def _config(**kwargs) -> PhaseConfig:
    base = {
        "phase_order": 1,
        "phase_level": "Easy",
        "num_cases": 3,
        "parallel_cases": 1,
        "artifact_url": "http://artifact",
        "artifact_checksum": "",
        "user_bridge": "sandbox/_user_bridge.py",
        "adapter_preset": "maze",
        "solve_attr_name": "solve",
    }
    base.update(kwargs)
    return PhaseConfig(**base)


def _submission(code_files=None, runtime_config=None, phase_config=None) -> UserSubmission:
    return UserSubmission(
        submit_id=10,
        user_id=20,
        phase_id=1,
        code_url="http://code",
        code_checksum="",
        code_files=code_files or {"requirements.txt": "pytest\n", "solution.py": "def solve(x): return x"},
        phase_config=phase_config or _config(),
        runtime_config=runtime_config or RuntimeConfig(),
        phase_type="agent",
    )


def test_message_type_register_and_all_types() -> None:
    MessageType.register("FRAME_UPDATE", "frame_update")
    types = MessageType.all_types()
    assert "frame_update" in types
    assert MessageType.CASE_REQUEST in types


def test_filter_requirements_blocks_not_whitelisted() -> None:
    text = "numpy==1.0\nunknown_pkg>=2\n--index-url x\n"
    out = filter_requirements(text, ["numpy"])
    assert "numpy==1.0" in out
    assert "# [BLOCKED] unknown_pkg>=2" in out
    assert "--index-url x" in out


def test_extract_and_parse_history_and_case_result() -> None:
    msg = {"history_events": {"kind": "observation", "payload": 1}}
    assert extract_history_events(msg) == [{"kind": "observation", "payload": 1}]

    h = {}
    record_action_history(h, 0, {"type": "action", "error": "bad"})
    assert h[0][0]["kind"] == "action"
    assert h[0][0]["error"] == "bad"

    parsed = parse_case_result(
        {
            "status": "running",
            "case_index": "2",
            "score": "3",
            "chars_used": "11",
            "requests_used": "2",
        },
        fallback_index=0,
    )
    assert parsed.status == CaseStatus.ERROR
    assert parsed.case_index == 2
    assert parsed.score == 3
    assert parsed.chars_used == 11
    assert parsed.requests_used == 2
    parsed_unknown = parse_case_result({"status": "something_new"}, fallback_index=9)
    assert parsed_unknown.status == CaseStatus.FAILED
    assert parsed_unknown.case_index == 9
    assert parsed_unknown.chars_used == 0
    assert parsed_unknown.requests_used == 0


def test_attach_case_history_fallback_to_plain_text(monkeypatch) -> None:
    case = CaseResult(case_index=0, status=CaseStatus.ERROR, logs="judge-log")
    hist = {0: [{"k": "v"}]}

    def _dumps(*args, **kwargs):
        raise TypeError("boom")

    monkeypatch.setattr(json, "dumps", _dumps)
    attach_case_history(case, hist, current_case_index=0)
    assert "judge_log" in case.logs


def test_with_step_deadline_uses_case_idle_timeout(monkeypatch) -> None:
    ev = DualSandboxEvaluator(_config(case_idle_timeout=5))
    monkeypatch.setattr("evaluation.dual_sandbox_evaluator.time.time", lambda: 100.0)
    assert ev._with_step_deadline(200.0) == 105.0
    assert DualSandboxEvaluator(_config(case_idle_timeout=0))._with_step_deadline(200.0) == 200.0


def test_evaluate_marks_missing_cases_as_phase_error(monkeypatch) -> None:
    ev = DualSandboxEvaluator(_config(num_cases=3, artifact_url="http://artifact"))
    sub = _submission()

    monkeypatch.setattr(dse_mod, "runtime_create_gateway_token_for_user", lambda *args, **kwargs: None)
    monkeypatch.setattr(dse_mod, "runtime_download_artifact", lambda *args, **kwargs: b"zip")
    monkeypatch.setattr(
        dse_mod,
        "runtime_extract_artifact",
        lambda data: {"sandbox/run.py": b"print(1)", "sandbox/user_adapter.py": b"class X: pass"},
    )
    monkeypatch.setattr(
        ev,
        "_run_parallel_cases",
        lambda **kwargs: [CaseResult(case_index=0, status=CaseStatus.PASSED, score=1)],
    )
    revoked = {"ok": False}
    monkeypatch.setattr(dse_mod, "runtime_revoke_gateway_token", lambda *args, **kwargs: revoked.__setitem__("ok", True))

    result = ev.evaluate(submission=sub, parallel_cases=1)
    assert result.status == PhaseStatus.ERROR
    assert "missing 2/3 cases" in (result.error or "")
    assert len(result.cases) == 3
    assert revoked["ok"] is True


def test_create_gateway_token_for_user_calls_client(monkeypatch) -> None:
    cfg = _config(allow_user_key=True)
    ev = DualSandboxEvaluator(cfg)
    sub = _submission(runtime_config=RuntimeConfig(key_ids=[9]), phase_config=cfg)
    captured = {}

    class FakeClient:
        def create_gateway_token(self, **kwargs):
            captured.update(kwargs)
            return {"token": "tok-123", "gateway_url": "http://gw"}

    monkeypatch.setattr(ev, "_get_client", lambda: FakeClient())
    result = create_gateway_token_for_user(ev, sub)
    assert result == "tok-123"
    assert captured["submit_id"] == 10
    assert captured["user_id"] == 20


def test_create_gateway_token_for_user_raises_when_key_required_but_missing() -> None:
    cfg = _config(allow_user_key=True)
    ev = DualSandboxEvaluator(cfg)
    sub = _submission(runtime_config=RuntimeConfig(), phase_config=cfg)

    try:
        create_gateway_token_for_user(ev, sub)
        assert False, "expected ValueError when allow_user_key is true but no key_ids"
    except ValueError as e:
        assert "no key_id was provided" in str(e)


def test_evaluate_returns_clear_error_when_gateway_token_creation_fails(monkeypatch) -> None:
    cfg = _config(allow_user_key=True, num_cases=1, artifact_url="http://artifact")
    ev = DualSandboxEvaluator(cfg)
    sub = _submission(runtime_config=RuntimeConfig(key_ids=[9]), phase_config=cfg)

    class FakeClient:
        def create_gateway_token(self, **kwargs):
            return None

    monkeypatch.setattr(ev, "_get_client", lambda: FakeClient())
    result = ev.evaluate(submission=sub, parallel_cases=1)
    assert result.status == PhaseStatus.ERROR
    assert "Failed to create Gateway Token" in (result.error or "")


def test_revoke_gateway_token_calls_client(monkeypatch) -> None:
    ev = DualSandboxEvaluator(_config())
    sub = _submission()
    revoked = {"called": False}

    class FakeClient:
        def revoke_gateway_token(self, submit_id):
            revoked["called"] = True
            revoked["submit_id"] = submit_id
            return True

    # Must set _gateway_token_info so revoke path is entered
    ev._gateway_token_info = {"token": "tok-old"}
    monkeypatch.setattr(ev, "_get_client", lambda: FakeClient())
    revoke_gateway_token(ev, sub)
    assert revoked["called"] is True
    assert revoked["submit_id"] == 10
    assert ev._gateway_token_info is None


def test_revoke_gateway_token_noop_when_no_token() -> None:
    ev = DualSandboxEvaluator(_config())
    sub = _submission()
    ev._gateway_token_info = None
    # Should not raise even without a client
    revoke_gateway_token(ev, sub)


def test_attach_llm_usage_delta_computes_difference(monkeypatch) -> None:
    ev = DualSandboxEvaluator(_config())
    sub = _submission()
    case = CaseResult(case_index=0, status=CaseStatus.PASSED, score=1)

    class FakeClient:
        def get_gateway_token_usage(self, submit_id):
            return {"used_chars": 5000, "used_requests": 10}

    # Must set _gateway_token_info so the method actually queries usage
    ev._gateway_token_info = {"token": "tok-123"}
    ev._prev_usage_chars = 3000
    ev._prev_usage_requests = 7
    monkeypatch.setattr(ev, "_get_client", lambda: FakeClient())
    attach_llm_usage_delta(ev, case, sub)
    assert case.chars_used == 2000
    assert case.requests_used == 3
    # Check that prev counters were updated
    assert ev._prev_usage_chars == 5000
    assert ev._prev_usage_requests == 10


def test_generate_user_wrapper_contains_protocol_guards() -> None:
    ev = DualSandboxEvaluator(_config())
    code = ev._generate_user_wrapper()
    assert "from _user_bridge import serve" in code
    assert "bridge-only mode requires _user_bridge.py" in code


def test_load_grpc_bridge_support_files_contains_runtime_modules() -> None:
    files = load_grpc_bridge_support_files(dse_mod.__file__)
    assert "eval_bridge_pb2.py" in files
    assert "eval_bridge_pb2_grpc.py" in files
    assert "eval_runtime/__init__.py" in files
    assert "eval_runtime/judge_runtime.py" in files
    assert "eval_runtime/judge_scaffold.py" in files
    assert "eval_runtime/user_runtime.py" in files
    assert "eval_runtime/user_adapter.py" in files


def test_generate_managed_user_bridge_uses_config_fields() -> None:
    ev = DualSandboxEvaluator(_config())
    code = ev._generate_managed_user_bridge(solve_attr_name="run", adapter_preset="maze")
    assert "serve_user_runtime" in code
    assert "'run'" in code or '"run"' in code
    assert "'maze'" in code or '"maze"' in code

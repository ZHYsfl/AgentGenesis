from __future__ import annotations

from types import SimpleNamespace

from .. import dual_sandbox_evaluator as dse_mod
from ..config import SystemConfig
from ..dual_sandbox_evaluator import DualSandboxEvaluator
from ..models import CaseResult, CaseStatus, PhaseConfig, PhaseStatus, RuntimeConfig, UserSubmission


def _cfg(**kwargs) -> PhaseConfig:
    base = {
        "phase_order": 1,
        "phase_level": "Easy",
        "num_cases": 2,
        "parallel_cases": 2,
        "artifact_url": "http://artifact",
        "artifact_checksum": "",
        "sandbox_timeout": 20,
        "user_bridge": "sandbox/_user_bridge.py",
        "adapter_preset": "maze",
        "solve_attr_name": "solve",
    }
    base.update(kwargs)
    return PhaseConfig(**base)


def _submission(cfg: PhaseConfig, files=None) -> UserSubmission:
    return UserSubmission(
        submit_id=1,
        user_id=2,
        phase_id=3,
        code_url="http://code",
        code_checksum="",
        code_files=files or {"requirements.txt": "pytest\n", "solution.py": "def solve(x): return x"},
        phase_config=cfg,
        runtime_config=RuntimeConfig(),
        phase_type="agent",
    )


def test_cleanup_swallow_destroy_errors(monkeypatch) -> None:
    ev = DualSandboxEvaluator(_cfg())
    ev._judge_sandbox = object()
    ev._user_sandbox = object()
    monkeypatch.setattr(dse_mod, "destroy_sandbox", lambda sb: (_ for _ in ()).throw(RuntimeError("boom")))
    ev.cleanup()
    assert ev._judge_sandbox is None
    assert ev._user_sandbox is None


def test_run_parallel_cases_handles_case_failure(monkeypatch) -> None:
    ev = DualSandboxEvaluator(_cfg(num_cases=3, parallel_cases=2))
    sub = _submission(ev.config)

    calls = {"n": 0}

    def _run_single(**kwargs):
        calls["n"] += 1
        idx = kwargs["case_index"]
        if idx == 0:
            raise RuntimeError("case fail")
        return CaseResult(case_index=idx, status=CaseStatus.PASSED, score=1)

    monkeypatch.setattr(ev, "_run_single_case", _run_single)
    out = ev._run_parallel_cases(
        submission=sub,
        gateway_token=None,
        artifact_files={"sandbox/run.py": b"print(1)"},
        user_files_bytes={"solution.py": b"ok"},
        user_req_path="",
        num_cases=3,
        parallel=2,
        on_case_start=None,
        on_case_end=None,
        deadline=10**9,
        track_per_case_usage=False,
    )
    assert len(out) == 3
    assert out[0].status == CaseStatus.ERROR
    assert out[1].status == CaseStatus.PASSED


def test_evaluate_additional_branches(monkeypatch) -> None:
    cfg = _cfg(user_bridge="sandbox/_user_bridge.py", allowed_packages=["pytest"], parallel_cases=2, num_cases=2)
    ev = DualSandboxEvaluator(cfg)
    sub = _submission(cfg)

    def _create_token(*args, **kwargs):  # type: ignore[no-untyped-def]
        ev._gateway_token_info = {"token": "tok"}
        return "tok"

    monkeypatch.setattr(dse_mod, "runtime_create_gateway_token_for_user", _create_token)
    monkeypatch.setattr(dse_mod, "runtime_download_artifact", lambda *args, **kwargs: b"zip")
    monkeypatch.setattr(
        dse_mod,
        "runtime_extract_artifact",
        lambda data: {
            "sandbox/run.py": b"print(1)",
            "sandbox/_user_bridge.py": b"def serve(): pass",
            "sandbox/user_adapter.py": b"class X: pass\n",
        },
    )
    monkeypatch.setattr(dse_mod, "runtime_filter_requirements", lambda req, allow: req)
    monkeypatch.setattr(
        ev,
        "_run_parallel_cases",
        lambda **kwargs: [CaseResult(case_index=0, status=CaseStatus.PASSED, score=1)],
    )
    monkeypatch.setattr(ev, "_get_client", lambda: SimpleNamespace(get_gateway_token_usage=lambda submit_id: {"used_chars": 12, "used_requests": 3}))
    revoked = {"ok": False}
    monkeypatch.setattr(dse_mod, "runtime_revoke_gateway_token", lambda *args, **kwargs: revoked.__setitem__("ok", True))

    result = ev.evaluate(sub, parallel_cases=2)
    assert result.status == PhaseStatus.ERROR  # missing case backfill path
    assert result.total_chars == 12
    assert result.total_requests == 3
    assert revoked["ok"] is True


def test_run_single_case_uses_handle_process_contract(monkeypatch) -> None:
    cfg = _cfg(num_cases=1, parallel_cases=1)
    ev = DualSandboxEvaluator(cfg)
    sub = _submission(cfg)
    captured = {"deps": None}

    def _capture_run_pair_session(**kwargs):  # type: ignore[no-untyped-def]
        captured["deps"] = kwargs["deps"]
        return CaseResult(case_index=0, status=CaseStatus.PASSED, score=1)

    monkeypatch.setattr(dse_mod, "run_sandbox_pair_session", _capture_run_pair_session)
    monkeypatch.setattr(dse_mod, "get_or_create_template", lambda *args, **kwargs: "test:latest")

    result = ev._run_single_case(
        submission=sub,
        gateway_token=None,
        artifact_files={"sandbox/run.py": b"print(1)"},
        user_files_bytes={"solution.py": b"def solve(x): return x"},
        user_req_path="",
        case_index=0,
        track_per_case_usage=False,
        on_case_start=None,
        on_case_end=None,
        deadline=10**9,
    )
    assert result.status == CaseStatus.PASSED
    deps = captured["deps"]
    assert deps is not None
    assert callable(deps.stop_process)
    assert callable(deps.is_process_alive)
    assert callable(deps.describe_process)
    assert deps.template_image == "test:latest"
    assert not hasattr(deps, "kill_pid")
    assert not hasattr(deps, "is_pid_alive")


def test_evaluate_downloads_code_when_submission_files_empty(monkeypatch) -> None:
    cfg = _cfg(num_cases=1, parallel_cases=1, allowed_packages=["pytest"])
    ev = DualSandboxEvaluator(cfg)
    sub = _submission(cfg, files={})

    captured: dict[str, object] = {}
    revoked = {"ok": False}

    monkeypatch.setattr(dse_mod, "runtime_create_gateway_token_for_user", lambda *args, **kwargs: None)
    monkeypatch.setattr(dse_mod, "runtime_download_artifact", lambda *args, **kwargs: b"zip")
    monkeypatch.setattr(
        dse_mod,
        "runtime_extract_artifact",
        lambda data: {
            "sandbox/run.py": b"print(1)",
            "sandbox/_user_bridge.py": b"def serve(): pass",
            "sandbox/user_adapter.py": b"class X: pass\n",
        },
    )
    monkeypatch.setattr(dse_mod, "runtime_filter_requirements", lambda req, allow: "pytest\n")
    monkeypatch.setattr(
        ev,
        "_get_client",
        lambda: SimpleNamespace(
            download_code=lambda code_url, expected_checksum="": {
                "requirements.txt": "pytest\n",
                "solution.py": "def solve(x): return x",
            }
        ),
    )

    def _run_parallel_cases(**kwargs):  # type: ignore[no-untyped-def]
        captured["user_files_bytes"] = kwargs["user_files_bytes"]
        captured["user_req_path"] = kwargs["user_req_path"]
        return [CaseResult(case_index=0, status=CaseStatus.PASSED, score=1, time_used=10)]

    monkeypatch.setattr(ev, "_run_parallel_cases", _run_parallel_cases)
    monkeypatch.setattr(
        dse_mod,
        "runtime_revoke_gateway_token",
        lambda *args, **kwargs: revoked.__setitem__("ok", True),
    )

    result = ev.evaluate(sub, parallel_cases=1)
    assert result.status == PhaseStatus.SUCCESS
    assert result.total_cases == 1
    assert result.passed_cases == 1
    assert result.total_time == 10
    assert revoked["ok"] is True

    user_files_bytes = captured["user_files_bytes"]
    assert isinstance(user_files_bytes, dict)
    assert user_files_bytes["requirements.txt"] == b"pytest\n"
    assert "_agent_wrapper.py" in user_files_bytes
    assert "_user_bridge.py" in user_files_bytes
    assert captured["user_req_path"] == "requirements.txt"


def test_evaluate_returns_error_when_requirements_missing(monkeypatch) -> None:
    cfg = _cfg(num_cases=1, parallel_cases=1)
    ev = DualSandboxEvaluator(cfg)
    sub = _submission(cfg, files={"solution.py": "def solve(x): return x"})

    monkeypatch.setattr(dse_mod, "runtime_create_gateway_token_for_user", lambda *args, **kwargs: None)
    monkeypatch.setattr(dse_mod, "runtime_download_artifact", lambda *args, **kwargs: b"zip")
    monkeypatch.setattr(
        dse_mod,
        "runtime_extract_artifact",
        lambda data: {
            "sandbox/run.py": b"print(1)",
            "sandbox/_user_bridge.py": b"def serve(): pass",
            "sandbox/user_adapter.py": b"class X: pass\n",
        },
    )
    monkeypatch.setattr(dse_mod, "runtime_revoke_gateway_token", lambda *args, **kwargs: None)

    result = ev.evaluate(sub, parallel_cases=1)
    assert result.status == PhaseStatus.ERROR
    assert "Missing requirements.txt" in (result.error or "")


def test_evaluate_uses_generated_bridge_from_config(monkeypatch) -> None:
    cfg = _cfg(num_cases=1, parallel_cases=1, adapter_preset="maze", solve_attr_name="solve")
    ev = DualSandboxEvaluator(cfg)
    sub = _submission(cfg)

    monkeypatch.setattr(dse_mod, "runtime_create_gateway_token_for_user", lambda *args, **kwargs: None)
    monkeypatch.setattr(dse_mod, "runtime_download_artifact", lambda *args, **kwargs: b"zip")
    monkeypatch.setattr(
        dse_mod,
        "runtime_extract_artifact",
        lambda data: {
            "sandbox/run.py": b"print(1)",
            # Artifact bridge has mismatched content, but evaluator should ignore it
            # and generate _user_bridge.py from phase_config.
            "sandbox/_user_bridge.py": b"def serve():\n    raise RuntimeError('wrong bridge')\n",
            "sandbox/user_adapter.py": b"class X: pass\n",
        },
    )
    monkeypatch.setattr(
        ev,
        "_run_parallel_cases",
        lambda **kwargs: [CaseResult(case_index=0, status=CaseStatus.PASSED, score=1, time_used=10)],
    )
    monkeypatch.setattr(dse_mod, "runtime_revoke_gateway_token", lambda *args, **kwargs: None)

    result = ev.evaluate(sub, parallel_cases=1)
    assert result.status == PhaseStatus.SUCCESS


def test_evaluate_returns_error_when_bridge_uses_runtime_without_user_adapter(monkeypatch) -> None:
    cfg = _cfg(num_cases=1, parallel_cases=1, adapter_preset="maze", solve_attr_name="solve")
    ev = DualSandboxEvaluator(cfg)
    sub = _submission(cfg)

    monkeypatch.setattr(dse_mod, "runtime_create_gateway_token_for_user", lambda *args, **kwargs: None)
    monkeypatch.setattr(dse_mod, "runtime_download_artifact", lambda *args, **kwargs: b"zip")
    monkeypatch.setattr(
        dse_mod,
        "runtime_extract_artifact",
        lambda data: {
            "sandbox/run.py": b"print(1)",
            "sandbox/_user_bridge.py": b"def serve(): pass\n",
        },
    )
    monkeypatch.setattr(dse_mod, "runtime_revoke_gateway_token", lambda *args, **kwargs: None)

    result = ev.evaluate(sub, parallel_cases=1)
    assert result.status == PhaseStatus.ERROR
    assert "Missing sandbox/user_adapter.py" in (result.error or "")


def test_run_parallel_cases_capped_by_max_case_parallelism(monkeypatch) -> None:
    """The ThreadPoolExecutor size must respect MAX_CASE_PARALLELISM."""
    SystemConfig.reset()
    monkeypatch.setenv("MAX_CASE_PARALLELISM", "3")
    SystemConfig.reset()

    ev = DualSandboxEvaluator(_cfg(num_cases=20, parallel_cases=10))
    sub = _submission(ev.config)

    observed_workers: list[int] = []
    original_init = dse_mod.ThreadPoolExecutor.__init__

    def _capture_init(self, *args, **kwargs):
        observed_workers.append(kwargs.get("max_workers", args[0] if args else None))
        return original_init(self, *args, **kwargs)

    monkeypatch.setattr(dse_mod.ThreadPoolExecutor, "__init__", _capture_init)
    monkeypatch.setattr(
        ev,
        "_run_single_case",
        lambda **kwargs: CaseResult(
            case_index=kwargs["case_index"], status=CaseStatus.PASSED, score=1,
        ),
    )

    out = ev._run_parallel_cases(
        submission=sub,
        gateway_token=None,
        artifact_files={},
        user_files_bytes={},
        user_req_path="",
        num_cases=20,
        parallel=10,
        on_case_start=None,
        on_case_end=None,
        deadline=10**9,
    )
    assert len(out) == 20
    assert observed_workers[-1] == 3

    SystemConfig.reset()


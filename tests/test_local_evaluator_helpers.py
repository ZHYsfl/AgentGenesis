from __future__ import annotations

import signal
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ..local import evaluator as local_eval_mod
from ..local.eval_types import EvalEventType
from ..local.evaluator import LocalEvaluator
from ..models import CaseResult, CaseStatus, PhaseConfig, PhaseStatus, RuntimeConfig, UserSubmission


def _phase_config(**overrides: Any) -> PhaseConfig:
    base: dict[str, Any] = {
        "phase_name": "local",
        "phase_order": 1,
        "phase_level": "Easy",
        "num_cases": 2,
        "parallel_cases": 1,
        "sandbox_timeout": 20,
        "case_idle_timeout": 5,
        "solve_attr_name": "solve",
        "adapter_preset": "maze",
    }
    base.update(overrides)
    return PhaseConfig(**base)


def _make_bare_evaluator(tmp_path: Path) -> LocalEvaluator:
    ev = object.__new__(LocalEvaluator)
    ev.problem_path = tmp_path
    ev.user_code_path = tmp_path
    ev.llm_config = SimpleNamespace(model="demo-model", base_url="http://llm", api_key="k")
    ev.on_event = None
    ev.protocol_version = "v1"
    ev.config = _phase_config()
    ev._artifact_files = {"sandbox/user_adapter.py": b"class Adapter: pass"}
    ev._user_files = {
        "requirements.txt": "pytest\n",
        "solution.py": "def solve(x):\n    return x\n",
    }
    return ev


def test_load_user_files_for_file_and_directory(tmp_path: Path) -> None:
    file_ev = object.__new__(LocalEvaluator)
    file_path = tmp_path / "solution.py"
    file_path.write_text("def solve(x): return x", encoding="utf-8")
    file_ev.user_code_path = file_path
    file_files = LocalEvaluator._load_user_files(file_ev)
    assert "solution.py" in file_files
    assert "requirements.txt" in file_files
    assert "openai" in file_files["requirements.txt"]

    file_with_req_ev = object.__new__(LocalEvaluator)
    file_with_req_path = tmp_path / "solution_with_req.py"
    file_with_req_path.write_text("def solve(x): return x", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("pydantic\n", encoding="utf-8")
    file_with_req_ev.user_code_path = file_with_req_path
    file_with_req_files = LocalEvaluator._load_user_files(file_with_req_ev)
    assert file_with_req_files["requirements.txt"] == "pydantic\n"

    dir_ev = object.__new__(LocalEvaluator)
    code_dir = tmp_path / "code_dir"
    code_dir.mkdir()
    (code_dir / "main.py").write_text("print('ok')", encoding="utf-8")
    (code_dir / "requirements.txt").write_text("requests\n", encoding="utf-8")
    dir_ev.user_code_path = code_dir
    dir_files = LocalEvaluator._load_user_files(dir_ev)
    assert "main.py" in dir_files
    assert dir_files["requirements.txt"] == "requests\n"


def test_validate_config_checks_required_fields(tmp_path: Path) -> None:
    ev = _make_bare_evaluator(tmp_path)
    ev.config = _phase_config(solve_attr_name="")
    with pytest.raises(ValueError, match="solve_attr_name"):
        LocalEvaluator._validate_config(ev)

    ev.config = _phase_config(adapter_preset="")
    with pytest.raises(ValueError, match="adapter_preset"):
        LocalEvaluator._validate_config(ev)

    ev.config = _phase_config()
    ev._artifact_files = {}
    with pytest.raises(ValueError, match="user_adapter.py"):
        LocalEvaluator._validate_config(ev)


def test_init_wires_loader_builder_and_user_files(monkeypatch, tmp_path: Path) -> None:
    cfg = _phase_config()
    artifact = {"sandbox/user_adapter.py": b"class Adapter: pass"}
    calls: dict[str, Any] = {}

    class _Loader:
        def load(self, problem_path: Path) -> PhaseConfig:
            calls["load"] = str(problem_path)
            return cfg

    class _Builder:
        def build(self, problem_path: Path, config: PhaseConfig) -> dict[str, bytes]:
            calls["build"] = (str(problem_path), config.phase_name)
            return artifact

    monkeypatch.setattr(local_eval_mod, "LocalProblemLoader", _Loader)
    monkeypatch.setattr(local_eval_mod, "LocalArtifactBuilder", _Builder)
    monkeypatch.setattr(
        LocalEvaluator,
        "_load_user_files",
        lambda self: {
            "requirements.txt": "pytest\n",
            "solution.py": "def solve(x): return x\n",
        },
    )

    ev = LocalEvaluator(
        problem_path=tmp_path,
        user_code_path=tmp_path,
        llm_config=SimpleNamespace(model="demo-model", base_url="http://llm", api_key="k"),
    )
    assert ev.config.phase_name == "local"
    assert ev._artifact_files == artifact
    assert "load" in calls
    assert "build" in calls


def test_create_submission_deadline_helpers_and_wrappers(tmp_path: Path) -> None:
    ev = _make_bare_evaluator(tmp_path)
    submission = LocalEvaluator._create_submission(ev, submit_id=9)
    assert submission.submit_id == 9
    assert submission.phase_config is ev.config
    assert submission.code_files == ev._user_files

    future_deadline = time.time() + 1000.0
    bounded = LocalEvaluator._with_step_deadline(ev, future_deadline)
    assert bounded <= time.time() + 6.0

    ev.config.case_idle_timeout = 0
    assert LocalEvaluator._with_step_deadline(ev, future_deadline) == future_deadline

    wrapped_start_calls: list[int] = []
    wrapped_start = LocalEvaluator._wrap_on_case_start(ev, lambda i: wrapped_start_calls.append(i))
    assert wrapped_start is not None
    wrapped_start(3)
    assert wrapped_start_calls == [3]

    wrapped_end_calls: list[int] = []
    wrapped_end = LocalEvaluator._wrap_on_case_end(
        ev,
        lambda i, result: wrapped_end_calls.append(i),
    )
    assert wrapped_end is not None
    wrapped_end(4, CaseResult(case_index=4, status=CaseStatus.PASSED, score=1))
    assert wrapped_end_calls == [4]

    assert "bridge-only mode requires _user_bridge.py" in LocalEvaluator._generate_user_wrapper(ev)
    bridge = LocalEvaluator._generate_managed_user_bridge(
        ev,
        solve_attr_name="solve_agent",
        adapter_preset="maze",
    )
    assert "solve_agent" in bridge
    assert "maze" in bridge


def test_emit_event_calls_callback_and_swallows_errors(tmp_path: Path) -> None:
    ev = _make_bare_evaluator(tmp_path)
    events: list[Any] = []
    ev.on_event = events.append
    LocalEvaluator._emit_event(ev, EvalEventType.CASE_START, 0, {})
    assert len(events) == 1
    assert events[0].type == EvalEventType.CASE_START

    def _broken_callback(event: Any) -> None:
        _ = event
        raise RuntimeError("callback failed")

    ev.on_event = _broken_callback
    # Should not raise.
    LocalEvaluator._emit_event(ev, EvalEventType.ERROR, -1, {"error": "x"})


def test_evaluate_serial_parallel_and_empty_case_paths(monkeypatch, tmp_path: Path) -> None:
    ev = _make_bare_evaluator(tmp_path)
    emitted: list[Any] = []
    ev.on_event = emitted.append
    ev.config = _phase_config(num_cases=3, parallel_cases=2)

    cleanup_calls = {"count": 0}
    monkeypatch.setattr(
        local_eval_mod,
        "shutdown_all_sandboxes",
        lambda: cleanup_calls.__setitem__("count", cleanup_calls["count"] + 1),
    )
    ev._setup_sigint_guard = lambda: (signal.getsignal(signal.SIGINT), threading.Event())  # type: ignore[method-assign]

    def _run_single_case_stub(**kwargs: Any) -> CaseResult:
        idx = kwargs["case_index"]
        if kwargs["on_case_start"]:
            kwargs["on_case_start"](idx)
        result = CaseResult(
            case_index=idx,
            status=CaseStatus.PASSED,
            score=1,
            time_used=5,
            chars_used=2,
            requests_used=1,
        )
        if kwargs["on_case_end"]:
            kwargs["on_case_end"](idx, result)
        return result

    ev._run_single_case = _run_single_case_stub  # type: ignore[method-assign]

    serial = LocalEvaluator.evaluate(ev, parallel_cases=1)
    assert serial.status == PhaseStatus.SUCCESS
    assert serial.total_cases == 3
    assert serial.passed_cases == 3

    parallel = LocalEvaluator.evaluate(ev, parallel_cases=2)
    assert parallel.status == PhaseStatus.SUCCESS
    assert parallel.total_cases == 3

    empty = LocalEvaluator.evaluate(ev, case_indices=[99], parallel_cases=1)
    assert empty.status == PhaseStatus.ERROR
    assert "No valid cases" in (empty.error or "")

    event_types = {e.type for e in emitted}
    assert EvalEventType.PROGRESS in event_types
    assert EvalEventType.CASE_START in event_types
    assert EvalEventType.CASE_END in event_types
    assert cleanup_calls["count"] >= 3


def test_evaluate_filters_requirements_and_handles_case_exception(monkeypatch, tmp_path: Path) -> None:
    ev = _make_bare_evaluator(tmp_path)
    ev.config = _phase_config(num_cases=2, allowed_packages=["pytest"])
    ev._setup_sigint_guard = lambda: (signal.getsignal(signal.SIGINT), threading.Event())  # type: ignore[method-assign]
    monkeypatch.setattr(local_eval_mod, "shutdown_all_sandboxes", lambda: None)
    monkeypatch.setattr(local_eval_mod, "filter_requirements", lambda reqs, allow: "pytest\n")

    raised_once = {"done": False}

    def _run_single_case_stub(**kwargs: Any) -> CaseResult:
        idx = kwargs["case_index"]
        if kwargs["on_case_start"]:
            kwargs["on_case_start"](idx)
        if idx == 1 and not raised_once["done"]:
            raised_once["done"] = True
            raise RuntimeError("case crash")
        result = CaseResult(case_index=idx, status=CaseStatus.PASSED, score=1)
        if kwargs["on_case_end"]:
            kwargs["on_case_end"](idx, result)
        return result

    ev._run_single_case = _run_single_case_stub  # type: ignore[method-assign]
    result = LocalEvaluator.evaluate(ev, parallel_cases=1)

    assert result.status in {PhaseStatus.FAILED, PhaseStatus.SUCCESS}
    assert any(case.status == CaseStatus.ERROR for case in result.cases)
    assert ev._user_files["requirements.txt"] == "pytest\n"


def test_evaluate_handles_exceptions(monkeypatch, tmp_path: Path) -> None:
    ev = _make_bare_evaluator(tmp_path)
    monkeypatch.setattr(local_eval_mod, "shutdown_all_sandboxes", lambda: None)
    ev._setup_sigint_guard = lambda: (signal.getsignal(signal.SIGINT), threading.Event())  # type: ignore[method-assign]
    ev._create_submission = (  # type: ignore[method-assign]
        lambda submit_id=1: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    result = LocalEvaluator.evaluate(ev, parallel_cases=1)
    assert result.status == PhaseStatus.ERROR
    assert "RuntimeError: boom" in (result.error or "")


def test_evaluate_stream_yields_events_and_restores_callback(tmp_path: Path) -> None:
    ev = _make_bare_evaluator(tmp_path)
    original_callback = lambda event: None
    ev.on_event = original_callback

    def _evaluate_emit(case_indices=None, parallel_cases=None):  # noqa: ANN001
        _ = (case_indices, parallel_cases)
        LocalEvaluator._emit_event(ev, EvalEventType.CASE_START, 0, {})
        return None

    ev.evaluate = _evaluate_emit  # type: ignore[method-assign]
    events = list(LocalEvaluator.evaluate_stream(ev))
    assert len(events) == 1
    assert events[0].type == EvalEventType.CASE_START
    assert ev.on_event is original_callback


def test_evaluate_stream_emits_error_event_on_exception(tmp_path: Path) -> None:
    ev = _make_bare_evaluator(tmp_path)
    ev.evaluate = (  # type: ignore[method-assign]
        lambda case_indices=None, parallel_cases=None: (_ for _ in ()).throw(RuntimeError("stream boom"))
    )
    events = list(LocalEvaluator.evaluate_stream(ev))
    assert events
    assert events[0].type == EvalEventType.ERROR
    assert "stream boom" in str(events[0].data.get("error", ""))


def test_run_single_case_wires_session_callbacks(monkeypatch, tmp_path: Path) -> None:
    ev = _make_bare_evaluator(tmp_path)
    seen_events: list[Any] = []
    ev.on_event = seen_events.append
    ev.config = _phase_config(num_cases=1, parallel_cases=1)
    ev.llm_config = SimpleNamespace(
        model="demo-model",
        base_url="http://llm",
        api_key="k",
        extra_body={"x": 1},
    )

    starts: list[int] = []
    ends: list[int] = []

    class _FakeSession:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs
            self.callbacks: dict[str, Any] = {}

        def set_event_callbacks(self, **kwargs: Any) -> None:
            self.callbacks = kwargs

        def run(self) -> CaseResult:
            case_index = self.kwargs["case_index"]
            if self.kwargs.get("on_case_start"):
                self.kwargs["on_case_start"](case_index)
            self.callbacks["on_observation"](case_index, {"data": "obs"})
            self.callbacks["on_action"](case_index, {"data": "act", "error": "bad"})
            self.callbacks["on_user_log"](case_index, "user-log")
            self.callbacks["on_judge_log"](case_index, "judge-log")
            self.callbacks["on_error"](case_index, "oops")
            result = CaseResult(case_index=case_index, status=CaseStatus.PASSED, score=9)
            if self.kwargs.get("on_case_end"):
                self.kwargs["on_case_end"](case_index, result)
            return result

    monkeypatch.setattr(local_eval_mod, "get_or_create_template", lambda **kwargs: "tmpl:v1")
    monkeypatch.setattr(local_eval_mod, "extract_image_data_files", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        "agent_genesis.runtime.pair_session._SandboxPairSession",
        _FakeSession,
    )

    submission = UserSubmission(
        submit_id=1,
        user_id=2,
        phase_id=3,
        code_url="",
        code_files=ev._user_files,
        phase_config=ev.config,
        runtime_config=RuntimeConfig(),
    )
    user_files_bytes = {k: v.encode("utf-8") for k, v in ev._user_files.items()}
    result = LocalEvaluator._run_single_case(
        ev,
        submission=submission,
        artifact_files=ev._artifact_files,
        user_files_bytes=user_files_bytes,
        user_req_path="requirements.txt",
        case_index=0,
        on_case_start=lambda idx: starts.append(idx),
        on_case_end=lambda idx, case: ends.append(idx),
    )

    assert result.status == CaseStatus.PASSED
    assert starts == [0]
    assert ends == [0]
    emitted_types = {e.type for e in seen_events}
    assert EvalEventType.OBSERVATION in emitted_types
    assert EvalEventType.ACTION in emitted_types
    assert EvalEventType.USER_LOG in emitted_types
    assert EvalEventType.JUDGE_LOG in emitted_types
    assert EvalEventType.ERROR in emitted_types

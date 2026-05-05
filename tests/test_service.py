"""Unit tests for evaluation worker service behavior."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import evaluation.service as worker_mod
from evaluation.models import CaseResult, CaseStatus, PhaseConfig, PhaseResult, PhaseStatus, UserSubmission
from evaluation.service import EvaluationService


def _sub() -> UserSubmission:
    return UserSubmission(
        submit_id=1,
        user_id=2,
        phase_id=3,
        code_url="http://code",
        code_checksum="",
        phase_type="agent",
        phase_config=PhaseConfig(
            phase_order=1,
            phase_level="Easy",
            parallel_cases=1,
            evaluator_module="",
            evaluator_class="",
        ),
    )


class FakeClient:
    def __init__(self) -> None:
        self.claimed = []
        self.unclaimed = []
        self.reported = []
        self.case_status = []
        self.cases_saved = []

    def claim_submission(self, submit_id: int) -> bool:
        self.claimed.append(submit_id)
        return True

    def unclaim_submission(self, submit_id: int) -> bool:
        self.unclaimed.append(submit_id)
        return True

    def report_result(self, submit_id: int, result: PhaseResult) -> bool:
        self.reported.append((submit_id, result.status))
        return True

    def report_case_status(self, submit_id: int, case_index: int, status: str) -> bool:
        self.case_status.append((submit_id, case_index, status))
        return True

    def create_case_record(self, submit_id: int, case: CaseResult):
        self.cases_saved.append((submit_id, case.case_index))
        return {"case_id": 1, "submit_id": submit_id}

    def download_code(self, code_url: str, expected_checksum: str = ""):
        return {"requirements.txt": "pytest==8.0.0", "solution.py": "print(1)"}


def test_load_evaluator_fallback_to_dual() -> None:
    w = EvaluationService(client=FakeClient(), enable_health_server=False)
    cfg = PhaseConfig(evaluator_module="", evaluator_class="")
    ev = w.load_evaluator(cfg)
    assert ev.__class__.__name__ == "DualSandboxEvaluator"


def test_load_evaluator_invalid_type_raises(monkeypatch) -> None:
    w = EvaluationService(client=FakeClient(), enable_health_server=False)
    cfg = PhaseConfig(evaluator_module="x.y", evaluator_class="Nope")

    monkeypatch.setattr(worker_mod.importlib, "import_module", lambda _: SimpleNamespace(Nope=123))
    with pytest.raises(TypeError):
        w.load_evaluator(cfg)


def test_process_submission_happy_path(monkeypatch) -> None:
    client = FakeClient()
    w = EvaluationService(client=client, enable_health_server=False)
    submission = _sub()

    class EvalOK:
        def __init__(self, config, client=None) -> None:
            self.config = config

        def evaluate(self, submission, parallel_cases=1, on_case_start=None, on_case_end=None):
            if on_case_start:
                on_case_start(0)
            case = CaseResult(case_index=0, status=CaseStatus.PASSED, score=1)
            if on_case_end:
                on_case_end(0, case)
            return PhaseResult(status=PhaseStatus.SUCCESS, score=1, passed_cases=1, total_cases=1, cases=[case])

    monkeypatch.setattr(w, "load_evaluator", lambda cfg: EvalOK(cfg))
    result = w.process_submission(submission)
    assert result.status == PhaseStatus.SUCCESS
    assert client.claimed == [1]
    assert client.reported and client.reported[0][0] == 1
    assert client.case_status[0] == (1, 0, "running")
    assert client.cases_saved == [(1, 0)]


def test_process_submission_sandbox_busy_returns_pending(monkeypatch) -> None:
    client = FakeClient()
    w = EvaluationService(client=client, enable_health_server=False)
    submission = _sub()

    class BusyEval:
        def evaluate(self, *args, **kwargs):
            raise worker_mod.SandboxBusyError("busy")

    monkeypatch.setattr(w, "load_evaluator", lambda cfg: BusyEval())
    result = w.process_submission(submission)
    assert result.status == PhaseStatus.PENDING
    assert client.unclaimed == [1]


def test_validate_and_download_code() -> None:
    client = FakeClient()
    w = EvaluationService(client=client, enable_health_server=False)
    submission = _sub()

    files = w._download_code(submission)
    assert "requirements.txt" in files
    w._validate_submission(files)
    with pytest.raises(ValueError):
        w._validate_submission({"solution.py": "x"})

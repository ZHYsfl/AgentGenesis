from __future__ import annotations

import signal
import time
from concurrent.futures import Future
from types import SimpleNamespace

import pytest

import evaluation.service as worker_mod
from evaluation.models import CaseResult, CaseStatus, PhaseConfig, PhaseResult, PhaseStatus, RuntimeConfig, UserSubmission
from evaluation.service import DEFAULT_SUBMISSION_TIMEOUT, EvaluationService, SubmissionTask


class _Client:
    def __init__(self) -> None:
        self.base_url = "http://backend"
        self.claim_ok = True
        self.downloaded = {"requirements.txt": "ok", "solution.py": "ok"}
        self.claimed: list[int] = []
        self.unclaimed: list[int] = []
        self.reported: list[tuple[int, str]] = []
        self.case_status: list[tuple[int, int, str]] = []
        self.cases: list[int] = []
        self.pending: list[UserSubmission] = []

    def claim_submission(self, submit_id: int) -> bool:
        self.claimed.append(submit_id)
        return self.claim_ok

    def unclaim_submission(self, submit_id: int) -> bool:
        self.unclaimed.append(submit_id)
        return True

    def report_result(self, submit_id: int, result: PhaseResult) -> bool:
        self.reported.append((submit_id, result.status.value))
        return True

    def report_case_status(self, submit_id: int, case_index: int, status: str) -> bool:
        self.case_status.append((submit_id, case_index, status))
        return True

    def create_case_record(self, submit_id: int, case: CaseResult):
        self.cases.append(case.case_index)
        return {"case_id": 1}

    def download_code(self, code_url: str, expected_checksum: str = ""):
        _ = (code_url, expected_checksum)
        return dict(self.downloaded)

    def get_pending_submissions(self, limit: int = 1):
        _ = limit
        return list(self.pending)


def _submission(submit_id: int = 1, timeout: int = 30) -> UserSubmission:
    cfg = PhaseConfig(
        phase_order=1,
        phase_level="Easy",
        phase_name="p1",
        sandbox_timeout=timeout,
        parallel_cases=1,
    )
    return UserSubmission(
        submit_id=submit_id,
        user_id=2,
        phase_id=3,
        code_url="http://code.zip",
        code_checksum="",
        code_files={},
        phase_config=cfg,
        runtime_config=RuntimeConfig(),
        phase_type="agent",
    )


def test_submission_task_timeout() -> None:
    task = SubmissionTask(submit_id=1, start_time=time.time() - 10, timeout=1)
    assert task.is_timed_out() is True


def test_process_submission_claim_and_download_failures(monkeypatch) -> None:
    client = _Client()
    worker = EvaluationService(client=client, enable_health_server=False)
    sub = _submission()

    client.claim_ok = False
    r1 = worker.process_submission(sub)
    assert r1.status == PhaseStatus.ERROR
    assert "claim failed" in (r1.error or "")

    client.claim_ok = True
    client.downloaded = {}
    r2 = worker.process_submission(sub)
    assert r2.status == PhaseStatus.ERROR
    assert client.unclaimed == [1]


def test_process_submission_cleanup_and_exception_paths(monkeypatch) -> None:
    client = _Client()
    worker = EvaluationService(client=client, enable_health_server=False)
    sub = _submission()

    class _EvalWithCleanup:
        def __init__(self, config, client=None):
            _ = (config, client)

        def evaluate(self, submission, parallel_cases=1, on_case_start=None, on_case_end=None):
            if on_case_start:
                on_case_start(0)
            case = CaseResult(case_index=0, status=CaseStatus.PASSED, score=1)
            if on_case_end:
                on_case_end(0, case)
            return PhaseResult(status=PhaseStatus.SUCCESS, cases=[case], passed_cases=1, total_cases=1, score=1)

        def cleanup(self):
            raise RuntimeError("cleanup failed")

    monkeypatch.setattr(worker, "load_evaluator", lambda cfg: _EvalWithCleanup(cfg))
    ok = worker.process_submission(sub)
    assert ok.status == PhaseStatus.SUCCESS
    assert client.case_status[0] == (1, 0, "running")
    assert client.case_status[1] == (1, 0, "passed")

    monkeypatch.setattr(worker, "load_evaluator", lambda cfg: (_ for _ in ()).throw(RuntimeError("load failed")))
    bad = worker.process_submission(sub)
    assert bad.status == PhaseStatus.ERROR
    assert "RuntimeError" in (bad.error or "")


def test_worker_internal_helpers(monkeypatch) -> None:
    client = _Client()
    worker = EvaluationService(client=client, enable_health_server=False)

    # _save_cases no-op / with cases
    worker._save_cases(1, PhaseResult(status=PhaseStatus.SUCCESS, cases=[]))
    worker._save_cases(
        1,
        PhaseResult(
            status=PhaseStatus.SUCCESS,
            cases=[CaseResult(case_index=0, status=CaseStatus.PASSED)],
        ),
    )
    assert client.cases == [0]

    # _try_report_error should swallow client exceptions
    client.report_result = lambda submit_id, result: (_ for _ in ()).throw(RuntimeError("boom"))  # type: ignore[assignment]
    worker._try_report_error(1, PhaseResult(status=PhaseStatus.ERROR))


def test_register_signal_handlers_and_stop(monkeypatch) -> None:
    client = _Client()
    worker = EvaluationService(client=client, enable_health_server=False)
    captured = {}

    def _signal(sig, handler):
        captured["sig"] = sig
        captured["handler"] = handler

    monkeypatch.setattr(worker_mod.signal, "signal", _signal)
    worker._active_submit_ids = {1, 2}
    worker._register_signal_handlers()
    assert captured["sig"] == signal.SIGTERM
    captured["handler"](signal.SIGTERM, object())
    assert set(client.unclaimed) == {1, 2}
    worker.stop()
    assert worker._running is False


def test_tick_branches(monkeypatch) -> None:
    client = _Client()
    worker = EvaluationService(client=client, enable_health_server=False, poll_interval=0, max_workers=2)
    futures: dict[Future[PhaseResult], SubmissionTask] = {}

    # no futures and no submissions -> sleep branch
    client.pending = []
    slept = {"count": 0}
    monkeypatch.setattr(worker_mod.time, "sleep", lambda sec: slept.__setitem__("count", slept["count"] + 1))

    class _Exec:
        def submit(self, fn, sub):
            fut: Future[PhaseResult] = Future()
            fut.set_result(PhaseResult(status=PhaseStatus.SUCCESS))
            return fut

    worker._tick(_Exec(), futures)
    assert slept["count"] >= 1

    # fill slot and done future branches
    client.pending = [_submission(submit_id=10, timeout=1)]
    monkeypatch.setattr(worker, "process_submission", lambda sub: PhaseResult(status=PhaseStatus.SUCCESS))

    def _wait_done(keys, timeout, return_when):
        return set(keys), set()

    monkeypatch.setattr(worker_mod, "wait", _wait_done)
    worker._tick(_Exec(), futures)
    assert futures == {}

    # done future raises
    fut_err: Future[PhaseResult] = Future()
    fut_err.set_exception(RuntimeError("task failed"))
    futures[fut_err] = SubmissionTask(submit_id=20, start_time=time.time(), timeout=10)
    worker._tick(_Exec(), futures)
    assert 20 not in [task.submit_id for task in futures.values()]

    # not_done timeout warning (do not force terminal report)
    fut_timeout: Future[PhaseResult] = Future()
    futures[fut_timeout] = SubmissionTask(submit_id=30, start_time=time.time() - 1000, timeout=1)

    def _wait_not_done(keys, timeout, return_when):
        return set(), set(keys)

    reported = {"called": False}
    monkeypatch.setattr(worker_mod, "wait", _wait_not_done)
    monkeypatch.setattr(worker, "_try_report_error", lambda submit_id, result: reported.__setitem__("called", True))
    worker._tick(_Exec(), futures)
    assert reported["called"] is False
    assert fut_timeout in futures
    assert futures[fut_timeout].timeout_reported is True


def test_run_main_loop_safety(monkeypatch) -> None:
    client = _Client()
    worker = EvaluationService(client=client, enable_health_server=True, poll_interval=0, max_workers=1)

    monkeypatch.setattr(worker, "_log_startup", lambda: None)
    monkeypatch.setattr(worker, "_register_signal_handlers", lambda: None)
    monkeypatch.setattr(worker_mod, "start_health_server", lambda port=0: None)
    monkeypatch.setattr(worker_mod, "stop_health_server", lambda: None)
    monkeypatch.setattr(worker_mod.SandboxManager, "get_instance", staticmethod(lambda: SimpleNamespace(shutdown=lambda: None)))

    calls = {"n": 0}

    def _tick(executor, futures):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("loop error")
        worker._running = False

    monkeypatch.setattr(worker, "_tick", _tick)
    worker.run()
    assert calls["n"] >= 2


def test_download_code_requires_code_url() -> None:
    client = _Client()
    worker = EvaluationService(client=client, enable_health_server=False)
    sub = _submission()
    sub.code_url = ""
    with pytest.raises(ValueError, match="missing code URL"):
        worker._download_code(sub)


def test_log_startup_outputs_health_endpoints() -> None:
    client = _Client()
    worker = EvaluationService(
        client=client,
        enable_health_server=True,
        health_port=18080,
        max_workers=3,
        poll_interval=5,
    )
    lines: list[str] = []
    old_info = worker_mod.logger.info
    worker_mod.logger.info = lambda msg: lines.append(str(msg))  # type: ignore[assignment]
    try:
        worker._log_startup()
    finally:
        worker_mod.logger.info = old_info  # type: ignore[assignment]
    assert any("evaluation service started" in s for s in lines)
    assert any("health" in s and "18080" in s for s in lines)
    assert any("/metrics" in s for s in lines)


def test_main_bootstrap_invokes_worker_run(monkeypatch) -> None:
    called = {"run": False}

    class _Worker:
        def run(self) -> None:
            called["run"] = True

    monkeypatch.setattr(worker_mod, "EvaluationService", _Worker)
    monkeypatch.setattr(worker_mod.logging, "basicConfig", lambda **kwargs: None)
    worker_mod.main()
    assert called["run"] is True


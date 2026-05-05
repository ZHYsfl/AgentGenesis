"""Integration tests for end-to-end worker service pipeline."""

from __future__ import annotations

from types import SimpleNamespace

import evaluation.client as client_mod
import evaluation.service as worker_mod
from evaluation.client import EvaluationClient
from evaluation.models import CaseResult, CaseStatus, PhaseResult, PhaseStatus
from evaluation.service import EvaluationService


def _mount_requests(monkeypatch, fake_transport) -> None:
    monkeypatch.setattr(client_mod.requests, "post", fake_transport.post)
    monkeypatch.setattr(client_mod.requests, "get", fake_transport.get)
    monkeypatch.setattr(client_mod.requests, "head", fake_transport.head)


def test_process_submission_success_integration(monkeypatch, fake_transport, fake_cfg, submission_factory, dummy_response_cls, zip_bytes) -> None:
    _mount_requests(monkeypatch, fake_transport)
    monkeypatch.setattr(client_mod, "get_config", lambda: fake_cfg)
    monkeypatch.setattr(worker_mod, "get_config", lambda: fake_cfg)

    code_zip = zip_bytes({"requirements.txt": "pytest\n", "solution.py": "def solve(x): return x"})
    base = fake_cfg.backend_url
    fake_transport.post_routes[f"{base}/internal/claim-submission"] = lambda _: dummy_response_cls(200)
    fake_transport.post_routes[f"{base}/internal/eval-update"] = lambda _: dummy_response_cls(200)
    fake_transport.post_routes[f"{base}/internal/create-evaluation-case"] = (
        lambda _: dummy_response_cls(200, json_data={"data": {"case_id": 99}})
    )
    fake_transport.head_routes["http://code.zip"] = lambda _: dummy_response_cls(200, headers={"Content-Length": str(len(code_zip))})
    fake_transport.get_routes["http://code.zip"] = lambda _: dummy_response_cls(200, content=code_zip)

    class EvalOK:
        def __init__(self, config, client=None):
            self.config = config

        def evaluate(self, submission, parallel_cases=1, on_case_start=None, on_case_end=None):
            if on_case_start:
                on_case_start(0)
            case = CaseResult(case_index=0, status=CaseStatus.PASSED, score=1, logs="[]")
            if on_case_end:
                on_case_end(0, case)
            return PhaseResult(
                status=PhaseStatus.SUCCESS,
                score=1,
                passed_cases=1,
                total_cases=1,
                cases=[case],
            )

    client = EvaluationClient()
    worker = EvaluationService(client=client, enable_health_server=False)
    monkeypatch.setattr(worker, "load_evaluator", lambda cfg: EvalOK(cfg))

    result = worker.process_submission(submission_factory(code_files={}))
    assert result.status == PhaseStatus.SUCCESS

    urls = [c.url for c in fake_transport.calls]
    assert f"{base}/internal/claim-submission" in urls
    assert f"{base}/internal/create-evaluation-case" in urls
    assert urls.count(f"{base}/internal/eval-update") >= 2  # case status + final complete


def test_process_submission_sandbox_busy_requeue(monkeypatch, fake_transport, fake_cfg, submission_factory, dummy_response_cls) -> None:
    _mount_requests(monkeypatch, fake_transport)
    monkeypatch.setattr(client_mod, "get_config", lambda: fake_cfg)
    monkeypatch.setattr(worker_mod, "get_config", lambda: fake_cfg)

    base = fake_cfg.backend_url
    fake_transport.post_routes[f"{base}/internal/claim-submission"] = lambda _: dummy_response_cls(200)
    fake_transport.post_routes[f"{base}/internal/unclaim-submission"] = lambda _: dummy_response_cls(200)

    class BusyEval:
        def evaluate(self, *args, **kwargs):
            raise worker_mod.SandboxBusyError("busy")

    client = EvaluationClient()
    worker = EvaluationService(client=client, enable_health_server=False)
    monkeypatch.setattr(worker, "load_evaluator", lambda cfg: BusyEval())
    monkeypatch.setattr(worker, "_download_code", lambda sub: {"requirements.txt": "ok", "solution.py": "ok"})

    result = worker.process_submission(submission_factory(code_files={}))
    assert result.status == PhaseStatus.PENDING
    assert any(c.url.endswith("/internal/unclaim-submission") for c in fake_transport.calls)


def test_process_submission_exception_reports_error(monkeypatch, fake_transport, fake_cfg, submission_factory, dummy_response_cls) -> None:
    _mount_requests(monkeypatch, fake_transport)
    monkeypatch.setattr(client_mod, "get_config", lambda: fake_cfg)
    monkeypatch.setattr(worker_mod, "get_config", lambda: fake_cfg)

    base = fake_cfg.backend_url
    fake_transport.post_routes[f"{base}/internal/claim-submission"] = lambda _: dummy_response_cls(200)
    fake_transport.post_routes[f"{base}/internal/eval-update"] = lambda _: dummy_response_cls(200)

    class BadEval:
        def evaluate(self, *args, **kwargs):
            raise RuntimeError("boom")

    client = EvaluationClient()
    worker = EvaluationService(client=client, enable_health_server=False)
    monkeypatch.setattr(worker, "load_evaluator", lambda cfg: BadEval())
    monkeypatch.setattr(worker, "_download_code", lambda sub: {"requirements.txt": "ok", "solution.py": "ok"})

    result = worker.process_submission(submission_factory(code_files={}))
    assert result.status == PhaseStatus.ERROR
    assert any(c.url.endswith("/internal/eval-update") for c in fake_transport.calls)

"""Unit tests for base evaluator behavior."""

from __future__ import annotations

from ..base import BaseEvaluator
from ..models import CaseResult, PhaseConfig, PhaseResult, PhaseStatus, UserSubmission


class DemoEvaluator(BaseEvaluator):
    def evaluate(
        self,
        submission: UserSubmission,
        parallel_cases: int = 1,
        on_case_start=None,
        on_case_end=None,
    ) -> PhaseResult:
        return PhaseResult(status=PhaseStatus.SUCCESS, total_cases=0, passed_cases=0)


def test_base_evaluator_client_cache(monkeypatch) -> None:
    class DummyClient:
        def __init__(self) -> None:
            self.marker = "ok"

    from .. import client as client_mod

    monkeypatch.setattr(client_mod, "EvaluationClient", DummyClient)
    cfg = PhaseConfig()
    ev = DemoEvaluator(cfg, client=None)
    c1 = ev._get_client()
    c2 = ev._get_client()
    assert c1 is c2
    assert c1.marker == "ok"


def test_base_evaluator_accepts_injected_client() -> None:
    cfg = PhaseConfig()
    injected = object()
    ev = DemoEvaluator(cfg, client=injected)  # type: ignore[arg-type]
    assert ev._get_client() is injected

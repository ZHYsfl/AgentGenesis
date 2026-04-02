"""Base evaluator abstraction and shared client access."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Callable, TYPE_CHECKING

from .models import (
    PhaseConfig,
    PhaseResult,
    CaseResult,
    UserSubmission,
)

if TYPE_CHECKING:
    from .client import EvaluationClient


class BaseEvaluator(ABC):
    config: PhaseConfig
    _client: Optional[EvaluationClient]

    def __init__(self, config: PhaseConfig, client: Optional[EvaluationClient] = None) -> None:
        self.config = config
        self._client = client

    def _get_client(self) -> EvaluationClient:
        if self._client is None:
            from .client import EvaluationClient as _EvaluationClient
            self._client = _EvaluationClient()
        return self._client

    @abstractmethod
    def evaluate(
        self,
        submission: UserSubmission,
        parallel_cases: int = 1,
        on_case_start: Optional[Callable[[int], None]] = None,
        on_case_end: Optional[Callable[[int, CaseResult], None]] = None,
    ) -> PhaseResult:
        ...

"""Structured Output environment — exact-match evaluation."""

from __future__ import annotations

import json


class StructuredOutputEnvironment:
    """Single-question environment: get question, submit answer, JSON semantic match."""

    def __init__(self, case_data: dict) -> None:
        self.question_text: str = case_data["question"]
        self.expected_answer: str = case_data["expected_answer"]
        self.question_id: int = case_data.get("question_id", 0)
        self._submitted: bool = False
        self.success: bool = False

    @property
    def done(self) -> bool:
        return self._submitted

    def get_question(self) -> str:
        return self.question_text

    def submit_answer(self, answer: str) -> str:
        self._submitted = True
        try:
            submitted_obj = json.loads(answer)
            expected_obj = json.loads(self.expected_answer)
        except Exception:
            self.success = False
            return "wrong"

        if submitted_obj == expected_obj:
            self.success = True
            return "correct"
        self.success = False
        return "wrong"

    def compute_score(self) -> int:
        return 100 if self.success else 0

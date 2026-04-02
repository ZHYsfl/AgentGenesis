# problems/interrupt_judge/sandbox/environment.py
"""
Interrupt judgment environment.
"""

import time
from typing import Any


class InterruptJudgeEnvironment:
    """
    Interactive interrupt judgment environment.

    Usage:
        env = InterruptJudgeEnvironment(case_data)
        questions = env.get_problem()  # list[str]
        result = env.submit_answer(answers)  # list[bool]
        print(result["accuracy"], result["passed"])
    """

    def __init__(self, case_data: dict):
        self.questions = case_data["questions"]  # list[str]
        self.labels = case_data["labels"]  # list[bool]: True=interrupt
        self.user_answers = None
        self._start_time = None

    def get_problem(self) -> list[str]:
        """Return the list of questions (user utterances)."""
        self._start_time = time.time()
        return self.questions

    @property
    def done(self) -> bool:
        """Whether the case has ended (user submitted answer)."""
        return self.user_answers is not None

    def submit_answer(self, answers: list[bool]) -> dict:
        """Submit answers and compute accuracy."""
        elapsed = time.time() - self._start_time
        self.user_answers = answers

        if not self.labels:
            return {
                "accuracy": 0,
                "score": 0,
                "correct": 0,
                "total": 0,
                "elapsed_seconds": elapsed,
                "time_exceeded": elapsed > 25,
                "passed": False,
            }

        correct = sum(1 for a, b in zip(answers, self.labels) if a == b)
        accuracy = correct / len(self.labels)

        # 正确率即得分，98.4% 正确率 = 98.4 分
        # 正确率 >= 98.5% 才算通过（绿色）
        return {
            "accuracy": accuracy,
            "score": accuracy,
            "correct": correct,
            "total": len(self.labels),
            "elapsed_seconds": elapsed,
            "time_exceeded": elapsed > 25,
            "passed": accuracy >= 0.985 and elapsed <= 25,
        }

    def compute_score(self) -> float:
        """Compute score based on accuracy. Returns accuracy as score (0-100)."""
        if self.user_answers is None:
            return 0
        correct = sum(1 for a, b in zip(self.user_answers, self.labels) if a == b)
        accuracy = correct / len(self.labels) if self.labels else 0
        return accuracy

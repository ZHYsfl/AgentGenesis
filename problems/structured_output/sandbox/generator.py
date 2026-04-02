"""Load question bank from baked-in data/ directory and sample test cases."""

from __future__ import annotations

import os
import random
from typing import Optional


_DATA_ROOT = os.path.join(os.environ.get("WORKSPACE", "/workspace"), "data")


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def generate_cases(
    num_cases: int = 20,
    total_questions: int = 1000,
    seed: Optional[int] = None,
) -> list[dict]:
    rng = random.Random(seed)
    indices = rng.sample(range(1, total_questions + 1), min(num_cases, total_questions))

    cases: list[dict] = []
    for i, qid in enumerate(indices):
        q_dir = os.path.join(_DATA_ROOT, f"problem_{qid}")
        question = _read_text(os.path.join(q_dir, "question.txt"))
        expected = _read_text(os.path.join(q_dir, "answer.txt"))
        cases.append({
            "case_index": i,
            "question_id": qid,
            "question": question,
            "expected_answer": expected,
        })
    return cases

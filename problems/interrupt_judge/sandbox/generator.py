# problems/interrupt_judge/sandbox/generator.py
"""
Test case generator for interrupt judgment problem.
"""

import json
import os
import random
from pathlib import Path


def load_data() -> list[dict]:
    """Load data from data.jsonl."""
    data_path = Path(__file__).parent.parent / "data" / "data.jsonl"
    data = []
    with open(data_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                data.append(json.loads(line))
    return data


def generate_cases(num_cases: int = 5, seed: int = None) -> list[dict]:
    """
    Generate test cases for interrupt judgment.

    Args:
        num_cases: Number of test cases (default: 5)
        seed: Random seed for reproducibility

    Returns:
        List of case_data dicts, each containing:
        - questions: list[str]
        - labels: list[bool]
    """
    if seed is not None:
        random.seed(seed)

    all_data = load_data()
    random.shuffle(all_data)

    # Each case should have 500 samples
    samples_per_case = 500
    cases = []

    for i in range(num_cases):
        start_idx = i * samples_per_case
        end_idx = start_idx + samples_per_case
        case_data = all_data[start_idx:end_idx]

        questions = [item["content"] for item in case_data]
        # label: "interrupt" -> True, "do not interrupt" -> False
        labels = [item["label"] == "interrupt" for item in case_data]

        cases.append({
            "questions": questions,
            "labels": labels,
        })

    return cases


if __name__ == "__main__":
    # Test generation
    cases = generate_cases(num_cases=5)
    print(f"Generated {len(cases)} cases")
    for i, case in enumerate(cases):
        print(f"Case {i}: {len(case['questions'])} questions")

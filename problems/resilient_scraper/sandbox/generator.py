"""Generate random test cases for The Resilient Scraper.

All data pools (fact pairs, templates, etc.) are loaded from data_pool.json
which is listed in private_files — users cannot see its contents.
"""

from __future__ import annotations

import json
import random
import string
from pathlib import Path

SUCCESS_PROBABILITIES = [0.30, 0.50, 0.80, 0.95]

_DATA_POOL_PATH = Path(__file__).with_name("data_pool.json")
_pool: dict | None = None


def _load_pool() -> dict:
    global _pool
    if _pool is None:
        _pool = json.loads(_DATA_POOL_PATH.read_text(encoding="utf-8"))
    return _pool


def _random_id(rng: random.Random, prefix: str, length: int = 5) -> str:
    chars = string.ascii_uppercase + string.digits
    body = "".join(rng.choices(chars, k=length))
    return f"{prefix}-{body}"


def _generate_real_data(rng: random.Random, pool: dict) -> str:
    templates = pool["real_data_templates"]
    t = rng.choice(templates)
    return t.format(
        c=rng.choice(pool["cluster_names"]), cpu=rng.randint(15, 95),
        mem=rng.randint(4, 28), tot=32, up=rng.randint(1, 365),
        code=_random_id(rng, "ALR", 4),
        acc=_random_id(rng, "ACC", 6), name=rng.choice(pool["names"]),
        role=rng.choice(pool["roles"]), dept=rng.choice(pool["departments"]),
        badge=_random_id(rng, "BDG", 5), lv=rng.randint(1, 5),
        n=_random_id(rng, "NODE", 4), r=rng.choice(pool["regions"]),
        load=f"{rng.uniform(0.1, 8.0):.2f}", t=rng.randint(5, 200),
        ref=_random_id(rng, "REF", 6),
        ver=f"v{rng.randint(1,5)}.{rng.randint(0,9)}.{rng.randint(0,20)}",
        svc=_random_id(rng, "SVC", 4), inst=rng.randint(2, 20),
        rps=rng.randint(100, 50000), lat=rng.randint(5, 500),
        err=f"{rng.uniform(0, 5):.2f}", did=_random_id(rng, "DPL", 8),
        wh=_random_id(rng, "WH", 4), items=rng.randint(500, 50000),
        cap=rng.randint(30, 98),
        sync=f"2026-{rng.randint(1,3):02d}-{rng.randint(1,28):02d}",
        mid=_random_id(rng, "MAN", 6), z=rng.choice(["A", "B", "C", "D"]),
    )


def _generate_garbage_data(rng: random.Random, pool: dict) -> str:
    templates = pool["garbage_data_templates"]
    t = rng.choice(templates)
    return t.format(
        x="".join(rng.choices(string.digits, k=4)),
        y="".join(rng.choices(string.ascii_uppercase + string.digits, k=5)),
    )


def _build_response(rng: random.Random, claim: str, data: str, pool: dict) -> str:
    template = rng.choice(pool["response_templates"])
    return template.format(claim=claim, data=data)


def _roll_success_attempt(rng: random.Random) -> int | None:
    """Returns 1-4 if that attempt succeeds, None if all fail."""
    for i, prob in enumerate(SUCCESS_PROBABILITIES):
        if rng.random() < prob:
            return i + 1
    return None


def generate_cases(
    num_cases: int = 10,
    seed: int | None = None,
) -> list[dict]:
    pool = _load_pool()
    fact_pairs: list[list[str]] = pool["fact_pairs"]
    rng = random.Random(seed)
    cases: list[dict] = []

    for i in range(num_cases):
        task_template = rng.choice(pool["task_templates"])
        task_description = task_template.format(
            cluster=rng.choice(pool["cluster_names"]),
            account=_random_id(rng, "ACC", 5),
            node=_random_id(rng, "N", 4),
            service=_random_id(rng, "SVC", 4),
            deploy=_random_id(rng, "DEP", 5),
            warehouse=_random_id(rng, "WH", 3),
        )

        expected_data = _generate_real_data(rng, pool)
        success_on_attempt = _roll_success_attempt(rng)

        used_facts: set[int] = set()
        attempt_responses: list[str] = []

        for attempt_num in range(1, 5):
            fact_idx = rng.randint(0, len(fact_pairs) - 1)
            while fact_idx in used_facts:
                fact_idx = rng.randint(0, len(fact_pairs) - 1)
            used_facts.add(fact_idx)

            correct_claim, wrong_claim = fact_pairs[fact_idx]

            if attempt_num == success_on_attempt:
                response = _build_response(rng, correct_claim, expected_data, pool)
            else:
                garbage = _generate_garbage_data(rng, pool)
                response = _build_response(rng, wrong_claim, garbage, pool)

            attempt_responses.append(response)

        cases.append({
            "case_index": i,
            "task_description": task_description,
            "expected_data": expected_data,
            "success_on_attempt": success_on_attempt,
            "attempt_responses": attempt_responses,
        })

    return cases

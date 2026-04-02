"""Test case generator for the werewolf problem.

Each case is a game with a different random seed.  Role assignments
are fixed (2 wolves, 1 seer, 1 witch, 2 villagers) but the seed
changes wolf AI behaviour and randomised game elements.
"""

from __future__ import annotations

import random


def generate_cases(
    *,
    num_cases: int = 5,
    seed: int | None = None,
    max_rounds: int = 15,
) -> list[dict]:
    rng = random.Random(seed)
    cases: list[dict] = []
    for i in range(num_cases):
        case_seed = rng.randint(0, 2**31 - 1)
        cases.append({
            "case_index": i,
            "seed": case_seed,
            "max_rounds": max_rounds,
        })
    return cases

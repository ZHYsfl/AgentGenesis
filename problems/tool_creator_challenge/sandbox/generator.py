"""Generator for the Tool Creator Challenge.

Loads 100 computation task entries from data_pool.json (10 types x 10 each),
provides solver functions for each type, and generates test cases by sampling.
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Any

_DATA_POOL_PATH = Path(__file__).with_name("data_pool.json")
_pool: dict | None = None


def _ordinal(n: int) -> str:
    """Return n with English ordinal suffix (e.g. 1st, 2nd, 3rd, 113th)."""
    if 11 <= (n % 100) <= 13:
        return f"{n}th"
    return f"{n}{('th','st','nd','rd','th','th','th','th','th','th')[n % 10]}"


# ---------------------------------------------------------------------------
# Description builder functions (type -> callable that accepts params dict)
# ---------------------------------------------------------------------------


def _desc_fibonacci(p: dict) -> str:
    n = p["n"]
    return (
        f"Create a Fibonacci number calculator tool. "
        f"Compute F({n}), the {_ordinal(n)} Fibonacci number. "
        f"Definition: F(1)=1, F(2)=1, F(n)=F(n-1)+F(n-2) for n>=3."
    )


def _desc_factorial_digit_sum(p: dict) -> str:
    n = p["n"]
    return (
        f"Create a factorial digit-sum calculator tool. "
        f"Compute the sum of all digits of {n}! (that is, {n} factorial). "
        f"For example, the digit sum of 10! = 3628800 is 3+6+2+8+8+0+0 = 27."
    )


def _desc_power_mod(p: dict) -> str:
    return (
        f"Create a modular exponentiation tool. "
        f"Compute {p['base']}^{p['exp']} mod {p['mod']} "
        f"(i.e. {p['base']} raised to the power {p['exp']}, then take remainder "
        f"when divided by {p['mod']})."
    )


def _desc_collatz_steps(p: dict) -> str:
    n = p["n"]
    return (
        f"Create a Collatz sequence step-counter tool. "
        f"Count the number of steps for {n} to reach 1 in the Collatz sequence. "
        f"Rules: if n is even, n -> n/2; if n is odd, n -> 3*n+1. "
        f"Each application is one step."
    )


def _desc_nth_prime(p: dict) -> str:
    n = p["n"]
    return (
        f"Create a prime-number finder tool. "
        f"Find the {_ordinal(n)} prime number. "
        f"Convention: the 1st prime is 2, 2nd is 3, 3rd is 5, 4th is 7, etc."
    )


def _desc_combinations(p: dict) -> str:
    n, k = p["n"], p["k"]
    return (
        f"Create a binomial coefficient calculator tool. "
        f"Compute C({n}, {k}) = {n}! / ({k}! * ({n}-{k})!). "
        f"Return the exact integer value."
    )


def _desc_catalan(p: dict) -> str:
    n = p["n"]
    return (
        f"Create a Catalan number calculator tool. "
        f"Compute the {_ordinal(n)} Catalan number. "
        f"Formula: C(n) = C(2n, n) / (n+1), where C(2n,n) is the binomial coefficient. "
        f"Convention: C(0)=1, C(1)=1, C(2)=2, C(3)=5, ..."
    )


def _desc_tribonacci(p: dict) -> str:
    n = p["n"]
    return (
        f"Create a Tribonacci number calculator tool. "
        f"Compute T({n}), the {_ordinal(n)} Tribonacci number. "
        f"Definition: T(0)=0, T(1)=0, T(2)=1, T(n)=T(n-1)+T(n-2)+T(n-3) for n>=3."
    )


def _desc_lucas(p: dict) -> str:
    n = p["n"]
    return (
        f"Create a Lucas number calculator tool. "
        f"Compute L({n}), the {_ordinal(n)} Lucas number. "
        f"Definition: L(1)=1, L(2)=3, L(n)=L(n-1)+L(n-2) for n>=3."
    )


def _desc_partition(p: dict) -> str:
    n = p["n"]
    return (
        f"Create an integer-partition counter tool. "
        f"Compute p({n}), the number of ways to write {n} as a sum of positive integers "
        f"(order does not matter). For example, p(5) = 7."
    )


DESC_BUILDERS: dict[str, Any] = {
    "fibonacci": _desc_fibonacci,
    "factorial_digit_sum": _desc_factorial_digit_sum,
    "power_mod": _desc_power_mod,
    "collatz_steps": _desc_collatz_steps,
    "nth_prime": _desc_nth_prime,
    "combinations": _desc_combinations,
    "catalan": _desc_catalan,
    "tribonacci": _desc_tribonacci,
    "lucas": _desc_lucas,
    "partition": _desc_partition,
}

# ---------------------------------------------------------------------------
# Solver functions
# ---------------------------------------------------------------------------


def _solve_fibonacci(n: int) -> str:
    if n <= 0:
        return "0"
    if n <= 2:
        return "1"
    a, b = 1, 1
    for _ in range(n - 2):
        a, b = b, a + b
    return str(b)


def _solve_factorial_digit_sum(n: int) -> str:
    return str(sum(int(d) for d in str(math.factorial(n))))


def _solve_power_mod(base: int, exp: int, mod: int) -> str:
    return str(pow(base, exp, mod))


def _solve_collatz_steps(n: int) -> str:
    steps = 0
    while n != 1:
        if n % 2 == 0:
            n //= 2
        else:
            n = 3 * n + 1
        steps += 1
    return str(steps)


def _solve_nth_prime(n: int) -> str:
    if n == 1:
        return "2"
    count = 1
    candidate = 3
    while True:
        if _is_prime(candidate):
            count += 1
            if count == n:
                return str(candidate)
        candidate += 2


def _is_prime(num: int) -> bool:
    if num < 2:
        return False
    if num < 4:
        return True
    if num % 2 == 0 or num % 3 == 0:
        return False
    i = 5
    while i * i <= num:
        if num % i == 0 or num % (i + 2) == 0:
            return False
        i += 6
    return True


def _solve_combinations(n: int, k: int) -> str:
    return str(math.comb(n, k))


def _solve_catalan(n: int) -> str:
    return str(math.comb(2 * n, n) // (n + 1))


def _solve_tribonacci(n: int) -> str:
    if n == 0:
        return "0"
    if n == 1:
        return "0"
    if n == 2:
        return "1"
    a, b, c = 0, 0, 1
    for _ in range(n - 2):
        a, b, c = b, c, a + b + c
    return str(c)


def _solve_lucas(n: int) -> str:
    if n == 1:
        return "1"
    if n == 2:
        return "3"
    a, b = 1, 3
    for _ in range(n - 2):
        a, b = b, a + b
    return str(b)


def _solve_partition(n: int) -> str:
    p = [0] * (n + 1)
    p[0] = 1
    for k in range(1, n + 1):
        for i in range(k, n + 1):
            p[i] += p[i - k]
    return str(p[n])


def _compute_answer(task_type: str, params: dict) -> str:
    if task_type == "fibonacci":
        return _solve_fibonacci(params["n"])
    if task_type == "factorial_digit_sum":
        return _solve_factorial_digit_sum(params["n"])
    if task_type == "power_mod":
        return _solve_power_mod(params["base"], params["exp"], params["mod"])
    if task_type == "collatz_steps":
        return _solve_collatz_steps(params["n"])
    if task_type == "nth_prime":
        return _solve_nth_prime(params["n"])
    if task_type == "combinations":
        return _solve_combinations(params["n"], params["k"])
    if task_type == "catalan":
        return _solve_catalan(params["n"])
    if task_type == "tribonacci":
        return _solve_tribonacci(params["n"])
    if task_type == "lucas":
        return _solve_lucas(params["n"])
    if task_type == "partition":
        return _solve_partition(params["n"])
    raise ValueError(f"unknown task type: {task_type}")


# ---------------------------------------------------------------------------
# Pool loading & expansion
# ---------------------------------------------------------------------------


def _load_pool() -> dict:
    global _pool
    if _pool is None:
        _pool = json.loads(_DATA_POOL_PATH.read_text(encoding="utf-8"))
    return _pool


def _build_full_pool() -> list[dict]:
    """Expand data_pool.json into 100 flat entries with descriptions."""
    raw = _load_pool()
    entries: list[dict] = []
    idx = 0

    for task_type, param_list in raw.items():
        builder = DESC_BUILDERS[task_type]
        for raw_params in param_list:
            if task_type == "power_mod":
                params = {"base": raw_params[0], "exp": raw_params[1], "mod": raw_params[2]}
            elif task_type == "combinations":
                params = {"n": raw_params[0], "k": raw_params[1]}
            else:
                params = {"n": raw_params}
            entries.append({
                "id": idx,
                "type": task_type,
                "params": params,
                "description": builder(params),
            })
            idx += 1

    return entries


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_cases(
    num_cases: int = 5,
    queries_per_case: int = 10,
    seed: int | None = None,
) -> list[dict]:
    pool = _build_full_pool()
    rng = random.Random(seed)
    cases: list[dict] = []

    for case_idx in range(num_cases):
        selected = rng.sample(pool, k=queries_per_case)
        queries: list[dict] = []
        expected: dict[int, str] = {}

        for q_idx, entry in enumerate(selected):
            answer = _compute_answer(entry["type"], entry["params"])
            queries.append({
                "query_id": q_idx,
                "description": entry["description"],
            })
            expected[q_idx] = answer

        cases.append({
            "case_index": case_idx,
            "queries": queries,
            "expected": expected,
        })

    return cases

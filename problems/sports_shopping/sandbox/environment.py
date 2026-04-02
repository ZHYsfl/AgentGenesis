"""Sports Shopping judge-side environment.

Tracks timing from get_problem() and validates submit_answer / guardrail correctness.
"""

from __future__ import annotations

import json
import time

PRICE_TOLERANCE = 0.01


class SportsShoppingEnvironment:

    def __init__(
        self,
        case_data: dict,
        guardrail_time_limit: float = 15.0,
        submit_time_limit: float = 27.0,
    ) -> None:
        self._question_type: str = case_data["question_type"]
        self._user_message: str = case_data["user_message"]
        self._product_catalog: dict[str, str] = case_data["product_catalog"]
        self._expected_price: float | None = case_data.get("expected_price")
        self._expected_brand: str | None = case_data.get("expected_brand")
        self._expected_guardrail: str | None = case_data.get("expected_guardrail")
        self._guardrail_time_limit = guardrail_time_limit
        self._submit_time_limit = submit_time_limit

        self._start_time: float | None = None
        self._submitted: bool = False
        self._success: bool = False
        self._error_detail: str = ""

    @property
    def done(self) -> bool:
        return self._submitted

    @property
    def success(self) -> bool:
        return self._success

    @property
    def elapsed_time(self) -> float:
        if self._start_time is None:
            return 0.0
        return time.time() - self._start_time

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def get_problem(self) -> str:
        """Start the timer and return user message + product catalog (for adapter)."""
        self._start_time = time.time()
        payload = {
            "user_message": self._user_message,
            "product_catalog": self._product_catalog,
        }
        return json.dumps(payload, ensure_ascii=False)

    def submit_answer(self, price: float | str, brand: str) -> str:
        """Check purchase answer: price within tolerance and brand exact match."""
        if self._submitted:
            return "wrong: already submitted"
        if self._start_time is None:
            return "wrong: call get_problem() first"

        self._submitted = True

        if self._question_type != "purchase":
            return self._fail("this message required guardrail, not submit_answer")

        elapsed = self.elapsed_time
        if elapsed > self._submit_time_limit:
            return self._fail(
                f"submit deadline exceeded: {elapsed:.1f}s > {self._submit_time_limit}s limit"
            )

        try:
            price_val = float(price)
        except (TypeError, ValueError):
            return self._fail("invalid price value")

        if abs(price_val - self._expected_price) > PRICE_TOLERANCE:
            return self._fail(
                f"incorrect price: expected {self._expected_price}, got {price_val}"
            )

        if str(brand).strip().lower() != self._expected_brand.lower():
            return self._fail(
                f"incorrect brand: expected '{self._expected_brand}', got '{brand}'"
            )

        self._success = True
        return "correct"

    def guardrail(self, guardrail_type: str) -> str:
        """Check guardrail: correct type and within time limit."""
        if self._submitted:
            return "wrong: already submitted"
        if self._start_time is None:
            return "wrong: call get_problem() first"

        self._submitted = True

        if self._question_type == "purchase":
            return self._fail("this was a purchase query, not a guardrail case")

        elapsed = self.elapsed_time
        if elapsed > self._guardrail_time_limit:
            return self._fail(
                f"guardrail timeout: {elapsed:.1f}s > {self._guardrail_time_limit}s limit"
            )

        if str(guardrail_type).strip() != self._expected_guardrail:
            return self._fail(
                f"incorrect guardrail type: expected '{self._expected_guardrail}', "
                f"got '{guardrail_type}'"
            )

        self._success = True
        return "correct"

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def compute_score(self) -> int:
        return 100 if self._success else 0

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _fail(self, detail: str) -> str:
        self._success = False
        self._error_detail = detail
        return f"wrong: {detail}"

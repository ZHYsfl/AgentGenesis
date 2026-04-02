"""Resilient Scraper judge-side environment.

Tracks fetch_data attempts, validates exponential backoff timing,
enforces attempt limits, and validates submitted data.

Each fetch_data() response contains a factual claim + data record.
Correct claim = successful fetch (valid data).
Wrong claim = failed fetch (garbage data).
The agent must use an LLM to verify the claim — no regex shortcut.
"""

from __future__ import annotations

import time


class ResilientScraperEnvironment:

    def __init__(
        self,
        case_data: dict,
        backoff_base: float = 10.0,
        backoff_tolerance: float = 1.0,
    ) -> None:
        self._task_description: str = case_data["task_description"]
        self._expected_data: str = case_data["expected_data"]
        self._success_on_attempt: int | None = case_data["success_on_attempt"]
        self._attempt_responses: list[str] = case_data["attempt_responses"]
        self._backoff_base = backoff_base
        self._backoff_tolerance = backoff_tolerance
        self._max_attempts = 4

        self._attempt_count: int = 0
        self._attempt_times: list[float] = []
        self._submitted: bool = False
        self._done: bool = False
        self._success: bool = False
        self._error_detail: str = ""

    @property
    def done(self) -> bool:
        return self._done

    @property
    def success(self) -> bool:
        return self._success

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def get_problem(self) -> str:
        return self._task_description

    def fetch_data(self) -> str:
        """Return a response with a factual claim + data record.

        Validates attempt count and exponential backoff timing.
        """
        if self._submitted:
            return self._fail("fetch_data called after submit")
        if self._attempt_count >= self._max_attempts:
            return self._fail(
                f"exceeded maximum fetch_data attempts ({self._max_attempts})"
            )

        now = time.time()
        if self._attempt_count > 0:
            elapsed = now - self._attempt_times[-1]
            required = self._backoff_base * (2 ** (self._attempt_count - 1))
            if elapsed < required - self._backoff_tolerance:
                return self._fail(
                    f"backoff violation: waited {elapsed:.2f}s but minimum "
                    f"is {required:.1f}s before attempt {self._attempt_count + 1}"
                )

        self._attempt_count += 1
        self._attempt_times.append(now)

        return self._attempt_responses[self._attempt_count - 1]

    def submit(self, data: str) -> str:
        """Validate submitted data.

        - If a correct claim existed: agent must submit matching data.
        - If all claims were wrong: any submission (including empty) is
          accepted — the scraper legitimately found nothing.
        """
        if self._submitted:
            return self._fail("already submitted")
        self._submitted = True

        if self._success_on_attempt is None:
            self._success = True
            self._done = True
            return "correct"

        if str(data).strip() != self._expected_data.strip():
            return self._fail(
                f"incorrect data: expected '{self._expected_data[:60]}...', "
                f"got '{str(data)[:60]}...'"
            )

        self._success = True
        self._done = True
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
        self._done = True
        self._error_detail = detail
        return f"wrong: {detail}"

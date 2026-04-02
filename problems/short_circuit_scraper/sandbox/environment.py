"""Short-Circuit Scraper judge-side environment.

Tracks timing from get_user() and validates submit(email, member_id).
Implements the two-phase done protocol: submit validates but only sets
done on failure; cascade_check completes the success path.
"""

from __future__ import annotations

import json
import time


class ShortCircuitScraperEnvironment:

    def __init__(
        self,
        case_data: dict,
        submit_deadline: float = 25.0,
    ) -> None:
        self._user_name: str = case_data["user_name"]
        self._valid_index: int = case_data["valid_index"]
        self._profile_data: str = case_data["profile_data"]
        self._expected_email: str = case_data["expected_email"]
        self._expected_member_id: str = case_data["expected_member_id"]
        self._num_endpoints: int = case_data["num_endpoints"]
        self._error_template: str = case_data["error_template"]
        self._submit_deadline = submit_deadline

        self._start_time: float | None = None
        self._submitted: bool = False
        self._submitted_correct: bool = False
        self._done: bool = False
        self._success: bool = False
        self._error_detail: str = ""

    @property
    def done(self) -> bool:
        return self._done

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

    def get_user(self) -> str:
        """Start the timer and return case data for the adapter."""
        self._start_time = time.time()
        payload = {
            "user_name": self._user_name,
            "valid_index": self._valid_index,
            "profile_data": self._profile_data,
            "num_endpoints": self._num_endpoints,
            "error_template": self._error_template,
        }
        return json.dumps(payload, ensure_ascii=False)

    def submit(self, email: str, member_id: str) -> str:
        """Validate extracted fields and deadline.

        On wrong answer: sets done=True immediately.
        On correct answer: does NOT set done — waits for cascade_check.
        """
        if self._submitted:
            return self._fail("already submitted")
        if self._start_time is None:
            return self._fail("call get_user() first")

        self._submitted = True

        elapsed = self.elapsed_time
        if elapsed > self._submit_deadline:
            return self._fail(
                f"submit deadline exceeded: {elapsed:.1f}s > {self._submit_deadline}s limit"
            )

        email_ok = str(email).strip().lower() == self._expected_email.strip().lower()
        mid_ok = str(member_id).strip() == self._expected_member_id.strip()

        if not email_ok and not mid_ok:
            return self._fail(
                f"incorrect email and member_id: "
                f"expected '{self._expected_email}' / '{self._expected_member_id}', "
                f"got '{email}' / '{member_id}'"
            )
        if not email_ok:
            return self._fail(
                f"incorrect email: expected '{self._expected_email}', got '{email}'"
            )
        if not mid_ok:
            return self._fail(
                f"incorrect member_id: expected '{self._expected_member_id}', got '{member_id}'"
            )

        self._submitted_correct = True
        return "correct"

    def cascade_check(self, leaked_count: int) -> str:
        """Called by the adapter after the post-submit detection window.

        If leaked_count > 0, the user failed cascade termination.
        Otherwise, mark success based on submit result.
        """
        leaked = int(leaked_count)
        if leaked > 0:
            return self._fail(
                f"cascade violation: {leaked} scraper thread(s) still running after submit"
            )

        self._success = self._submitted_correct
        self._done = True
        return "pass" if self._success else f"wrong: {self._error_detail}"

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

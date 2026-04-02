"""Tool Creator Challenge judge-side environment.

Stores precomputed expected answers for each query. Validates submissions
and tracks progress — a case passes when all queries are answered correctly.
"""

from __future__ import annotations

import json


class ToolCreatorEnvironment:

    def __init__(self, case_data: dict) -> None:
        self._queries: list[dict] = case_data["queries"]
        self._expected: dict[int, str] = {
            int(k): v for k, v in case_data["expected"].items()
        }
        self._total = len(self._queries)
        self._correct: set[int] = set()
        self._submitted: set[int] = set()
        self._done: bool = False
        self._success: bool = False

    @property
    def done(self) -> bool:
        return self._done

    @property
    def success(self) -> bool:
        return self._success

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def get_queries(self) -> str:
        return json.dumps(self._queries, ensure_ascii=False)

    def submit(self, query_id: int, answer: str) -> str:
        if self._done:
            return "wrong: environment already finished"

        qid = int(query_id)
        if qid not in self._expected:
            return f"wrong: invalid query_id {qid}"

        if qid in self._submitted:
            return f"wrong: query_id {qid} already submitted"

        self._submitted.add(qid)

        expected = self._expected[qid]
        actual = str(answer).strip()

        if actual != expected:
            self._done = True
            self._success = False
            return (
                f"wrong: incorrect answer for query {qid}"
            )

        self._correct.add(qid)

        if len(self._correct) == self._total:
            self._done = True
            self._success = True

        return "correct"

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def compute_score(self) -> int:
        return 100 if self._success else 0

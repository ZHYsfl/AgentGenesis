"""Resilient Scraper user adapter.

All calls go through the judge queue — no local execution needed.
The judge tracks attempt counts, timestamps, and backoff validation.
"""

from __future__ import annotations

import json
import queue
from types import SimpleNamespace
from typing import Any, Optional

from agent_genesis.runtime.user_adapter import UserAdapter


class ResilientScraperAdapter(UserAdapter):

    def create_user_api(
        self,
        act_queue: "queue.Queue[Optional[dict[str, Any]]]",
        obs_queue: "queue.Queue[Optional[Any]]",
    ) -> Any:

        def _call_judge(action_name: str, **kwargs: Any) -> str:
            payload = {"action": action_name, **kwargs}
            act_queue.put(payload)
            obs = obs_queue.get()
            if obs is None:
                raise StopIteration("environment closed")
            return str(obs)

        def get_problem() -> str:
            return _call_judge("get_problem")

        def fetch_data() -> str:
            return _call_judge("fetch_data")

        def submit(data: str) -> str:
            return _call_judge("submit", data=str(data))

        env = SimpleNamespace()
        env.get_problem = get_problem
        env.fetch_data = fetch_data
        env.submit = submit
        return env


def get_adapter(preset_name: str = "resilient_scraper") -> UserAdapter:
    if preset_name != "resilient_scraper":
        raise RuntimeError(
            f"unsupported adapter preset for resilient_scraper: {preset_name}"
        )
    return ResilientScraperAdapter()

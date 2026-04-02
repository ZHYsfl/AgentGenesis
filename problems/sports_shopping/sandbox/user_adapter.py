"""Sports Shopping user adapter.

get_problem / submit_answer / guardrail go through the judge queue.
get_info runs LOCALLY with an artificial delay, using product catalog
data received from the judge's get_problem response.
"""

from __future__ import annotations

import json
import os
import queue
import time
from types import SimpleNamespace
from typing import Any, Optional

from agent_genesis.runtime.user_adapter import UserAdapter

INFO_DELAY = float(os.environ.get("INFO_DELAY", "20.0"))


class SportsShoppingAdapter(UserAdapter):

    def create_user_api(
        self,
        act_queue: "queue.Queue[Optional[dict[str, Any]]]",
        obs_queue: "queue.Queue[Optional[Any]]",
    ) -> Any:
        product_catalog: dict[str, str] = {}

        def _call_judge(action_name: str, **kwargs: Any) -> str:
            payload = {"action": action_name, **kwargs}
            act_queue.put(payload)
            obs = obs_queue.get()
            if obs is None:
                raise StopIteration("environment closed")
            return str(obs)

        def get_problem() -> str:
            raw = _call_judge("get_problem")
            try:
                full = json.loads(raw)
                product_catalog.update(full.get("product_catalog", {}))
                return full["user_message"]
            except (json.JSONDecodeError, KeyError):
                return raw

        def get_info(item_key: str) -> str:
            """Look up product info — deliberately blocks for INFO_DELAY seconds."""
            time.sleep(INFO_DELAY)
            info = product_catalog.get(item_key)
            if info is None:
                return f"Sorry, we don't carry '{item_key}' in our store."
            return info

        def submit_answer(price: float, brand: str) -> str:
            return _call_judge(
                "submit_answer",
                price=float(price),
                brand=str(brand),
            )

        def guardrail(type: str) -> str:
            return _call_judge("guardrail", guardrail_type=str(type))

        env = SimpleNamespace()
        env.get_problem = get_problem
        env.get_info = get_info
        env.submit_answer = submit_answer
        env.guardrail = guardrail
        return env


def get_adapter(preset_name: str = "sports_shopping") -> UserAdapter:
    if preset_name != "sports_shopping":
        raise RuntimeError(
            f"unsupported adapter preset for sports_shopping: {preset_name}"
        )
    return SportsShoppingAdapter()

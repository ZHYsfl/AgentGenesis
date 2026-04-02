"""Tool Creator Challenge user adapter.

Provides env.get_queries() and env.submit() via the judge queue.
The create_tool capability lives entirely in the user sandbox.
"""

from __future__ import annotations

import json
import queue
from types import SimpleNamespace
from typing import Any, Optional

from agent_genesis.runtime.user_adapter import UserAdapter


class ToolCreatorAdapter(UserAdapter):

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

        def get_queries() -> list[dict]:
            raw = _call_judge("get_queries")
            return json.loads(raw)

        def submit(query_id: int, answer: str) -> str:
            return _call_judge("submit", query_id=int(query_id), answer=str(answer))

        env = SimpleNamespace()
        env.get_queries = get_queries
        env.submit = submit
        return env


def get_adapter(preset_name: str = "tool_creator") -> UserAdapter:
    if preset_name != "tool_creator":
        raise RuntimeError(
            f"unsupported adapter preset for tool_creator: {preset_name}"
        )
    return ToolCreatorAdapter()

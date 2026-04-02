"""Structured Output user adapter.

Exposes ``get_question()`` and ``submit_answer(answer)`` to the user's
``solve(env)`` function via the standard act/obs queue protocol.
"""

from __future__ import annotations

import queue
from types import SimpleNamespace
from typing import Any, Optional

from agent_genesis.runtime.user_adapter import UserAdapter


class StructuredOutputAdapter(UserAdapter):

    def create_user_api(
        self,
        act_queue: "queue.Queue[Optional[dict[str, Any]]]",
        obs_queue: "queue.Queue[Optional[Any]]",
    ) -> Any:
        def _call(action_name: str, **kwargs: Any) -> str:
            payload = {"action": action_name, **kwargs}
            act_queue.put(payload)
            obs = obs_queue.get()
            if obs is None:
                raise StopIteration("environment closed")
            return str(obs)

        env = SimpleNamespace()
        env.get_question = lambda: _call("get_question")
        env.submit_answer = lambda answer: _call("submit_answer", answer=str(answer))
        return env


def get_adapter(preset_name: str = "structured_output") -> UserAdapter:
    if preset_name != "structured_output":
        raise RuntimeError(
            f"unsupported adapter preset for structured_output: {preset_name}"
        )
    return StructuredOutputAdapter()

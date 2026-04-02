# problems/interrupt_judge/sandbox/user_adapter.py
"""
User adapter for interrupt judgment problem.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional
import queue

from agent_genesis.runtime.user_adapter import UserAdapter


class InterruptAdapter(UserAdapter):
    def create_user_api(
        self,
        act_queue: "queue.Queue[Optional[dict[str, Any]]]",
        obs_queue: "queue.Queue[Optional[Any]]",
    ) -> Any:
        def _call(action_name: str, **kwargs: Any) -> Any:
            payload = {"type": action_name, **kwargs}
            act_queue.put(payload)
            obs = obs_queue.get()
            if obs is None:
                raise StopIteration("environment closed")
            return obs

        env = SimpleNamespace()
        env.get_problem = lambda: _call("get_problem")
        env.submit_answer = lambda answers: _call("submit_answer", answers=answers)
        return env


def get_adapter(preset_name: str = "interrupt_judge") -> UserAdapter:
    if preset_name != "interrupt_judge":
        raise RuntimeError(f"unsupported adapter preset for interrupt_judge: {preset_name}")
    return InterruptAdapter()

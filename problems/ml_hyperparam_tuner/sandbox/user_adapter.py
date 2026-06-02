"""User-facing API adapter for ML hyperparameter tuning."""

from __future__ import annotations

import queue
from types import SimpleNamespace
from typing import Any, Optional

from agent_genesis.runtime.user_adapter import UserAdapter


class MLHyperparamTunerAdapter(UserAdapter):
    def create_user_api(
        self,
        act_queue: "queue.Queue[Optional[dict[str, Any]]]",
        obs_queue: "queue.Queue[Optional[Any]]",
    ) -> Any:
        def call(action_name: str, **kwargs: Any) -> Any:
            act_queue.put({"action": action_name, **kwargs})
            obs = obs_queue.get()
            if obs is None:
                raise StopIteration("environment closed")
            return obs

        env = SimpleNamespace()
        env.get_problem_info = lambda: call("get_problem_info")
        env.train = lambda model_name, params: call("train", model_name=model_name, params=params)
        env.submit_answer = lambda config: call("submit_answer", config=config)
        return env


def get_adapter(preset_name: str = "ml_hyperparam_tuner") -> UserAdapter:
    if preset_name != "ml_hyperparam_tuner":
        raise RuntimeError(f"unsupported adapter preset: {preset_name}")
    return MLHyperparamTunerAdapter()

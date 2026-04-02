"""Parallel Weather user adapter.

Key design: get_questions / submit_answer(s) go through the judge queue,
but get_weather (sync) and get_humidity (async) run LOCALLY in the user
sandbox with artificial delays. This allows true parallel tool execution
that the turn-based queue protocol cannot support.

The judge's get_questions response contains `questions` (shown to user)
and `nl_texts` (pre-generated natural-language sentences for each city's
temperature and humidity, stored internally for local tool lookups).
No raw numeric values are exposed to the user sandbox.
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import time
from types import SimpleNamespace
from typing import Any, Optional

from agent_genesis.runtime.user_adapter import UserAdapter

TOOL_DELAY = float(os.environ.get("TOOL_DELAY", "10.0"))


class ParallelWeatherAdapter(UserAdapter):

    def create_user_api(
        self,
        act_queue: "queue.Queue[Optional[dict[str, Any]]]",
        obs_queue: "queue.Queue[Optional[Any]]",
    ) -> Any:
        nl_texts: dict[str, dict[str, str]] = {}

        def _call_judge(action_name: str, **kwargs: Any) -> str:
            payload = {"action": action_name, **kwargs}
            act_queue.put(payload)
            obs = obs_queue.get()
            if obs is None:
                raise StopIteration("environment closed")
            return str(obs)

        def get_questions() -> str:
            raw = _call_judge("get_questions")
            try:
                full = json.loads(raw)
                nl_texts.update(full.get("nl_texts", {}))
                return json.dumps(full["questions"], ensure_ascii=False)
            except (json.JSONDecodeError, KeyError):
                return raw

        def get_weather(city: str) -> str:
            """Synchronous tool — deliberately blocks for TOOL_DELAY seconds."""
            time.sleep(TOOL_DELAY)
            texts = nl_texts.get(city)
            if texts is None:
                return f"error: unknown city '{city}'"
            return texts["temperature_text"]

        async def get_humidity(city: str) -> str:
            """Asynchronous tool — deliberately blocks for TOOL_DELAY seconds."""
            await asyncio.sleep(TOOL_DELAY)
            texts = nl_texts.get(city)
            if texts is None:
                return f"error: unknown city '{city}'"
            return texts["humidity_text"]

        def submit_answers(answers: str) -> str:
            return _call_judge("submit_answers", payload=answers)

        def submit_answer(
            q_index: int,
            city_a_temperature: float,
            city_a_humidity: float,
            city_b_temperature: float,
            city_b_humidity: float,
        ) -> str:
            return _call_judge(
                "submit_answer",
                q_index=q_index,
                city_a_temperature=city_a_temperature,
                city_a_humidity=city_a_humidity,
                city_b_temperature=city_b_temperature,
                city_b_humidity=city_b_humidity,
            )

        env = SimpleNamespace()
        env.get_questions = get_questions
        env.get_weather = get_weather
        env.get_humidity = get_humidity
        env.submit_answer = submit_answer
        env.submit_answers = submit_answers
        return env


def get_adapter(preset_name: str = "parallel_weather") -> UserAdapter:
    if preset_name != "parallel_weather":
        raise RuntimeError(
            f"unsupported adapter preset for parallel_weather: {preset_name}"
        )
    return ParallelWeatherAdapter()

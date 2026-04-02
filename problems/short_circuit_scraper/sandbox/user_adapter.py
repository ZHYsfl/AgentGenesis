"""Short-Circuit Scraper user adapter.

get_user / submit / cascade_check go through the judge queue.
get_info runs LOCALLY with an interruptible sleep (threading.Event),
simulating a scraper agent dispatched to an endpoint.
cancel() sets the event, waking all sleeping get_info threads.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from types import SimpleNamespace
from typing import Any, Optional

from agent_genesis.runtime.user_adapter import UserAdapter

VALID_DELAY = float(os.environ.get("VALID_DELAY", "10.0"))
INVALID_DELAY = float(os.environ.get("INVALID_DELAY", "25.0"))
SUBMIT_BLOCK_DELAY = float(os.environ.get("SUBMIT_BLOCK_DELAY", "25.0"))


class ShortCircuitScraperAdapter(UserAdapter):

    def create_user_api(
        self,
        act_queue: "queue.Queue[Optional[dict[str, Any]]]",
        obs_queue: "queue.Queue[Optional[Any]]",
    ) -> Any:
        _valid_index: int = -1
        _profile_data: str = ""
        _error_template: str = ""
        _num_endpoints: int = 10

        _cancel_event = threading.Event()
        _lock = threading.Lock()
        _submitted = [False]
        _post_submit_completions = [0]

        def _call_judge(action_name: str, **kwargs: Any) -> str:
            payload = {"action": action_name, **kwargs}
            act_queue.put(payload)
            obs = obs_queue.get()
            if obs is None:
                raise StopIteration("environment closed")
            return str(obs)

        def get_user() -> str:
            raw = _call_judge("get_user")
            try:
                full = json.loads(raw)
                nonlocal _valid_index, _profile_data, _error_template, _num_endpoints
                _valid_index = int(full["valid_index"])
                _profile_data = full["profile_data"]
                _error_template = full.get("error_template", "Error: no data at endpoint {i} for '{user_name}'.")
                _num_endpoints = int(full.get("num_endpoints", 10))
                return full["user_name"]
            except (json.JSONDecodeError, KeyError):
                return raw

        def get_info(user_name: str, i: str) -> str:
            """Dispatch a scraper agent to endpoint i. Blocks for the appropriate delay."""
            i_int = int(i)
            delay = VALID_DELAY if i_int == _valid_index else INVALID_DELAY

            cancelled = _cancel_event.wait(delay)

            if cancelled:
                return f"Error: scraper agent for endpoint {i} was cancelled."

            with _lock:
                if _submitted[0]:
                    _post_submit_completions[0] += 1

            if i_int == _valid_index:
                return _profile_data
            return _error_template.format(i=i, user_name=user_name)

        def cancel() -> None:
            """Cascade-terminate all pending scraper agents."""
            _cancel_event.set()

        def submit(email: str, member_id: str) -> str:
            with _lock:
                _submitted[0] = True

            result = _call_judge(
                "submit",
                email=str(email),
                member_id=str(member_id),
            )

            if result.startswith("wrong"):
                return result

            time.sleep(SUBMIT_BLOCK_DELAY)

            with _lock:
                leaked = _post_submit_completions[0]

            cascade_result = _call_judge("cascade_check", leaked_count=leaked)
            if cascade_result.startswith("wrong"):
                return cascade_result
            return result

        env = SimpleNamespace()
        env.get_user = get_user
        env.get_info = get_info
        env.cancel = cancel
        env.submit = submit
        return env


def get_adapter(preset_name: str = "short_circuit_scraper") -> UserAdapter:
    if preset_name != "short_circuit_scraper":
        raise RuntimeError(
            f"unsupported adapter preset for short_circuit_scraper: {preset_name}"
        )
    return ShortCircuitScraperAdapter()

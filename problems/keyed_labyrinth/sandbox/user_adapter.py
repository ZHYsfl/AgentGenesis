from __future__ import annotations

from typing import Any, Optional
import queue

from agent_genesis.runtime.user_adapter import UserAdapter


class KeyedLabyrinthAdapter(UserAdapter):
    def create_user_api(
        self,
        act_queue: "queue.Queue[Optional[dict[str, Any]]]",
        obs_queue: "queue.Queue[Optional[Any]]",
    ) -> Any:
        def move(direction: str) -> str:
            act_queue.put({"direction": str(direction)})
            obs = obs_queue.get()
            if obs is None:
                raise StopIteration("environment closed")
            return obs

        return move


def get_adapter(preset_name: str = "keyed_labyrinth") -> UserAdapter:
    if preset_name != "keyed_labyrinth":
        raise RuntimeError(f"unsupported adapter preset for keyed_labyrinth problem: {preset_name}")
    return KeyedLabyrinthAdapter()

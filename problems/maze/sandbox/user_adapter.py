from __future__ import annotations

from typing import Any, Optional
import queue

from agent_genesis.runtime.user_adapter import UserAdapter


class MazeAdapter(UserAdapter):
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


def get_adapter(preset_name: str = "maze") -> UserAdapter:
    if preset_name != "maze":
        raise RuntimeError(f"unsupported adapter preset for maze problem: {preset_name}")
    return MazeAdapter()

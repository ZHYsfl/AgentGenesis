"""Werewolf per-sandbox adapter.

Each sandbox has exactly one agent.  The adapter reads ``AGENT_ID``
from the environment and builds an ``env`` namespace whose attributes
are synchronous blocking tool functions (same pattern as maze's
``move(direction)``).

Entry-point routing:
    AGENT_ID=wolf_1      -> solve_wolf_1(env)
    AGENT_ID=wolf_2      -> solve_wolf_2(env)
    AGENT_ID=witch        -> solve_witch(env)
    AGENT_ID=seer         -> solve_seer(env)
    AGENT_ID=villager_1   -> solve_villager_1(env)
    AGENT_ID=villager_2   -> solve_villager_2(env)
"""

from __future__ import annotations

import os
import queue
from types import SimpleNamespace
from typing import Any, Optional

from agent_genesis.runtime.user_adapter import UserAdapter


class IsolatedWerewolfAdapter(UserAdapter):

    def create_user_api(
        self,
        act_queue: "queue.Queue[Optional[dict[str, Any]]]",
        obs_queue: "queue.Queue[Optional[Any]]",
    ) -> Any:
        agent_id = os.environ.get("AGENT_ID", "unknown")

        def _call(action_name: str, **kwargs: Any) -> str:
            payload = {"action": action_name, **kwargs}
            act_queue.put(payload)
            obs = obs_queue.get()
            if obs is None:
                raise StopIteration("game ended")
            return str(obs)

        env = SimpleNamespace(player_id=agent_id)

        if agent_id.startswith("wolf"):
            env.kill = lambda target: _call("kill", target=str(target))
            env.speak = lambda text: _call("speak", text=str(text))
            env.vote = lambda target: _call("vote", target=str(target))
            env.connection = lambda: _call("connection")

        elif agent_id == "witch":
            env.save = lambda: _call("save")
            env.poison = lambda target: _call("poison", target=str(target))
            env.speak = lambda text: _call("speak", text=str(text))
            env.vote = lambda target: _call("vote", target=str(target))
            env.connection = lambda: _call("connection")

        elif agent_id == "seer":
            env.check = lambda target: _call("check", target=str(target))
            env.speak = lambda text: _call("speak", text=str(text))
            env.vote = lambda target: _call("vote", target=str(target))
            env.connection = lambda: _call("connection")

        else:
            env.speak = lambda text: _call("speak", text=str(text))
            env.vote = lambda target: _call("vote", target=str(target))
            env.connection = lambda: _call("connection")

        return env


def get_adapter(preset_name: str = "isolated_werewolf") -> UserAdapter:
    if preset_name != "isolated_werewolf":
        raise RuntimeError(
            f"unsupported adapter preset for werewolf: {preset_name}"
        )
    return IsolatedWerewolfAdapter()

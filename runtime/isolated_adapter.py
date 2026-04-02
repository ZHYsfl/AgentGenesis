"""Base adapter for isolated multi-agent sandboxes.

Each sandbox has exactly one agent.  The adapter reads ``AGENT_ID``
from the environment, builds a namespace object with blocking tool
functions (same pattern as MazeAdapter's ``move``), and calls the
corresponding ``solve_<agent_id>(env)`` entry point.

Concrete problem adapters (e.g. WerewolfAdapter) inherit from
``IsolatedAgentAdapter`` and override ``_build_tool_functions`` to
provide role-specific tools.
"""

from __future__ import annotations

import os
import queue
from abc import abstractmethod
from types import SimpleNamespace
from typing import Any, Optional

from .user_adapter import UserAdapter


class IsolatedAgentAdapter(UserAdapter):
    """Base class for per-sandbox adapters in isolated multi-agent mode."""

    def create_user_api(
        self,
        act_queue: "queue.Queue[Optional[dict[str, Any]]]",
        obs_queue: "queue.Queue[Optional[Any]]",
    ) -> Any:
        agent_id = os.environ.get("AGENT_ID", "unknown")

        def _call_tool(action_name: str, **kwargs: Any) -> str:
            payload = {"action": action_name, **kwargs}
            act_queue.put(payload)
            obs = obs_queue.get()
            if obs is None:
                raise StopIteration("game ended")
            return str(obs)

        env = self._build_env(agent_id, _call_tool)
        return env

    @abstractmethod
    def _build_env(
        self,
        agent_id: str,
        call_tool: Any,
    ) -> Any:
        """Return the env namespace for the given agent_id.

        ``call_tool(action_name, **kwargs) -> str`` is a blocking helper
        that serializes one action through the bridge and returns the
        observation string.

        The returned object should have attributes that are callable
        functions (e.g. ``env.save()``, ``env.check(target)``).
        """
        ...

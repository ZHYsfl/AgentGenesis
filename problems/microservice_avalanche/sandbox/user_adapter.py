"""
Microservice Avalanche - User Adapter

Exposes API for 3 agents:
- order: Transaction Coordinator (TC)
- inventory: Resource Manager (RM)
- payment: Resource Manager (RM)
"""

from __future__ import annotations

import queue
from types import SimpleNamespace
from typing import Any, Optional

from agent_genesis.runtime.user_adapter import UserAdapter


class MicroserviceAdapter(UserAdapter):
    """
    Adapter for Microservice Avalanche V3 protocol.

    Each agent runs in an isolated sandbox and can:
    1. Send RPC messages to other agents
    2. Prepare/Commit/Rollback transactions
    3. Wait via connection()
    """

    def create_user_api(
        self,
        act_queue: "queue.Queue[Optional[dict[str, Any]]]",
        obs_queue: "queue.Queue[Optional[Any]]",
    ) -> Any:
        """
        Create the user-facing API object.

        Returns a SimpleNamespace with methods:
        - send_rpc(target, payload)
        - prepare_tx(tx_id)
        - commit_tx(tx_id)
        - rollback_tx(tx_id)
        - connection()
        """

        def _call(action_type: str, **kwargs: Any) -> Any:
            """Send action to judge and wait for observation."""
            payload = {"type": action_type, **kwargs}
            act_queue.put(payload)
            obs = obs_queue.get()
            if obs is None:
                raise StopIteration("environment closed")
            return obs

        # Create API namespace
        env = SimpleNamespace()

        # RPC Communication
        env.send_rpc = lambda target, payload: _call(
            "send_rpc",
            target=target,
            payload=payload
        )

        # Transaction operations
        env.prepare_tx = lambda tx_id: _call(
            "prepare_tx",
            tx_id=tx_id
        )

        env.commit_tx = lambda tx_id: _call(
            "commit_tx",
            tx_id=tx_id
        )

        env.rollback_tx = lambda tx_id: _call(
            "rollback_tx",
            tx_id=tx_id
        )

        # Frame sync / connection
        env.connection = lambda: _call("connection")

        return env


def get_adapter(preset_name: str = "microservice_avalanche") -> UserAdapter:
    """Factory function for adapter."""
    if preset_name != "microservice_avalanche":
        raise RuntimeError(f"Unsupported adapter preset: {preset_name}")
    return MicroserviceAdapter()

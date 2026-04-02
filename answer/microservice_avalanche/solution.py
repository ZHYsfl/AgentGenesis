"""
Microservice Avalanche - Reference Solution

Implements Two-Phase Commit (2PC) protocol with chaos handling.
"""

from __future__ import annotations


def solve_order(env):
    """
    Order Service - Transaction Coordinator (TC)
    Implements 2PC with timeout and chaos handling.
    """
    # Initial connection to get transactions
    obs = env.connection()
    transactions = obs.get("transactions", [])

    for tx in transactions:
        tx_id = tx["tx_id"]

        # Phase 1: Send prepare to both RMs
        env.send_rpc("inventory", {"action": "prepare", "tx_id": tx_id})
        env.send_rpc("payment", {"action": "prepare", "tx_id": tx_id})

        # Wait for responses (up to 3 rounds timeout)
        responses = {"inventory": None, "payment": None}
        rounds_waited = 0

        while rounds_waited < 3:
            obs = env.connection()
            msgs = obs.get("rpc_messages", [])

            for msg in msgs:
                if msg.get("payload", {}).get("action") == "prepared":
                    sender = msg.get("sender")
                    payload = msg.get("payload", {})
                    if payload.get("tx_id") == tx_id:
                        responses[sender] = payload.get("status")

            # Check if we got all responses
            if all(responses.values()):
                break

            rounds_waited += 1

        # Phase 2: Decide commit or rollback
        all_prepared = all(
            status == "ok" for status in responses.values() if status is not None
        )

        if all_prepared and None not in responses.values():
            # All prepared successfully - commit
            env.send_rpc("inventory", {"action": "commit", "tx_id": tx_id})
            env.send_rpc("payment", {"action": "commit", "tx_id": tx_id})
        else:
            # Any failure or timeout - rollback (compensate)
            env.send_rpc("inventory", {"action": "rollback", "tx_id": tx_id})
            env.send_rpc("payment", {"action": "rollback", "tx_id": tx_id})

    # Wait for all to complete
    while True:
        obs = env.connection()
        # Check if environment is done
        if obs.get("done", False):
            break


def solve_inventory(env):
    """Inventory Service - Resource Manager (RM)"""
    while True:
        obs = env.connection()

        # Process RPC messages
        msgs = obs.get("rpc_messages", [])
        for msg in msgs:
            payload = msg.get("payload", {})
            action = payload.get("action")
            tx_id = payload.get("tx_id")

            if action == "prepare":
                # Attempt to prepare
                result = env.prepare_tx(tx_id)
                status = result.get("status", "failed")

                # Send response back to order
                env.send_rpc("order", {
                    "action": "prepared",
                    "tx_id": tx_id,
                    "status": status
                })

            elif action == "commit":
                env.commit_tx(tx_id)

            elif action == "rollback":
                env.rollback_tx(tx_id)


def solve_payment(env):
    """Payment Service - Resource Manager (RM)"""
    # Same logic as inventory
    solve_inventory(env)

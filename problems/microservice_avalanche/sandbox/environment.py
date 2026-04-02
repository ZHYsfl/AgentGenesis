"""
Microservice Avalanche - Distributed Transaction Environment

Core Features:
1. 2PC State Machine Validation (INIT -> PREPARED -> COMMITTED/ROLLED_BACK)
2. Chaos Engine (20% resource failure, 10% network delay/packet loss)
3. Message Routing Inbox with Network Simulation
4. Strict Consistency Checking
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class TXState(Enum):
    INIT = auto()
    PREPARING = auto()
    PREPARED = auto()
    COMMITTED = auto()
    ROLLED_BACK = auto()


class ChaosType(Enum):
    NONE = auto()
    RESOURCE_FAILURE = auto()  # prepare_tx fails
    NETWORK_DELAY = auto()     # message delayed
    PACKET_LOSS = auto()       # message lost


@dataclass
class Transaction:
    tx_id: str
    item: str
    quantity: int
    price: float
    states: dict[str, TXState] = field(default_factory=dict)
    # Track state at each agent


@dataclass
class Message:
    sender: str
    target: str
    payload: dict
    deliver_round: int  # When to deliver (for network delay simulation)
    msg_id: str


class MicroserviceEnvironment:
    """
    Chaos-enabled distributed transaction environment.

    Physics:
    - 3 Agents: order, inventory, payment
    - 10 Transactions to process
    - 20% probability: resource failure on prepare
    - 10% probability: network delay or packet loss
    """

    # Chaos configuration
    RESOURCE_FAILURE_RATE = 0.20  # 20% prepare fails
    NETWORK_DELAY_RATE = 0.10     # 10% messages affected
    NETWORK_DELAY_MIN = 1         # Min delay rounds
    NETWORK_DELAY_MAX = 3         # Max delay rounds
    PACKET_LOSS_RATE = 0.30       # Of delayed, 30% are lost

    def __init__(self, case_data: dict, seed: int | None = None):
        if seed is not None:
            random.seed(seed)

        self.transactions: dict[str, Transaction] = {}
        self.current_round = 0
        self.step_count = 0
        self._start_time: float | None = None
        self._completed = False
        self._error_reason: str | None = None

        # Message routing system
        self.inboxes: dict[str, list[Message]] = {
            "order": [],
            "inventory": [],
            "payment": []
        }
        self.delayed_messages: list[Message] = []  # Messages in transit

        # Database state for consistency checking
        self.db_state: dict[str, dict] = {
            "order": {},      # tx_id -> state
            "inventory": {},  # tx_id -> state
            "payment": {}     # tx_id -> state
        }

        # Resource locks
        self.locks: dict[str, set[str]] = {  # agent -> set of locked tx_ids
            "inventory": set(),
            "payment": set()
        }

        # Initialize transactions
        self._init_transactions(case_data.get("transactions", []))

    def _init_transactions(self, tx_list: list[dict]):
        """Initialize transaction state machines."""
        for tx_data in tx_list:
            tx = Transaction(
                tx_id=tx_data["tx_id"],
                item=tx_data["item"],
                quantity=tx_data["quantity"],
                price=tx_data["price"]
            )
            # All agents start at INIT
            for agent in ["order", "inventory", "payment"]:
                tx.states[agent] = TXState.INIT
                self.db_state[agent][tx.tx_id] = TXState.INIT
            self.transactions[tx.tx_id] = tx

    def get_problem(self, agent_id: str) -> dict:
        """Return initial observation for an agent."""
        if self._start_time is None:
            self._start_time = time.time()

        return {
            "agent_id": agent_id,
            "transactions": [
                {
                    "tx_id": tx.tx_id,
                    "item": tx.item,
                    "quantity": tx.quantity,
                    "price": tx.price
                }
                for tx in self.transactions.values()
            ],
            "rpc_messages": [],  # No messages initially
            "db_state": self._get_agent_db_state(agent_id)
        }

    def _get_agent_db_state(self, agent_id: str) -> dict:
        """Get database state visible to an agent."""
        return {
            tx_id: state.value
            for tx_id, state in self.db_state[agent_id].items()
        }

    def apply_actions(self, actions: dict[str, dict]) -> dict[str, Any]:
        """
        Process actions from all agents.

        Actions:
        - send_rpc: Route message with chaos
        - prepare_tx: Attempt to lock resources (with 20% failure)
        - commit_tx: Commit transaction (state machine check)
        - rollback_tx: Rollback transaction (state machine check)
        - connection: No-op, just sync
        """
        self.current_round += 1
        self.step_count += 1

        results = {}

        # Phase 1: Process actions
        for agent_id, action in actions.items():
            if not isinstance(action, dict):
                results[agent_id] = {"error": "Invalid action format"}
                continue

            action_type = action.get("type", "")
            result = self._handle_action(agent_id, action_type, action)
            results[agent_id] = result

        # Phase 2: Deliver delayed messages
        self._deliver_messages()

        # Phase 3: Check for completion
        self._check_completion()

        # Phase 4: Build observations
        observations = self._build_observations(results)

        return {
            "observations": observations,
            "results": results,
            "round": self.current_round
        }

    def _handle_action(self, agent_id: str, action_type: str, action: dict) -> dict:
        """Handle a single agent action."""
        if action_type == "connection":
            return {"status": "ok", "action": "connection"}

        elif action_type == "send_rpc":
            return self._handle_send_rpc(agent_id, action)

        elif action_type == "prepare_tx":
            return self._handle_prepare_tx(agent_id, action)

        elif action_type == "commit_tx":
            return self._handle_commit_tx(agent_id, action)

        elif action_type == "rollback_tx":
            return self._handle_rollback_tx(agent_id, action)

        else:
            return {"error": f"Unknown action: {action_type}"}

    def _handle_send_rpc(self, sender: str, action: dict) -> dict:
        """Send RPC message with network chaos simulation."""
        target = action.get("target", "")
        payload = action.get("payload", {})

        if target not in self.inboxes:
            return {"error": f"Invalid target: {target}"}

        msg_id = f"msg_{self.current_round}_{random.randint(1000, 9999)}"

        # Apply network chaos
        chaos_roll = random.random()

        if chaos_roll < self.NETWORK_DELAY_RATE:
            # Network delay or packet loss
            if random.random() < self.PACKET_LOSS_RATE:
                # Packet loss - message never delivered
                return {
                    "status": "sent",
                    "msg_id": msg_id,
                    "note": "network_unstable"
                }
            else:
                # Delayed delivery
                delay = random.randint(self.NETWORK_DELAY_MIN, self.NETWORK_DELAY_MAX)
                msg = Message(
                    sender=sender,
                    target=target,
                    payload=payload,
                    deliver_round=self.current_round + delay,
                    msg_id=msg_id
                )
                self.delayed_messages.append(msg)
                return {
                    "status": "sent",
                    "msg_id": msg_id,
                    "delay": delay
                }
        else:
            # Normal delivery - immediate
            msg = Message(
                sender=sender,
                target=target,
                payload=payload,
                deliver_round=self.current_round,
                msg_id=msg_id
            )
            self.inboxes[target].append(msg)
            return {
                "status": "sent",
                "msg_id": msg_id,
                "delivered": True
            }

    def _handle_prepare_tx(self, agent_id: str, action: dict) -> dict:
        """
        Prepare transaction - attempt to lock resources.
        20% probability of resource failure (chaos).
        """
        tx_id = action.get("tx_id", "")

        if tx_id not in self.transactions:
            return {"error": f"Unknown transaction: {tx_id}"}

        tx = self.transactions[tx_id]

        # State machine check: must be in INIT
        if tx.states[agent_id] != TXState.INIT:
            return {
                "error": f"Invalid state transition: {tx.states[agent_id].name} -> PREPARED",
                "current_state": tx.states[agent_id].name
            }

        # Chaos: Resource failure simulation
        if random.random() < self.RESOURCE_FAILURE_RATE:
            failure_reason = random.choice([
                "out_of_stock",
                "insufficient_balance",
                "resource_locked"
            ])
            return {
                "status": "failed",
                "reason": failure_reason,
                "tx_id": tx_id
            }

        # Success: Lock resource and transition state
        tx.states[agent_id] = TXState.PREPARED
        self.db_state[agent_id][tx_id] = TXState.PREPARED
        self.locks[agent_id].add(tx_id)

        return {
            "status": "ok",
            "tx_id": tx_id,
            "state": "PREPARED"
        }

    def _handle_commit_tx(self, agent_id: str, action: dict) -> dict:
        """
        Commit transaction - strict state machine check.
        Must be in PREPARED state first!
        """
        tx_id = action.get("tx_id", "")

        if tx_id not in self.transactions:
            return {"error": f"Unknown transaction: {tx_id}"}

        tx = self.transactions[tx_id]
        current_state = tx.states[agent_id]

        # STRICT: Must be PREPARED before COMMIT
        if current_state != TXState.PREPARED:
            self._error_reason = f"Illegal commit: {agent_id} tried to commit {tx_id} from state {current_state.name}"
            return {
                "error": f"Cannot commit from state: {current_state.name}",
                "required": "PREPARED",
                "current": current_state.name,
                "tx_id": tx_id
            }

        # Success: Commit
        tx.states[agent_id] = TXState.COMMITTED
        self.db_state[agent_id][tx_id] = TXState.COMMITTED
        self.locks[agent_id].discard(tx_id)

        return {
            "status": "ok",
            "tx_id": tx_id,
            "state": "COMMITTED"
        }

    def _handle_rollback_tx(self, agent_id: str, action: dict) -> dict:
        """
        Rollback transaction.
        Can rollback from PREPARED or INIT.
        """
        tx_id = action.get("tx_id", "")

        if tx_id not in self.transactions:
            return {"error": f"Unknown transaction: {tx_id}"}

        tx = self.transactions[tx_id]
        current_state = tx.states[agent_id]

        # Can rollback from INIT or PREPARED
        if current_state not in [TXState.INIT, TXState.PREPARED, TXState.PREPARING]:
            return {
                "error": f"Cannot rollback from state: {current_state.name}",
                "tx_id": tx_id
            }

        # Success: Rollback
        tx.states[agent_id] = TXState.ROLLED_BACK
        self.db_state[agent_id][tx_id] = TXState.ROLLED_BACK
        self.locks[agent_id].discard(tx_id)

        return {
            "status": "ok",
            "tx_id": tx_id,
            "state": "ROLLED_BACK"
        }

    def _deliver_messages(self):
        """Deliver delayed messages that are scheduled for this round."""
        delivered = []
        remaining = []

        for msg in self.delayed_messages:
            if msg.deliver_round <= self.current_round:
                # Deliver message
                self.inboxes[msg.target].append(msg)
                delivered.append(msg)
            else:
                remaining.append(msg)

        self.delayed_messages = remaining

    def _check_completion(self):
        """Check if all transactions are finalized."""
        all_done = True

        for tx in self.transactions.values():
            tx_done = True
            for agent in ["order", "inventory", "payment"]:
                state = tx.states[agent]
                if state not in [TXState.COMMITTED, TXState.ROLLED_BACK]:
                    tx_done = False
                    break
            if not tx_done:
                all_done = False
                break

        if all_done:
            self._completed = True

    def _build_observations(self, action_results: dict) -> dict[str, dict]:
        """Build observation for each agent."""
        observations = {}

        for agent_id in ["order", "inventory", "payment"]:
            # Get messages from inbox
            messages = self.inboxes[agent_id]
            self.inboxes[agent_id] = []  # Clear after reading

            observations[agent_id] = {
                "agent_id": agent_id,
                "round": self.current_round,
                "rpc_messages": [
                    {
                        "sender": msg.sender,
                        "payload": msg.payload,
                        "msg_id": msg.msg_id
                    }
                    for msg in messages
                ],
                "action_result": action_results.get(agent_id, {}),
                "db_state": self._get_agent_db_state(agent_id)
            }

        return observations

    def check_consistency(self) -> tuple[bool, str]:
        """
        Check if database is in consistent state.

        Consistency rules:
        1. No transaction should be COMMITTED in one agent and ROLLED_BACK in another
        2. All transactions should reach final state
        3. Resource locks should be released for finalized transactions
        """
        for tx in self.transactions.values():
            states = list(tx.states.values())

            # Check for partial commit (the ultimate sin)
            has_committed = TXState.COMMITTED in states
            has_rolled_back = TXState.ROLLED_BACK in states

            if has_committed and has_rolled_back:
                committed_agents = [a for a, s in tx.states.items() if s == TXState.COMMITTED]
                rolled_agents = [a for a, s in tx.states.items() if s == TXState.ROLLED_BACK]
                return False, f"PARTIAL COMMIT: {tx.tx_id} committed in {committed_agents} but rolled back in {rolled_agents}"

            # Check for stuck transactions
            if not all(s in [TXState.COMMITTED, TXState.ROLLED_BACK] for s in states):
                unfinished = [a for a, s in tx.states.items() if s not in [TXState.COMMITTED, TXState.ROLLED_BACK]]
                return False, f"UNFINISHED: {tx.tx_id} still pending in {unfinished}"

        return True, "Consistent"

    @property
    def done(self) -> bool:
        """Check if environment is done."""
        return self._completed or self._error_reason is not None

    @property
    def success(self) -> bool:
        """Check if all transactions were processed successfully."""
        if self._error_reason:
            return False
        consistent, _ = self.check_consistency()
        return consistent and self._completed

    def compute_score(self) -> int:
        """
        Compute score based on consistency.

        100: All transactions consistent and complete
        0: Any inconsistency detected
        """
        if self._error_reason:
            return 0

        consistent, reason = self.check_consistency()
        if not consistent:
            return 0

        if self._completed:
            return 100

        # Partial completion - could add partial scoring here
        return 0

    def build_output_data(self) -> dict:
        """Build final output data."""
        consistent, reason = self.check_consistency()

        return {
            "transactions_processed": len(self.transactions),
            "rounds": self.current_round,
            "consistent": consistent,
            "consistency_reason": reason,
            "error": self._error_reason,
            "final_db_state": {
                agent: {
                    tx_id: state.value
                    for tx_id, state in states.items()
                }
                for agent, states in self.db_state.items()
            }
        }

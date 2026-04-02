"""User-side gRPC bridge runtime for action/observation exchange."""

from __future__ import annotations

import contextlib
from concurrent import futures
from importlib import import_module
import json
import os
import queue
import sys
import threading
import traceback
from typing import Any, Optional

import grpc

from .user_adapter import AdapterConfig, get_adapter, load_user_entry


def _load_bridge_modules() -> tuple[Any, Any]:
    try:
        return (
            import_module("eval_bridge_pb2"),
            import_module("eval_bridge_pb2_grpc"),
        )
    except ImportError:
        return (
            import_module("agent_genesis.proto.eval_bridge_pb2"),
            import_module("agent_genesis.proto.eval_bridge_pb2_grpc"),
        )


eval_bridge_pb2, eval_bridge_pb2_grpc = _load_bridge_modules()


def bridge_main(
    inbound_queue: "queue.Queue[Optional[dict[str, Any]]]",
    outbound_queue: "queue.Queue[dict[str, Any]]",
    *,
    solve_attr_name: str = "solve",
    adapter_preset: str = "default",
    agent_id: str = "",
) -> None:
    obs_queue: queue.Queue[Optional[Any]] = queue.Queue()
    act_queue: queue.Queue[Optional[dict[str, Any]]] = queue.Queue()
    error_info: list[Optional[str]] = [None, None]

    adapter = get_adapter(adapter_preset)
    config = AdapterConfig(solve_attr_name=solve_attr_name, agent_id=agent_id)
    user_api = adapter.create_user_api(act_queue, obs_queue)

    def _user_thread() -> None:
        try:
            entry = load_user_entry(config)
            with contextlib.redirect_stdout(sys.stderr):
                entry(user_api)
        except StopIteration:
            pass
        except Exception as exc:
            error_info[0] = f"{type(exc).__name__}: {exc}"
            error_info[1] = traceback.format_exc()
        finally:
            act_queue.put(None)

    threading.Thread(target=_user_thread, daemon=True).start()

    def _emit_action_from_queue() -> bool:
        action_data = act_queue.get()
        if action_data is None:
            if error_info[0]:
                resp: dict[str, Any] = {
                    "type": "action",
                    "error": error_info[0],
                    "status": "error",
                    "traceback": error_info[1],
                }
            else:
                resp = {"type": "action", "data": None}
            outbound_queue.put(resp)
            return False

        resp = {"type": "action", "data": action_data}
        outbound_queue.put(resp)
        return True

    while True:
        msg = inbound_queue.get()
        if msg is None:
            break
        msg_type = msg.get("type")
        if msg_type not in ("observation", "action_request"):
            continue

        if msg_type == "observation":
            raw = msg.get("data", "")
            obs_queue.put(raw)
            continue

        if not _emit_action_from_queue():
            break

    obs_queue.put(None)


class UserBridgeServicer(eval_bridge_pb2_grpc.SandboxBridgeServicer):
    def __init__(
        self,
        *,
        solve_attr_name: str = "solve",
        adapter_preset: str = "default",
        agent_id: str = "",
    ) -> None:
        self._inbound_queue: "queue.Queue[Optional[dict[str, Any]]]" = queue.Queue()
        self._outbound_queue: "queue.Queue[dict[str, Any]]" = queue.Queue()
        self._agent_id = agent_id
        self._bridge_thread = threading.Thread(
            target=bridge_main,
            args=(self._inbound_queue, self._outbound_queue),
            kwargs={
                "solve_attr_name": solve_attr_name,
                "adapter_preset": adapter_preset,
                "agent_id": agent_id,
            },
            daemon=True,
        )
        self._bridge_thread.start()

    def CheckReady(self, request, context):
        _ = (request, context)
        return eval_bridge_pb2.ReadyStatus(
            is_ready=True,
            message="user bridge ready",
        )

    def SendMessage(self, request, context):
        _ = context
        raw = request.json_message or ""
        if not raw:
            return eval_bridge_pb2.SendAck(ok=False, error="empty message")
        try:
            msg = json.loads(raw)
        except Exception as exc:
            return eval_bridge_pb2.SendAck(ok=False, error=f"invalid json: {exc}")
        if not isinstance(msg, dict):
            return eval_bridge_pb2.SendAck(ok=False, error="message must be json object")
        self._inbound_queue.put(msg)
        return eval_bridge_pb2.SendAck(ok=True, error="")

    def RecvMessage(self, request, context):
        _ = context
        timeout_ms = int(getattr(request, "timeout_ms", 0) or 0)
        if timeout_ms <= 0:
            msg = self._outbound_queue.get()
        else:
            try:
                msg = self._outbound_queue.get(timeout=timeout_ms / 1000.0)
            except queue.Empty:
                return eval_bridge_pb2.RecvResponse(
                    has_message=False,
                    json_message="",
                )
        return eval_bridge_pb2.RecvResponse(
            has_message=True,
            json_message=json.dumps(msg, ensure_ascii=False),
        )


def serve_user_runtime(
    *,
    solve_attr_name: str = "solve",
    adapter_preset: str = "default",
) -> None:
    """Start gRPC server for user bridge (single agent mode - v1)."""
    grpc_port = int(os.getenv("SANDBOX_GRPC_PORT", os.getenv("USER_GRPC_PORT", "50052")))

    servicer = UserBridgeServicer(
        solve_attr_name=solve_attr_name,
        adapter_preset=adapter_preset,
    )
    _MAX_MSG = 50 * 1024 * 1024
    grpc_server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=8),
        options=[
            ("grpc.max_receive_message_length", _MAX_MSG),
            ("grpc.max_send_message_length", _MAX_MSG),
        ],
    )
    eval_bridge_pb2_grpc.add_SandboxBridgeServicer_to_server(servicer, grpc_server)
    grpc_server.add_insecure_port(f"[::]:{grpc_port}")
    print(f"[user_bridge] grpc listening on {grpc_port}", file=sys.stderr, flush=True)
    grpc_server.start()

    grpc_server.wait_for_termination()


def serve_shared_user_runtime(
    *,
    agent_ids: list[str],
    solve_attr_names: dict[str, str],
    adapter_preset: str = "shared_multi_agent",
    base_port: int = 50052,
) -> None:
    """Start gRPC servers for shared multi-agent mode (v2).

    Each agent runs in the same container but connects via separate gRPC ports.

    Args:
        agent_ids: List of agent IDs (e.g., ["agent_1", "agent_2"])
        solve_attr_names: Dict mapping agent_id to solve function name
                         (e.g., {"agent_1": "solve_agent_1", "agent_2": "solve_agent_2"})
        adapter_preset: Adapter preset to use
        base_port: Base port number, each agent gets base_port + index
    """
    _MAX_MSG = 50 * 1024 * 1024

    # Start a gRPC server for each agent
    servers = []

    for idx, agent_id in enumerate(agent_ids):
        grpc_port = base_port + idx

        solve_attr_name = solve_attr_names.get(agent_id, f"solve_{agent_id}")

        servicer = UserBridgeServicer(
            solve_attr_name=solve_attr_name,
            adapter_preset=adapter_preset,
            agent_id=agent_id,
        )

        grpc_server = grpc.server(
            futures.ThreadPoolExecutor(max_workers=8),
            options=[
                ("grpc.max_receive_message_length", _MAX_MSG),
                ("grpc.max_send_message_length", _MAX_MSG),
            ],
        )
        eval_bridge_pb2_grpc.add_SandboxBridgeServicer_to_server(servicer, grpc_server)
        grpc_server.add_insecure_port(f"[::]:{grpc_port}")
        print(f"[user_bridge/{agent_id}] grpc listening on {grpc_port}", file=sys.stderr, flush=True)
        grpc_server.start()
        servers.append(grpc_server)

    print(f"[user_bridge] started {len(agent_ids)} agent bridges", file=sys.stderr, flush=True)

    # Wait for all servers
    for server in servers:
        server.wait_for_termination()

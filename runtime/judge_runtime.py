"""Judge-side gRPC bridge runtime implementation."""

from __future__ import annotations

from concurrent import futures
from importlib import import_module
import json
import os
import queue
import sys
import threading
from typing import Any, Callable, Optional

import grpc


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


class JudgeRuntime:
    def __init__(self) -> None:
        self._inbound_queue: "queue.Queue[Optional[dict[str, Any]]]" = queue.Queue()
        self._outbound_queue: "queue.Queue[dict[str, Any]]" = queue.Queue()

    def send(self, msg: dict[str, Any]) -> None:
        self._outbound_queue.put(dict(msg))

    def recv(self) -> Optional[dict[str, Any]]:
        msg = self._inbound_queue.get()
        if msg is None:
            return None
        if not isinstance(msg, dict):
            return None
        return msg

    def request_next_case_index(self) -> Optional[int]:
        self.send({"type": "case_request"})
        reply = self.recv()
        if not reply:
            return None
        msg_type = str(reply.get("type", ""))
        if msg_type == "case_stop":
            return None
        if msg_type != "case_assign":
            raise RuntimeError(f"unexpected scheduler msg type: {msg_type}")
        return int(reply.get("case_index", -1))

    @staticmethod
    def with_history_events(msg: dict[str, Any], event_or_events: dict | list[dict]) -> dict[str, Any]:
        out = dict(msg)
        out["history_events"] = event_or_events
        return out

    class _BridgeServicer(eval_bridge_pb2_grpc.SandboxBridgeServicer):
        def __init__(self, runtime: "JudgeRuntime") -> None:
            self._runtime = runtime

        def CheckReady(self, request, context):
            _ = (request, context)
            return eval_bridge_pb2.ReadyStatus(
                is_ready=True,
                message="judge bridge ready",
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
            self._runtime._inbound_queue.put(msg)
            return eval_bridge_pb2.SendAck(ok=True, error="")

        def RecvMessage(self, request, context):
            _ = context
            timeout_ms = int(getattr(request, "timeout_ms", 0) or 0)
            if timeout_ms <= 0:
                msg = self._runtime._outbound_queue.get()
            else:
                try:
                    msg = self._runtime._outbound_queue.get(timeout=timeout_ms / 1000.0)
                except queue.Empty:
                    return eval_bridge_pb2.RecvResponse(
                        has_message=False,
                        json_message="",
                    )
            return eval_bridge_pb2.RecvResponse(
                has_message=True,
                json_message=json.dumps(msg, ensure_ascii=False),
            )


def serve_judge_runtime(main_fn: Callable[[JudgeRuntime], None]) -> None:
    """Start gRPC server for judge bridge, then run *main_fn*."""
    runtime = JudgeRuntime()
    grpc_port = int(os.getenv("SANDBOX_GRPC_PORT", os.getenv("JUDGE_GRPC_PORT", "50051")))

    _MAX_MSG = 50 * 1024 * 1024
    grpc_server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=8),
        options=[
            ("grpc.max_receive_message_length", _MAX_MSG),
            ("grpc.max_send_message_length", _MAX_MSG),
        ],
    )
    eval_bridge_pb2_grpc.add_SandboxBridgeServicer_to_server(
        JudgeRuntime._BridgeServicer(runtime),
        grpc_server,
    )
    grpc_server.add_insecure_port(f"[::]:{grpc_port}")
    print(f"[judge_bridge] grpc listening on {grpc_port}", file=sys.stderr, flush=True)
    grpc_server.start()

    def _run_main() -> None:
        try:
            main_fn(runtime)
        except Exception as exc:
            runtime.send({"type": "error", "error": str(exc)})

    threading.Thread(target=_run_main, daemon=True).start()
    grpc_server.wait_for_termination()

"""gRPC transport between worker and sandbox bridge."""

from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Optional

import grpc

from .proto import eval_bridge_pb2, eval_bridge_pb2_grpc

logger: logging.Logger = logging.getLogger(__name__)


class SandboxTransportError(RuntimeError):
    """Transport-level failure between worker and sandbox bridge."""


class SandboxTransportConnectionError(SandboxTransportError):
    """Connection failure to sandbox bridge."""


class SandboxTransport(ABC):
    @abstractmethod
    def wait_for_ready(self, timeout: int) -> bool:
        raise NotImplementedError

    @abstractmethod
    def send_message(self, msg: dict[str, Any], timeout: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def recv_message(self, timeout: int) -> Optional[str]:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError


def resolve_grpc_target(host_or_target: str) -> str:
    """Parse a host string into a gRPC target (always insecure for Docker)."""
    raw = str(host_or_target or "").strip()
    if not raw:
        raise ValueError("empty grpc host/target")

    for prefix in ("https://", "http://"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
            break

    if "/" in raw:
        raw = raw.split("/", 1)[0]

    if ":" not in raw:
        raw = f"{raw}:50051"

    return raw


class GrpcSandboxTransport(SandboxTransport):
    _SERVICE_CANDIDATES: tuple[str, ...] = (
        "agent_genesis.evaluation.SandboxBridge",
        "evaluation.SandboxBridge",
        "SandboxBridge",
    )

    def __init__(
        self,
        host_or_target: str,
        *,
        options: Optional[list[tuple[str, int]]] = None,
    ) -> None:
        self.target = resolve_grpc_target(host_or_target)

        # Disable keepalive ping to avoid triggering "Too many pings" server limit
        # INT_MAX ms (~24 days) effectively disables keepalive
        channel_options = options or [
            ("grpc.max_receive_message_length", 50 * 1024 * 1024),
            ("grpc.max_send_message_length", 50 * 1024 * 1024),
            ("grpc.keepalive_time_ms", 2_147_483_647),
        ]

        self._channel = grpc.insecure_channel(self.target, options=channel_options)
        self._stub = eval_bridge_pb2_grpc.SandboxBridgeStub(self._channel)
        self._active_service = self._SERVICE_CANDIDATES[0]
        self._bind_rpc_methods(self._active_service)

    def _bind_rpc_methods(self, service_name: str) -> None:
        self._active_service = service_name
        if not hasattr(self._channel, "unary_unary"):
            self._check_ready_rpc = self._stub.CheckReady
            self._send_message_rpc = self._stub.SendMessage
            self._recv_message_rpc = self._stub.RecvMessage
            return
        base = f"/{service_name}"
        self._check_ready_rpc = self._channel.unary_unary(
            f"{base}/CheckReady",
            request_serializer=eval_bridge_pb2.Empty.SerializeToString,
            response_deserializer=eval_bridge_pb2.ReadyStatus.FromString,
        )
        self._send_message_rpc = self._channel.unary_unary(
            f"{base}/SendMessage",
            request_serializer=eval_bridge_pb2.ProtocolEnvelope.SerializeToString,
            response_deserializer=eval_bridge_pb2.SendAck.FromString,
        )
        self._recv_message_rpc = self._channel.unary_unary(
            f"{base}/RecvMessage",
            request_serializer=eval_bridge_pb2.RecvRequest.SerializeToString,
            response_deserializer=eval_bridge_pb2.RecvResponse.FromString,
        )

    def _try_switch_service_name(self, probe_timeout_seconds: float) -> bool:
        if not hasattr(self._channel, "unary_unary"):
            return False
        probe_timeout = max(0.2, min(2.0, float(probe_timeout_seconds)))
        not_found_codes = {
            getattr(grpc.StatusCode, "UNIMPLEMENTED", None),
            getattr(grpc.StatusCode, "NOT_FOUND", None),
            getattr(grpc.StatusCode, "UNAVAILABLE", None),
        }
        for service_name in self._SERVICE_CANDIDATES:
            if service_name == self._active_service:
                continue
            probe_rpc = self._channel.unary_unary(
                f"/{service_name}/CheckReady",
                request_serializer=eval_bridge_pb2.Empty.SerializeToString,
                response_deserializer=eval_bridge_pb2.ReadyStatus.FromString,
            )
            try:
                resp = probe_rpc(eval_bridge_pb2.Empty(), timeout=probe_timeout)
            except grpc.RpcError as err:
                if err.code() in not_found_codes:
                    continue
                logger.debug(
                    "gRPC bridge service probe failed (%s, %s): %s",
                    self.target,
                    service_name,
                    err,
                )
                continue
            self._bind_rpc_methods(service_name)
            logger.info(
                "gRPC bridge service resolved (%s): %s",
                self.target,
                service_name,
            )
            return bool(resp.is_ready)
        return False

    def wait_for_ready(self, timeout: int) -> bool:
        ready_timeout = max(1, int(timeout))
        deadline = time.monotonic() + ready_timeout
        retry_interval = 0.5
        last_error: Optional[str] = None
        not_ready_codes = {
            getattr(grpc.StatusCode, "UNIMPLEMENTED", None),
            getattr(grpc.StatusCode, "NOT_FOUND", None),
            getattr(grpc.StatusCode, "UNAVAILABLE", None),
        }
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if last_error:
                    logger.warning(
                        "gRPC wait_for_ready timeout (%s, service=%s): %s",
                        self.target,
                        self._active_service,
                        last_error,
                    )
                return False
            try:
                grpc.channel_ready_future(self._channel).result(
                    timeout=min(1.0, remaining)
                )
                resp = self._check_ready_rpc(
                    eval_bridge_pb2.Empty(),
                    timeout=min(5, int(remaining) + 1),
                )
                if resp.is_ready:
                    return True
                last_error = f"bridge returned is_ready={resp.is_ready}: {resp.message}"
            except grpc.FutureTimeoutError:
                last_error = "channel not ready before probe timeout"
            except grpc.RpcError as err:
                code = err.code()
                if code in not_ready_codes:
                    code_name = getattr(code, "name", str(code))
                    details_fn = getattr(err, "details", None)
                    details = details_fn() if callable(details_fn) else str(err)
                    last_error = f"{code_name}: {details or err}"
                    if self._try_switch_service_name(
                        probe_timeout_seconds=remaining
                    ):
                        return True
                else:
                    logger.warning(
                        "gRPC wait_for_ready rpc failed (%s): %s",
                        self.target,
                        err,
                    )
                    return False
            sleep_time = min(retry_interval, max(0.05, deadline - time.monotonic()))
            time.sleep(sleep_time)

    def send_message(self, msg: dict[str, Any], timeout: int) -> None:
        payload = json.dumps(msg, ensure_ascii=False)
        try:
            ack = self._send_message_rpc(
                eval_bridge_pb2.ProtocolEnvelope(json_message=payload),
                timeout=max(1, min(int(timeout), 120)),
            )
        except grpc.RpcError as err:
            raise SandboxTransportConnectionError(
                f"gRPC send failed ({self.target}): {err}"
            ) from err
        if not ack.ok:
            raise SandboxTransportError(
                f"bridge rejected message ({self.target}): {ack.error}"
            )

    def recv_message(self, timeout: int) -> Optional[str]:
        wait_seconds = max(1, int(timeout))
        try:
            resp = self._recv_message_rpc(
                eval_bridge_pb2.RecvRequest(timeout_ms=wait_seconds * 1000),
                timeout=wait_seconds + 2,
            )
        except grpc.RpcError as err:
            if err.code() == grpc.StatusCode.DEADLINE_EXCEEDED:
                return None
            raise SandboxTransportConnectionError(
                f"gRPC recv failed ({self.target}): {err}"
            ) from err

        if not resp.has_message:
            return None
        return resp.json_message or None

    def close(self) -> None:
        self._channel.close()

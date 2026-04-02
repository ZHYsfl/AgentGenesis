"""Generated protobuf modules for sandbox bridge transport."""

from .eval_bridge_pb2 import (
    Empty,
    ProtocolEnvelope,
    ReadyStatus,
    RecvRequest,
    RecvResponse,
    SendAck,
)

# gRPC symbols require grpcio which is optional
try:
    from .eval_bridge_pb2_grpc import (
        SandboxBridgeServicer,
        SandboxBridgeStub,
    )
    _HAS_GRPC = True
except ImportError:
    _HAS_GRPC = False
    SandboxBridgeServicer = None  # type: ignore
    SandboxBridgeStub = None  # type: ignore

__all__ = [
    "Empty",
    "ProtocolEnvelope",
    "ReadyStatus",
    "RecvRequest",
    "RecvResponse",
    "SendAck",
    "SandboxBridgeServicer",
    "SandboxBridgeStub",
]

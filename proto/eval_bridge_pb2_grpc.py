"""Generated gRPC bindings for evaluation sandbox bridge."""

from __future__ import annotations

import grpc

from . import eval_bridge_pb2 as eval_bridge__pb2


class SandboxBridgeStub:
    def __init__(self, channel: grpc.Channel) -> None:
        self.CheckReady = channel.unary_unary(
            "/agent_genesis.evaluation.SandboxBridge/CheckReady",
            request_serializer=eval_bridge__pb2.Empty.SerializeToString,
            response_deserializer=eval_bridge__pb2.ReadyStatus.FromString,
        )
        self.SendMessage = channel.unary_unary(
            "/agent_genesis.evaluation.SandboxBridge/SendMessage",
            request_serializer=eval_bridge__pb2.ProtocolEnvelope.SerializeToString,
            response_deserializer=eval_bridge__pb2.SendAck.FromString,
        )
        self.RecvMessage = channel.unary_unary(
            "/agent_genesis.evaluation.SandboxBridge/RecvMessage",
            request_serializer=eval_bridge__pb2.RecvRequest.SerializeToString,
            response_deserializer=eval_bridge__pb2.RecvResponse.FromString,
        )


class SandboxBridgeServicer:
    def CheckReady(self, request, context):  # type: ignore[no-untyped-def]
        raise NotImplementedError()

    def SendMessage(self, request, context):  # type: ignore[no-untyped-def]
        raise NotImplementedError()

    def RecvMessage(self, request, context):  # type: ignore[no-untyped-def]
        raise NotImplementedError()


def add_SandboxBridgeServicer_to_server(
    servicer: SandboxBridgeServicer,
    server: grpc.Server,
) -> None:
    rpc_method_handlers = {
        "CheckReady": grpc.unary_unary_rpc_method_handler(
            servicer.CheckReady,
            request_deserializer=eval_bridge__pb2.Empty.FromString,
            response_serializer=eval_bridge__pb2.ReadyStatus.SerializeToString,
        ),
        "SendMessage": grpc.unary_unary_rpc_method_handler(
            servicer.SendMessage,
            request_deserializer=eval_bridge__pb2.ProtocolEnvelope.FromString,
            response_serializer=eval_bridge__pb2.SendAck.SerializeToString,
        ),
        "RecvMessage": grpc.unary_unary_rpc_method_handler(
            servicer.RecvMessage,
            request_deserializer=eval_bridge__pb2.RecvRequest.FromString,
            response_serializer=eval_bridge__pb2.RecvResponse.SerializeToString,
        ),
    }
    generic_handler = grpc.method_handlers_generic_handler(
        "agent_genesis.evaluation.SandboxBridge",
        rpc_method_handlers,
    )
    server.add_generic_rpc_handlers((generic_handler,))

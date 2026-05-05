from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import evaluation.transport as transport_mod
from evaluation.transport import (
    GrpcSandboxTransport,
    SandboxTransportConnectionError,
    SandboxTransportError,
    resolve_grpc_target,
)


def test_resolve_grpc_target_variants() -> None:
    with pytest.raises(ValueError, match="empty grpc host/target"):
        resolve_grpc_target("")

    assert resolve_grpc_target("localhost") == "localhost:50051"
    assert resolve_grpc_target("127.0.0.1:6000") == "127.0.0.1:6000"
    assert resolve_grpc_target("http://abc.com/path") == "abc.com:50051"
    assert resolve_grpc_target("https://abc.com") == "abc.com:50051"
    assert resolve_grpc_target("abc.com:7000") == "abc.com:7000"


class _FakeGrpcRpcError(Exception):
    def __init__(self, msg: str, code_value: Any = None) -> None:
        super().__init__(msg)
        self._code_value = code_value

    def code(self):  # type: ignore[no-untyped-def]
        return self._code_value


class _FakeFutureTimeoutError(Exception):
    pass


class _FakeChannel:
    def __init__(self, stub):
        self.stub = stub
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _mount_fake_grpc(monkeypatch, *, stub_obj, ready_outcome="ok"):
    channels = {"insecure": None}

    def _insecure_channel(target, options=None):
        _ = (target, options)
        ch = _FakeChannel(stub_obj)
        channels["insecure"] = ch
        return ch

    class _ReadyFuture:
        def result(self, timeout: int) -> None:
            _ = timeout
            if isinstance(ready_outcome, Exception):
                raise ready_outcome
            return None

    fake_grpc = SimpleNamespace(
        insecure_channel=_insecure_channel,
        channel_ready_future=lambda channel: _ReadyFuture(),
        FutureTimeoutError=_FakeFutureTimeoutError,
        RpcError=_FakeGrpcRpcError,
        StatusCode=SimpleNamespace(DEADLINE_EXCEEDED="DEADLINE_EXCEEDED"),
    )
    monkeypatch.setattr(transport_mod, "grpc", fake_grpc)
    monkeypatch.setattr(transport_mod.eval_bridge_pb2_grpc, "SandboxBridgeStub", lambda channel: channel.stub)
    return channels


def test_grpc_transport_wait_for_ready_and_close(monkeypatch) -> None:
    stub = SimpleNamespace(
        CheckReady=lambda req, timeout=1: SimpleNamespace(is_ready=True),
        SendMessage=lambda req, timeout=1: SimpleNamespace(ok=True, error=""),
        RecvMessage=lambda req, timeout=1: SimpleNamespace(has_message=False, json_message=""),
    )
    channels = _mount_fake_grpc(monkeypatch, stub_obj=stub, ready_outcome="ok")
    t = GrpcSandboxTransport("localhost")
    assert t.wait_for_ready(3) is True
    t.close()
    assert channels["insecure"].closed is True

    channels2 = _mount_fake_grpc(
        monkeypatch,
        stub_obj=stub,
        ready_outcome=_FakeFutureTimeoutError("timeout"),
    )
    t2 = GrpcSandboxTransport("localhost")
    assert t2.wait_for_ready(3) is False
    t2.close()
    assert channels2["insecure"].closed is True

    def _check_ready_err(req, timeout=1):
        raise _FakeGrpcRpcError("rpc fail")

    stub_err = SimpleNamespace(
        CheckReady=_check_ready_err,
        SendMessage=lambda req, timeout=1: SimpleNamespace(ok=True, error=""),
        RecvMessage=lambda req, timeout=1: SimpleNamespace(has_message=False, json_message=""),
    )
    _mount_fake_grpc(monkeypatch, stub_obj=stub_err, ready_outcome="ok")
    t3 = GrpcSandboxTransport("localhost")
    assert t3.wait_for_ready(3) is False


def test_grpc_transport_send_and_recv_paths(monkeypatch) -> None:
    stub = SimpleNamespace(
        CheckReady=lambda req, timeout=1: SimpleNamespace(is_ready=True),
        SendMessage=lambda req, timeout=1: SimpleNamespace(ok=False, error="bad payload"),
        RecvMessage=lambda req, timeout=1: SimpleNamespace(has_message=False, json_message=""),
    )
    _mount_fake_grpc(monkeypatch, stub_obj=stub)
    t = GrpcSandboxTransport("localhost")
    with pytest.raises(SandboxTransportError, match="bridge rejected"):
        t.send_message({"k": "v"}, timeout=5)

    def _send_err(req, timeout=1):
        raise _FakeGrpcRpcError("send down")

    stub_send_err = SimpleNamespace(
        CheckReady=lambda req, timeout=1: SimpleNamespace(is_ready=True),
        SendMessage=_send_err,
        RecvMessage=lambda req, timeout=1: SimpleNamespace(has_message=False, json_message=""),
    )
    _mount_fake_grpc(monkeypatch, stub_obj=stub_send_err)
    t2 = GrpcSandboxTransport("localhost")
    with pytest.raises(SandboxTransportConnectionError, match="gRPC send failed"):
        t2.send_message({"k": "v"}, timeout=5)

    stub_recv = SimpleNamespace(
        CheckReady=lambda req, timeout=1: SimpleNamespace(is_ready=True),
        SendMessage=lambda req, timeout=1: SimpleNamespace(ok=True, error=""),
        RecvMessage=lambda req, timeout=1: SimpleNamespace(has_message=True, json_message='{"x":1}'),
    )
    _mount_fake_grpc(monkeypatch, stub_obj=stub_recv)
    t3 = GrpcSandboxTransport("localhost")
    assert t3.recv_message(3) == '{"x":1}'

    stub_recv_none = SimpleNamespace(
        CheckReady=lambda req, timeout=1: SimpleNamespace(is_ready=True),
        SendMessage=lambda req, timeout=1: SimpleNamespace(ok=True, error=""),
        RecvMessage=lambda req, timeout=1: SimpleNamespace(has_message=False, json_message=""),
    )
    _mount_fake_grpc(monkeypatch, stub_obj=stub_recv_none)
    t4 = GrpcSandboxTransport("localhost")
    assert t4.recv_message(3) is None

    def _recv_deadline(req, timeout=1):
        raise _FakeGrpcRpcError("deadline", code_value="DEADLINE_EXCEEDED")

    stub_recv_deadline = SimpleNamespace(
        CheckReady=lambda req, timeout=1: SimpleNamespace(is_ready=True),
        SendMessage=lambda req, timeout=1: SimpleNamespace(ok=True, error=""),
        RecvMessage=_recv_deadline,
    )
    _mount_fake_grpc(monkeypatch, stub_obj=stub_recv_deadline)
    t5 = GrpcSandboxTransport("localhost")
    assert t5.recv_message(3) is None

    def _recv_err(req, timeout=1):
        raise _FakeGrpcRpcError("recv down", code_value="UNAVAILABLE")

    stub_recv_err = SimpleNamespace(
        CheckReady=lambda req, timeout=1: SimpleNamespace(is_ready=True),
        SendMessage=lambda req, timeout=1: SimpleNamespace(ok=True, error=""),
        RecvMessage=_recv_err,
    )
    _mount_fake_grpc(monkeypatch, stub_obj=stub_recv_err)
    t6 = GrpcSandboxTransport("localhost")
    with pytest.raises(SandboxTransportConnectionError, match="gRPC recv failed"):
        t6.recv_message(3)


def test_grpc_transport_wait_for_ready_switches_service_name(monkeypatch) -> None:
    class _Code:
        DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"
        UNIMPLEMENTED = "UNIMPLEMENTED"
        NOT_FOUND = "NOT_FOUND"
        UNAVAILABLE = "UNAVAILABLE"

    class _RpcError(Exception):
        def __init__(self, msg: str, code_value: Any) -> None:
            super().__init__(msg)
            self._code_value = code_value

        def code(self):  # type: ignore[no-untyped-def]
            return self._code_value

        def details(self) -> str:
            return str(self)

    class _ReadyFuture:
        def result(self, timeout: int) -> None:
            _ = timeout
            return None

    class _SwitchChannel:
        def __init__(self) -> None:
            self.closed = False

        def unary_unary(self, path: str, **kwargs):  # type: ignore[no-untyped-def]
            _ = kwargs

            if path.endswith("/CheckReady"):
                def _rpc(req, timeout=1):  # type: ignore[no-untyped-def]
                    _ = (req, timeout)
                    if path.startswith("/agent_genesis.evaluation.SandboxBridge"):
                        raise _RpcError("unimplemented", _Code.UNIMPLEMENTED)
                    if path.startswith("/evaluation.SandboxBridge"):
                        return SimpleNamespace(is_ready=True, message="ready")
                    raise _RpcError("not found", _Code.NOT_FOUND)

                return _rpc

            if path.endswith("/SendMessage"):
                return lambda req, timeout=1: SimpleNamespace(ok=True, error="")
            if path.endswith("/RecvMessage"):
                return lambda req, timeout=1: SimpleNamespace(has_message=False, json_message="")
            raise AssertionError(f"unexpected rpc path: {path}")

        def close(self) -> None:
            self.closed = True

    channel_holder = {"channel": None}

    def _insecure_channel(target, options=None):  # type: ignore[no-untyped-def]
        _ = (target, options)
        ch = _SwitchChannel()
        channel_holder["channel"] = ch
        return ch

    fake_grpc = SimpleNamespace(
        insecure_channel=_insecure_channel,
        channel_ready_future=lambda ch: _ReadyFuture(),
        FutureTimeoutError=_FakeFutureTimeoutError,
        RpcError=_RpcError,
        StatusCode=_Code,
    )
    monkeypatch.setattr(transport_mod, "grpc", fake_grpc)
    monkeypatch.setattr(
        transport_mod.eval_bridge_pb2_grpc,
        "SandboxBridgeStub",
        lambda channel: SimpleNamespace(),
    )

    t = GrpcSandboxTransport("localhost")
    assert t.wait_for_ready(3) is True
    assert t._active_service == "evaluation.SandboxBridge"
    t.close()
    assert channel_holder["channel"] is not None
    assert channel_holder["channel"].closed is True


def test_grpc_transport_wait_for_ready_returns_false_when_all_services_missing(monkeypatch) -> None:
    class _Code:
        DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"
        UNIMPLEMENTED = "UNIMPLEMENTED"
        NOT_FOUND = "NOT_FOUND"
        UNAVAILABLE = "UNAVAILABLE"

    class _RpcError(Exception):
        def __init__(self, msg: str, code_value: Any) -> None:
            super().__init__(msg)
            self._code_value = code_value

        def code(self):  # type: ignore[no-untyped-def]
            return self._code_value

        def details(self) -> str:
            return str(self)

    class _ReadyFuture:
        def result(self, timeout: int) -> None:
            _ = timeout
            return None

    class _MissingChannel:
        def unary_unary(self, path: str, **kwargs):  # type: ignore[no-untyped-def]
            _ = kwargs

            def _rpc(req, timeout=1):  # type: ignore[no-untyped-def]
                _ = (req, timeout, path)
                raise _RpcError("missing", _Code.NOT_FOUND)

            return _rpc

        def close(self) -> None:
            return None

    fake_grpc = SimpleNamespace(
        insecure_channel=lambda target, options=None: _MissingChannel(),
        channel_ready_future=lambda ch: _ReadyFuture(),
        FutureTimeoutError=_FakeFutureTimeoutError,
        RpcError=_RpcError,
        StatusCode=_Code,
    )
    monkeypatch.setattr(transport_mod, "grpc", fake_grpc)
    monkeypatch.setattr(
        transport_mod.eval_bridge_pb2_grpc,
        "SandboxBridgeStub",
        lambda channel: SimpleNamespace(),
    )

    t = GrpcSandboxTransport("localhost")
    assert t.wait_for_ready(1) is False

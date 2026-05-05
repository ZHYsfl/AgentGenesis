"""Unit tests for runtime core helper modules."""

from __future__ import annotations

import hashlib
import io
import json
import queue
import sys
import types
import zipfile
from types import SimpleNamespace
from typing import Any, Callable, Union

import pytest
import requests

import evaluation.dual_sandbox_evaluator as dse_mod
from evaluation.models import PhaseConfig, RuntimeConfig, UserSubmission
from evaluation.proto import eval_bridge_pb2 as pb2_mod
from evaluation.proto import eval_bridge_pb2_grpc as pb2_grpc_mod
from evaluation.runtime import artifact as artifact_mod
from evaluation.runtime import gateway as gateway_mod
from evaluation.runtime import history as history_mod
from evaluation.runtime import process as process_mod
from evaluation.runtime import results as results_mod
from evaluation.runtime import sandbox as sandbox_mod
from evaluation.runtime import user_adapter as user_adapter_mod
from evaluation.sandbox_backend import CommandResult, ExecHandle, Sandbox


class _DummyResponse:
    def __init__(self, *, status_code: int = 200, content: bytes = b"", text: str = "") -> None:
        self.status_code = status_code
        self.content = content
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            err = requests.HTTPError(f"HTTP {self.status_code}: {self.text}")
            err.response = self
            raise err


class _DummySandbox(Sandbox):
    def __init__(
        self,
        *,
        script: Callable[..., Any] | None = None,
        host: str = "localhost:50051",
        metrics: Any = None,
    ) -> None:
        self._script = script
        self._host = host
        self._metrics = metrics
        self._calls: list[dict[str, Any]] = []
        self._file_calls: list[list[dict[str, Any]]] = []

    @property
    def id(self) -> str:
        return "dummy"

    def run_command(
        self,
        command: str,
        *,
        timeout: int = 30,
        envs: dict[str, str] | None = None,
        background: bool = False,
    ) -> Union[CommandResult, ExecHandle]:
        payload = {
            "command": command,
            "timeout": timeout,
            "envs": envs or {},
            "background": bool(background),
        }
        self._calls.append(payload)
        if self._script is None:
            if background:
                return ExecHandle(_api=None, _exec_id="dummy", command=command)
            return CommandResult(stdout="", stderr="")
        result = self._script(
            command=command,
            timeout=timeout,
            envs=envs or {},
            background=bool(background),
        )
        if isinstance(result, CommandResult):
            return result
        if hasattr(result, "stdout"):
            return CommandResult(stdout=result.stdout or "", stderr=getattr(result, "stderr", "") or "")
        return result

    def write_files(self, files: list[dict[str, Any]]) -> None:
        self._file_calls.append(files)

    def get_host(self, port: int) -> str:
        _ = port
        return self._host

    def get_metrics(self) -> list[dict[str, Any]]:
        if callable(self._metrics):
            return self._metrics()
        return self._metrics or []

    def close(self) -> None:
        pass

    def kill(self) -> None:
        pass


def _submission() -> UserSubmission:
    cfg = PhaseConfig(phase_order=1, phase_level="Easy", phase_name="p1")
    return UserSubmission(
        submit_id=11,
        user_id=22,
        phase_id=33,
        code_url="http://code.zip",
        code_checksum="",
        code_files={"solution.py": "def solve(x): return x"},
        phase_config=cfg,
        runtime_config=RuntimeConfig(key_name="demo-key"),
        phase_type="agent",
    )


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, data in files.items():
            zf.writestr(path, data)
    return buf.getvalue()


def test_download_artifact_validation_and_retry_paths(monkeypatch) -> None:
    with pytest.raises(ValueError, match="artifact_url is required"):
        artifact_mod.download_artifact("", "")

    calls = {"count": 0}

    def _get_404(url: str, timeout: int = 0):  # type: ignore[no-untyped-def]
        _ = (url, timeout)
        calls["count"] += 1
        return _DummyResponse(status_code=404, text="not found")

    monkeypatch.setattr(artifact_mod.requests, "get", _get_404)
    with pytest.raises(ValueError, match="HTTP 404"):
        artifact_mod.download_artifact("http://artifact.zip", "", max_retries=5)
    assert calls["count"] == 1

    def _get_checksum(url: str, timeout: int = 0):  # type: ignore[no-untyped-def]
        _ = (url, timeout)
        return _DummyResponse(status_code=200, content=b"abc")

    monkeypatch.setattr(artifact_mod.requests, "get", _get_checksum)
    with pytest.raises(ValueError, match="SHA256"):
        artifact_mod.download_artifact("http://artifact.zip", "deadbeef")

    attempts = {"count": 0}
    sleeps: list[int] = []

    def _get_flaky(url: str, timeout: int = 0):  # type: ignore[no-untyped-def]
        _ = (url, timeout)
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("temporary network error")
        return _DummyResponse(status_code=200, content=b"ok")

    monkeypatch.setattr(artifact_mod.requests, "get", _get_flaky)
    monkeypatch.setattr("time.sleep", lambda sec: sleeps.append(int(sec)))
    checksum = hashlib.sha256(b"ok").hexdigest()
    assert artifact_mod.download_artifact("http://artifact.zip", checksum, max_retries=3) == b"ok"
    assert sleeps == [1]

    def _get_fail(url: str, timeout: int = 0):  # type: ignore[no-untyped-def]
        _ = (url, timeout)
        raise RuntimeError("offline")

    monkeypatch.setattr(artifact_mod.requests, "get", _get_fail)
    with pytest.raises(ValueError, match="failed after"):
        artifact_mod.download_artifact("http://artifact.zip", "", max_retries=2)


def test_artifact_extract_entrypoint_and_requirement_filters() -> None:
    payload = _zip_bytes(
        {
            "sandbox/run.py": b"print(1)",
            "sandbox/sub\\judge.py": b"print(2)",
            "../evil.py": b"pwned",
            "folder/": b"",
        }
    )
    files = artifact_mod.extract_artifact(payload)
    assert "sandbox/run.py" in files
    assert "sandbox/sub/judge.py" in files
    assert "../evil.py" not in files

    assert artifact_mod.resolve_entrypoint(SimpleNamespace(artifact_entry="a/b.py")) == "a/b.py"
    assert artifact_mod.resolve_entrypoint(SimpleNamespace(artifact_entry="")) == "sandbox/run.py"

    assert artifact_mod.extract_requirement_pkg_name("requests[socks]==2.0") == "requests"
    assert artifact_mod.extract_requirement_pkg_name("numpy>=1.24") == "numpy"
    assert artifact_mod.extract_requirement_pkg_name("# comment") is None
    assert artifact_mod.extract_requirement_pkg_name("-r requirements.txt") is None
    assert artifact_mod.extract_requirement_pkg_name("!!!") is None

    reqs = "numpy==1.0\nunknown_pkg>=2\n--index-url x\n\n# c\n"
    assert artifact_mod.filter_requirements(reqs, []) == reqs
    filtered = artifact_mod.filter_requirements(reqs, ["numpy"])
    assert "numpy==1.0" in filtered
    assert "# [BLOCKED] unknown_pkg>=2" in filtered
    assert "--index-url x" in filtered


def test_process_manager_paths() -> None:
    class _FakeExecHandle(ExecHandle):
        def __init__(self) -> None:
            super().__init__(_api=None, _exec_id="test", command="test")
            self._running = True
            self.killed = False

        def is_running(self) -> bool:
            return self._running

        def kill(self) -> None:
            self.killed = True
            self._running = False

    handle = _FakeExecHandle()
    sb_ok = _DummySandbox(script=lambda **kwargs: handle if kwargs.get("background") else CommandResult())
    process = process_mod.SandboxProcessManager.start_background_python(
        sb_ok,
        workdir="/workspace/judge",
        script_rel="sandbox/run.py",
        envs={"K": "V"},
        stderr_path="/workspace/judge_stderr.log",
        args=["--a", 1],
    )
    assert isinstance(process, process_mod.SandboxProcessHandle)
    assert process.raw_handle is handle
    assert process.script_rel == "sandbox/run.py"
    assert sb_ok._calls[0]["background"] is True
    assert "sandbox/run.py" in sb_ok._calls[0]["command"]
    assert "--a" in sb_ok._calls[0]["command"]

    assert process_mod.SandboxProcessManager.is_process_alive(process) is True

    process_mod.SandboxProcessManager.stop_process(None)
    process_mod.SandboxProcessManager.stop_process(process)
    assert handle.killed is True

    assert process_mod.SandboxProcessManager.is_process_alive(None) is False
    assert process_mod.SandboxProcessManager.is_process_alive(process) is False

    desc = process_mod.SandboxProcessManager.describe_process(process)
    assert "sandbox/run.py" in desc
    assert "stopped" in desc
    assert process_mod.SandboxProcessManager.describe_process(None) == "none"


def test_phase_config_pip_deps_whitelist_validation() -> None:
    from evaluation.models import PhaseConfig

    PhaseConfig(pip_dependencies=[], allowed_packages=[])

    PhaseConfig(
        pip_dependencies=["numpy==1.0", "pydantic>=2"],
        allowed_packages=["numpy", "pydantic"],
    )

    with pytest.raises(ValueError, match="not in allowed_packages"):
        PhaseConfig(
            pip_dependencies=["badpkg>=1"],
            allowed_packages=["goodpkg"],
        )


def test_sandbox_utility_functions(monkeypatch, tmp_path) -> None:
    sb = _DummySandbox()
    files = {f"f{i}.txt": f"d{i}".encode("utf-8") for i in range(401)}
    sandbox_mod.write_files_chunked(sb, files, "/workspace/base")
    assert len(sb._file_calls) == 3
    assert sb._file_calls[0][0]["path"].startswith("/workspace/base/")

    assert sandbox_mod.to_positive_int("3") == 3
    assert sandbox_mod.to_positive_int(0) is None
    assert sandbox_mod.to_positive_int("x") is None

    cfg = SimpleNamespace(sandbox_cpu_count=2, memory_limit_mb=512, cpu_count=9, memory_mb=99)
    assert sandbox_mod.resolve_sandbox_resources(cfg) == (2, 512)

    sb_snippet = _DummySandbox(script=lambda **kwargs: CommandResult(stdout="abcdef", stderr=""))
    assert sandbox_mod.read_file_snippet(sb_snippet, "/x", max_bytes=4) == "abcd"
    assert sandbox_mod.read_file_snippet(sb_snippet, "/x", max_bytes=0) == ""

    sb_raise = _DummySandbox(script=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    assert sandbox_mod.read_file_snippet(sb_raise, "/x", max_bytes=4) == ""

    sb_no_metrics = _DummySandbox(metrics=[])
    assert sandbox_mod.latest_mem_used_mib(sb_no_metrics) is None
    sb_with_metrics = _DummySandbox(metrics=[{"mem_used_mib": 123}])
    assert sandbox_mod.latest_mem_used_mib(sb_with_metrics) == 123.0
    sb_with_mib_obj = _DummySandbox(metrics=lambda: [SimpleNamespace(memUsedMiB=42)])
    assert sandbox_mod.latest_mem_used_mib(sb_with_mib_obj) == 42.0
    sb_wrong_key = _DummySandbox(metrics=lambda: [SimpleNamespace(memory_mb=42)])
    assert sandbox_mod.latest_mem_used_mib(sb_wrong_key) is None
    sb_wrong_key2 = _DummySandbox(metrics=[{"memory_mb": 42}])
    assert sandbox_mod.latest_mem_used_mib(sb_wrong_key2) is None
    sb_bad_val = _DummySandbox(metrics=[{"mem_used_mib": "x"}])
    assert sandbox_mod.latest_mem_used_mib(sb_bad_val) is None

    cfg_limit = SimpleNamespace(sandbox_cpu_count=1, memory_limit_mb=100, cpu_count=0, memory_mb=0)
    sb_limit = _DummySandbox(metrics=[{"mem_used_mib": 99}])
    assert sandbox_mod.is_likely_mle_exit(cfg_limit, sb_limit, "/stderr.log") is True

    monkeypatch.setattr(sandbox_mod, "read_file_snippet", lambda *args, **kwargs: "memoryerror occurred")
    sb_mid = _DummySandbox(metrics=[{"mem_used_mib": 80}])
    assert sandbox_mod.is_likely_mle_exit(cfg_limit, sb_mid, "/stderr.log") is False
    sb_high = _DummySandbox(metrics=[{"mem_used_mib": 90}])
    assert sandbox_mod.is_likely_mle_exit(cfg_limit, sb_high, "/stderr.log") is True
    cfg_no_limit = SimpleNamespace(sandbox_cpu_count=1, memory_limit_mb=0, cpu_count=0, memory_mb=0)
    sb_no_metrics2 = _DummySandbox(metrics=[])
    assert sandbox_mod.is_likely_mle_exit(cfg_no_limit, sb_no_metrics2, "/stderr.log") is True

    env = sandbox_mod.build_llm_env_vars("tok", "http://gw")
    assert env["OPENAI_API_KEY"] == "tok"
    assert env["OPENAI_BASE_URL"] == "http://gw"

    class _Cfg:
        def __init__(self) -> None:
            self.judge_envs = {"A": "x", "B": 1, "C": True, "D": {"x": 1}}

        def model_dump(self) -> dict[str, Any]:
            return {"phase_name": "p1"}

    sub = _submission()
    client_getter = lambda: SimpleNamespace(base_url="http://backend")
    monkeypatch.setattr(
        sandbox_mod,
        "_get_system_gateway_url",
        lambda: "http://172.17.0.1:8080",
    )
    judge_envs = sandbox_mod.build_judge_envs(
        config=_Cfg(),
        submission=sub,
        get_client=client_getter,
        gateway_token="tok",
    )
    assert judge_envs["DUAL_SANDBOX_MODE"] == "judge"
    assert judge_envs["A"] == "x"
    assert judge_envs["B"] == "1"
    assert judge_envs["C"] == "True"
    assert "D" not in judge_envs
    assert judge_envs["OPENAI_API_KEY"] == "tok"

    user_envs = sandbox_mod.build_user_envs(
        config=_Cfg(),
        submission=sub,
        get_client=client_getter,
        gateway_token="tok",
    )
    assert user_envs["DUAL_SANDBOX_MODE"] == "user"
    assert user_envs["OPENAI_BASE_URL"].endswith("/gateway/v1/keys/demo-key")

    class _CfgNoGateway:
        def __init__(self) -> None:
            self.judge_envs = {}

        def model_dump(self) -> dict[str, Any]:
            return {"phase_name": "p1"}

    monkeypatch.setattr(
        sandbox_mod,
        "_get_system_gateway_url",
        lambda: "http://172.17.0.1:8080",
    )
    fallback_envs = sandbox_mod.build_judge_envs(
        config=_CfgNoGateway(),
        submission=sub,
        get_client=client_getter,
        gateway_token="tok",
    )
    assert fallback_envs["OPENAI_BASE_URL"].endswith("/gateway/v1/keys/demo-key")

    loaded = sandbox_mod.load_grpc_bridge_support_files(dse_mod.__file__)
    assert "eval_bridge_pb2.py" in loaded
    assert "eval_bridge_pb2_grpc.py" in loaded
    assert "eval_runtime/judge_runtime.py" in loaded
    assert "eval_runtime/judge_scaffold.py" in loaded
    assert "eval_runtime/user_runtime.py" in loaded
    assert "eval_runtime/user_adapter.py" in loaded

    fake_base = tmp_path / "x.py"
    fake_base.write_text("# x", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="missing grpc bridge support file"):
        sandbox_mod.load_grpc_bridge_support_files(str(fake_base))

    sb_no_host = _DummySandbox(host="")
    with pytest.raises(RuntimeError, match="empty host"):
        sandbox_mod.create_grpc_transport(sb_no_host, 50051)

    class _FakeTransport:
        def __init__(self, host: str) -> None:
            self.host = host

    monkeypatch.setattr(sandbox_mod, "GrpcSandboxTransport", _FakeTransport)
    transport = sandbox_mod.create_grpc_transport(
        _DummySandbox(host="localhost:6000"),
        6000,
    )
    assert isinstance(transport, _FakeTransport)
    assert transport.host == "localhost:6000"


def test_gateway_history_and_results_paths(monkeypatch) -> None:
    evaluator = SimpleNamespace(
        config=SimpleNamespace(
            allow_user_key=False,
            gateway_max_chars=10,
            gateway_max_requests=2,
            num_cases=3,
            gateway_allowed_models=[],
            gateway_ttl_minutes=10,
        ),
        _gateway_token_info=None,
        _prev_usage_chars=0,
        _prev_usage_requests=0,
        _get_client=lambda: SimpleNamespace(),
    )
    assert gateway_mod.create_gateway_token_for_user(evaluator, _submission()) is None

    case = results_mod.parse_case_result({"status": "passed", "score": 1}, 0)
    assert gateway_mod.attach_llm_usage_delta(evaluator, case, _submission()) is case

    evaluator._gateway_token_info = {"token": "t"}

    def _usage_raise(submit_id: int):  # type: ignore[no-untyped-def]
        _ = submit_id
        raise RuntimeError("gateway down")

    evaluator._get_client = lambda: SimpleNamespace(
        get_gateway_token_usage=_usage_raise,
        revoke_gateway_token=lambda submit_id: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    out = gateway_mod.attach_llm_usage_delta(evaluator, case, _submission())
    assert out is case
    gateway_mod.revoke_gateway_token(evaluator, _submission())
    assert evaluator._gateway_token_info is None

    assert history_mod.extract_history_events({"history_events": [1, {"k": "v"}]}) == [{"k": "v"}]
    assert history_mod.extract_history_events({"history_events": "x"}) == []

    hist: dict[int, list[dict[str, Any]]] = {}
    history_mod.record_action_history(hist, 0, {"type": "action", "data": {"d": 1}, "error": "e"})
    assert hist[0][0]["payload"] == {"d": 1}
    assert hist[0][0]["error"] == "e"

    history_mod.record_action_history(hist, 1, {"weird": True})
    assert hist[1][0]["payload"] == {"weird": True}

    case_result = results_mod.parse_case_result({"status": "error"}, 1)
    old_dumps = json.dumps
    monkeypatch.setattr(json, "dumps", lambda *args, **kwargs: (_ for _ in ()).throw(TypeError("x")))
    history_mod.attach_case_history(case_result, {1: [{"k": object()}]}, current_case_index=1)
    assert isinstance(case_result.logs, str)
    monkeypatch.setattr(json, "dumps", old_dumps)

    assert results_mod.to_int("not-int", default=7) == 7


def test_proto_json_shim_roundtrip_and_edge_paths() -> None:
    base = pb2_mod._JsonMessage()
    with pytest.raises(NotImplementedError):
        base.to_dict()
    with pytest.raises(NotImplementedError):
        pb2_mod._JsonMessage.from_dict({})

    assert isinstance(pb2_mod.Empty.FromString(b""), pb2_mod.Empty)
    assert isinstance(pb2_mod.Empty.FromString(b"\xff"), pb2_mod.Empty)
    assert isinstance(pb2_mod.Empty.FromString(b"[]"), pb2_mod.Empty)

    ready = pb2_mod.ReadyStatus(is_ready=True, message="ok")
    ready2 = pb2_mod.ReadyStatus.FromString(ready.SerializeToString())
    assert ready2.is_ready is True
    assert ready2.message == "ok"

    env = pb2_mod.ProtocolEnvelope(json_message='{"k":1}')
    env2 = pb2_mod.ProtocolEnvelope.FromString(env.SerializeToString())
    assert env2.json_message == '{"k":1}'

    ack = pb2_mod.SendAck(ok=True, error="")
    ack2 = pb2_mod.SendAck.FromString(ack.SerializeToString())
    assert ack2.ok is True
    assert ack2.error == ""
    ack_default = pb2_mod.SendAck.from_dict({})
    assert ack_default.ok is False

    req_bad = pb2_mod.RecvRequest(timeout_ms="not-int")
    assert req_bad.timeout_ms == 0
    req = pb2_mod.RecvRequest.from_dict({"timeout_ms": "9"})
    assert req.timeout_ms == 9

    resp = pb2_mod.RecvResponse(has_message=True, json_message='{"x":1}')
    resp2 = pb2_mod.RecvResponse.FromString(resp.SerializeToString())
    assert resp2.has_message is True
    assert resp2.json_message == '{"x":1}'


def test_proto_grpc_stub_servicer_and_registration_paths(monkeypatch) -> None:
    class _FakeChannel:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def unary_unary(self, path, request_serializer, response_deserializer):  # type: ignore[no-untyped-def]
            self.calls.append(
                {
                    "path": path,
                    "request_serializer": request_serializer,
                    "response_deserializer": response_deserializer,
                }
            )
            return {"path": path}

    channel = _FakeChannel()
    stub = pb2_grpc_mod.SandboxBridgeStub(channel)  # type: ignore[arg-type]
    assert stub.CheckReady["path"].endswith("/CheckReady")
    assert stub.SendMessage["path"].endswith("/SendMessage")
    assert stub.RecvMessage["path"].endswith("/RecvMessage")
    assert len(channel.calls) == 3

    servicer = pb2_grpc_mod.SandboxBridgeServicer()
    with pytest.raises(NotImplementedError):
        servicer.CheckReady(None, None)
    with pytest.raises(NotImplementedError):
        servicer.SendMessage(None, None)
    with pytest.raises(NotImplementedError):
        servicer.RecvMessage(None, None)

    captured: dict[str, Any] = {}

    def _fake_handler(fn, request_deserializer=None, response_serializer=None):  # type: ignore[no-untyped-def]
        return {
            "fn": fn,
            "request_deserializer": request_deserializer,
            "response_serializer": response_serializer,
        }

    def _fake_generic_handler(service_name, rpc_handlers):  # type: ignore[no-untyped-def]
        captured["service_name"] = service_name
        captured["rpc_handlers"] = rpc_handlers
        return {"service_name": service_name, "rpc_handlers": rpc_handlers}

    monkeypatch.setattr(pb2_grpc_mod.grpc, "unary_unary_rpc_method_handler", _fake_handler)
    monkeypatch.setattr(pb2_grpc_mod.grpc, "method_handlers_generic_handler", _fake_generic_handler)

    class _FakeServer:
        def __init__(self) -> None:
            self.handlers = None

        def add_generic_rpc_handlers(self, handlers) -> None:  # type: ignore[no-untyped-def]
            self.handlers = handlers

    class _Servicer(pb2_grpc_mod.SandboxBridgeServicer):
        def CheckReady(self, request, context):  # type: ignore[no-untyped-def]
            _ = (request, context)
            return pb2_mod.ReadyStatus(is_ready=True, message="")

        def SendMessage(self, request, context):  # type: ignore[no-untyped-def]
            _ = (request, context)
            return pb2_mod.SendAck(ok=True, error="")

        def RecvMessage(self, request, context):  # type: ignore[no-untyped-def]
            _ = (request, context)
            return pb2_mod.RecvResponse(has_message=False, json_message="")

    fake_server = _FakeServer()
    pb2_grpc_mod.add_SandboxBridgeServicer_to_server(_Servicer(), fake_server)  # type: ignore[arg-type]
    assert captured["service_name"] == "agent_genesis.evaluation.SandboxBridge"
    assert set(captured["rpc_handlers"].keys()) == {"CheckReady", "SendMessage", "RecvMessage"}
    assert fake_server.handlers is not None


def test_user_adapter_default_and_fallback_paths(monkeypatch) -> None:
    class _PassthroughAdapter(user_adapter_mod.UserAdapter):
        def create_user_api(self, act_queue, obs_queue):  # type: ignore[no-untyped-def]
            _ = (act_queue, obs_queue)
            return lambda x: x

    module = types.ModuleType("agent_genesis.runtime.problem_adapter")

    def _factory(preset_name: str = "default") -> user_adapter_mod.UserAdapter:
        _ = preset_name
        return _PassthroughAdapter()

    module.get_adapter = _factory  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "agent_genesis.runtime.problem_adapter", module)

    adapter = user_adapter_mod.get_adapter("unknown-preset")
    assert isinstance(adapter, _PassthroughAdapter)


def test_process_manager_error_and_fallback_paths() -> None:
    sb_bad = _DummySandbox(
        script=lambda **kwargs: CommandResult(stdout="", stderr=""),
    )
    with pytest.raises(RuntimeError, match="unexpected type"):
        process_mod.SandboxProcessManager.start_background_python(
            sb_bad,
            workdir="/workspace/user",
            script_rel="worker.py",
            args=None,
        )

    class _KillFailExecHandle(ExecHandle):
        def __init__(self) -> None:
            super().__init__(_api=None, _exec_id="kill-fail", command="cmd")

        def is_running(self) -> bool:
            return True

        def kill(self) -> None:
            raise RuntimeError("kill failed")

    class _AliveFailExecHandle(ExecHandle):
        def __init__(self) -> None:
            super().__init__(_api=None, _exec_id="alive-fail", command="cmd")

        def is_running(self) -> bool:
            raise RuntimeError("probe failed")

    process_mod.SandboxProcessManager.stop_process(
        process_mod.SandboxProcessHandle(
            raw_handle=_KillFailExecHandle(),
            workdir="/workspace",
            script_rel="x.py",
        )
    )

    alive_on_probe_error = process_mod.SandboxProcessManager.is_process_alive(
        process_mod.SandboxProcessHandle(
            raw_handle=_AliveFailExecHandle(),
            workdir="/workspace",
            script_rel="y.py",
        )
    )
    assert alive_on_probe_error is True


def test_user_adapter_error_paths(monkeypatch) -> None:
    def _always_import_error(module_name: str):  # type: ignore[no-untyped-def]
        _ = module_name
        raise ImportError("missing")

    monkeypatch.setattr(user_adapter_mod.importlib, "import_module", _always_import_error)
    assert user_adapter_mod._load_problem_adapter_module() is None
    with pytest.raises(RuntimeError, match="problem adapter module not found"):
        user_adapter_mod.get_adapter()

    mod_without_factory = types.SimpleNamespace()
    monkeypatch.setattr(user_adapter_mod, "_load_problem_adapter_module", lambda: mod_without_factory)
    with pytest.raises(RuntimeError, match="must provide get_adapter"):
        user_adapter_mod.get_adapter()

    mod_bad_factory = types.SimpleNamespace(get_adapter=lambda preset: object())
    monkeypatch.setattr(user_adapter_mod, "_load_problem_adapter_module", lambda: mod_bad_factory)
    with pytest.raises(RuntimeError, match="must return UserAdapter"):
        user_adapter_mod.get_adapter("default")

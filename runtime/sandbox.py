"""Sandbox environment, dependency, and transport helpers."""

from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any, Optional

from ..models import UserSubmission
from ..sandbox_backend import Sandbox
from ..transport import GrpcSandboxTransport, SandboxTransport


def write_files_chunked(sandbox: Sandbox, files: dict[str, bytes], base_dir: str) -> None:
    items = list(files.items())
    chunk_size = 200
    for i in range(0, len(items), chunk_size):
        chunk = items[i : i + chunk_size]
        payload = [{"path": f"{base_dir}/{path}", "data": data} for path, data in chunk]
        sandbox.write_files(payload)



def to_positive_int(raw: Any) -> Optional[int]:
    try:
        value = int(raw)
    except Exception:
        return None
    return value if value > 0 else None


def resolve_sandbox_resources(config: Any) -> tuple[Optional[int], Optional[int]]:
    cpu_count = to_positive_int(
        getattr(config, "sandbox_cpu_count", None) or getattr(config, "cpu_count", None)
    )
    memory_mb = to_positive_int(
        getattr(config, "memory_limit_mb", None)
        or getattr(config, "memory_limit_mib", None)
        or getattr(config, "memory_mb", None)
    )
    return cpu_count, memory_mb


def read_file_snippet(sandbox: Sandbox, path: str, max_bytes: int = 8192) -> str:
    if max_bytes <= 0:
        return ""
    cmd = (
        "python -c "
        + shlex.quote(
            "import pathlib,sys;"
            f"p=pathlib.Path({path!r});"
            f"n={int(max_bytes)};"
            "b=(p.read_bytes()[-n:] if p.exists() else b'');"
            "sys.stdout.write(b.decode('utf-8','ignore'))"
        )
    )
    try:
        r = sandbox.run_command(cmd, timeout=8)
        return (r.stdout or "")[:max_bytes]
    except Exception:
        return ""


def latest_mem_used_mib(sandbox: Sandbox) -> Optional[float]:
    try:
        metrics = sandbox.get_metrics()
    except Exception:
        return None
    if not metrics:
        return None
    last = metrics[-1]
    if isinstance(last, dict):
        raw = last.get("mem_used_mib") or last.get("memUsedMiB")
    else:
        raw = getattr(last, "mem_used_mib", None) or getattr(last, "memUsedMiB", None)
    try:
        return float(raw)
    except Exception:
        return None


def is_likely_mle_exit(config: Any, sandbox: Sandbox, stderr_path: str) -> bool:
    _, limit_mb = resolve_sandbox_resources(config)
    used_mib = latest_mem_used_mib(sandbox)
    if limit_mb and used_mib is not None:
        if used_mib >= float(limit_mb) * 0.98:
            return True

    stderr_text = read_file_snippet(sandbox, stderr_path, max_bytes=12000).lower()
    if not stderr_text:
        return False

    strong_keywords = (
        "memoryerror",
        "cannot allocate memory",
        "out of memory",
        "std::bad_alloc",
    )
    has_strong_signal = any(k in stderr_text for k in strong_keywords)
    if not has_strong_signal:
        return False

    if limit_mb and used_mib is not None:
        return used_mib >= float(limit_mb) * 0.85

    return True


# manufacturer -> default model for judge only (刷题端 user 自己指定，不注入)
# Keys must match backend db.validManufacturers / settings validManufacturers
_JUDGE_MANUFACTURER_MODEL: dict[str, str] = {
    "openai": "gpt-5.2",
    "google-gemini": "gemini-3-flash-preview",
    "anthropic": "claude-4.6-sonnet",
    "deepseek": "deepseek-chat",
    "qwen": "qwen-plus",
    "grok": "grok-4",
    "openrouter": "moonshotai/kimi-k2.5",
    "siliconflow": "Pro/moonshotai/Kimi-K2.5",
    "kimi": "kimi-k2.5",
    "minimax": "MiniMax-M2.5",
    "custom": "", # custom model is not supported now
}


def build_llm_env_vars(gateway_token: str, gateway_url: str) -> dict[str, str]:
    return {
        "LLM_GATEWAY_TOKEN": gateway_token,
        "LLM_GATEWAY_URL": gateway_url,
        "LLM_API_KEY": gateway_token,
        "LLM_BASE_URL": gateway_url,
        "OPENAI_API_KEY": gateway_token,
        "OPENAI_BASE_URL": gateway_url,
        "DEEPSEEK_API_KEY": gateway_token,
        "DEEPSEEK_BASE_URL": gateway_url,
        "QWEN_API_KEY": gateway_token,
        "QWEN_BASE_URL": gateway_url,
        "GROK_API_KEY": gateway_token,
        "GROK_BASE_URL": gateway_url,
        "GEMINI_API_KEY": gateway_token,
        "GEMINI_BASE_URL": gateway_url,
        "ANTHROPIC_API_KEY": gateway_token,
        "ANTHROPIC_BASE_URL": gateway_url,
        "SILICONFLOW_API_KEY": gateway_token,
        "SILICONFLOW_BASE_URL": gateway_url,
        "MOONSHOT_API_KEY": gateway_token,
        "MOONSHOT_BASE_URL": gateway_url,
        "MINIMAX_API_KEY": gateway_token,
        "MINIMAX_BASE_URL": gateway_url,
        "OPENROUTER_API_KEY": gateway_token,
        "OPENROUTER_BASE_URL": gateway_url,
    }


def _get_system_gateway_url() -> str:
    from ..config import get_config

    return str(get_config().sandbox_gateway_url or "")


def resolve_gateway_base_url(*, submission: UserSubmission) -> str:
    configured = _get_system_gateway_url().strip().rstrip("/")
    if not configured:
        raise ValueError(
            "Missing SANDBOX_GATEWAY_URL: when gateway token is enabled, "
            "set SANDBOX_GATEWAY_URL to a sandbox-reachable backend address "
            "(for example, http://172.17.0.1:8080)."
        )
    key_name = str(getattr(submission.runtime_config, "key_name", "") or "").strip()
    if not key_name:
        raise ValueError(
            "Missing runtime_config.key_name: gateway proxy requires key-specific route "
            "(/gateway/v1/keys/{key_name}/...)."
        )
    return f"{configured}/gateway/v1/keys/{key_name}"


def build_judge_envs(
    *,
    config: Any,
    submission: UserSubmission,
    get_client: Any,
    gateway_token: Optional[str] = None,
) -> dict[str, str]:
    envs: dict[str, str] = {
        "SUBMIT_ID": str(submission.submit_id),
        "PHASE_ID": str(submission.phase_id),
        "USER_ID": str(submission.user_id),
        "PHASE_CONFIG": json.dumps(config.model_dump(), ensure_ascii=False),
        "RUNTIME_CONFIG": json.dumps(submission.runtime_config.model_dump(), ensure_ascii=False),
        "PYTHONPATH": "/workspace/judge",
        "DUAL_SANDBOX_MODE": "judge",
        "PYTHONUNBUFFERED": "1",
    }
    extra_env = getattr(config, "judge_envs", {}) or {}
    if isinstance(extra_env, dict):
        for k, v in extra_env.items():
            if k and isinstance(v, (str, int, float, bool)):
                envs[str(k)] = str(v)
    if gateway_token:
        gateway_base_url = resolve_gateway_base_url(submission=submission)
        envs.update(build_llm_env_vars(gateway_token, gateway_base_url))
        llm_model = _resolve_judge_llm_model(submission, get_client)
        if llm_model:
            envs["LLM_MODEL"] = llm_model
    return envs


def _resolve_judge_llm_model(submission: UserSubmission, get_client: Any) -> Optional[str]:
    """Fetch key manufacturer and map to default model for judge only."""
    key_ids = getattr(submission.runtime_config, "key_ids", None) or []
    key_id = getattr(submission.runtime_config, "key_id", None)
    if not key_ids and key_id is not None:
        key_ids = [key_id]
    if not key_ids:
        return None
    try:
        client = get_client() if callable(get_client) else get_client
        info = client.get_key_info(submission.user_id, key_ids[0])
        if not info:
            return None
        mfr = (info.get("manufacturer") or "").strip().lower()
        return _JUDGE_MANUFACTURER_MODEL.get(mfr) if mfr else None
    except Exception:
        return None


def build_user_envs(
    *,
    config: Any,
    submission: UserSubmission,
    get_client: Any,
    gateway_token: Optional[str],
) -> dict[str, str]:
    envs: dict[str, str] = {
        "SUBMIT_ID": str(submission.submit_id),
        "PHASE_ID": str(submission.phase_id),
        "USER_ID": str(submission.user_id),
        "PHASE_CONFIG": json.dumps(config.model_dump(), ensure_ascii=False),
        "RUNTIME_CONFIG": json.dumps(submission.runtime_config.model_dump(), ensure_ascii=False),
        "PYTHONPATH": "/workspace/user",
        "DUAL_SANDBOX_MODE": "user",
        "PYTHONUNBUFFERED": "1",
    }
    extra_env = getattr(config, "judge_envs", {}) or {}
    if isinstance(extra_env, dict):
        for k, v in extra_env.items():
            if k and isinstance(v, (str, int, float, bool)):
                envs[str(k)] = str(v)
    if gateway_token:
        gateway_base_url = resolve_gateway_base_url(submission=submission)
        envs.update(build_llm_env_vars(gateway_token, gateway_base_url))
        llm_model = _resolve_judge_llm_model(submission, get_client)
        if llm_model:
            envs["LLM_MODEL"] = llm_model
    return envs


def load_grpc_bridge_support_files(base_file: str) -> dict[str, bytes]:
    root = Path(base_file).resolve().parent
    proto_base = root / "proto"
    runtime_base = root / "runtime"
    required = [
        (proto_base / "eval_bridge_pb2.py", "eval_bridge_pb2.py"),
        (proto_base / "eval_bridge_pb2_grpc.py", "eval_bridge_pb2_grpc.py"),
        (runtime_base / "judge_runtime.py", "eval_runtime/judge_runtime.py"),
        (runtime_base / "judge_scaffold.py", "eval_runtime/judge_scaffold.py"),
        (runtime_base / "multi_agent_scaffold.py", "eval_runtime/multi_agent_scaffold.py"),
        (runtime_base / "user_runtime.py", "eval_runtime/user_runtime.py"),
        (runtime_base / "user_adapter.py", "eval_runtime/user_adapter.py"),
    ]
    files: dict[str, bytes] = {"eval_runtime/__init__.py": b""}
    for path, target in required:
        if not path.exists():
            raise FileNotFoundError(f"missing grpc bridge support file: {path}")
        files[target] = path.read_bytes()
    return files


def create_grpc_transport(sandbox: Sandbox, port: int) -> SandboxTransport:
    """Create gRPC transport to sandbox bridge."""
    host = sandbox.get_host(int(port))
    if not host:
        raise RuntimeError(f"sandbox get_host returned empty host for port={port}")
    return GrpcSandboxTransport(host)

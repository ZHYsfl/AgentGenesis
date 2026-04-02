"""Top-level exports for the agent-genesis SDK package.

Lightweight imports (pydantic, requests only) are eager.
Server-heavy imports (docker, grpcio) are deferred via __getattr__
so that ``from agent_genesis import PhaseConfig`` works without
docker/grpcio installed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .dual_sandbox_evaluator import DualSandboxEvaluator

from .api import (
    create_config,
    create_phase,
    create_problem,
    init_registry,
    get_registry,
    register_problem,
    sync_problem,
    sync_all_problems,
    create_problem_revision,
    create_client,
    get_version_history,
    get_version_diff,
    list_revisions,
    create_revision,
    merge_revision,
    close_revision,
    get_data_export,
    get_phase_template,
    get_phase_files,
)

from .base import BaseEvaluator

from .models import (
    PhaseConfig,
    RuntimeConfig,
    CaseResult,
    PhaseResult,
    UserSubmission,
    CaseStatus,
    PhaseStatus,
    ProblemConfig,
)

from .client import EvaluationClient
from .registry import ProblemRegistry, build_artifact_from_dir, build_artifact_from_dirs
from .config import ClientMode

# ---- public API for problem authors (always importable) ----
__all__: list[str] = [
    # api helpers
    "create_config",
    "create_phase",
    "create_problem",
    "init_registry",
    "get_registry",
    "register_problem",
    "sync_problem",
    "sync_all_problems",
    "create_problem_revision",
    "create_client",
    "get_version_history",
    "get_version_diff",
    "list_revisions",
    "create_revision",
    "merge_revision",
    "close_revision",
    "get_data_export",
    "get_phase_template",
    "get_phase_files",
    # evaluator base
    "BaseEvaluator",
    "DualSandboxEvaluator",
    "IsolatedMultiAgentEvaluator",
    # v2: Shared multi-agent session (experimental)
    "SharedMultiAgentSession",
    "run_shared_multi_agent_session",
    "serve_shared_user_runtime",
    # models
    "PhaseConfig",
    "RuntimeConfig",
    "CaseResult",
    "PhaseResult",
    "UserSubmission",
    "CaseStatus",
    "PhaseStatus",
    "ProblemConfig",
    # client / registry
    "EvaluationClient",
    "ProblemRegistry",
    "build_artifact_from_dir",
    "build_artifact_from_dirs",
    "ClientMode",
    # tool-calling
    "Agent",
    "LLMConfig",
    "Tool",
    "batch",
]

# ---- server-only symbols: lazy-loaded on first access ----
# Avoids pulling in docker / grpcio / protobuf when only
# the lightweight SDK surface is used.

_SERVER_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "DualSandboxEvaluator": (".dual_sandbox_evaluator", "DualSandboxEvaluator"),
    "IsolatedMultiAgentEvaluator": (".isolated_evaluator", "IsolatedMultiAgentEvaluator"),
    # v2: Shared multi-agent session (experimental)
    "SharedMultiAgentSession": (".runtime.pair_session", "SharedMultiAgentSession"),
    "run_shared_multi_agent_session": (".runtime.pair_session", "run_shared_multi_agent_session"),
    "serve_shared_user_runtime": (".runtime.user_runtime", "serve_shared_user_runtime"),
    "EvaluationService": (".service", "EvaluationService"),
    "Sandbox": (".sandbox_backend", "Sandbox"),
    "DockerSandbox": (".sandbox_backend", "DockerSandbox"),
    "CommandResult": (".sandbox_backend", "CommandResult"),
    "ExecHandle": (".sandbox_backend", "ExecHandle"),
    "SandboxManager": (".sandbox_pool", "SandboxManager"),
    "SandboxBusyError": (".sandbox_pool", "SandboxBusyError"),
    "create_sandbox": (".sandbox_pool", "create_sandbox"),
    "destroy_sandbox": (".sandbox_pool", "destroy_sandbox"),
    "get_sandbox_stats": (".sandbox_pool", "get_sandbox_stats"),
    "MetricsCollector": (".health", "MetricsCollector"),
    "HealthServer": (".health", "HealthServer"),
    "get_metrics_collector": (".health", "get_metrics_collector"),
    "start_health_server": (".health", "start_health_server"),
    "stop_health_server": (".health", "stop_health_server"),
    "SystemConfig": (".config", "SystemConfig"),
    "get_config": (".config", "get_config"),
    # tool-calling exports (implemented in ../tool_calling)
    "Agent": (".tool_calling.async_tool_calling", "Agent"),
    "LLMConfig": (".tool_calling.async_tool_calling", "LLMConfig"),
    "Tool": (".tool_calling.async_tool_calling", "Tool"),
    "batch": (".tool_calling.batch", "batch"),
}


def __getattr__(name: str):  # noqa: ANN001
    if name in _SERVER_LAZY_IMPORTS:
        module_path, attr = _SERVER_LAZY_IMPORTS[name]
        import importlib
        mod = importlib.import_module(module_path, __package__)
        val = getattr(mod, attr)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


try:
    from importlib.metadata import version as _pkg_version, PackageNotFoundError as _PNF
    __version__: str = _pkg_version("agent-genesis")
except Exception:
    __version__ = "0.0.48"

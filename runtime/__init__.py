"""Runtime helper modules used by evaluator sessions and problem sandboxes."""
from __future__ import annotations

from .history import (
    attach_case_history,
    extract_history_events,
    record_action_history,
    record_observation_history,
)
from .process import SandboxProcessManager
from .protocol import MessageType, sanitize_user_message
from .results import parse_case_result
from .router import ProtocolRunState, run_pair_protocol_router
from .pair_session import PairSessionDeps, run_sandbox_pair_session

__all__ = [
    # session orchestration
    "MessageType",
    "SandboxProcessManager",
    "sanitize_user_message",
    "extract_history_events",
    "record_observation_history",
    "record_action_history",
    "attach_case_history",
    "parse_case_result",
    "ProtocolRunState",
    "run_pair_protocol_router",
    "PairSessionDeps",
    "run_sandbox_pair_session",
    # judge-side (used in sandbox/run.py) -- lazy, requires grpcio
    "JudgeRuntime",
    "serve_judge_runtime",
    "run_case_scheduler",
    "run_turn_based_case",
    "run_multi_agent_case",
    "send_eval_complete",
    # user-side (used in sandbox/user_adapter.py)
    "UserAdapter",
    "IsolatedAgentAdapter",
    # isolated multi-agent session
    "AgentSandboxSpec",
    "IsolatedSessionDeps",
    "IsolatedMultiAgentSession",
]

# Judge/scaffold symbols require grpcio which is only available inside
# the sandbox container, so we defer them to avoid ImportError on the
# worker side where grpcio IS present but we don't want to couple the
# import chain for lightweight SDK users.
_LAZY_RUNTIME_IMPORTS: dict[str, tuple[str, str]] = {
    "JudgeRuntime": (".judge_runtime", "JudgeRuntime"),
    "serve_judge_runtime": (".judge_runtime", "serve_judge_runtime"),
    "run_case_scheduler": (".judge_scaffold", "run_case_scheduler"),
    "run_turn_based_case": (".judge_scaffold", "run_turn_based_case"),
    "run_multi_agent_case": (".multi_agent_scaffold", "run_multi_agent_case"),
    "send_eval_complete": (".judge_scaffold", "send_eval_complete"),
    "UserAdapter": (".user_adapter", "UserAdapter"),
    "IsolatedAgentAdapter": (".isolated_adapter", "IsolatedAgentAdapter"),
    "AgentSandboxSpec": (".isolated_session", "AgentSandboxSpec"),
    "IsolatedSessionDeps": (".isolated_session", "IsolatedSessionDeps"),
    "IsolatedMultiAgentSession": (".isolated_session", "IsolatedMultiAgentSession"),
}


def __getattr__(name: str):  # noqa: ANN001
    if name in _LAZY_RUNTIME_IMPORTS:
        import importlib
        module_path, attr = _LAZY_RUNTIME_IMPORTS[name]
        mod = importlib.import_module(module_path, __package__)
        val = getattr(mod, attr)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

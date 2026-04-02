"""Dual-sandbox pair session lifecycle orchestration.

Each case runs in its own fresh judge + user container pair for full isolation.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from ..models import CaseResult, CaseStatus, PhaseConfig, UserSubmission
from ..sandbox_backend import Sandbox
from ..transport import SandboxTransport

from .router import run_pair_protocol_router

logger: logging.Logger = logging.getLogger(__name__)


@dataclass
class PairSessionDeps:
    create_sandbox: Callable[..., Sandbox]
    destroy_sandbox: Callable[[Sandbox], None]
    resolve_sandbox_resources: Callable[[], tuple[Optional[int], Optional[int]]]
    load_bridge_support_files: Callable[[], dict[str, bytes]]
    write_files_chunked: Callable[[Sandbox, dict[str, bytes], str], None]
    build_judge_envs: Callable[[UserSubmission, Optional[str]], dict[str, str]]
    build_user_envs: Callable[[UserSubmission, Optional[str]], dict[str, str]]
    resolve_entrypoint: Callable[[], str]
    start_background_python: Callable[..., Any]
    create_transport: Callable[[Sandbox, int], SandboxTransport]
    stop_process: Callable[[Optional[Any]], None]
    is_process_alive: Callable[[Optional[Any]], bool]
    describe_process: Callable[[Optional[Any]], str]
    is_likely_mle_exit: Callable[[Sandbox, str], bool]
    parse_case_result: Callable[[dict[str, Any], int], CaseResult]
    attach_case_history: Callable[[CaseResult, dict[int, list[dict[str, Any]]], int], None]
    record_observation_history: Callable[[dict[int, list[dict[str, Any]]], int, dict[str, Any]], None]
    record_action_history: Callable[[dict[int, list[dict[str, Any]]], int, dict[str, Any]], None]
    template_image: Optional[str] = None


class _SandboxPairSession:
    """Runs a single case in an isolated judge + user container pair."""

    def __init__(
        self,
        *,
        deps: PairSessionDeps,
        config: PhaseConfig,
        submission: UserSubmission,
        gateway_token: Optional[str],
        artifact_files: dict[str, bytes],
        user_files_bytes: dict[str, bytes],
        user_req_path: str,
        case_index: int,
        track_per_case_usage: bool,
        on_case_start: Optional[Callable[[int], None]],
        on_case_end: Optional[Callable[[int, CaseResult], None]],
        deadline: float,
        compute_step_deadline: Callable[[float], float],
        attach_llm_usage_delta: Optional[Callable[[CaseResult], CaseResult]],
    ) -> None:
        self.deps = deps
        self.config = config
        self.submission = submission
        self.gateway_token = gateway_token
        self.artifact_files = artifact_files
        self.user_files_bytes = user_files_bytes
        self.user_req_path = user_req_path
        self.case_index = case_index
        self.track_per_case_usage = track_per_case_usage
        self.on_case_start = on_case_start
        self.on_case_end = on_case_end
        self.deadline = deadline
        self.compute_step_deadline = compute_step_deadline
        self.attach_llm_usage_delta = attach_llm_usage_delta

        self.judge_sb: Optional[Sandbox] = None
        self.user_sb: Optional[Sandbox] = None
        self.judge_process: Optional[Any] = None
        self.user_process: Optional[Any] = None
        self.judge_transport: Optional[SandboxTransport] = None
        self.user_transport: Optional[SandboxTransport] = None
        self.result: Optional[CaseResult] = None

        self.logged_user_timeout_snapshot: bool = False
        self.logged_user_exit_snapshot: bool = False
        self.judge_envs: dict[str, str] = {}
        self.user_envs: dict[str, str] = {}
        self.user_port: int = 50052
        self._user_stderr_offset: int = 0
        self._judge_stderr_offset: int = 0  # For reading judge stderr logs

        # Optional event callbacks (for local evaluation)
        self._on_observation: Optional[Callable[[int, dict[str, Any]], None]] = None
        self._on_action: Optional[Callable[[int, dict[str, Any]], None]] = None
        self._on_user_log: Optional[Callable[[int, str], None]] = None
        self._on_judge_log: Optional[Callable[[int, str], None]] = None
        self._on_error: Optional[Callable[[int, str], None]] = None

    def run(self) -> CaseResult:
        try:
            self._setup_sandboxes_and_runtime()
            self._run_router()
            return self.result or CaseResult(
                case_index=self.case_index,
                status=CaseStatus.ERROR,
                score=0,
                error="no case result returned from session",
            )
        finally:
            self._cleanup()

    def _setup_sandboxes_and_runtime(self) -> None:
        cpu_count, memory_mb = self.deps.resolve_sandbox_resources()
        template_id = self.deps.template_image
        self.judge_sb = self.deps.create_sandbox(
            sandbox_timeout=int(self.config.sandbox_timeout),
            template_id=template_id,
            cpu_count=cpu_count,
            memory_mb=memory_mb,
        )
        self.user_sb = self.deps.create_sandbox(
            sandbox_timeout=int(self.config.sandbox_timeout),
            template_id=template_id,
            cpu_count=cpu_count,
            memory_mb=memory_mb,
        )

        logger.info(
            "[%s] case %d pair: judge=%s, user=%s",
            self.submission.submit_id,
            self.case_index,
            self.judge_sb.id,
            self.user_sb.id,
        )

        bridge_support_files = self.deps.load_bridge_support_files()
        self._prepare_judge_runtime(bridge_support_files)
        self._prepare_user_runtime(bridge_support_files)

        self.judge_envs = self.deps.build_judge_envs(self.submission, self.gateway_token)
        self.user_envs = self.deps.build_user_envs(self.submission, self.gateway_token)

        judge_port = 50051
        self.user_port = 50052
        self.judge_envs["SANDBOX_GRPC_PORT"] = str(judge_port)
        self.user_envs["SANDBOX_GRPC_PORT"] = str(self.user_port)

        entrypoint = self.deps.resolve_entrypoint()
        self.judge_process = self.deps.start_background_python(
            sandbox=self.judge_sb,
            workdir="/workspace/judge",
            script_rel=entrypoint,
            envs=self.judge_envs,
            stderr_path="/workspace/judge_stderr.log",
        )
        logger.info(
            "[daemon] started judge runtime: %s",
            self.deps.describe_process(self.judge_process),
        )

        self.judge_transport = self.deps.create_transport(self.judge_sb, judge_port)
        judge_ready_timeout = max(15, min(60, max(1, int(self.deadline - time.time()))))
        if not self.judge_transport.wait_for_ready(timeout=judge_ready_timeout):
            raise RuntimeError("judge bridge not ready")

        self.user_process = self.deps.start_background_python(
            sandbox=self.user_sb,
            workdir="/workspace/user",
            script_rel="_agent_wrapper.py",
            envs=self.user_envs,
            stderr_path="/workspace/user_stderr.log",
        )
        logger.info(
            "[daemon] started user runtime: %s",
            self.deps.describe_process(self.user_process),
        )

        self.user_transport = self.deps.create_transport(self.user_sb, self.user_port)
        user_ready_timeout = max(3, min(30, max(1, int(self.deadline - time.time()))))
        if not self.user_transport.wait_for_ready(timeout=user_ready_timeout):
            self._log_user_runtime_snapshot("probe_timeout")
            raise RuntimeError("user bridge not ready")

    def _prepare_judge_runtime(self, bridge_support_files: dict[str, bytes]) -> None:
        assert self.judge_sb is not None
        self.judge_sb.run_command(
            "mkdir -p /workspace/judge && chmod 777 /workspace",
            timeout=30,
        )
        judge_runtime_files = dict(self.artifact_files)
        judge_runtime_files.update(bridge_support_files)
        self.deps.write_files_chunked(self.judge_sb, judge_runtime_files, "/workspace/judge")

    def _prepare_user_runtime(self, bridge_support_files: dict[str, bytes]) -> None:
        assert self.user_sb is not None
        self.user_sb.run_command(
            "mkdir -p /workspace/user && chmod 777 /workspace",
            timeout=30,
        )
        user_runtime_files = dict(self.user_files_bytes)
        user_runtime_files.update(bridge_support_files)
        self.deps.write_files_chunked(self.user_sb, user_runtime_files, "/workspace/user")
        if self.user_req_path:
            self.user_sb.run_command(
                f"cd /workspace && source .venv/bin/activate && "
                f"uv pip install -r /workspace/user/{self.user_req_path} -q",
                timeout=int(self.config.user_deps_timeout),
            )

    def _read_user_stderr_delta(self) -> str:
        """Read new user stderr content since last call."""
        if not self.user_sb:
            return ""
        try:
            offset = self._user_stderr_offset + 1
            r = self.user_sb.run_command(
                f"tail -c +{offset} /workspace/user_stderr.log 2>/dev/null || true",
                timeout=6,
            )
            content = r.stdout or ""
            if content:
                self._user_stderr_offset += len(content.encode("utf-8", "replace"))
            return content
        except Exception:
            return ""

    def _read_judge_stderr_delta(self) -> str:
        """Read new judge stderr content since last call."""
        if not self.judge_sb:
            return ""
        try:
            offset = self._judge_stderr_offset + 1
            r = self.judge_sb.run_command(
                f"tail -c +{offset} /workspace/judge_stderr.log 2>/dev/null || true",
                timeout=6,
            )
            content = r.stdout or ""
            if content:
                self._judge_stderr_offset += len(content.encode("utf-8", "replace"))
            return content
        except Exception:
            return ""

    def set_event_callbacks(
        self,
        on_observation: Optional[Callable[[int, dict[str, Any]], None]] = None,
        on_action: Optional[Callable[[int, dict[str, Any]], None]] = None,
        on_user_log: Optional[Callable[[int, str], None]] = None,
        on_judge_log: Optional[Callable[[int, str], None]] = None,
        on_error: Optional[Callable[[int, str], None]] = None,
    ) -> None:
        """Set event callbacks for local evaluation.

        These callbacks are optional and only used by local evaluation SDK.
        Remote evaluation service does not use these callbacks.
        """
        self._on_observation = on_observation
        self._on_action = on_action
        self._on_user_log = on_user_log
        self._on_judge_log = on_judge_log
        self._on_error = on_error

    def _wrap_on_case_end(
        self, original: Optional[Callable[[int, CaseResult], None]]
    ) -> Optional[Callable[[int, CaseResult], None]]:
        if original is None:
            return None

        def wrapped(idx: int, result: CaseResult) -> None:
            stderr_delta = self._read_user_stderr_delta()
            if stderr_delta.strip():
                try:
                    history = json.loads(result.logs) if result.logs else []
                except (json.JSONDecodeError, TypeError):
                    history = []
                history.append({"kind": "user_output", "payload": stderr_delta})
                result.logs = json.dumps(history, ensure_ascii=False)
            original(idx, result)

        return wrapped

    def _run_router(self) -> None:
        case_served = [False]

        def case_provider() -> Optional[int]:
            if not case_served[0]:
                case_served[0] = True
                return self.case_index
            return None

        # Wrap send functions to capture stderr logs
        def wrapped_send_to_user(msg: dict[str, Any], timeout: int) -> None:
            # Check user stderr before sending
            if self._on_user_log:
                user_log = self._read_user_stderr_delta()
                if user_log.strip():
                    self._on_user_log(self.case_index, user_log)
            self._send_to_user(msg, timeout)

        def wrapped_send_to_judge(msg: dict[str, Any], timeout: int) -> None:
            # Check judge stderr before sending
            if self._on_judge_log:
                judge_log = self._read_judge_stderr_delta()
                if judge_log.strip():
                    self._on_judge_log(self.case_index, judge_log)
            self._send_to_judge(msg, timeout)

        route_state = run_pair_protocol_router(
            submission_id=self.submission.submit_id,
            deadline=self.deadline,
            case_provider=case_provider,
            compute_step_deadline=self.compute_step_deadline,
            poll_judge_line=self._poll_judge_line,
            restart_user_runtime=lambda: None,
            ensure_user_runtime=lambda: None,
            request_user_action=self._request_user_action,
            send_to_judge=wrapped_send_to_judge,
            send_to_user=wrapped_send_to_user,
            parse_case_result=self.deps.parse_case_result,
            attach_case_history=self.deps.attach_case_history,
            record_observation_history=self.deps.record_observation_history,
            record_action_history=self.deps.record_action_history,
            on_case_start=self.on_case_start,
            on_case_end=self._wrap_on_case_end(self.on_case_end),
            track_per_case_usage=self.track_per_case_usage,
            attach_llm_usage_delta=self.attach_llm_usage_delta,
            # Optional callbacks for local evaluation
            on_observation=self._on_observation,
            on_action=self._on_action,
            on_error=self._on_error,
        )
        if route_state.cases:
            self.result = route_state.cases[0]

    def _poll_judge_line(self, stop_deadline: float) -> tuple[Optional[str], bool]:
        if not self.judge_transport:
            return None, True
        return self._poll_transport_line(
            transport=self.judge_transport,
            process=self.judge_process,
            stop_deadline=stop_deadline,
            poll_seconds=3,
        )

    def _poll_transport_line(
        self,
        *,
        transport: SandboxTransport,
        process: Optional[Any],
        stop_deadline: float,
        poll_seconds: int,
    ) -> tuple[Optional[str], bool]:
        """Poll transport for a message until deadline or process exit."""
        while True:
            remaining = stop_deadline - time.time()
            if remaining <= 0:
                return None, False
            slice_timeout = max(1, int(min(float(poll_seconds), remaining)))
            try:
                line = transport.recv_message(timeout=slice_timeout)
            except Exception:
                if not self.deps.is_process_alive(process):
                    return None, True
                return None, False
            if line is not None:
                return line, False
            if not self.deps.is_process_alive(process):
                return None, True

    def _request_user_action(self, trigger_msg: dict[str, Any]) -> dict[str, Any]:
        user_msg = dict(trigger_msg)
        user_msg.pop("history_events", None)
        if not self.user_transport:
            return {
                "type": "action",
                "error": "user transport unavailable",
                "status": "error",
            }

        remaining = max(1, int(self.deadline - time.time()))
        try:
            self.user_transport.send_message(user_msg, timeout=remaining)
        except Exception as exc:
            return {
                "type": "action",
                "error": f"user transport send failed: {type(exc).__name__}: {exc}",
                "status": "error",
            }

        user_wait_deadline = self.compute_step_deadline(self.deadline)
        user_line, user_process_exited = self._poll_transport_line(
            transport=self.user_transport,
            process=self.user_process,
            stop_deadline=user_wait_deadline,
            poll_seconds=2,
        )
        if user_line is None:
            if user_process_exited:
                self._log_user_runtime_snapshot("process_exited")
                assert self.user_sb is not None
                is_mle = self.deps.is_likely_mle_exit(
                    self.user_sb,
                    "/workspace/user_stderr.log",
                )
                action_msg: dict[str, Any] = {
                    "type": "action",
                    "error": "user process exited",
                    "status": "error",
                }
                if is_mle:
                    action_msg["status"] = "mle"
                    action_msg["error"] = "user process exited (mle)"
                return action_msg
            action_msg = {
                "type": "action",
                "error": (
                    "user idle timeout"
                    if user_wait_deadline < self.deadline
                    else "user timeout"
                ),
                "status": "tle",
            }
            self._log_user_runtime_snapshot(action_msg["error"])
            return action_msg

        try:
            action_msg = json.loads(user_line)
        except Exception:
            action_msg = {
                "type": "action",
                "error": f"invalid user output: {user_line[:200]}",
                "status": "error",
            }
        if action_msg.get("error") and "status" not in action_msg:
            action_msg["status"] = "error"
        return action_msg

    def _send_to_judge(self, msg: dict[str, Any], timeout: int) -> None:
        if not self.judge_transport:
            raise RuntimeError("judge transport unavailable")
        self.judge_transport.send_message(msg, timeout=timeout)

    def _send_to_user(self, msg: dict[str, Any], timeout: int) -> None:
        if not self.user_transport:
            raise RuntimeError("user transport unavailable")
        self.user_transport.send_message(msg, timeout=timeout)

    def _log_user_runtime_snapshot(self, reason: str) -> None:
        if reason == "process_exited":
            if self.logged_user_exit_snapshot:
                return
            self.logged_user_exit_snapshot = True
        elif reason in ("user idle timeout", "user timeout"):
            if self.logged_user_timeout_snapshot:
                return
            self.logged_user_timeout_snapshot = True

        stderr_snippet = ""
        process_desc = self.deps.describe_process(self.user_process)
        try:
            assert self.user_sb is not None
            r_stderr = self.user_sb.run_command(
                "tail -c 8192 /workspace/user_stderr.log 2>/dev/null || true",
                timeout=6,
            )
            stderr_text = r_stderr.stdout or ""
            stderr_snippet = stderr_text.strip().replace("\n", "\\n")
            if len(stderr_snippet) > 600:
                stderr_snippet = f"{stderr_snippet[:600]}...(truncated)"
        except Exception:
            pass

        logger.warning(
            "[%s] user runtime snapshot (%s): process=%s, stderr=%r",
            self.submission.submit_id,
            reason,
            process_desc,
            stderr_snippet,
        )

    def _cleanup(self) -> None:
        for transport in [self.judge_transport, self.user_transport]:
            try:
                if transport:
                    transport.close()
            except Exception:
                pass

        if self.result is None:
            for label, sb, stderr_path, process in [
                ("judge", self.judge_sb, "/workspace/judge_stderr.log", self.judge_process),
                ("user", self.user_sb, "/workspace/user_stderr.log", self.user_process),
            ]:
                try:
                    if sb:
                        r = sb.run_command(
                            f"tail -c 4096 {stderr_path} 2>/dev/null || echo '[file not found]'",
                            timeout=10,
                        )
                        snippet = (r.stdout or "").strip()
                        if snippet and snippet != "[file not found]":
                            logger.error(
                                "[%s] %s stderr (%s): %s",
                                self.submission.submit_id,
                                label,
                                self.deps.describe_process(process),
                                snippet[:2000],
                            )
                        else:
                            logger.warning(
                                "[%s] %s stderr empty or missing (%s)",
                                self.submission.submit_id,
                                label,
                                self.deps.describe_process(process),
                            )
                except Exception as diag_err:
                    logger.warning(
                        "[%s] %s diag failed: %s",
                        self.submission.submit_id,
                        label,
                        diag_err,
                    )

        for process in [self.judge_process, self.user_process]:
            try:
                self.deps.stop_process(process)
            except Exception:
                pass
        for sb in [self.judge_sb, self.user_sb]:
            try:
                if sb:
                    self.deps.destroy_sandbox(sb)
            except Exception:
                pass


def run_sandbox_pair_session(
    *,
    deps: PairSessionDeps,
    config: PhaseConfig,
    submission: UserSubmission,
    gateway_token: Optional[str],
    artifact_files: dict[str, bytes],
    user_files_bytes: dict[str, bytes],
    user_req_path: str,
    case_index: int,
    track_per_case_usage: bool,
    on_case_start: Optional[Callable[[int], None]],
    on_case_end: Optional[Callable[[int, CaseResult], None]],
    deadline: float,
    compute_step_deadline: Callable[[float], float],
    attach_llm_usage_delta: Optional[Callable[[CaseResult], CaseResult]],
) -> CaseResult:
    session = _SandboxPairSession(
        deps=deps,
        config=config,
        submission=submission,
        gateway_token=gateway_token,
        artifact_files=artifact_files,
        user_files_bytes=user_files_bytes,
        user_req_path=user_req_path,
        case_index=case_index,
        track_per_case_usage=track_per_case_usage,
        on_case_start=on_case_start,
        on_case_end=on_case_end,
        deadline=deadline,
        compute_step_deadline=compute_step_deadline,
        attach_llm_usage_delta=attach_llm_usage_delta,
    )
    return session.run()


# =============================================================================
# Shared Multi-Agent Session (v2)
# =============================================================================
# This is for v2 protocol: multiple agents in the same User sandbox,
# sharing memory but with separate gRPC ports.


from concurrent.futures import ThreadPoolExecutor
from concurrent import futures


@dataclass
class SharedMultiAgentSessionDeps:
    """Dependencies for shared multi-agent session."""
    create_sandbox: Callable[..., Sandbox]
    load_bridge_support_files: Callable[[], dict[str, bytes]]
    create_transport: Callable[[Sandbox, int], SandboxTransport]
    is_process_alive: Callable[[Any], bool]
    is_likely_mle_exit: Callable[[Sandbox, str], bool]
    describe_process: Callable[[Any], str]
    stop_process: Callable[[Any], None]
    destroy_sandbox: Callable[[Sandbox], None]


class SharedMultiAgentSession:
    """Session for v2 shared multi-agent protocol.

    This runs multiple agents in the same User sandbox container,
    each connecting via separate gRPC ports.
    """

    def __init__(
        self,
        *,
        deps: SharedMultiAgentSessionDeps,
        config: PhaseConfig,
        submission: UserSubmission,
        gateway_token: Optional[str],
        artifact_files: dict[str, bytes],
        user_files_bytes: dict[str, bytes],
        user_req_path: str,
        case_index: int,
        track_per_case_usage: bool,
        on_case_start: Optional[Callable[[int], None]],
        on_case_end: Optional[Callable[[int, CaseResult], None]],
        deadline: float,
        compute_step_deadline: Callable[[float], float],
        attach_llm_usage_delta: Optional[Callable[[CaseResult], CaseResult]],
        agent_ids: list[str],
        solve_entry_map: dict[str, str],
    ):
        self.deps = deps
        self.config = config
        self.submission = submission
        self.gateway_token = gateway_token
        self.artifact_files = artifact_files
        self.user_files_bytes = user_files_bytes
        self.user_req_path = user_req_path
        self.case_index = case_index
        self.track_per_case_usage = track_per_case_usage
        self.on_case_start = on_case_start
        self.on_case_end = on_case_end
        self.deadline = deadline
        self.compute_step_deadline = compute_step_deadline
        self.attach_llm_usage_delta = attach_llm_usage_delta

        # v2 specific
        self.agent_ids = agent_ids
        self.solve_entry_map = solve_entry_map

        self.judge_sb: Optional[Sandbox] = None
        self.user_sb: Optional[Sandbox] = None
        self.judge_process: Optional[Any] = None
        self.user_process: Optional[Any] = None

        self.judge_transport: Optional[SandboxTransport] = None
        self.agent_transports: dict[str, SandboxTransport] = {}

        self.base_port = 50052  # Base port for agents

        self.result: Optional[CaseResult] = None
        self.logged_judge_exit_snapshot = False
        self.logged_user_exit_snapshot = False
        self.logged_user_timeout_snapshot = False

    def run(self) -> CaseResult:
        """Run the session."""
        try:
            self._setup_sandboxes_and_runtime()
            self._run_protocol()
        except Exception as exc:
            logger.exception("[%d] session failed: %s", self.submission.submit_id, exc)
            self.result = CaseResult(
                case_index=self.case_index,
                status=CaseStatus.ERROR,
                error_message=str(exc),
            )
        finally:
            self._cleanup()

        if self.on_case_end:
            self.on_case_end(self.case_index, self.result)

        return self.result

    def _setup_sandboxes_and_runtime(self) -> None:
        """Set up sandboxes and start runtimes."""
        # Same as v1: 1 judge + 1 user container
        template_id = self.config.artifact_entry or "default"
        cpu_count = self.config.sandbox_cpu_count
        memory_mb = self.config.memory_limit_mb or 512

        bridge_support_files = self.deps.load_bridge_support_files()

        # Create judge sandbox
        self.judge_sb = self.deps.create_sandbox(
            sandbox_timeout=int(self.config.sandbox_timeout),
            template_id=template_id,
            cpu_count=cpu_count,
            memory_mb=memory_mb,
        )

        # Create user sandbox (shared by all agents)
        self.user_sb = self.deps.create_sandbox(
            sandbox_timeout=int(self.config.sandbox_timeout),
            template_id=template_id,
            cpu_count=cpu_count,
            memory_mb=memory_mb,
        )

        judge_port = 50051

        judge_envs = dict(self.config.judge_envs or {})
        judge_envs["SANDBOX_GRPC_PORT"] = str(judge_port)
        judge_envs["EVAL_GATEWAY_TOKEN"] = self.gateway_token or ""

        # User envs - tell it to use shared multi-agent mode
        user_envs = {}
        user_envs["SANDBOX_GRPC_PORT"] = str(self.base_port)
        user_envs["SHARED_MULTI_AGENT"] = "1"
        user_envs["AGENT_IDS"] = ",".join(self.agent_ids)

        self.judge_process, _ = self.judge_sb.run_command(
            "python -m evaluation.runtime.judge_runtime",
            envs=judge_envs,
            cwd="/workspace",
        )

        # Prepare user runtime with multi-agent support
        user_runtime_files = dict(bridge_support_files)
        from .. import dual_sandbox_evaluator
        user_runtime_files["_agent_wrapper.py"] = dual_sandbox_evaluator._generate_managed_user_bridge(
            solve_attr_name=self.solve_attr_name(),
            adapter_preset="shared_multi_agent",
            agent_ids=self.agent_ids,
            solve_entry_map=self.solve_entry_map,
        ).encode()

        # Upload user files
        for path, content in user_runtime_files.items():
            self.user_sb.upload(path, content)
        for path, content in self.artifact_files.items():
            self.user_sb.upload(path, content)
        for path, content in self.user_files_bytes.items():
            self.user_sb.upload(path, content)

        # Start user runtime with shared multi-agent mode
        import os
        user_envs["EVAL_RUNTIME"] = "shared_multi_agent"
        self.user_process, _ = self.user_sb.run_command(
            f"python -c 'from evaluation.runtime.user_runtime import serve_shared_user_runtime; "
            f"agent_ids={self.agent_ids}; "
            f"solve_attr_names={self.solve_entry_map}; "
            f"serve_shared_user_runtime(agent_ids=agent_ids, solve_attr_names=solve_attr_names, base_port={self.base_port})'",
            envs=user_envs,
            cwd="/workspace",
            script_rel="_agent_wrapper.py",
        )

        # Wait for judge to be ready
        self.judge_transport = self.deps.create_transport(self.judge_sb, judge_port)
        judge_ready_timeout = 60
        if not self.judge_transport.wait_for_ready(timeout=judge_ready_timeout):
            raise RuntimeError("judge not ready")

        # Wait for each agent port to be ready
        for idx, agent_id in enumerate(self.agent_ids):
            port = self.base_port + idx
            transport = self.deps.create_transport(self.user_sb, port)
            if not transport.wait_for_ready(timeout=judge_ready_timeout):
                raise RuntimeError(f"agent {agent_id} not ready on port {port}")
            self.agent_transports[agent_id] = transport

    def solve_attr_name(self) -> str:
        """Get the solve attribute name for v2."""
        # In v2, each agent has its own solve function
        return self.solve_entry_map.get(self.agent_ids[0], "solve")

    def _run_protocol(self) -> None:
        """Run the protocol loop."""
        if self.on_case_start:
            self.on_case_start(self.case_index)

        from .router import run_pair_protocol_router
        from .router import MessageType

        self.result = run_pair_protocol_router(
            send_to_judge=self._send_to_judge,
            recv_from_judge=self._recv_from_judge,
            send_to_user=self._send_to_user,
            request_user_action=self._request_user_action,
            compute_step_deadline=self.compute_step_deadline,
            deadline=self.deadline,
            trace=self.submission.submit_id,
            case_index=self.case_index,
            on_result=self._on_case_result,
            attach_llm_usage_delta=self.attach_llm_usage_delta,
        )

    def _send_to_judge(self, msg: dict[str, Any], timeout: int) -> None:
        if not self.judge_transport:
            raise RuntimeError("judge transport unavailable")
        self.judge_transport.send_message(msg, timeout=timeout)

    def _recv_from_judge(self) -> tuple[Optional[str], bool]:
        if not self.judge_transport:
            return None, True
        return self._poll_judge_line()

    def _poll_judge_line(self) -> tuple[Optional[str], bool]:
        from .router import poll_judge_line
        return poll_judge_line(
            transport=self.judge_transport,
            process=self.judge_process,
            deadline=self.deadline,
        )

    def _send_to_user(self, msg: dict[str, Any], timeout: int) -> None:
        """Broadcast message to all agents (Fan-out)."""
        obs = msg.get("data", "")

        # Check if this is a dict (per-agent observation) or a string (broadcast)
        if isinstance(obs, dict):
            # Per-agent observation - each agent gets their specific obs
            for agent_id, transport in self.agent_transports.items():
                agent_obs = obs.get(agent_id, "")
                try:
                    transport.send_message(
                        {"type": "observation", "data": agent_obs},
                        timeout=timeout,
                    )
                except Exception as e:
                    logger.warning(f"Failed to send to agent {agent_id}: {e}")
        else:
            # Broadcast - all agents get the same observation
            for agent_id, transport in self.agent_transports.items():
                try:
                    transport.send_message(
                        {"type": "observation", "data": obs},
                        timeout=timeout,
                    )
                except Exception as e:
                    logger.warning(f"Failed to broadcast to agent {agent_id}: {e}")

    def _request_user_action(self, trigger_msg: dict[str, Any]) -> dict[str, Any]:
        """Collect actions from all agents (Fan-in)."""
        # Remove history events
        trigger_msg = dict(trigger_msg)
        trigger_msg.pop("history_events", None)

        # Send action_request to all agents
        for agent_id, transport in self.agent_transports.items():
            try:
                transport.send_message(trigger_msg, timeout=30)
            except Exception as e:
                logger.warning(f"Failed to request action from {agent_id}: {e}")

        # Collect responses from all agents (parallel)
        results: dict[str, Any] = {}
        remaining = max(1, int(self.deadline - time.time()))

        def collect_one(agent_id: str, transport: SandboxTransport) -> tuple[str, dict[str, Any]]:
            try:
                line, _ = self._poll_agent_line(transport, self.user_process, self.deadline)
                if line:
                    return agent_id, json.loads(line)
                return agent_id, {"type": "action", "error": "timeout", "status": "tle"}
            except Exception as e:
                return agent_id, {"type": "action", "error": str(e), "status": "error"}

        with ThreadPoolExecutor(max_workers=len(self.agent_ids)) as pool:
            futures = {
                pool.submit(collect_one, aid, trans): aid
                for aid, trans in self.agent_transports.items()
            }
            for fut in futures.as_completed(futures):
                aid, result = fut.result()
                results[aid] = result

        # Aggregate results into action_dict
        action_dict = {}
        errors = []
        for agent_id, result in results.items():
            if result.get("error"):
                errors.append(f"{agent_id}: {result.get('error')}")
            action_dict[agent_id] = result.get("data")

        if errors:
            return {
                "type": "action",
                "data": action_dict,
                "error": "; ".join(errors),
                "status": "error",
            }

        return {"type": "action", "data": action_dict}

    def _poll_agent_line(
        self,
        transport: SandboxTransport,
        process: Any,
        deadline: float,
    ) -> tuple[Optional[str], bool]:
        """Poll for a message from an agent."""
        while True:
            remaining = max(1, int(deadline - time.time()))
            if remaining <= 0:
                return None, False

            try:
                line = transport.recv_message(timeout=min(remaining, 10))
            except Exception:
                if not self.deps.is_process_alive(process):
                    return None, True
                return None, False
            if line is not None:
                return line, False
            if not self.deps.is_process_alive(process):
                return None, True

    def _on_case_result(self, result: CaseResult) -> None:
        self.result = result

    def _cleanup(self) -> None:
        """Clean up resources."""
        if self.result is None:
            pass  # Add diagnostics if needed

        for process in [self.judge_process, self.user_process]:
            try:
                self.deps.stop_process(process)
            except Exception:
                pass
        for sb in [self.judge_sb, self.user_sb]:
            try:
                if sb:
                    self.deps.destroy_sandbox(sb)
            except Exception:
                pass


def run_shared_multi_agent_session(
    *,
    deps: SharedMultiAgentSessionDeps,
    config: PhaseConfig,
    submission: UserSubmission,
    gateway_token: Optional[str],
    artifact_files: dict[str, bytes],
    user_files_bytes: dict[str, bytes],
    user_req_path: str,
    case_index: int,
    track_per_case_usage: bool,
    on_case_start: Optional[Callable[[int], None]],
    on_case_end: Optional[Callable[[int, CaseResult], None]],
    deadline: float,
    compute_step_deadline: Callable[[float], float],
    attach_llm_usage_delta: Optional[Callable[[CaseResult], CaseResult]],
    agent_ids: list[str],
    solve_entry_map: dict[str, str],
) -> CaseResult:
    """Run a shared multi-agent session (v2 protocol)."""
    session = SharedMultiAgentSession(
        deps=deps,
        config=config,
        submission=submission,
        gateway_token=gateway_token,
        artifact_files=artifact_files,
        user_files_bytes=user_files_bytes,
        user_req_path=user_req_path,
        case_index=case_index,
        track_per_case_usage=track_per_case_usage,
        on_case_start=on_case_start,
        on_case_end=on_case_end,
        deadline=deadline,
        compute_step_deadline=compute_step_deadline,
        attach_llm_usage_delta=attach_llm_usage_delta,
        agent_ids=agent_ids,
        solve_entry_map=solve_entry_map,
    )
    return session.run()


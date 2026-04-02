"""Isolated multi-agent session: 1 Judge + N per-agent sandboxes.

Each agent runs in its own OS-level container with a standard v1
single-agent bridge.  The fan-in / fan-out logic lives entirely in
this session layer so that the existing ``run_pair_protocol_router``
can be reused without modification.
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ..models import CaseResult, CaseStatus, PhaseConfig, UserSubmission
from ..sandbox_backend import Sandbox
from ..transport import SandboxTransport

from .router import run_pair_protocol_router

logger: logging.Logger = logging.getLogger(__name__)


@dataclass
class AgentSandboxSpec:
    """Describes one agent sandbox to create."""
    agent_id: str
    code_files: dict[str, bytes]
    env_overrides: dict[str, str] = field(default_factory=dict)
    requirements_path: str = ""


@dataclass
class IsolatedSessionDeps:
    """Dependency-injection bag (mirrors PairSessionDeps)."""
    create_sandbox: Callable[..., Sandbox]
    destroy_sandbox: Callable[[Sandbox], None]
    resolve_sandbox_resources: Callable[[], tuple[Optional[int], Optional[int]]]
    load_bridge_support_files: Callable[[], dict[str, bytes]]
    write_files_chunked: Callable[[Sandbox, dict[str, bytes], str], None]
    build_judge_envs: Callable[[UserSubmission, Optional[str]], dict[str, str]]
    build_agent_envs: Callable[[UserSubmission, Optional[str]], dict[str, str]]
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


class IsolatedMultiAgentSession:
    """Run a single case with 1 judge sandbox + N isolated agent sandboxes."""

    def __init__(
        self,
        *,
        deps: IsolatedSessionDeps,
        config: PhaseConfig,
        submission: UserSubmission,
        agent_specs: list[AgentSandboxSpec],
        judge_artifact_files: dict[str, bytes],
        judge_envs_base: dict[str, str],
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
        self.agent_specs = agent_specs
        self.judge_artifact_files = judge_artifact_files
        self.judge_envs_base = judge_envs_base
        self.gateway_token: Optional[str] = judge_envs_base.get("LLM_GATEWAY_TOKEN")
        self.case_index = case_index
        self.track_per_case_usage = track_per_case_usage
        self.on_case_start = on_case_start
        self.on_case_end = on_case_end
        self.deadline = deadline
        self.compute_step_deadline = compute_step_deadline
        self.attach_llm_usage_delta = attach_llm_usage_delta

        self.judge_sb: Optional[Sandbox] = None
        self.judge_process: Optional[Any] = None
        self.judge_transport: Optional[SandboxTransport] = None

        self.agent_sandboxes: dict[str, Sandbox] = {}
        self.agent_processes: dict[str, Any] = {}
        self.agent_transports: dict[str, SandboxTransport] = {}

        self.result: Optional[CaseResult] = None
        self._agent_stderr_offsets: dict[str, int] = {}  # per-agent stderr byte offset

    def run(self) -> CaseResult:
        try:
            self._setup_sandboxes_and_runtime()
            self._run_router()
            result = self.result or CaseResult(
                case_index=self.case_index,
                status=CaseStatus.ERROR,
                score=0,
                error="no case result returned from isolated session",
            )
            if result.status != CaseStatus.PASSED:
                logger.warning(
                    "[%d] case finished: status=%s score=%s error=%s",
                    self.case_index, result.status, result.score,
                    result.error or "(none)",
                )
            else:
                logger.info("[%d] case passed: score=%s", self.case_index, result.score)
            return result
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

        logger.info(
            "[%s] isolated session case %d: judge=%s, agents=%s",
            self.submission.submit_id,
            self.case_index,
            self.judge_sb.id,
            [s.agent_id for s in self.agent_specs],
        )

        bridge_support_files = self.deps.load_bridge_support_files()
        self._prepare_judge_runtime(bridge_support_files)

        judge_port = 50051
        judge_envs = dict(self.judge_envs_base)
        judge_envs["SANDBOX_GRPC_PORT"] = str(judge_port)

        entrypoint = self.deps.resolve_entrypoint()
        self.judge_process = self.deps.start_background_python(
            sandbox=self.judge_sb,
            workdir="/workspace/judge",
            script_rel=entrypoint,
            envs=judge_envs,
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

        agent_port = 50052
        for spec in self.agent_specs:
            sb = self.deps.create_sandbox(
                sandbox_timeout=int(self.config.sandbox_timeout),
                template_id=template_id,
                cpu_count=cpu_count,
                memory_mb=memory_mb,
            )
            self.agent_sandboxes[spec.agent_id] = sb
            self._prepare_agent(sb, spec, bridge_support_files)

            agent_envs = dict(self.deps.build_agent_envs(self.submission, self.gateway_token))
            agent_envs["SANDBOX_GRPC_PORT"] = str(agent_port)
            agent_envs["AGENT_ID"] = spec.agent_id
            agent_envs.update(spec.env_overrides)

            proc = self.deps.start_background_python(
                sandbox=sb,
                workdir="/workspace/user",
                script_rel="_agent_wrapper.py",
                envs=agent_envs,
                stderr_path="/workspace/user_stderr.log",
            )
            self.agent_processes[spec.agent_id] = proc
            logger.info(
                "[daemon] started agent %s runtime: %s",
                spec.agent_id,
                self.deps.describe_process(proc),
            )

            transport = self.deps.create_transport(sb, agent_port)
            agent_ready_timeout = max(3, min(30, max(1, int(self.deadline - time.time()))))
            if not transport.wait_for_ready(timeout=agent_ready_timeout):
                raise RuntimeError(
                    f"agent bridge not ready for {spec.agent_id}"
                )
            self.agent_transports[spec.agent_id] = transport

    def _prepare_judge_runtime(self, bridge_support_files: dict[str, bytes]) -> None:
        assert self.judge_sb is not None
        self.judge_sb.run_command(
            "mkdir -p /workspace/judge && chmod 777 /workspace",
            timeout=30,
        )
        judge_runtime_files = dict(self.judge_artifact_files)
        judge_runtime_files.update(bridge_support_files)
        self.deps.write_files_chunked(self.judge_sb, judge_runtime_files, "/workspace/judge")

    def _prepare_agent(self, sb: Sandbox, spec: AgentSandboxSpec, bridge_support_files: dict[str, bytes]) -> None:
        sb.run_command(
            "mkdir -p /workspace/user && chmod 777 /workspace",
            timeout=30,
        )
        agent_files = dict(spec.code_files)
        agent_files.update(bridge_support_files)
        self.deps.write_files_chunked(sb, agent_files, "/workspace/user")
        if spec.requirements_path:
            sb.run_command(
                f"cd /workspace && source .venv/bin/activate && "
                f"uv pip install -r /workspace/user/{spec.requirements_path} -q",
                timeout=int(self.config.user_deps_timeout),
            )

    def _read_agent_stderr_deltas(self) -> str:
        """Read new stderr content from all agent sandboxes since last call."""
        parts: list[str] = []
        for aid, sb in self.agent_sandboxes.items():
            try:
                offset = self._agent_stderr_offsets.get(aid, 0) + 1
                r = sb.run_command(
                    f"tail -c +{offset} /workspace/user_stderr.log 2>/dev/null || true",
                    timeout=6,
                )
                content = r.stdout or ""
                if content:
                    self._agent_stderr_offsets[aid] = (
                        self._agent_stderr_offsets.get(aid, 0) + len(content.encode("utf-8", "replace"))
                    )
                    header = f"[agent:{aid}]" if len(self.agent_sandboxes) > 1 else ""
                    parts.append(f"{header}\n{content}" if header else content)
            except Exception:
                pass
        return "\n".join(parts)

    def _wrap_on_case_end(
        self, original: Optional[Callable[[int, CaseResult], None]]
    ) -> Optional[Callable[[int, CaseResult], None]]:
        if original is None:
            return None

        def wrapped(idx: int, result: CaseResult) -> None:
            stderr_delta = self._read_agent_stderr_deltas()
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

        route_state = run_pair_protocol_router(
            submission_id=self.submission.submit_id,
            deadline=self.deadline,
            case_provider=case_provider,
            compute_step_deadline=self.compute_step_deadline,
            poll_judge_line=self._poll_judge_line,
            restart_user_runtime=lambda: None,
            ensure_user_runtime=lambda: None,
            request_user_action=self._request_user_action,
            send_to_judge=self._send_to_judge,
            send_to_user=self._send_to_user,
            parse_case_result=self.deps.parse_case_result,
            attach_case_history=self.deps.attach_case_history,
            record_observation_history=self.deps.record_observation_history,
            record_action_history=self.deps.record_action_history,
            on_case_start=self.on_case_start,
            on_case_end=self._wrap_on_case_end(self.on_case_end),
            track_per_case_usage=self.track_per_case_usage,
            attach_llm_usage_delta=self.attach_llm_usage_delta,
        )
        if route_state.cases:
            self.result = route_state.cases[0]

    def _request_user_action(self, trigger_msg: dict[str, Any]) -> dict[str, Any]:
        agent_msg = dict(trigger_msg)
        agent_msg.pop("history_events", None)

        agent_ids = list(self.agent_transports.keys())
        remaining = max(1, int(self.deadline - time.time()))

        for aid in agent_ids:
            transport = self.agent_transports[aid]
            try:
                transport.send_message(agent_msg, timeout=remaining)
            except Exception as exc:
                return {
                    "type": "action",
                    "error": f"send to {aid} failed: {type(exc).__name__}: {exc}",
                    "status": "error",
                }

        results: dict[str, Any] = {}
        errors: list[str] = []

        def _collect_one(aid: str) -> tuple[str, Any]:
            step_deadline = self.compute_step_deadline(self.deadline)
            line = self._poll_agent_line(aid, step_deadline)
            if line is None:
                return aid, None
            try:
                msg = json.loads(line)
            except Exception:
                return aid, {"error": f"invalid json from {aid}"}
            return aid, msg

        with ThreadPoolExecutor(max_workers=len(agent_ids)) as pool:
            futures = {pool.submit(_collect_one, aid): aid for aid in agent_ids}
            for fut in as_completed(futures):
                aid, msg = fut.result()
                if msg is None:
                    errors.append(f"{aid}: no response")
                    logger.error("[%d] agent %s: no response (timeout)", self.case_index, aid)
                elif isinstance(msg, dict) and msg.get("error"):
                    errors.append(f"{aid}: {msg.get('error')}")
                    logger.error("[%d] agent %s error: %s", self.case_index, aid, msg.get("error"))
                    results[aid] = msg
                elif isinstance(msg, dict) and "data" in msg:
                    results[aid] = msg.get("data")
                else:
                    results[aid] = msg

        if errors and not results:
            combined = "; ".join(errors)
            logger.error("[%d] all agents failed: %s", self.case_index, combined)
            return {
                "type": "action",
                "error": combined,
                "status": "error",
            }

        if any(
            isinstance(results.get(aid), dict) and results[aid].get("error")
            for aid in agent_ids
            if aid in results
        ):
            first_err = next(
                (results[aid]["error"] for aid in agent_ids
                 if isinstance(results.get(aid), dict) and results[aid].get("error")),
                "unknown",
            )
            action_msg: dict[str, Any] = {
                "type": "action",
                "error": first_err,
                "status": results.get(agent_ids[0], {}).get("status", "error")
                if isinstance(results.get(agent_ids[0]), dict) else "error",
            }
            if action_msg.get("error") and "status" not in action_msg:
                action_msg["status"] = "error"
            return action_msg

        all_none = all(
            results.get(aid) is None
            for aid in agent_ids
        )
        if all_none:
            return {"type": "action", "data": None}

        return {"type": "action", "data": results}

    def _send_to_user(self, msg: dict[str, Any], timeout: int) -> None:
        obs_dict = msg.get("data", {})
        if not isinstance(obs_dict, dict):
            for aid, transport in self.agent_transports.items():
                try:
                    transport.send_message(
                        {"type": "observation", "data": obs_dict},
                        timeout=timeout,
                    )
                except Exception as exc:
                    logger.warning(
                        "fan-out to %s failed: %s", aid, exc,
                    )
            return

        for aid, transport in self.agent_transports.items():
            agent_obs = obs_dict.get(aid, "")
            try:
                transport.send_message(
                    {"type": "observation", "data": agent_obs},
                    timeout=timeout,
                )
            except Exception as exc:
                logger.warning(
                    "fan-out observation to %s failed: %s", aid, exc,
                )

    def _poll_judge_line(self, stop_deadline: float) -> tuple[Optional[str], bool]:
        if not self.judge_transport:
            return None, True
        return self._poll_transport_line(
            transport=self.judge_transport,
            process=self.judge_process,
            stop_deadline=stop_deadline,
            poll_seconds=3,
        )

    def _poll_agent_line(self, agent_id: str, stop_deadline: float) -> Optional[str]:
        transport = self.agent_transports.get(agent_id)
        process = self.agent_processes.get(agent_id)
        if not transport:
            return None
        line, _ = self._poll_transport_line(
            transport=transport,
            process=process,
            stop_deadline=stop_deadline,
            poll_seconds=2,
        )
        return line

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

    def _send_to_judge(self, msg: dict[str, Any], timeout: int) -> None:
        if not self.judge_transport:
            raise RuntimeError("judge transport unavailable")
        self.judge_transport.send_message(msg, timeout=timeout)

    def _cleanup(self) -> None:
        for transport in [self.judge_transport, *self.agent_transports.values()]:
            try:
                if transport:
                    transport.close()
            except Exception:
                pass

        for proc in [self.judge_process, *self.agent_processes.values()]:
            try:
                self.deps.stop_process(proc)
            except Exception:
                pass

        for sb in [self.judge_sb, *self.agent_sandboxes.values()]:
            try:
                if sb:
                    self.deps.destroy_sandbox(sb)
            except Exception:
                pass

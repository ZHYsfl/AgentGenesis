"""Isolated multi-agent evaluator: 1 Judge + N per-agent sandboxes.

Follows the same lifecycle as DualSandboxEvaluator but creates N
agent sandboxes (some with problem-provided code, some with user code)
instead of a single user sandbox.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional, Callable

from .base import BaseEvaluator
from .models import (
    PhaseResult,
    CaseResult,
    UserSubmission,
    CaseStatus,
    PhaseStatus,
)
from .config import get_config
from .sandbox_pool import (
    create_sandbox,
    destroy_sandbox,
    get_or_create_template,
    extract_image_data_files,
    compute_data_content_hash,
)
from .runtime.artifact import (
    download_artifact as runtime_download_artifact,
    extract_artifact as runtime_extract_artifact,
    filter_requirements as runtime_filter_requirements,
    resolve_entrypoint as runtime_resolve_entrypoint,
)
from .runtime.gateway import (
    attach_llm_usage_delta as runtime_attach_llm_usage_delta,
    create_gateway_token_for_user as runtime_create_gateway_token_for_user,
    revoke_gateway_token as runtime_revoke_gateway_token,
)
from .runtime.history import (
    attach_case_history as runtime_attach_case_history,
    record_action_history as runtime_record_action_history,
    record_observation_history as runtime_record_observation_history,
)
from .runtime.process import SandboxProcessManager
from .runtime.results import parse_case_result as runtime_parse_case_result
from .runtime.isolated_session import (
    AgentSandboxSpec,
    IsolatedSessionDeps,
    IsolatedMultiAgentSession,
)
from .runtime.sandbox import (
    build_judge_envs as runtime_build_judge_envs,
    build_user_envs as runtime_build_user_envs,
    create_grpc_transport as runtime_create_grpc_transport,
    is_likely_mle_exit as runtime_is_likely_mle_exit,
    load_grpc_bridge_support_files as runtime_load_grpc_bridge_support_files,
    resolve_sandbox_resources as runtime_resolve_sandbox_resources,
    write_files_chunked as runtime_write_files_chunked,
)

logger: logging.Logger = logging.getLogger(__name__)
__all__ = ["IsolatedMultiAgentEvaluator"]


class IsolatedMultiAgentEvaluator(BaseEvaluator):
    """Evaluator for problems where each agent runs in an isolated sandbox.

    Config must provide:
    - ``agent_ids``: list of all agent identifiers (e.g. wolf_1 .. villager_2)
    - ``npc_agent_ids``: subset of agent_ids whose code comes from the
      problem artifact (e.g. wolf_1, wolf_2)
    - ``npc_code_prefix``: path prefix inside artifact for NPC code
      (e.g. "wolf_agent/")
    - ``solve_entry_map``: mapping of agent_id -> entry function name
      (e.g. {"witch": "solve_witch", ...})
    """

    _gateway_token_info: Optional[dict[str, Any]] = None
    _prev_usage_chars: int = 0
    _prev_usage_requests: int = 0

    def _run_single_case(
        self,
        *,
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
    ) -> CaseResult:
        template_image: Optional[str] = None
        try:
            image_data_dirs: list[str] = getattr(self.config, "image_data_dirs", []) or []
            data_files: Optional[dict[str, bytes]] = None
            data_hash: Optional[str] = None
            if image_data_dirs:
                data_files = extract_image_data_files(artifact_files, image_data_dirs)
                if data_files:
                    data_hash = compute_data_content_hash(data_files)

            template_image = get_or_create_template(
                pip_dependencies=list(self.config.pip_dependencies),
                deps_timeout_seconds=int(self.config.user_deps_timeout),
                data_files=data_files,
                data_content_hash=data_hash,
            )
        except Exception as exc:
            logger.warning(
                "[%s] template build failed: %s", submission.submit_id, exc,
            )

        agent_ids: list[str] = getattr(self.config, "agent_ids", [])
        npc_ids: set[str] = set(getattr(self.config, "npc_agent_ids", []))
        npc_prefix: str = getattr(self.config, "npc_code_prefix", "wolf_agent/")
        solve_entry_map: dict[str, str] = getattr(
            self.config, "solve_entry_map", {},
        )

        npc_code: dict[str, bytes] = {}
        for fpath, fbytes in artifact_files.items():
            if fpath.startswith(npc_prefix):
                rel = fpath[len(npc_prefix):]
                if rel:
                    npc_code[rel] = fbytes

        adapter_code = artifact_files.get("sandbox/user_adapter.py")

        agent_specs: list[AgentSandboxSpec] = []
        for aid in agent_ids:
            entry_name = solve_entry_map.get(aid, f"solve_{aid}")
            is_npc = aid in npc_ids

            code: dict[str, bytes]
            req_path: str
            if is_npc:
                code = dict(npc_code)
                req_path = "requirements.txt" if "requirements.txt" in npc_code else ""
            else:
                code = dict(user_files_bytes)
                req_path = user_req_path

            adapter_preset = str(
                getattr(self.config, "adapter_preset", "") or ""
            ).strip()
            if not adapter_preset:
                raise ValueError("phase_config.adapter_preset must not be empty")

            code["_agent_wrapper.py"] = self._generate_user_wrapper().encode("utf-8")
            code["_user_bridge.py"] = self._generate_managed_user_bridge(
                solve_attr_name=entry_name,
                adapter_preset=adapter_preset,
            ).encode("utf-8")
            if adapter_code:
                code["eval_runtime/problem_adapter.py"] = adapter_code

            agent_specs.append(AgentSandboxSpec(
                agent_id=aid,
                code_files=code,
                env_overrides={"AGENT_ID": aid},
                requirements_path=req_path,
            ))

        deps = IsolatedSessionDeps(
            create_sandbox=create_sandbox,
            destroy_sandbox=destroy_sandbox,
            resolve_sandbox_resources=lambda: runtime_resolve_sandbox_resources(
                self.config,
            ),
            load_bridge_support_files=lambda: runtime_load_grpc_bridge_support_files(
                __file__,
            ),
            write_files_chunked=runtime_write_files_chunked,
            build_judge_envs=lambda sub, token: runtime_build_judge_envs(
                config=self.config,
                submission=sub,
                get_client=self._get_client,
                gateway_token=token,
            ),
            build_agent_envs=lambda sub, token: runtime_build_user_envs(
                config=self.config,
                submission=sub,
                get_client=self._get_client,
                gateway_token=token,
            ),
            resolve_entrypoint=lambda: runtime_resolve_entrypoint(self.config),
            start_background_python=SandboxProcessManager.start_background_python,
            create_transport=runtime_create_grpc_transport,
            stop_process=SandboxProcessManager.stop_process,
            is_process_alive=SandboxProcessManager.is_process_alive,
            describe_process=SandboxProcessManager.describe_process,
            is_likely_mle_exit=lambda sb, path: runtime_is_likely_mle_exit(
                self.config, sb, path,
            ),
            parse_case_result=runtime_parse_case_result,
            attach_case_history=runtime_attach_case_history,
            record_observation_history=runtime_record_observation_history,
            record_action_history=runtime_record_action_history,
            template_image=template_image,
        )

        judge_envs_base = runtime_build_judge_envs(
            config=self.config,
            submission=submission,
            get_client=self._get_client,
            gateway_token=gateway_token,
        )

        session = IsolatedMultiAgentSession(
            deps=deps,
            config=self.config,
            submission=submission,
            agent_specs=agent_specs,
            judge_artifact_files=artifact_files,
            judge_envs_base=judge_envs_base,
            case_index=case_index,
            track_per_case_usage=track_per_case_usage,
            on_case_start=on_case_start,
            on_case_end=on_case_end,
            deadline=deadline,
            compute_step_deadline=self._with_step_deadline,
            attach_llm_usage_delta=(
                (lambda c: runtime_attach_llm_usage_delta(self, c, submission))
                if track_per_case_usage
                else None
            ),
        )
        return session.run()

    def _run_parallel_cases(
        self,
        submission: UserSubmission,
        gateway_token: Optional[str],
        artifact_files: dict[str, bytes],
        user_files_bytes: dict[str, bytes],
        user_req_path: str,
        num_cases: int,
        parallel: int,
        on_case_start: Optional[Callable[[int], None]],
        on_case_end: Optional[Callable[[int, CaseResult], None]],
        deadline: float,
        track_per_case_usage: bool = False,
    ) -> list[CaseResult]:
        cfg = get_config()
        active_workers = max(1, min(parallel, num_cases, cfg.max_case_parallelism))
        lock = threading.Lock()

        def safe_start(idx: int) -> None:
            if on_case_start:
                with lock:
                    on_case_start(idx)

        def safe_end(idx: int, result: CaseResult) -> None:
            if on_case_end:
                with lock:
                    on_case_end(idx, result)

        def run_case(case_idx: int) -> CaseResult:
            try:
                return self._run_single_case(
                    submission=submission,
                    gateway_token=gateway_token,
                    artifact_files=artifact_files,
                    user_files_bytes=user_files_bytes,
                    user_req_path=user_req_path,
                    case_index=case_idx,
                    track_per_case_usage=track_per_case_usage,
                    on_case_start=safe_start,
                    on_case_end=safe_end,
                    deadline=deadline,
                )
            except Exception as exc:
                logger.exception(
                    "[%s] case %d failed: %s",
                    submission.submit_id, case_idx, exc,
                )
                return CaseResult(
                    case_index=case_idx,
                    status=CaseStatus.ERROR,
                    score=0,
                    error=f"{type(exc).__name__}: {exc}",
                )

        all_cases: list[CaseResult] = []
        with ThreadPoolExecutor(max_workers=active_workers) as pool:
            futures = [pool.submit(run_case, idx) for idx in range(num_cases)]
            for fut in futures:
                all_cases.append(fut.result())
        all_cases.sort(key=lambda c: c.case_index)
        return all_cases

    def evaluate(
        self,
        submission: UserSubmission,
        parallel_cases: int = 1,
        on_case_start: Optional[Callable[[int], None]] = None,
        on_case_end: Optional[Callable[[int, CaseResult], None]] = None,
    ) -> PhaseResult:
        start_time = time.time()
        try:
            num_cases = self.config.num_cases
            is_parallel = parallel_cases > 1 and num_cases > 1
            effective_parallel = (
                min(parallel_cases, num_cases) if is_parallel else 1
            )

            try:
                gateway_token = runtime_create_gateway_token_for_user(
                    self, submission, aggregate_limit=True,
                )
            except ValueError as e:
                return PhaseResult(
                    status=PhaseStatus.ERROR,
                    error=str(e),
                    total_time=int((time.time() - start_time) * 1000),
                )
            self._prev_usage_chars = 0
            self._prev_usage_requests = 0

            artifact_bytes = runtime_download_artifact(
                self.config.artifact_url, self.config.artifact_checksum,
            )
            artifact_files = runtime_extract_artifact(artifact_bytes)

            user_files_text = submission.code_files or {}
            if not user_files_text:
                user_files_text = self._get_client().download_code(
                    submission.code_url,
                    expected_checksum=submission.code_checksum,
                )
            if "requirements.txt" not in user_files_text:
                raise ValueError(
                    "Missing requirements.txt in submission"
                )
            if (
                "requirements.txt" in user_files_text
                and self.config.allowed_packages
            ):
                filtered = runtime_filter_requirements(
                    user_files_text["requirements.txt"],
                    self.config.allowed_packages,
                )
                user_files_text["requirements.txt"] = filtered

            user_files_bytes: dict[str, bytes] = {
                p: s.encode("utf-8") for p, s in user_files_text.items()
            }

            user_req_path = (
                "requirements.txt"
                if "requirements.txt" in user_files_text
                else ""
            )

            eval_start_time = time.time()
            deadline = eval_start_time + float(self.config.sandbox_timeout)

            cases = self._run_parallel_cases(
                submission=submission,
                gateway_token=gateway_token,
                artifact_files=artifact_files,
                user_files_bytes=user_files_bytes,
                user_req_path=user_req_path,
                num_cases=num_cases,
                parallel=effective_parallel,
                on_case_start=on_case_start,
                on_case_end=on_case_end,
                deadline=deadline,
                track_per_case_usage=(effective_parallel <= 1),
            )

            total_cases = len(cases)
            passed_cases = sum(1 for c in cases if c.status == CaseStatus.PASSED)
            score = sum(int(c.score or 0) for c in cases)
            min_passed = getattr(self.config, "min_passed_cases", None)
            is_success = (
                passed_cases >= min_passed
                if min_passed is not None and min_passed > 0
                else passed_cases == total_cases
            )

            return PhaseResult(
                status=PhaseStatus.SUCCESS if is_success else PhaseStatus.FAILED,
                score=score,
                passed_cases=passed_cases,
                total_cases=total_cases,
                cases=cases,
                total_time=int((time.time() - eval_start_time) * 1000),
            )

        except Exception as e:
            logger.exception(
                "[%s] isolated evaluator error: %s", submission.submit_id, e,
            )
            return PhaseResult(
                status=PhaseStatus.ERROR,
                error=f"Isolated eval error: {type(e).__name__}: {e}",
                total_time=int((time.time() - start_time) * 1000),
            )
        finally:
            runtime_revoke_gateway_token(self, submission)

    def _with_step_deadline(self, deadline: float) -> float:
        raw_idle = getattr(self.config, "case_idle_timeout", 0)
        try:
            idle_sec = int(raw_idle)
        except Exception:
            idle_sec = 0
        if idle_sec <= 0:
            return deadline
        return min(deadline, time.time() + float(idle_sec))

    def _generate_user_wrapper(self) -> str:
        return r'''#!/usr/bin/env python3
from __future__ import annotations
import sys, traceback

def main() -> None:
    try:
        from _user_bridge import serve
    except ImportError as e:
        print(f"[wrapper] import failed: {e}", file=sys.stderr, flush=True)
        raise RuntimeError("bridge-only mode requires _user_bridge.py") from e
    try:
        serve()
    except Exception as e:
        print(f"[wrapper] exception: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        print(traceback.format_exc(), file=sys.stderr, flush=True)
        raise

if __name__ == "__main__":
    main()
'''

    def _generate_managed_user_bridge(
        self,
        *,
        solve_attr_name: str,
        adapter_preset: str,
    ) -> str:
        return f'''#!/usr/bin/env python3
from __future__ import annotations
from importlib import import_module

def serve() -> None:
    try:
        runtime_mod = import_module("eval_runtime.user_runtime")
    except ImportError:
        runtime_mod = import_module("agent_genesis.runtime.user_runtime")
    serve_user_runtime = getattr(runtime_mod, "serve_user_runtime")
    serve_user_runtime(
        solve_attr_name={repr(solve_attr_name)},
        adapter_preset={repr(adapter_preset)},
    )

if __name__ == "__main__":
    serve()
'''

"""Main Local Evaluator Class

Provides a local implementation corresponding to the cloud DualSandboxEvaluator,
supporting v1, v2, and v3 protocol dual-sandbox evaluation.
"""

from __future__ import annotations

import hashlib
import logging
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Queue
from typing import Any, Callable, Iterator, Optional

from ..models import (
    CaseResult,
    CaseStatus,
    PhaseConfig,
    PhaseResult,
    PhaseStatus,
    RuntimeConfig,
    UserSubmission,
)
from ..runtime.artifact import filter_requirements, resolve_entrypoint
from ..runtime.history import (
    attach_case_history,
    record_action_history,
    record_observation_history,
)
from ..runtime.pair_session import PairSessionDeps, run_sandbox_pair_session
from ..runtime.process import SandboxProcessManager
from ..runtime.results import parse_case_result
from ..runtime.sandbox import (
    build_local_judge_envs,
    build_local_user_envs,
    create_grpc_transport,
    is_likely_mle_exit,
    load_grpc_bridge_support_files,
    resolve_sandbox_resources,
    write_files_chunked,
)
from ..sandbox_pool import (
    compute_data_content_hash,
    create_sandbox,
    destroy_sandbox,
    extract_image_data_files,
    get_or_create_template,
    shutdown_all_sandboxes,
)
from .artifact_builder import LocalArtifactBuilder
from .problem_loader import LocalProblemLoader
from .eval_types import EvalEvent, EvalEventType

# Import LLMConfig from tool_calling
from agent_genesis.tool_calling import LLMConfig

# Get agent_genesis package path for loading support files
import agent_genesis as _agent_genesis_pkg
_AGENT_GENESIS_ROOT = _agent_genesis_pkg.__file__

logger: logging.Logger = logging.getLogger(__name__)


class LocalEvaluator:
    """Local Evaluator

    Runs dual-sandbox evaluation locally without cloud services.
    Supports v1, v2, v3 protocols.

    Example:
        from evaluation.local import LocalEvaluator, LLMConfig

        # User configures LLM themselves
        llm_config = LLMConfig(
            model="deepseek-chat",
            base_url="https://api.deepseek.com",
            api_key="your-api-key",
            # extra_body={"enable_thinking": False},
        )

        # Create evaluator and run
        evaluator = LocalEvaluator(
            problem_path="problems/interrupt_judge",
            user_code_path="answer/interrupt_judge/solution.py",
            llm_config=llm_config,
        )
        result = evaluator.evaluate()
        print(f"Passed: {result.passed_cases}/{result.total_cases}")

        # Streaming evaluation (with visualization)
        for event in evaluator.evaluate_stream():
            print(event)
    """

    def __init__(
        self,
        problem_path: str | Path,
        user_code_path: str | Path,
        llm_config: LLMConfig,
        on_event: Optional[Callable[[EvalEvent], None]] = None,
        protocol_version: str = "v1",
    ):
        """Initialize local evaluator

        Args:
            problem_path: Path to the problem directory, e.g., "problems/interrupt_judge"
            user_code_path: Path to user code, e.g., "answer/interrupt_judge/solution.py"
            llm_config: LLM configuration (provided by caller, can include extra_body)
            on_event: Event callback function
            protocol_version: Protocol version (v1, v2, v3), defaults to v1

        Example:
            from evaluation.local import LocalEvaluator, LLMConfig
            from dotenv import load_dotenv
            import os

            load_dotenv()
            llm_config = LLMConfig(
                model=os.getenv("LLM_MODEL", "deepseek-chat"),
                base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com"),
                api_key=os.getenv("LLM_API_KEY"),
                extra_body={"enable_thinking": False},
            )

            evaluator = LocalEvaluator(
                problem_path="problems/interrupt_judge",
                user_code_path="answer/interrupt_judge/solution.py",
                llm_config=llm_config,
            )
        """
        self.problem_path = Path(problem_path).resolve()
        self.user_code_path = Path(user_code_path).resolve()
        self.llm_config = llm_config
        self.on_event = on_event
        self.protocol_version = protocol_version

        # Load problem configuration
        self._loader = LocalProblemLoader()
        self.config: PhaseConfig = self._loader.load(self.problem_path)

        # Build artifact
        self._artifact_builder = LocalArtifactBuilder()
        self._artifact_files: dict[str, bytes] = self._artifact_builder.build(
            self.problem_path, self.config
        )

        # Load user code
        self._user_files: dict[str, str] = self._load_user_files()

        # Validate configuration
        self._validate_config()

    def _load_user_files(self) -> dict[str, str]:
        """Load user code files"""
        files: dict[str, str] = {}

        # If user_code_path is a file, treat it as the main solution.py
        if self.user_code_path.is_file():
            with open(self.user_code_path, "r", encoding="utf-8") as f:
                files["solution.py"] = f.read()

            # Find requirements.txt in the same directory
            req_path = self.user_code_path.parent / "requirements.txt"
            if req_path.exists():
                with open(req_path, "r", encoding="utf-8") as f:
                    files["requirements.txt"] = f.read()
            else:
                # Create default requirements.txt
                files["requirements.txt"] = "openai\n"
        else:
            # If it's a directory, load all .py files
            for py_file in self.user_code_path.rglob("*.py"):
                rel_path = py_file.relative_to(self.user_code_path)
                with open(py_file, "r", encoding="utf-8") as f:
                    files[str(rel_path)] = f.read()

            # Load requirements.txt
            req_path = self.user_code_path / "requirements.txt"
            if req_path.exists():
                with open(req_path, "r", encoding="utf-8") as f:
                    files["requirements.txt"] = f.read()
            else:
                files["requirements.txt"] = "openai\n"

        return files

    def _validate_config(self) -> None:
        """Validate configuration completeness"""
        solve_attr_name = str(getattr(self.config, "solve_attr_name", "") or "").strip()
        adapter_preset = str(getattr(self.config, "adapter_preset", "") or "").strip()

        if not solve_attr_name:
            raise ValueError("phase_config.solve_attr_name must not be empty")
        if not adapter_preset:
            raise ValueError("phase_config.adapter_preset must not be empty")

        # Check if user_adapter.py exists in artifact
        if "sandbox/user_adapter.py" not in self._artifact_files:
            raise ValueError("Missing sandbox/user_adapter.py in artifact")

    def _create_submission(self, submit_id: int = 1) -> UserSubmission:
        """Create UserSubmission object"""
        return UserSubmission(
            submit_id=submit_id,
            user_id=1,
            phase_id=1,
            code_url="",  # Not used in local mode
            code_files=self._user_files,
            phase_config=self.config,
            runtime_config=RuntimeConfig(),
            language="python",
            phase_type="agent",
        )

    def _setup_sigint_guard(self) -> tuple[Any, threading.Event]:
        """Setup SIGINT guard to prevent second Ctrl+C during cleanup.

        Returns:
            (original_handler, cleanup_event): Original signal handler and cleanup status flag
        """
        _cleanup_in_progress = threading.Event()
        _original_sigint: Any = signal.getsignal(signal.SIGINT)

        def _sigint_guard(signum: int, frame: Any) -> None:  # noqa: ANN001, ARG001
            if _cleanup_in_progress.is_set():
                logger.warning("Ctrl+C ignored: sandbox cleanup in progress, please wait…")
                return
            # Not in cleanup yet; restore original handler and re-raise
            signal.signal(signal.SIGINT, _original_sigint)
            raise KeyboardInterrupt

        # Only install on the main thread
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGINT, _sigint_guard)

        return _original_sigint, _cleanup_in_progress

    def evaluate(
        self,
        case_indices: Optional[list[int]] = None,
        parallel_cases: Optional[int] = None,
    ) -> PhaseResult:
        """Run evaluation

        Args:
            case_indices: Which cases to run, None means run all
            parallel_cases: Number of parallel cases, None uses config value

        Returns:
            PhaseResult evaluation result
        """
        start_time = time.time()
        _original_sigint, _cleanup_in_progress = self._setup_sigint_guard()

        try:
            # Create submission
            submission = self._create_submission()

            # Determine case range
            num_cases = self.config.num_cases
            if case_indices is not None:
                # Filter invalid indices
                case_indices = [i for i in case_indices if 0 <= i < num_cases]
            else:
                case_indices = list(range(num_cases))

            if not case_indices:
                return PhaseResult(
                    status=PhaseStatus.ERROR,
                    error="No valid cases to evaluate",
                    total_time=int((time.time() - start_time) * 1000),
                )

            # Parallelism
            effective_parallel = parallel_cases or self.config.parallel_cases or 1
            effective_parallel = min(effective_parallel, len(case_indices))

            # Emit progress event
            self._emit_event(EvalEventType.PROGRESS, -1, {"completed": 0, "total": len(case_indices)})

            # Prepare user code bytes
            user_files_bytes = {p: s.encode("utf-8") for p, s in self._user_files.items()}
            user_files_bytes["_agent_wrapper.py"] = self._generate_user_wrapper().encode("utf-8")

            # Add problem_adapter.py
            if "sandbox/user_adapter.py" in self._artifact_files:
                user_files_bytes["eval_runtime/problem_adapter.py"] = self._artifact_files[
                    "sandbox/user_adapter.py"
                ]

            # Generate user bridge
            solve_attr_name = str(getattr(self.config, "solve_attr_name", "") or "").strip()
            adapter_preset = str(getattr(self.config, "adapter_preset", "") or "").strip()
            user_files_bytes["_user_bridge.py"] = self._generate_managed_user_bridge(
                solve_attr_name=solve_attr_name,
                adapter_preset=adapter_preset,
            ).encode("utf-8")

            # Check requirements.txt
            user_req_path = "requirements.txt" if "requirements.txt" in self._user_files else ""
            if user_req_path and self.config.allowed_packages:
                filtered = filter_requirements(
                    self._user_files["requirements.txt"],
                    self.config.allowed_packages,
                )
                self._user_files["requirements.txt"] = filtered
                user_files_bytes["requirements.txt"] = filtered.encode("utf-8")

            # Run evaluation
            completed_count = [0]
            lock = threading.Lock()

            def on_case_start(idx: int) -> None:
                self._emit_event(EvalEventType.CASE_START, idx, {})

            def on_case_end(idx: int, result: CaseResult) -> None:
                with lock:
                    completed_count[0] += 1
                    completed = completed_count[0]
                self._emit_event(
                    EvalEventType.CASE_END,
                    idx,
                    {
                        "status": result.status,
                        "score": result.score,
                        "error": result.error,
                    },
                )
                self._emit_event(
                    EvalEventType.PROGRESS,
                    -1,
                    {"completed": completed, "total": len(case_indices)},
                )

            def run_single(idx: int) -> CaseResult:
                try:
                    return self._run_single_case(
                        submission=submission,
                        artifact_files=self._artifact_files,
                        user_files_bytes=user_files_bytes,
                        user_req_path=user_req_path,
                        case_index=idx,
                        on_case_start=on_case_start,
                        on_case_end=on_case_end,
                    )
                except Exception as exc:
                    logger.exception(f"Case {idx} failed: {exc}")
                    # Emit ERROR event
                    self._emit_event(
                        EvalEventType.ERROR,
                        idx,
                        {"error": f"{type(exc).__name__}: {exc}"}
                    )
                    return CaseResult(
                        case_index=idx,
                        status=CaseStatus.ERROR,
                        score=0,
                        error=f"{type(exc).__name__}: {exc}",
                    )

            # Serial or parallel execution
            pool: Optional[ThreadPoolExecutor] = None
            if effective_parallel <= 1:
                cases = [run_single(idx) for idx in case_indices]
            else:
                cases = []
                pool = ThreadPoolExecutor(max_workers=effective_parallel)
                futures = [pool.submit(run_single, idx) for idx in case_indices]
                try:
                    for fut in futures:
                        cases.append(fut.result())
                finally:
                    # Cancel pending futures and shutdown without waiting
                    # to avoid blocking on interrupted worker threads
                    for fut in futures:
                        if not fut.done():
                            fut.cancel()
                    pool.shutdown(wait=False)
                    pool = None

            # Sort
            cases.sort(key=lambda c: c.case_index)

            # Compute results
            total_cases = len(cases)
            passed_cases = sum(1 for c in cases if c.status == CaseStatus.PASSED)
            score = sum(int(c.score or 0) for c in cases)
            cases_elapsed_ms = sum(max(0, int(c.time_used or 0)) for c in cases)
            total_chars = sum(c.chars_used for c in cases)
            total_requests = sum(c.requests_used for c in cases)

            # Determine pass/fail
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
                total_time=cases_elapsed_ms,
                total_chars=total_chars,
                total_requests=total_requests,
            )
        except Exception as exc:
            logger.exception(f"Evaluation failed: {exc}")
            # Emit ERROR event
            self._emit_event(
                EvalEventType.ERROR,
                -1,
                {"error": f"{type(exc).__name__}: {exc}"}
            )
            return PhaseResult(
                status=PhaseStatus.ERROR,
                error=f"{type(exc).__name__}: {exc}",
                total_time=int((time.time() - start_time) * 1000),
            )
        finally:
            # Mark cleanup in progress
            _cleanup_in_progress.set()

            # Emergency cleanup: force destroy all sandboxes immediately.
            # This prevents memory leaks if worker threads were interrupted
            # during sandbox creation or cleanup.
            logger.info("Emergency sandbox cleanup initiated...")
            shutdown_all_sandboxes()
            logger.info("Emergency sandbox cleanup completed.")

            # Restore original signal handler
            if threading.current_thread() is threading.main_thread():
                signal.signal(signal.SIGINT, _original_sigint)

    def evaluate_stream(
        self,
        case_indices: Optional[list[int]] = None,
        parallel_cases: Optional[int] = None,
    ) -> Iterator[EvalEvent]:
        """Streaming evaluation

        Produces an evaluation event stream for real-time visualization.

        Args:
            case_indices: Which cases to run, None means run all
            parallel_cases: Number of parallel cases

        Yields:
            EvalEvent event objects
        """
        # Use queue to collect events
        event_queue: Queue[EvalEvent] = Queue()

        def event_handler(event: EvalEvent) -> None:
            event_queue.put(event)

        # Save original callback
        original_callback = self.on_event

        try:
            # Set new callback
            self.on_event = event_handler

            # Run evaluation in background thread
            result_holder: list[PhaseResult] = []

            def run_eval():
                try:
                    result = self.evaluate(case_indices, parallel_cases)
                    result_holder.append(result)
                except Exception as e:
                    event_queue.put(
                        EvalEvent(
                            type=EvalEventType.ERROR,
                            case_index=-1,
                            data={"error": str(e)},
                        )
                    )

            eval_thread = threading.Thread(target=run_eval)
            eval_thread.start()

            # Read events from queue
            while eval_thread.is_alive() or not event_queue.empty():
                try:
                    event = event_queue.get(timeout=0.1)
                    yield event
                except Exception:
                    continue

            eval_thread.join()

        finally:
            # Restore original callback
            self.on_event = original_callback

    def _run_single_case(
        self,
        submission: UserSubmission,
        artifact_files: dict[str, bytes],
        user_files_bytes: dict[str, bytes],
        user_req_path: str,
        case_index: int,
        on_case_start: Optional[Callable[[int], None]] = None,
        on_case_end: Optional[Callable[[int, CaseResult], None]] = None,
    ) -> CaseResult:
        """Run a single case"""
        # Calculate timeout
        eval_start_time = time.time()
        deadline = eval_start_time + float(self.config.sandbox_timeout)

        # Get or create template image
        template_image: Optional[str] = None
        try:
            image_data_dirs: list[str] = (
                getattr(self.config, "image_data_dirs", []) or []
            )
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
            logger.warning(f"Template build failed, falling back to base: {exc}")

        # Build dependencies
        # Extract extra_body from llm_config (if present)
        llm_extra_body = getattr(self.llm_config, 'extra_body', None)

        deps = PairSessionDeps(
            create_sandbox=create_sandbox,
            destroy_sandbox=destroy_sandbox,
            resolve_sandbox_resources=lambda: resolve_sandbox_resources(self.config),
            load_bridge_support_files=lambda: load_grpc_bridge_support_files(_AGENT_GENESIS_ROOT),
            write_files_chunked=write_files_chunked,
            build_judge_envs=lambda sub, token: build_local_judge_envs(
                config=self.config,
                llm_model=self.llm_config.model,
                llm_base_url=self.llm_config.base_url,
                llm_api_key=self.llm_config.api_key,
                llm_extra_body=llm_extra_body,
            ),
            build_user_envs=lambda sub, token: build_local_user_envs(
                config=self.config,
                llm_model=self.llm_config.model,
                llm_base_url=self.llm_config.base_url,
                llm_api_key=self.llm_config.api_key,
                llm_extra_body=llm_extra_body,
            ),
            resolve_entrypoint=lambda: resolve_entrypoint(self.config),
            start_background_python=SandboxProcessManager.start_background_python,
            create_transport=create_grpc_transport,
            stop_process=SandboxProcessManager.stop_process,
            is_process_alive=SandboxProcessManager.is_process_alive,
            describe_process=SandboxProcessManager.describe_process,
            is_likely_mle_exit=lambda sandbox, stderr_path: is_likely_mle_exit(
                self.config, sandbox, stderr_path
            ),
            parse_case_result=parse_case_result,
            attach_case_history=attach_case_history,
            record_observation_history=record_observation_history,
            record_action_history=record_action_history,
            template_image=template_image,
        )

        # Wrap callbacks to capture OA sequence
        wrapped_on_case_start = self._wrap_on_case_start(on_case_start)
        wrapped_on_case_end = self._wrap_on_case_end(on_case_end)

        # Create session
        from ..runtime.pair_session import _SandboxPairSession

        session = _SandboxPairSession(
            deps=deps,
            config=self.config,
            submission=submission,
            gateway_token=None,
            artifact_files=artifact_files,
            user_files_bytes=user_files_bytes,
            user_req_path=user_req_path,
            case_index=case_index,
            track_per_case_usage=False,
            on_case_start=wrapped_on_case_start,
            on_case_end=wrapped_on_case_end,
            deadline=deadline,
            compute_step_deadline=self._with_step_deadline,
            attach_llm_usage_delta=None,
        )

        # Set event callbacks to emit EvalEvent
        def on_observation(case_idx: int, msg: dict) -> None:
            self._emit_event(
                EvalEventType.OBSERVATION,
                case_idx,
                {"data": msg.get("data")}
            )

        def on_action(case_idx: int, msg: dict) -> None:
            self._emit_event(
                EvalEventType.ACTION,
                case_idx,
                {"data": msg.get("data"), "error": msg.get("error")}
            )

        def on_user_log(case_idx: int, log: str) -> None:
            self._emit_event(
                EvalEventType.USER_LOG,
                case_idx,
                {"data": log}
            )

        def on_judge_log(case_idx: int, log: str) -> None:
            self._emit_event(
                EvalEventType.JUDGE_LOG,
                case_idx,
                {"data": log}
            )

        def on_error(case_idx: int, error: str) -> None:
            self._emit_event(
                EvalEventType.ERROR,
                case_idx,
                {"error": error}
            )

        session.set_event_callbacks(
            on_observation=on_observation,
            on_action=on_action,
            on_user_log=on_user_log,
            on_judge_log=on_judge_log,
            on_error=on_error,
        )

        return session.run()

    def _wrap_on_case_start(
        self, original: Optional[Callable[[int], None]]
    ) -> Optional[Callable[[int], None]]:
        """Wrap on_case_start callback"""
        if original is None:
            return None

        def wrapped(idx: int) -> None:
            original(idx)

        return wrapped

    def _wrap_on_case_end(
        self, original: Optional[Callable[[int, CaseResult], None]]
    ) -> Optional[Callable[[int, CaseResult], None]]:
        """Wrap on_case_end callback to capture logs"""
        if original is None:
            return None

        def wrapped(idx: int, result: CaseResult) -> None:
            original(idx, result)

        return wrapped

    def _with_step_deadline(self, deadline: float) -> float:
        """Calculate step deadline"""
        raw_idle = getattr(self.config, "case_idle_timeout", 0)
        try:
            idle_sec = int(raw_idle)
        except Exception:
            idle_sec = 0
        if idle_sec <= 0:
            return deadline
        return min(deadline, time.time() + float(idle_sec))

    def _emit_event(self, event_type: EvalEventType, case_index: int, data: dict[str, Any]) -> None:
        """Emit event"""
        event = EvalEvent(
            type=event_type,
            case_index=case_index,
            data=data,
        )

        # Call user callback
        if self.on_event:
            try:
                self.on_event(event)
            except Exception as exc:
                logger.warning(f"Event callback error: {exc}")

    def _generate_user_wrapper(self) -> str:
        """Generate user wrapper code"""
        return r'''#!/usr/bin/env python3
from __future__ import annotations

import sys
import traceback


def main() -> None:
    try:
        from _user_bridge import serve  # type: ignore
    except ImportError as e:
        print(f"[wrapper] import _user_bridge failed: {e}", file=sys.stderr, flush=True)
        raise RuntimeError("bridge-only mode requires _user_bridge.py") from e
    try:
        serve()
    except Exception as e:
        print(f"[wrapper] bridge exception: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
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
        """Generate managed user bridge code"""
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
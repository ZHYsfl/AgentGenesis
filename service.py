"""Worker service loop for polling, evaluating, and reporting."""

from __future__ import annotations

import signal
import time
import logging
import importlib
from concurrent.futures import ThreadPoolExecutor, Future, wait, FIRST_COMPLETED
from typing import Any, Optional
from dataclasses import dataclass

from .client import EvaluationClient
from .base import BaseEvaluator
from .dual_sandbox_evaluator import DualSandboxEvaluator
from .models import PhaseConfig, PhaseResult, CaseResult, UserSubmission, PhaseStatus
from .registry import ProblemRegistry
from .config import get_config
from .health import (
    get_metrics_collector,
    start_health_server,
    stop_health_server,
    MetricsCollector,
)
from .sandbox_pool import SandboxManager, SandboxBusyError

logger: logging.Logger = logging.getLogger(__name__)

DEFAULT_SUBMISSION_TIMEOUT: int = 600


@dataclass
class SubmissionTask:
    submit_id: int
    start_time: float
    timeout: int
    timeout_reported: bool = False
    
    def is_timed_out(self) -> bool:
        return time.time() - self.start_time > self.timeout


_service_instance: Optional[EvaluationService] = None


class EvaluationService:
    client: EvaluationClient
    registry: Optional[ProblemRegistry]
    max_workers: int
    poll_interval: int
    _running: bool
    _metrics: MetricsCollector
    _enable_health_server: bool
    _health_port: int
    _active_submit_ids: set[int]
    
    def __init__(
        self,
        client: Optional[EvaluationClient] = None,
        registry: Optional[ProblemRegistry] = None,
        max_workers: Optional[int] = None,
        poll_interval: Optional[int] = None,
        enable_health_server: Optional[bool] = None,
        health_port: Optional[int] = None,
    ) -> None:
        cfg = get_config()
        
        self.client = client or EvaluationClient()
        self.registry = registry
        self.max_workers = max_workers if max_workers is not None else cfg.max_workers
        self.poll_interval = poll_interval if poll_interval is not None else cfg.poll_interval
        self._running = False
        self._metrics = get_metrics_collector()
        self._enable_health_server = enable_health_server if enable_health_server is not None else cfg.health_enabled
        self._health_port = health_port if health_port is not None else cfg.health_port
        self._active_submit_ids = set()
    
    def load_evaluator(self, config: PhaseConfig) -> BaseEvaluator:
        module_path: str = config.evaluator_module
        class_name: str = config.evaluator_class

        if not module_path or not class_name:
            logger.warning(
                "Missing evaluator_module/evaluator_class in config, falling back to DualSandboxEvaluator"
            )
            module_path = DualSandboxEvaluator.__module__
            class_name = DualSandboxEvaluator.__name__

        _LEGACY_MODULE_ALIASES = {
            "evaluation.dual_sandbox_evaluator": "agent_genesis.dual_sandbox_evaluator",
            "evaluation.base": "agent_genesis.base",
        }
        if BaseEvaluator.__module__.startswith("agent_genesis."):
            module_path = _LEGACY_MODULE_ALIASES.get(module_path, module_path)

        try:
            module = importlib.import_module(module_path)
            evaluator_cls: Any = getattr(module, class_name)
        except Exception as e:
            logger.warning(
                f"Failed to load evaluator (module={module_path}, class={class_name}): {e}; "
                f"falling back to {DualSandboxEvaluator.__module__}.{DualSandboxEvaluator.__name__}"
            )
            evaluator_cls = DualSandboxEvaluator

        if not isinstance(evaluator_cls, type) or not issubclass(evaluator_cls, BaseEvaluator):
            raise TypeError(
                f"Evaluator {evaluator_cls} must inherit BaseEvaluator"
            )

        return evaluator_cls(config, client=self.client)
    
    def process_submission(self, submission: UserSubmission) -> PhaseResult:
        submit_id: int = submission.submit_id
        logger.info(f"[{submit_id}] processing started")
        self._active_submit_ids.add(submit_id)
        
        start_time: float = time.time()
        self._metrics.record_submission_start()
        
        try:
            if not self.client.claim_submission(submit_id):
                logger.warning(f"[{submit_id}] claim failed")
                return PhaseResult(status=PhaseStatus.ERROR, error="claim failed")
            
            try:
                code_files: dict[str, str] = self._download_code(submission)
                if not code_files:
                    raise ValueError("code download failed: empty result")
                submission.code_files = code_files
            except Exception as download_err:
                logger.error(f"[{submit_id}] code download failed: {download_err}")
                self.client.unclaim_submission(submit_id)
                raise ValueError(f"code download failed: {download_err}")
            
            self._validate_submission(code_files)
            
            evaluator: BaseEvaluator = self.load_evaluator(submission.phase_config)
            logger.info(f"[{submit_id}] evaluator: {type(evaluator).__name__}")
            
            parallel: int = submission.phase_config.parallel_cases
            streamed_case_indexes: set[int] = set()
            
            def on_case_start(case_index: int) -> None:
                self.client.report_case_status(submit_id, case_index, "running")
            
            def on_case_end(case_index: int, case_result: CaseResult) -> None:
                saved_case_id: int | None = None
                try:
                    resp = self.client.create_case_record(submit_id=submit_id, case=case_result)
                    if resp:
                        saved_case_id = resp.get("case_id")
                    streamed_case_indexes.add(case_index)
                except Exception as exc:
                    logger.warning(f"[{submit_id}] streaming save failed for case {case_index}: {exc}")
                self.client.report_case_status(
                    submit_id, case_index, case_result.status.to_backend(),
                    case_id=saved_case_id,
                )
            
            try:
                result: PhaseResult = evaluator.evaluate(
                    submission,
                    parallel_cases=parallel,
                    on_case_start=on_case_start,
                    on_case_end=on_case_end,
                )
            finally:
                if hasattr(evaluator, 'cleanup'):
                    try:
                        evaluator.cleanup()
                    except Exception as cleanup_err:
                        logger.warning(f"[{submit_id}] evaluator cleanup failed: {cleanup_err}")
            
            logger.info(
                f"[{submit_id}] completed: {result.status.value}, "
                f"score={result.score}, passed={result.passed_cases}/{result.total_cases}"
            )
            
            self._save_cases(submit_id, result, skip_indexes=streamed_case_indexes)
            
            self.client.report_result(submit_id, result)
            
            duration_ms: int = int((time.time() - start_time) * 1000)
            self._metrics.record_submission_end(
                success=result.status == PhaseStatus.SUCCESS,
                duration_ms=duration_ms,
                passed_cases=result.passed_cases,
                total_cases=result.total_cases,
            )
            
            return result
        
        except SandboxBusyError as e:
            logger.warning(f"[{submit_id}] sandbox busy, returning to queue for retry")
            self.client.unclaim_submission(submit_id)
            self._metrics.record_submission_cancel()
            self._metrics.record_error("sandbox_busy")
            return PhaseResult(status=PhaseStatus.PENDING, error="sandbox busy, returned to queue")
            
        except Exception as e:
            logger.exception(f"[{submit_id}] exception: {e}")
            result = PhaseResult(
                status=PhaseStatus.ERROR,
                error=f"{type(e).__name__}: {str(e)}",
            )
            self._try_report_error(submit_id, result)
            
            duration_ms = int((time.time() - start_time) * 1000)
            self._metrics.record_submission_end(
                success=False,
                duration_ms=duration_ms,
                error=str(e),
            )
            
            return result
        
        finally:
            self._active_submit_ids.discard(submit_id)
    
    def _download_code(self, submission: UserSubmission) -> dict[str, str]:
        if not submission.code_url:
            raise ValueError("missing code URL")
        
        code_files: dict[str, str] = self.client.download_code(
            submission.code_url,
            expected_checksum=submission.code_checksum,
        )
        if code_files:
            logger.info(f"[{submission.submit_id}] code files: {list(code_files.keys())}")
        return code_files
    
    def _validate_submission(self, code_files: dict[str, str]) -> None:
        if "requirements.txt" not in code_files:
            raise ValueError("missing requirements.txt")
    
    def _save_cases(
        self,
        submit_id: int,
        result: PhaseResult,
        skip_indexes: set[int] | None = None,
    ) -> None:
        if not result.cases:
            return
        
        for case in result.cases:
            if skip_indexes and case.case_index in skip_indexes:
                continue
            self.client.create_case_record(
                submit_id=submit_id,
                case=case,
            )
    
    def _try_report_error(self, submit_id: int, result: PhaseResult) -> None:
        try:
            self.client.report_result(submit_id, result)
        except Exception:
            logger.error(f"[{submit_id}] error reporting also failed")
    
    def run(self) -> None:
        global _service_instance
        _service_instance = self
        
        self._log_startup()
        self._running = True
        
        self._register_signal_handlers()
        
        if self._enable_health_server:
            start_health_server(port=self._health_port)
        
        try:
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures: dict[Future[PhaseResult], SubmissionTask] = {}
                
                while self._running:
                    try:
                        self._tick(executor, futures)
                    except KeyboardInterrupt:
                        logger.info("interrupt signal received")
                        self._running = False
                    except Exception as e:
                        logger.exception(f"main loop exception: {e}")
                        self._metrics.record_error(str(e))
                        time.sleep(self.poll_interval)
        finally:
            if self._enable_health_server:
                stop_health_server()
            
            try:
                SandboxManager.get_instance().shutdown()
            except Exception:
                pass
            
            _service_instance = None
        
        logger.info("evaluation service stopped")
    
    def _register_signal_handlers(self) -> None:
        def _handle_sigterm(signum: int, frame: object) -> None:
            logger.warning("SIGTERM received, shutting down gracefully...")
            self._running = False
            for submit_id in list(self._active_submit_ids):
                try:
                    self.client.unclaim_submission(submit_id)
                    logger.info(f"[{submit_id}] unclaimed (SIGTERM)")
                except Exception as e:
                    logger.warning(f"[{submit_id}] unclaim failed: {e}")
            logger.info("all active tasks unclaimed, preparing to exit")
        
        signal.signal(signal.SIGTERM, _handle_sigterm)
    
    def _tick(
        self,
        executor: ThreadPoolExecutor,
        futures: dict[Future[PhaseResult], SubmissionTask],
    ) -> None:
        slots: int = self.max_workers - len(futures)
        if slots > 0:
            submissions: list[UserSubmission] = self.client.get_pending_submissions(slots)
            for sub in submissions:
                future: Future[PhaseResult] = executor.submit(self.process_submission, sub)
                timeout = sub.phase_config.sandbox_timeout if sub.phase_config else DEFAULT_SUBMISSION_TIMEOUT
                timeout = timeout + 30
                task = SubmissionTask(
                    submit_id=sub.submit_id,
                    start_time=time.time(),
                    timeout=timeout,
                )
                futures[future] = task
                logger.info(f"[{sub.submit_id}] enqueued (timeout: {timeout}s)")
        
        if futures:
            done, not_done = wait(futures.keys(), timeout=self.poll_interval, return_when=FIRST_COMPLETED)
            
            for future in done:
                task: SubmissionTask = futures.pop(future)
                try:
                    result: PhaseResult = future.result()
                    if result.status == PhaseStatus.PENDING:
                        logger.info(f"[{task.submit_id}] returned to queue, waiting for retry")
                    else:
                        logger.info(f"[{task.submit_id}] dequeued: {result.status.value}")
                except Exception as e:
                    logger.error(f"[{task.submit_id}] task exception: {e}")
            
            for future in list(not_done):
                task = futures.get(future) 
                if task and task.is_timed_out() and not task.timeout_reported:
                    task.timeout_reported = True
                    logger.error(
                        f"[{task.submit_id}] overall timeout ({task.timeout}s), "
                        "keep task running and avoid premature terminal overwrite"
                    )
                    self._metrics.record_error("submission_timeout")
        else:
            time.sleep(self.poll_interval)
    
    def _log_startup(self) -> None:
        logger.info("=" * 60)
        logger.info("evaluation service started")
        logger.info(f"  backend: {self.client.base_url}")
        logger.info(f"  max parallel submissions: {self.max_workers}")
        logger.info(f"  polling interval: {self.poll_interval}s")
        if self._enable_health_server:
            logger.info(f"  health: http://0.0.0.0:{self._health_port}")
            logger.info("    /health  - health status")
            logger.info("    /metrics - Prometheus metrics")
            logger.info("    /stats   - JSON stats")
        logger.info("=" * 60)
    
    def stop(self) -> None:
        self._running = False

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    
    service: EvaluationService = EvaluationService()
    service.run()


if __name__ == "__main__":
    main()

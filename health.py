"""Health endpoints and runtime metrics aggregation."""

from __future__ import annotations

import os
import time
import json
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional, Dict, Any, Callable, List
from datetime import datetime

logger: logging.Logger = logging.getLogger(__name__)


class MetricsCollector:
    def __init__(self) -> None:
        self.submissions_total: int = 0
        self.submissions_success: int = 0
        self.submissions_failed: int = 0
        self.cases_total: int = 0
        self.cases_passed: int = 0
        self.cases_failed: int = 0
        self.total_eval_time_ms: int = 0
        self.min_eval_time_ms: int = 0
        self.max_eval_time_ms: int = 0
        self.start_time: float = time.time()
        self.last_submission_time: Optional[float] = None
        self.current_submissions: int = 0
        self.errors: List[dict] = []
        self.max_errors: int = 100
        self._lock: threading.Lock = threading.Lock()
    
    def record_submission_start(self) -> None:
        with self._lock:
            self.current_submissions += 1
    
    def record_submission_end(
        self,
        success: bool,
        duration_ms: int,
        passed_cases: int = 0,
        total_cases: int = 0,
        error: Optional[str] = None,
    ) -> None:
        with self._lock:
            self.current_submissions -= 1
            self.submissions_total += 1
            self.last_submission_time = time.time()
            
            if success:
                self.submissions_success += 1
            else:
                self.submissions_failed += 1
            
            self.cases_total += total_cases
            self.cases_passed += passed_cases
            self.cases_failed += total_cases - passed_cases
            
            self.total_eval_time_ms += duration_ms
            if self.min_eval_time_ms == 0 or duration_ms < self.min_eval_time_ms:
                self.min_eval_time_ms = duration_ms
            if duration_ms > self.max_eval_time_ms:
                self.max_eval_time_ms = duration_ms
            
            if error:
                self._add_error(error)
    
    def record_submission_cancel(self) -> None:
        with self._lock:
            self.current_submissions -= 1
    
    def record_error(self, error: str) -> None:
        with self._lock:
            self._add_error(error)
    
    def _add_error(self, error: str) -> None:
        self.errors.append({
            "time": datetime.now().isoformat(),
            "error": error[:500],
        })
        if len(self.errors) > self.max_errors:
            self.errors = self.errors[-self.max_errors:]
    
    def get_stats(self) -> dict:
        with self._lock:
            uptime = time.time() - self.start_time
            avg_eval_time = (
                self.total_eval_time_ms / self.submissions_total
                if self.submissions_total > 0 else 0
            )
            
            return {
                "uptime_seconds": int(uptime),
                "submissions": { 
                    "total": self.submissions_total,
                    "success": self.submissions_success,
                    "failed": self.submissions_failed,
                    "current": self.current_submissions,
                    "success_rate": (
                        self.submissions_success / self.submissions_total
                        if self.submissions_total > 0 else 0
                    ),
                },
                "cases": {
                    "total": self.cases_total,
                    "passed": self.cases_passed,
                    "failed": self.cases_failed,
                    "pass_rate": (
                        self.cases_passed / self.cases_total
                        if self.cases_total > 0 else 0
                    ),
                },
                "timing_ms": {
                    "total": self.total_eval_time_ms,
                    "avg": avg_eval_time,
                    "min": self.min_eval_time_ms,
                    "max": self.max_eval_time_ms,
                },
                "last_submission": (
                    datetime.fromtimestamp(self.last_submission_time).isoformat()
                    if self.last_submission_time else None
                ),
                "recent_errors": self.errors[-10:],
            }
    
    def get_prometheus_metrics(self) -> str:
        with self._lock:
            lines = [
                "# HELP eval_submissions_total Total number of submissions",
                "# TYPE eval_submissions_total counter",
                f"eval_submissions_total {self.submissions_total}",
                "",
                "# HELP eval_submissions_success Successful submissions",
                "# TYPE eval_submissions_success counter",
                f"eval_submissions_success {self.submissions_success}",
                "",
                "# HELP eval_submissions_failed Failed submissions",
                "# TYPE eval_submissions_failed counter",
                f"eval_submissions_failed {self.submissions_failed}",
                "",
                "# HELP eval_submissions_current Current processing submissions",
                "# TYPE eval_submissions_current gauge",
                f"eval_submissions_current {self.current_submissions}",
                "",
                "# HELP eval_cases_total Total test cases",
                "# TYPE eval_cases_total counter",
                f"eval_cases_total {self.cases_total}",
                "",
                "# HELP eval_cases_passed Passed test cases",
                "# TYPE eval_cases_passed counter",
                f"eval_cases_passed {self.cases_passed}",
                "",
                "# HELP eval_cases_failed Failed test cases",
                "# TYPE eval_cases_failed counter",
                f"eval_cases_failed {self.cases_failed}",
                "",
                "# HELP eval_eval_time_ms_total Total evaluation time in ms",
                "# TYPE eval_eval_time_ms_total counter",
                f"eval_eval_time_ms_total {self.total_eval_time_ms}",
                "",
                "# HELP eval_eval_time_min_ms Minimum evaluation time in ms",
                "# TYPE eval_eval_time_min_ms gauge",
                f"eval_eval_time_min_ms {self.min_eval_time_ms}",
                "",
                "# HELP eval_eval_time_max_ms Maximum evaluation time in ms",
                "# TYPE eval_eval_time_max_ms gauge",
                f"eval_eval_time_max_ms {self.max_eval_time_ms}",
                "",
                "# HELP eval_eval_time_avg_ms Average evaluation time in ms",
                "# TYPE eval_eval_time_avg_ms gauge",
                f"eval_eval_time_avg_ms {self.total_eval_time_ms / self.submissions_total if self.submissions_total > 0 else 0}",
                "",
                "# HELP eval_errors_total Total number of errors recorded",
                "# TYPE eval_errors_total counter",
                f"eval_errors_total {len(self.errors)}",
                "",
                "# HELP eval_uptime_seconds Worker uptime in seconds",
                "# TYPE eval_uptime_seconds gauge",
                f"eval_uptime_seconds {int(time.time() - self.start_time)}",
            ]
            return "\n".join(lines) + "\n"

class HealthStatus:
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class HealthCheck:
    def __init__(
        self,
        name: str,
        check_fn: Callable[[], tuple[bool, str]],
        critical: bool = True,
    ) -> None:
        self.name = name
        self.check_fn = check_fn
        self.critical = critical
    
    def run(self) -> dict:
        try:
            ok, message = self.check_fn()
            return {
                "name": self.name,
                "status": "ok" if ok else "fail",
                "message": message,
                "critical": self.critical,
            }
        except Exception as e:
            return {
                "name": self.name,
                "status": "error",
                "message": str(e),
                "critical": self.critical,
            }


class HealthChecker:
    def __init__(self) -> None:
        self.checks: list[HealthCheck] = []
    
    def add_check(
        self,
        name: str,
        check_fn: Callable[[], tuple[bool, str]],
        critical: bool = True,
    ) -> None:
        self.checks.append(HealthCheck(name, check_fn, critical))
    
    def run_all(self) -> dict:
        results = [check.run() for check in self.checks]
        critical_failed = any(
            r["status"] != "ok" and r["critical"]
            for r in results
        )
        non_critical_failed = any(
            r["status"] != "ok" and not r["critical"]
            for r in results
        )
        
        if critical_failed:
            status = HealthStatus.UNHEALTHY
        elif non_critical_failed:
            status = HealthStatus.DEGRADED
        else:
            status = HealthStatus.HEALTHY
        
        return {
            "status": status,
            "checks": results,
            "timestamp": datetime.now().isoformat(),
        }

class HealthHandler(BaseHTTPRequestHandler):
    metrics_collector: MetricsCollector = None
    health_checker: HealthChecker = None
    extra_handlers: Dict[str, Callable[[], tuple[int, str, str]]] = {}
    
    def log_message(self, format: str, *args) -> None:
        pass
    
    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        
        if path == "/health":
            self._handle_health()
        elif path == "/metrics":
            self._handle_metrics()
        elif path == "/stats":
            self._handle_stats()
        elif path in self.extra_handlers:
            code, content_type, body = self.extra_handlers[path]()
            self._send_response(code, content_type, body)
        else:
            self._send_response(404, "text/plain", "Not Found")
    
    def _handle_health(self) -> None:
        if self.health_checker:
            result = self.health_checker.run_all()
            status = result["status"]
            
            if status == HealthStatus.HEALTHY:
                code = 200
            elif status == HealthStatus.DEGRADED:
                code = 200
            else:
                code = 503
            
            self._send_json(code, result)
        else:
            self._send_json(200, {
                "status": "healthy",
                "timestamp": datetime.now().isoformat(),
            })
    
    def _handle_metrics(self) -> None:
        if self.metrics_collector:
            metrics = self.metrics_collector.get_prometheus_metrics()
            try:
                from .sandbox_pool import get_sandbox_stats
                sandbox_stats = get_sandbox_stats()
                metrics += "\n"
                metrics += f"# HELP sandbox_current_active Current active sandboxes\n"
                metrics += f"# TYPE sandbox_current_active gauge\n"
                metrics += f"sandbox_current_active {sandbox_stats.get('current_active', 0)}\n"
                metrics += f"\n"
                metrics += f"# HELP sandbox_max_concurrent Max concurrent sandboxes allowed\n"
                metrics += f"# TYPE sandbox_max_concurrent gauge\n"
                metrics += f"sandbox_max_concurrent {sandbox_stats.get('max_concurrent', 0)}\n"
                metrics += f"\n"
                metrics += f"# HELP sandbox_total_created Total sandboxes created\n"
                metrics += f"# TYPE sandbox_total_created counter\n"
                metrics += f"sandbox_total_created {sandbox_stats.get('total_created', 0)}\n"
                metrics += f"\n"
                metrics += f"# HELP sandbox_total_destroyed Total sandboxes destroyed\n"
                metrics += f"# TYPE sandbox_total_destroyed counter\n"
                metrics += f"sandbox_total_destroyed {sandbox_stats.get('total_destroyed', 0)}\n"
            except Exception:
                pass
            
            self._send_response(200, "text/plain; charset=utf-8", metrics)
        else:
            self._send_response(503, "text/plain", "Metrics not available")
    
    def _handle_stats(self) -> None:
        if self.metrics_collector:
            stats = self.metrics_collector.get_stats()
            try:
                from .sandbox_pool import get_sandbox_stats
                stats["sandbox"] = get_sandbox_stats()
            except Exception:
                pass
            
            self._send_json(200, stats)
        else:
            self._send_json(503, {"error": "Stats not available"})
    
    def _send_json(self, code: int, data: dict) -> None:
        body = json.dumps(data, indent=2, ensure_ascii=False)
        self._send_response(code, "application/json", body)
    
    def _send_response(self, code: int, content_type: str, body: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body.encode())))
        self.end_headers()
        self.wfile.write(body.encode())

class HealthServer:
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8081,
        metrics_collector: Optional[MetricsCollector] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.metrics_collector = metrics_collector or MetricsCollector()
        self.health_checker = HealthChecker()
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        
        HealthHandler.metrics_collector = self.metrics_collector
        HealthHandler.health_checker = self.health_checker
    
    def add_health_check(
        self,
        name: str,
        check_fn: Callable[[], tuple[bool, str]],
        critical: bool = True,
    ) -> None:
        self.health_checker.add_check(name, check_fn, critical)
    
    def add_endpoint(
        self,
        path: str,
        handler: Callable[[], tuple[int, str, str]],
    ) -> None:
        HealthHandler.extra_handlers[path] = handler
    
    def start(self) -> None:
        if self._server:
            return
        
        self._server = HTTPServer((self.host, self.port), HealthHandler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="health-server",
        )
        self._thread.start()
        
        logger.info(f"Health service started: http://{self.host}:{self.port}")
        logger.info("  /health  - health check")
        logger.info("  /metrics - Prometheus metrics")
        logger.info("  /stats   - JSON stats")
    
    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server = None
            self._thread = None
            logger.info("Health service stopped")

_metrics_collector: Optional[MetricsCollector] = None
_health_server: Optional[HealthServer] = None


def get_metrics_collector() -> MetricsCollector:
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector()
    return _metrics_collector


def start_health_server(
    host: str = "0.0.0.0",
    port: int = 8081,
) -> HealthServer:
    global _health_server
    
    if _health_server is None:
        _health_server = HealthServer(
            host=host,
            port=port,
            metrics_collector=get_metrics_collector(),
        )
        
        _health_server.add_health_check(
            "worker",
            lambda: (True, "Worker is running"),
            critical=True,
        )
        
        def check_sandbox() -> tuple[bool, str]:
            try:
                from .sandbox_pool import get_sandbox_stats
                stats = get_sandbox_stats()
                active = stats.get("current_active", 0)
                max_concurrent = stats.get("max_concurrent", 20)
                if active >= max_concurrent:
                    return False, f"Sandbox full: {active}/{max_concurrent}"
                return True, f"Sandbox: {active}/{max_concurrent}"
            except Exception as e:
                return False, str(e)
        
        _health_server.add_health_check(
            "sandbox",
            check_sandbox,
            critical=False,
        )
        
        _health_server.start()
    
    return _health_server


def stop_health_server() -> None:
    global _health_server
    if _health_server:
        _health_server.stop()
        _health_server = None

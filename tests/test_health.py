"""Unit tests for health server and metrics endpoints."""

from __future__ import annotations

from types import SimpleNamespace

import evaluation.health as health


def setup_function() -> None:
    health._metrics_collector = None
    health._health_server = None


def test_metrics_collector_basic_stats() -> None:
    m = health.MetricsCollector()
    m.record_submission_start()
    m.record_submission_end(success=True, duration_ms=120, passed_cases=2, total_cases=3)
    m.record_error("boom")
    stats = m.get_stats()
    assert stats["submissions"]["total"] == 1
    assert stats["submissions"]["success"] == 1
    assert stats["cases"]["total"] == 3
    assert "eval_submissions_total" in m.get_prometheus_metrics()


def test_health_checker_statuses() -> None:
    checker = health.HealthChecker()
    checker.add_check("ok", lambda: (True, "ok"), critical=True)
    r = checker.run_all()
    assert r["status"] == health.HealthStatus.HEALTHY

    checker2 = health.HealthChecker()
    checker2.add_check("warn", lambda: (False, "warn"), critical=False)
    r2 = checker2.run_all()
    assert r2["status"] == health.HealthStatus.DEGRADED

    checker3 = health.HealthChecker()
    checker3.add_check("bad", lambda: (False, "bad"), critical=True)
    r3 = checker3.run_all()
    assert r3["status"] == health.HealthStatus.UNHEALTHY


def test_health_server_start_stop_with_fake_http(monkeypatch) -> None:
    started = {"serve": 0, "shutdown": 0}

    class FakeHTTPServer:
        def __init__(self, addr, handler):
            self.addr = addr
            self.handler = handler

        def serve_forever(self):
            started["serve"] += 1

        def shutdown(self):
            started["shutdown"] += 1

    class FakeThread:
        def __init__(self, target=None, daemon=None, name=None):
            self.target = target

        def start(self):
            if self.target:
                self.target()

    monkeypatch.setattr(health, "HTTPServer", FakeHTTPServer)
    monkeypatch.setattr(health.threading, "Thread", FakeThread)

    s = health.HealthServer(host="127.0.0.1", port=8999)
    s.start()
    assert started["serve"] == 1
    s.stop()
    assert started["shutdown"] == 1


def test_global_start_stop_health_server(monkeypatch) -> None:
    class DummyHS:
        def __init__(self, host="0.0.0.0", port=8081, metrics_collector=None):
            self.host = host
            self.port = port
            self.started = False
            self.stopped = False
            self.checks = []

        def add_health_check(self, name, check_fn, critical=True):
            self.checks.append((name, critical))

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True

    monkeypatch.setattr(health, "HealthServer", DummyHS)
    monkeypatch.setattr(health, "get_metrics_collector", lambda: health.MetricsCollector())
    server = health.start_health_server(port=8101)
    assert server.started is True
    assert any(name == "worker" for name, _ in server.checks)
    assert any(name == "sandbox" for name, _ in server.checks)

    health.stop_health_server()
    assert health._health_server is None

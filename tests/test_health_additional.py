from __future__ import annotations

import io
from types import SimpleNamespace

import evaluation.health as health


def _make_handler(path: str) -> health.HealthHandler:
    h = health.HealthHandler.__new__(health.HealthHandler)
    h.path = path
    h.wfile = io.BytesIO()
    h.sent = {"code": None, "headers": []}
    h.send_response = lambda code: h.sent.__setitem__("code", code)  # type: ignore[attr-defined]
    h.send_header = lambda k, v: h.sent["headers"].append((k, v))  # type: ignore[attr-defined]
    h.end_headers = lambda: None  # type: ignore[attr-defined]
    return h


def test_health_handler_endpoints_and_response_helpers(monkeypatch) -> None:
    # /health healthy/degraded/unhealthy/no-checker
    handler = _make_handler("/health")
    handler._send_json = lambda code, data: handler.sent.__setitem__("payload", (code, data))  # type: ignore[attr-defined]
    health.HealthHandler.health_checker = SimpleNamespace(run_all=lambda: {"status": health.HealthStatus.HEALTHY})
    handler.do_GET()
    assert handler.sent["payload"][0] == 200

    handler2 = _make_handler("/health")
    handler2._send_json = lambda code, data: handler2.sent.__setitem__("payload", (code, data))  # type: ignore[attr-defined]
    health.HealthHandler.health_checker = SimpleNamespace(run_all=lambda: {"status": health.HealthStatus.DEGRADED})
    handler2.do_GET()
    assert handler2.sent["payload"][0] == 200

    handler3 = _make_handler("/health")
    handler3._send_json = lambda code, data: handler3.sent.__setitem__("payload", (code, data))  # type: ignore[attr-defined]
    health.HealthHandler.health_checker = SimpleNamespace(run_all=lambda: {"status": health.HealthStatus.UNHEALTHY})
    handler3.do_GET()
    assert handler3.sent["payload"][0] == 503

    handler4 = _make_handler("/health")
    handler4._send_json = lambda code, data: handler4.sent.__setitem__("payload", (code, data))  # type: ignore[attr-defined]
    health.HealthHandler.health_checker = None
    handler4.do_GET()
    assert handler4.sent["payload"][0] == 200

    # /metrics with and without collector
    handler5 = _make_handler("/metrics")
    handler5._send_response = lambda code, ctype, body: handler5.sent.__setitem__("payload", (code, ctype, body))  # type: ignore[attr-defined]
    health.HealthHandler.metrics_collector = SimpleNamespace(get_prometheus_metrics=lambda: "base\n")
    monkeypatch.setattr(
        "evaluation.sandbox_pool.get_sandbox_stats",
        lambda: {"current_active": 1, "max_concurrent": 2, "total_created": 3, "total_destroyed": 4},
    )
    handler5.do_GET()
    assert handler5.sent["payload"][0] == 200
    assert "sandbox_current_active" in handler5.sent["payload"][2]

    handler6 = _make_handler("/metrics")
    handler6._send_response = lambda code, ctype, body: handler6.sent.__setitem__("payload", (code, ctype, body))  # type: ignore[attr-defined]
    health.HealthHandler.metrics_collector = None
    handler6.do_GET()
    assert handler6.sent["payload"][0] == 503

    # /stats with and without collector
    handler7 = _make_handler("/stats")
    handler7._send_json = lambda code, data: handler7.sent.__setitem__("payload", (code, data))  # type: ignore[attr-defined]
    health.HealthHandler.metrics_collector = SimpleNamespace(get_stats=lambda: {"a": 1})
    handler7.do_GET()
    assert handler7.sent["payload"][0] == 200

    handler8 = _make_handler("/stats")
    handler8._send_json = lambda code, data: handler8.sent.__setitem__("payload", (code, data))  # type: ignore[attr-defined]
    health.HealthHandler.metrics_collector = None
    handler8.do_GET()
    assert handler8.sent["payload"][0] == 503

    # extra endpoint and 404
    handler9 = _make_handler("/x")
    handler9._send_response = lambda code, ctype, body: handler9.sent.__setitem__("payload", (code, ctype, body))  # type: ignore[attr-defined]
    health.HealthHandler.extra_handlers["/x"] = lambda: (201, "text/plain", "ok")
    handler9.do_GET()
    assert handler9.sent["payload"][0] == 201
    health.HealthHandler.extra_handlers.pop("/x", None)

    handler10 = _make_handler("/nope")
    handler10._send_response = lambda code, ctype, body: handler10.sent.__setitem__("payload", (code, ctype, body))  # type: ignore[attr-defined]
    handler10.do_GET()
    assert handler10.sent["payload"][0] == 404

    # direct helper coverage
    h = _make_handler("/dummy")
    health.HealthHandler._send_response(h, 200, "text/plain", "hello")
    assert h.sent["code"] == 200
    assert h.wfile.getvalue() == b"hello"
    assert ("Content-Type", "text/plain") in h.sent["headers"]


def test_health_server_start_idempotent_and_singleton(monkeypatch) -> None:
    health._health_server = None

    started = {"start": 0, "stop": 0}

    class _Server:
        def __init__(self, host="0.0.0.0", port=8081, metrics_collector=None):
            self.host = host
            self.port = port
            self.metrics_collector = metrics_collector
            self.checks = []

        def add_health_check(self, name, check_fn, critical=True):
            self.checks.append((name, critical, check_fn))

        def start(self):
            started["start"] += 1

        def stop(self):
            started["stop"] += 1

    monkeypatch.setattr(health, "HealthServer", _Server)
    monkeypatch.setattr(health, "get_metrics_collector", lambda: health.MetricsCollector())

    s1 = health.start_health_server(host="127.0.0.1", port=9090)
    s2 = health.start_health_server(host="127.0.0.1", port=9090)
    assert s1 is s2
    assert started["start"] == 1
    assert any(name == "worker" for name, _, _ in s1.checks)
    assert any(name == "sandbox" for name, _, _ in s1.checks)
    # execute sandbox check closure
    sandbox_check = [fn for name, _, fn in s1.checks if name == "sandbox"][0]
    ok, msg = sandbox_check()
    assert isinstance(ok, bool)
    assert isinstance(msg, str)

    health.stop_health_server()
    assert started["stop"] == 1
    assert health._health_server is None


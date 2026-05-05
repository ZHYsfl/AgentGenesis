"""Unit tests for backend evaluation client helpers."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest
import requests

from evaluation.client import EvaluationClient
from evaluation.models import CaseResult, CaseStatus, PhaseResult, PhaseStatus


def _cfg(**overrides):
    base = {
        "backend_url": "http://backend",
        "internal_api_key": "internal-key",
        "user_api_key": "user-key",
        "request_timeout": 9,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_client_init_and_headers(monkeypatch) -> None:
    import evaluation.client as mod

    monkeypatch.setattr(mod, "get_config", lambda: _cfg())
    c = EvaluationClient()
    assert c.base_url == "http://backend"
    assert c._headers["X-Internal-Key"] == "internal-key"
    assert c._api_headers["X-API-Key"] == "user-key"


def test_client_init_requires_internal_key(monkeypatch) -> None:
    import evaluation.client as mod

    monkeypatch.setattr(mod, "get_config", lambda: _cfg(internal_api_key=""))
    with pytest.raises(ValueError):
        EvaluationClient()


def test_parse_submission_supports_json_string(monkeypatch, sample_submission_dict) -> None:
    import evaluation.client as mod

    monkeypatch.setattr(mod, "get_config", lambda: _cfg())
    c = EvaluationClient()
    raw = dict(sample_submission_dict)
    raw["phase_config"] = json.dumps(raw["phase_config"])
    raw["runtime_config"] = json.dumps(raw["runtime_config"])
    sub = c._parse_submission(raw)
    assert sub.submit_id == 101
    assert sub.phase_config.phase_name == "p1"
    assert sub.runtime_config.key_ids == [7]


def test_download_code_checksum_mismatch_returns_empty(monkeypatch, zip_bytes, make_response) -> None:
    import evaluation.client as mod

    monkeypatch.setattr(mod, "get_config", lambda: _cfg())
    c = EvaluationClient()
    content = zip_bytes({"solution.py": "print(1)"})
    bad_checksum = hashlib.sha256(b"something-else").hexdigest()

    monkeypatch.setattr(mod.requests, "head", lambda *args, **kwargs: make_response(headers={"Content-Length": str(len(content))}))
    monkeypatch.setattr(mod.requests, "get", lambda *args, **kwargs: make_response(status_code=200, content=content))

    assert c.download_code("http://signed", expected_checksum=bad_checksum) == {}


def test_download_code_4xx_no_retry(monkeypatch, make_response) -> None:
    import evaluation.client as mod

    monkeypatch.setattr(mod, "get_config", lambda: _cfg())
    c = EvaluationClient()
    monkeypatch.setattr(mod.requests, "head", lambda *args, **kwargs: make_response(headers={}))
    monkeypatch.setattr(mod.requests, "get", lambda *args, **kwargs: make_response(status_code=404, text="not found"))
    assert c.download_code("http://signed") == {}


def test_report_result_maps_status_and_posts(monkeypatch, make_response) -> None:
    import evaluation.client as mod

    monkeypatch.setattr(mod, "get_config", lambda: _cfg())
    posted = {}

    def _post(url, headers, json, timeout):
        posted["payload"] = json
        return make_response(status_code=200)

    monkeypatch.setattr(mod.requests, "post", _post)
    c = EvaluationClient()
    ok = c.report_result(11, PhaseResult(status=PhaseStatus.ERROR, score=1), max_retries=1)
    assert ok is True
    assert posted["payload"]["status"] == "failed"


def test_create_case_record_posts_backend_status(monkeypatch, make_response) -> None:
    import evaluation.client as mod

    monkeypatch.setattr(mod, "get_config", lambda: _cfg())
    captured = {}

    def _post(url, headers, json, timeout):
        captured["json"] = json
        return make_response(status_code=200, json_data={"data": {"case_id": 66}})

    monkeypatch.setattr(mod.requests, "post", _post)
    c = EvaluationClient()
    case = CaseResult(case_index=2, status=CaseStatus.ERROR, logs="x")
    result = c.create_case_record(1, case)
    assert result is not None
    assert result["case_id"] == 66
    assert captured["json"]["status"] == "failed"


def test_claim_submission_posts_correctly(monkeypatch, make_response) -> None:
    import evaluation.client as mod

    monkeypatch.setattr(mod, "get_config", lambda: _cfg())
    captured = {}

    def _post(url, headers, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return make_response(status_code=200)

    monkeypatch.setattr(mod.requests, "post", _post)
    c = EvaluationClient()
    assert c.claim_submission(42) is True
    assert "/claim-submission" in captured["url"]
    assert captured["json"]["submit_id"] == 42


def test_unclaim_submission_posts_correctly(monkeypatch, make_response) -> None:
    import evaluation.client as mod

    monkeypatch.setattr(mod, "get_config", lambda: _cfg())
    captured = {}

    def _post(url, headers, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return make_response(status_code=200)

    monkeypatch.setattr(mod.requests, "post", _post)
    c = EvaluationClient()
    assert c.unclaim_submission(99) is True
    assert "/unclaim-submission" in captured["url"]
    assert captured["json"]["submit_id"] == 99


def test_get_phase_artifact_info_returns_parsed(monkeypatch, make_response) -> None:
    import evaluation.client as mod

    monkeypatch.setattr(mod, "get_config", lambda: _cfg())

    def _post(url, headers, json, timeout):
        return make_response(
            status_code=200,
            json_data={"data": {
                "exists": True,
                "artifact_checksum": "abc123",
                "artifact_url": "http://oss/artifact.zip",
                "artifact_size": 12345,
            }},
        )

    monkeypatch.setattr(mod.requests, "post", _post)
    c = EvaluationClient()
    info = c.get_phase_artifact_info("Maze", phase_order=1)
    assert info is not None
    assert info["exists"] is True
    assert info["artifact_checksum"] == "abc123"


def test_create_gateway_token_returns_token(monkeypatch, make_response) -> None:
    import evaluation.client as mod

    monkeypatch.setattr(mod, "get_config", lambda: _cfg())

    def _post(url, headers, json, timeout):
        return make_response(
            status_code=200,
            json_data={"data": {"token": "gw-tok-1", "gateway_url": "http://gw"}},
        )

    monkeypatch.setattr(mod.requests, "post", _post)
    c = EvaluationClient()
    result = c.create_gateway_token(submit_id=1, user_id=2, key_ids=[3])
    assert result is not None
    assert result["token"] == "gw-tok-1"


def test_get_gateway_token_usage_returns_stats(monkeypatch, make_response) -> None:
    import evaluation.client as mod

    monkeypatch.setattr(mod, "get_config", lambda: _cfg())

    def _post(url, headers, json, timeout):
        return make_response(
            status_code=200,
            json_data={"data": {"used_chars": 5000, "used_requests": 12}},
        )

    monkeypatch.setattr(mod.requests, "post", _post)
    c = EvaluationClient()
    usage = c.get_gateway_token_usage(submit_id=1)
    assert usage is not None
    assert usage["used_chars"] == 5000
    assert usage["used_requests"] == 12


def test_revoke_gateway_token_posts_correctly(monkeypatch, make_response) -> None:
    import evaluation.client as mod

    monkeypatch.setattr(mod, "get_config", lambda: _cfg())
    captured = {}

    def _post(url, headers, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return make_response(status_code=200)

    monkeypatch.setattr(mod.requests, "post", _post)
    c = EvaluationClient()
    assert c.revoke_gateway_token(submit_id=77) is True
    assert "/revoke-gateway-token" in captured["url"]
    assert captured["json"]["submit_id"] == 77


def test_revision_create_and_list_use_slug(monkeypatch, make_response) -> None:
    import evaluation.client as mod

    monkeypatch.setattr(mod, "get_config", lambda: _cfg())
    calls = {"post": None, "get": None}

    def _post(url, headers, json, timeout):
        calls["post"] = {"url": url, "json": json}
        return make_response(status_code=200, json_data={"data": {"revision_id": 1}})

    def _get(url, headers, params, timeout):
        calls["get"] = {"url": url, "params": params}
        return make_response(status_code=200, json_data={"data": {"revisions": []}})

    monkeypatch.setattr(mod.requests, "post", _post)
    monkeypatch.setattr(mod.requests, "get", _get)

    c = EvaluationClient()
    out = c.create_revision("Maze Exploration", "rev", "desc", {"x": 1})
    lst = c.list_revisions("Maze Exploration", phase_order=2, status="open")
    assert out == {"revision_id": 1}
    assert lst == []
    assert "/problems/s/maze-exploration/revisions" in calls["post"]["url"]
    assert calls["get"]["params"]["phase_order"] == "2"

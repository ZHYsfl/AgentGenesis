from __future__ import annotations

import json
import zipfile
from types import SimpleNamespace

import pytest
import requests

import evaluation.client as client_mod
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


def _mk_client(monkeypatch) -> EvaluationClient:
    monkeypatch.setattr(client_mod, "get_config", lambda: _cfg())
    return EvaluationClient()


def test_get_pending_submissions_skip_bad_entry(monkeypatch, make_response) -> None:
    c = _mk_client(monkeypatch)
    good = {
        "submit_id": 1,
        "user_id": 2,
        "phase_id": 3,
        "phase_config": {"phase_order": 1, "phase_level": "Easy"},
        "runtime_config": {"key_id": 7},
    }
    bad = {"submit_id": 9}

    monkeypatch.setattr(
        client_mod.requests,
        "post",
        lambda *args, **kwargs: make_response(
            status_code=200,
            json_data={"data": {"submissions": [good, bad]}},
        ),
    )
    out = c.get_pending_submissions(limit=2)
    assert len(out) == 1
    assert out[0].submit_id == 1

    def _raise(*args, **kwargs):
        raise requests.RequestException("boom")

    monkeypatch.setattr(client_mod.requests, "post", _raise)
    assert c.get_pending_submissions() == []


def test_download_code_retry_and_extract_branches(monkeypatch, zip_bytes, make_response) -> None:
    c = _mk_client(monkeypatch)
    sleeps: list[int] = []
    monkeypatch.setattr("time.sleep", lambda sec: sleeps.append(int(sec)))

    payload = zip_bytes({"solution.py": "print(1)"})
    calls = {"count": 0}

    def _get(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise requests.Timeout("timeout")
        return make_response(status_code=200, content=payload)

    monkeypatch.setattr(client_mod.requests, "head", lambda *args, **kwargs: make_response(headers={}))
    monkeypatch.setattr(client_mod.requests, "get", _get)
    out = c.download_code("http://signed", max_retries=2)
    assert "solution.py" in out
    assert sleeps == [1]

    # 5xx -> retry, then non-zip content -> fallback to single solution.py
    calls2 = {"count": 0}

    class _Resp500:
        status_code = 500
        text = "err"
        content = b""

        def raise_for_status(self):
            err = requests.HTTPError("500")
            err.response = self
            raise err

    def _get_500_then_text(*args, **kwargs):
        calls2["count"] += 1
        if calls2["count"] == 1:
            return _Resp500()
        return make_response(status_code=200, content=b"print('x')")

    monkeypatch.setattr(client_mod.requests, "get", _get_500_then_text)
    out2 = c.download_code("http://signed", max_retries=2)
    assert out2["solution.py"] == "print('x')"

    # generic exception -> {}
    monkeypatch.setattr(client_mod.requests, "get", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("x")))
    assert c.download_code("http://signed") == {}


def test_report_and_case_record_failure_branches(monkeypatch, make_response) -> None:
    c = _mk_client(monkeypatch)

    # report_case_status mapping + exception
    captured = {}

    def _post_case(url, headers, json, timeout):
        captured["status"] = json["case_status"]
        return make_response(status_code=200)

    monkeypatch.setattr(client_mod.requests, "post", _post_case)
    assert c.report_case_status(1, 0, "tle") is True
    assert captured["status"] == "failed"

    monkeypatch.setattr(client_mod.requests, "post", lambda *args, **kwargs: (_ for _ in ()).throw(requests.RequestException("x")))
    assert c.report_case_status(1, 0, "passed") is False

    # report_result retries and final failure
    seq = {"n": 0}

    def _post_result(url, headers, json, timeout):
        seq["n"] += 1
        if seq["n"] < 3:
            return make_response(status_code=500, text="err")
        return make_response(status_code=200)

    monkeypatch.setattr(client_mod.requests, "post", _post_result)
    monkeypatch.setattr("time.sleep", lambda *_: None)
    ok = c.report_result(1, PhaseResult(status=PhaseStatus.RUNNING), max_retries=3)
    assert ok is True

    monkeypatch.setattr(client_mod.requests, "post", lambda *args, **kwargs: make_response(status_code=500, text="err"))
    assert c.report_result(1, PhaseResult(status=PhaseStatus.ERROR), max_retries=2) is False

    # create_case_record non-200 / exception
    case = CaseResult(case_index=0, status=CaseStatus.PASSED, input_data="a", output_data="b", expected_output="c")
    monkeypatch.setattr(client_mod.requests, "post", lambda *args, **kwargs: make_response(status_code=400, text="bad"))
    assert c.create_case_record(1, case) is None
    monkeypatch.setattr(client_mod.requests, "post", lambda *args, **kwargs: (_ for _ in ()).throw(requests.RequestException("x")))
    assert c.create_case_record(1, case) is None


def test_gateway_and_artifact_related_error_paths(monkeypatch, make_response) -> None:
    c = _mk_client(monkeypatch)

    # get_user_key: success empty => (None, None), non-200, exception
    monkeypatch.setattr(client_mod.requests, "post", lambda *args, **kwargs: make_response(status_code=200, json_data={"data": {}}))
    assert c.get_user_key(1, 2) == (None, None)
    monkeypatch.setattr(client_mod.requests, "post", lambda *args, **kwargs: make_response(status_code=500, text="x"))
    assert c.get_user_key(1, 2) == (None, None)
    monkeypatch.setattr(client_mod.requests, "post", lambda *args, **kwargs: (_ for _ in ()).throw(requests.RequestException("x")))
    assert c.get_user_key(1, 2) == (None, None)

    # artifact info / gateway token / revoke/reset/usage
    monkeypatch.setattr(client_mod.requests, "post", lambda *args, **kwargs: make_response(status_code=500, text="x"))
    assert c.get_phase_artifact_info("Maze", 1) is None
    assert c.create_gateway_token(submit_id=1, user_id=2, key_ids=[3]) is None
    assert c.revoke_gateway_token(1) is False
    assert c.reset_gateway_token_usage(1) is False
    assert c.get_gateway_token_usage(1) is None

    monkeypatch.setattr(client_mod.requests, "post", lambda *args, **kwargs: (_ for _ in ()).throw(requests.RequestException("x")))
    assert c.get_phase_artifact_info("Maze", 1) is None
    assert c.create_gateway_token(submit_id=1, user_id=2, key_ids=[3], allowed_models=["gpt"]) is None
    assert c.revoke_gateway_token(1) is False
    assert c.reset_gateway_token_usage(1) is False
    assert c.get_gateway_token_usage(1) is None


def test_version_and_revision_error_paths(monkeypatch, make_response) -> None:
    c = _mk_client(monkeypatch)

    monkeypatch.setattr(client_mod.requests, "get", lambda *args, **kwargs: (_ for _ in ()).throw(requests.RequestException("x")))
    assert c.get_version_history("Maze", phase_order=0) == {}
    assert c.get_version_diff("Maze", "a", "b") == {}
    assert c.list_revisions("Maze", phase_order=1, status="open") == []
    assert c.get_data_export("Maze", 10, 1) == {}
    assert c.get_phase_template("Maze", 1, "en", "sha") == {}
    assert c.get_phase_files("Maze", 1, "sha") == {}

    monkeypatch.setattr(client_mod.requests, "post", lambda *args, **kwargs: make_response(status_code=400, text="bad"))
    assert c.create_revision("Maze", "r", "d", {"x": 1}, problem_meta={"overview": "o"}) is None

    monkeypatch.setattr(client_mod.requests, "post", lambda *args, **kwargs: (_ for _ in ()).throw(requests.RequestException("x")))
    assert c.create_revision("Maze", "r", "d", {"x": 1}) is None

    monkeypatch.setattr(client_mod.requests, "put", lambda *args, **kwargs: (_ for _ in ()).throw(requests.RequestException("x")))
    assert "error" in c.merge_revision("Maze", 1)
    assert c.close_revision("Maze", 1) is False


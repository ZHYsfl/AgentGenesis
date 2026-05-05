"""Cross-module: EvaluationClient API calls against real Go backend."""

from __future__ import annotations

import pytest

from evaluation.client import EvaluationClient


@pytest.fixture(scope="module")
def api_client(backend_url: str) -> EvaluationClient:
    """Client with backend_url from env (INTERNAL_API_KEY, AGENT_GENESIS_API_KEY already set)."""
    return EvaluationClient(base_url=backend_url)


@pytest.mark.cross_module
def test_get_version_history(api_client: EvaluationClient, cross_slug: str) -> None:
    """get_version_history returns commits list for published problem."""
    # Client uses title -> slugify; slug format "crosstest-123" is idempotent under slugify.
    result = api_client.get_version_history(cross_slug, limit=10)
    assert isinstance(result, dict)
    commits = result.get("commits", [])
    assert len(commits) >= 1
    assert "sha" in commits[0]
    assert "message" in commits[0]


@pytest.mark.cross_module
def test_get_version_diff(api_client: EvaluationClient, cross_slug: str) -> None:
    """get_version_diff returns diff and optional artifact_diffs."""
    hist = api_client.get_version_history(cross_slug, limit=2)
    commits = hist.get("commits", [])
    if len(commits) < 2:
        pytest.skip("need at least 2 commits for diff")
    from_sha = commits[1]["sha"]
    to_sha = commits[0]["sha"]
    result = api_client.get_version_diff(cross_slug, from_sha, to_sha)
    assert isinstance(result, dict)
    assert "diff" in result
    # artifact_diffs optional
    if "artifact_diffs" in result:
        assert isinstance(result["artifact_diffs"], dict)


@pytest.mark.cross_module
def test_list_create_revisions(api_client: EvaluationClient, cross_slug: str) -> None:
    """Create revision via API, then list and verify."""
    from evaluation.api import create_revision
    cfg = {"phase_order": 1, "phase_name": "Cross Rev", "phase_type": "agent", "phase_level": "Easy",
           "language": "en", "artifact_base64": _minimal_artifact_b64(), "description": "x", "starter_code": "# x"}
    rev = create_revision(cross_slug, "CrossRev Title", cfg, description="desc", client=api_client)
    assert rev is not None, "create_revision returned None"
    assert isinstance(rev, dict)
    assert "revision_id" in rev or "error" in rev
    if "error" in rev:
        pytest.skip("create_revision failed (e.g. API key): %s" % rev.get("error"))
    rev_id = rev["revision_id"]
    lst = api_client.list_revisions(cross_slug, status="open")
    ids = [r.get("revision_id") for r in lst if isinstance(r, dict)]
    assert rev_id in ids


def _minimal_artifact_b64() -> str:
    import base64
    import io
    import json
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("sandbox/run.py", "print(1)")
        zf.writestr("visibility_manifest.json", json.dumps({"private": []}))
    return base64.b64encode(buf.getvalue()).decode("utf-8")


@pytest.mark.cross_module
def test_get_phase_files(api_client: EvaluationClient, cross_slug: str) -> None:
    """get_phase_files returns files and binary_files (binary_files may be None if absent)."""
    result = api_client.get_phase_files(cross_slug, 1)
    assert isinstance(result, dict)
    assert "files" in result
    assert "commit" in result
    assert isinstance(result["files"], dict)
    # binary_files: list or None (backend may return null when empty)
    bf = result.get("binary_files")
    assert bf is None or isinstance(bf, list)


@pytest.mark.cross_module
def test_get_phase_template(api_client: EvaluationClient, cross_slug: str) -> None:
    """get_phase_template returns description etc."""
    result = api_client.get_phase_template(cross_slug, phase_order=1)
    assert isinstance(result, dict)
    assert "description" in result or "starter_code" in result


@pytest.mark.cross_module
def test_get_data_export(api_client: EvaluationClient, cross_slug: str) -> None:
    """get_data_export returns structure (may be empty)."""
    result = api_client.get_data_export(cross_slug, limit=10)
    assert isinstance(result, dict)

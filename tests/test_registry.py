"""Tests for evaluation.registry — visibility manifest injection, checksum, _prepare_phase_data."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import zipfile
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ..models import PhaseConfig, ProblemConfig
from ..registry import (
    ProblemRegistry,
    compute_artifact_checksum,
    inject_visibility_manifest,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_zip(files: dict[str, str]) -> bytes:
    """Build a minimal in-memory zip from {filename: content}."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return buf.getvalue()


def _zip_to_b64(files: dict[str, str]) -> str:
    return base64.b64encode(_make_zip(files)).decode()


def _b64_to_zip_entries(b64: str) -> dict[str, str]:
    """Decode base64 → zip → {filename: content}."""
    raw = base64.b64decode(b64)
    entries: dict[str, str] = {}
    with zipfile.ZipFile(io.BytesIO(raw), "r") as zf:
        for info in zf.infolist():
            if not info.is_dir():
                entries[info.filename] = zf.read(info.filename).decode()
    return entries


# ===================================================================
# compute_artifact_checksum
# ===================================================================

class TestComputeArtifactChecksum:
    def test_known_input(self) -> None:
        data = b"hello-world"
        b64 = base64.b64encode(data).decode()
        expected = hashlib.sha256(data).hexdigest()
        assert compute_artifact_checksum(b64) == expected

    def test_empty_string(self) -> None:
        assert compute_artifact_checksum("") == ""

    def test_invalid_base64(self) -> None:
        # Should not raise, just return empty
        assert compute_artifact_checksum("!!!not-base64!!!") == ""


# ===================================================================
# inject_visibility_manifest (new format: {"private": [...]})
# ===================================================================

class TestInjectVisibilityManifest:
    def test_empty_artifact_returns_unchanged(self) -> None:
        assert inject_visibility_manifest("", ["f.py"]) == ""

    def test_creates_manifest_in_zip(self) -> None:
        original = _zip_to_b64({"sandbox/run.py": "print(1)"})
        private = ["sandbox/run.py"]
        result = inject_visibility_manifest(original, private)
        entries = _b64_to_zip_entries(result)
        assert "visibility_manifest.json" in entries
        manifest = json.loads(entries["visibility_manifest.json"])
        assert manifest == {"private": ["sandbox/run.py"]}

    def test_empty_private_list_creates_manifest(self) -> None:
        """Empty list = all files public, but manifest is still written."""
        original = _zip_to_b64({"sandbox/run.py": "print(1)"})
        result = inject_visibility_manifest(original, [])
        entries = _b64_to_zip_entries(result)
        assert "visibility_manifest.json" in entries
        manifest = json.loads(entries["visibility_manifest.json"])
        assert manifest == {"private": []}

    def test_preserves_other_files(self) -> None:
        original = _zip_to_b64({
            "sandbox/run.py": "print(1)",
            "sandbox/helper.py": "def f(): pass",
        })
        private = ["sandbox/run.py"]
        entries = _b64_to_zip_entries(inject_visibility_manifest(original, private))
        assert entries["sandbox/run.py"] == "print(1)"
        assert entries["sandbox/helper.py"] == "def f(): pass"

    def test_replaces_existing_manifest(self) -> None:
        old_manifest = json.dumps({"private": ["old.py"]})
        original = _zip_to_b64({
            "sandbox/run.py": "print(1)",
            "visibility_manifest.json": old_manifest,
        })
        new_private = ["sandbox/run.py"]
        entries = _b64_to_zip_entries(inject_visibility_manifest(original, new_private))
        manifest = json.loads(entries["visibility_manifest.json"])
        assert manifest == {"private": ["sandbox/run.py"]}

    def test_invalid_base64_raises(self) -> None:
        with pytest.raises(Exception):
            inject_visibility_manifest("!!!bad!!!", ["f.py"])


# ===================================================================
# _prepare_phase_data
# ===================================================================

class TestPreparePhaseData:
    """Tests for ProblemRegistry._prepare_phase_data (internal method)."""

    @staticmethod
    def _make_registry() -> ProblemRegistry:
        """Create a registry without singleton side effects."""
        reg = object.__new__(ProblemRegistry)
        reg.mode = __import__("agent_genesis.config", fromlist=["ClientMode"]).ClientMode.WORKER
        reg.api_key = "test-key"
        reg.backend_url = "http://localhost:9999"
        reg._problems = {}
        return reg

    @staticmethod
    def _make_problem(**kwargs: Any) -> ProblemConfig:
        defaults: dict[str, Any] = {
            "title": "Test Problem",
            "level": "Easy",
            "phases": [PhaseConfig(phase_order=1, phase_level="Easy", phase_name="p1")],
        }
        defaults.update(kwargs)
        return ProblemConfig(**defaults)

    def test_strips_private_files_from_payload(self) -> None:
        reg = self._make_registry()
        phase = PhaseConfig(
            phase_order=1,
            phase_level="Easy",
            phase_name="p1",
            private_files=["sandbox/run.py"],
        )
        problem = self._make_problem()
        with patch.object(reg, "_get_existing_checksum", return_value=""):
            data = reg._prepare_phase_data(problem, phase)
        assert "private_files" not in data

    def test_injects_manifest_into_zip(self) -> None:
        reg = self._make_registry()
        artifact_b64 = _zip_to_b64({"sandbox/run.py": "print(1)"})
        phase = PhaseConfig(
            phase_order=1,
            phase_level="Easy",
            phase_name="p1",
            artifact_base64=artifact_b64,
            private_files=["sandbox/run.py"],
        )
        problem = self._make_problem()
        with patch.object(reg, "_get_existing_checksum", return_value=""):
            data = reg._prepare_phase_data(problem, phase)

        # The returned artifact_base64 should contain the manifest
        entries = _b64_to_zip_entries(data["artifact_base64"])
        assert "visibility_manifest.json" in entries
        manifest = json.loads(entries["visibility_manifest.json"])
        assert manifest["private"] == ["sandbox/run.py"]

    def test_no_private_files_no_injection(self) -> None:
        """private_files=None (default) → no manifest injected."""
        reg = self._make_registry()
        artifact_b64 = _zip_to_b64({"sandbox/run.py": "print(1)"})
        phase = PhaseConfig(
            phase_order=1,
            phase_level="Easy",
            phase_name="p1",
            artifact_base64=artifact_b64,
            # private_files left as default None
        )
        problem = self._make_problem()
        with patch.object(reg, "_get_existing_checksum", return_value=""):
            data = reg._prepare_phase_data(problem, phase)

        entries = _b64_to_zip_entries(data["artifact_base64"])
        assert "visibility_manifest.json" not in entries

    def test_empty_private_list_injects_manifest(self) -> None:
        """private_files=[] → manifest with empty private list is injected."""
        reg = self._make_registry()
        artifact_b64 = _zip_to_b64({"sandbox/run.py": "print(1)"})
        phase = PhaseConfig(
            phase_order=1,
            phase_level="Easy",
            phase_name="p1",
            artifact_base64=artifact_b64,
            private_files=[],  # explicitly empty = all public
        )
        problem = self._make_problem()
        with patch.object(reg, "_get_existing_checksum", return_value=""):
            data = reg._prepare_phase_data(problem, phase)

        entries = _b64_to_zip_entries(data["artifact_base64"])
        assert "visibility_manifest.json" in entries
        manifest = json.loads(entries["visibility_manifest.json"])
        assert manifest["private"] == []

    def test_skips_upload_on_matching_checksum(self) -> None:
        reg = self._make_registry()
        artifact_b64 = _zip_to_b64({"sandbox/run.py": "print(1)"})
        expected_checksum = compute_artifact_checksum(artifact_b64)
        phase = PhaseConfig(
            phase_order=1,
            phase_level="Easy",
            phase_name="p1",
            artifact_base64=artifact_b64,
        )
        problem = self._make_problem()
        with patch.object(reg, "_get_existing_checksum", return_value=expected_checksum):
            data = reg._prepare_phase_data(problem, phase)

        # artifact_base64 should be removed, checksum sent instead
        assert "artifact_base64" not in data
        assert data["artifact_checksum"] == expected_checksum

    def test_uploads_on_different_checksum(self) -> None:
        reg = self._make_registry()
        artifact_b64 = _zip_to_b64({"sandbox/run.py": "print(1)"})
        phase = PhaseConfig(
            phase_order=1,
            phase_level="Easy",
            phase_name="p1",
            artifact_base64=artifact_b64,
        )
        problem = self._make_problem()
        with patch.object(reg, "_get_existing_checksum", return_value="different-checksum"):
            data = reg._prepare_phase_data(problem, phase)

        # artifact_base64 should still be present (upload required)
        assert "artifact_base64" in data


# ===================================================================
# _register_phase payload: is_public / data_public / background
# ===================================================================

class TestRegisterPhasePayload:
    """Verify that _register_phase builds payloads containing the open-source fields."""

    @staticmethod
    def _make_registry() -> ProblemRegistry:
        reg = object.__new__(ProblemRegistry)
        reg.mode = __import__("agent_genesis.config", fromlist=["ClientMode"]).ClientMode.WORKER
        reg.api_key = "test-key"
        reg.backend_url = "http://localhost:9999"
        reg._problems = {}
        return reg

    def test_register_phase_sends_is_public_and_background(self) -> None:
        reg = self._make_registry()
        phase = PhaseConfig(phase_order=1, phase_level="Easy", phase_name="p1")
        problem = ProblemConfig(
            title="Public Problem",
            level="Easy",
            phases=[phase],
            is_public=True,
            data_public=True,
            background="# BG\nHello",
        )

        captured: dict[str, Any] = {}

        def mock_post(url: str, *, headers: Any, json: Any, timeout: Any) -> MagicMock:
            captured.update(json)
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"data": {}}
            return resp

        with (
            patch.object(reg, "_get_existing_checksum", return_value=""),
            patch("agent_genesis.registry.requests.post", side_effect=mock_post),
        ):
            reg._register_phase(problem, phase, _allow_fallback=False)

        assert captured["is_public"] is True
        assert captured["data_public"] is True
        assert captured["background"] == "# BG\nHello"

    def test_register_phase_default_is_not_public(self) -> None:
        reg = self._make_registry()
        phase = PhaseConfig(phase_order=1, phase_level="Easy", phase_name="p1")
        problem = ProblemConfig(title="Private", level="Easy", phases=[phase])

        captured: dict[str, Any] = {}

        def mock_post(url: str, *, headers: Any, json: Any, timeout: Any) -> MagicMock:
            captured.update(json)
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"data": {}}
            return resp

        with (
            patch.object(reg, "_get_existing_checksum", return_value=""),
            patch("agent_genesis.registry.requests.post", side_effect=mock_post),
        ):
            reg._register_phase(problem, phase, _allow_fallback=False)

        assert captured["is_public"] is False
        assert captured["data_public"] is False
        assert captured["background"] == ""


# ===================================================================
# _create_revision payload: is_public / data_public / background
# ===================================================================

class TestCreateRevisionPayload:
    """Verify that _create_revision includes open-source fields in problem_meta."""

    @staticmethod
    def _make_registry() -> ProblemRegistry:
        reg = object.__new__(ProblemRegistry)
        reg.mode = __import__("agent_genesis.config", fromlist=["ClientMode"]).ClientMode.WORKER
        reg.api_key = "test-key"
        reg.backend_url = "http://localhost:9999"
        reg._problems = {}
        return reg

    def test_revision_includes_is_public_in_problem_meta(self) -> None:
        reg = self._make_registry()
        phase = PhaseConfig(phase_order=1, phase_level="Easy", phase_name="p1")
        problem = ProblemConfig(
            title="Rev Problem",
            level="Easy",
            phases=[phase],
            is_public=True,
            data_public=False,
            background="# Revision BG",
        )
        reg._problems[problem.title] = problem

        captured: dict[str, Any] = {}

        def mock_post(url: str, *, headers: Any, json: Any, timeout: Any) -> MagicMock:
            captured.update(json)
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"data": {"auto_merged": True}}
            return resp

        with (
            patch.object(reg, "_get_existing_checksum", return_value=""),
            patch("agent_genesis.registry.requests.post", side_effect=mock_post),
        ):
            reg._create_revision(problem, phase)

        meta = captured.get("problem_meta", {})
        assert meta["is_public"] is True
        assert meta["data_public"] is False
        assert meta["background"] == "# Revision BG"

    def test_revision_omits_background_when_empty(self) -> None:
        """background="" should not appear in problem_meta."""
        reg = self._make_registry()
        phase = PhaseConfig(phase_order=1, phase_level="Easy", phase_name="p1")
        problem = ProblemConfig(
            title="No BG Problem",
            level="Easy",
            phases=[phase],
            is_public=False,
            data_public=False,
            background="",
        )
        reg._problems[problem.title] = problem

        captured: dict[str, Any] = {}

        def mock_post(url: str, *, headers: Any, json: Any, timeout: Any) -> MagicMock:
            captured.update(json)
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"data": {"auto_merged": True}}
            return resp

        with (
            patch.object(reg, "_get_existing_checksum", return_value=""),
            patch("agent_genesis.registry.requests.post", side_effect=mock_post),
        ):
            reg._create_revision(problem, phase)

        meta = captured.get("problem_meta", {})
        assert "background" not in meta

    def test_revision_includes_background_when_nonempty(self) -> None:
        """Non-empty background must appear in problem_meta."""
        reg = self._make_registry()
        phase = PhaseConfig(phase_order=1, phase_level="Easy", phase_name="p1")
        problem = ProblemConfig(
            title="BG Problem",
            level="Easy",
            phases=[phase],
            background="# Context\nHere is the context.",
        )
        reg._problems[problem.title] = problem

        captured: dict[str, Any] = {}

        def mock_post(url: str, *, headers: Any, json: Any, timeout: Any) -> MagicMock:
            captured.update(json)
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"data": {"auto_merged": True}}
            return resp

        with (
            patch.object(reg, "_get_existing_checksum", return_value=""),
            patch("agent_genesis.registry.requests.post", side_effect=mock_post),
        ):
            reg._create_revision(problem, phase)

        meta = captured.get("problem_meta", {})
        assert meta["background"] == "# Context\nHere is the context."

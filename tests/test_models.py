"""Unit tests for core evaluation data models."""

from __future__ import annotations

import pytest

from ..models import (
    CaseStatus,
    PhaseConfig,
    PhaseResult,
    PhaseStatus,
    ProblemConfig,
    RuntimeConfig,
    slugify,
)


def _phase(order: int = 1) -> PhaseConfig:
    return PhaseConfig(
        phase_order=order,
        phase_level="Easy",
        phase_name=f"phase-{order}",
    )


def test_slugify_handles_basic_and_fallback() -> None:
    assert slugify("Maze Exploration") == "maze-exploration"
    assert slugify("A__B   C") == "a-b-c"
    assert slugify("!!!") == "untitled"


def test_case_status_to_backend_mapping() -> None:
    assert CaseStatus.TLE.to_backend() == "failed"
    assert CaseStatus.MLE.to_backend() == "failed"
    assert CaseStatus.ERROR.to_backend() == "failed"
    assert CaseStatus.PASSED.to_backend() == "passed"


def test_runtime_config_normalizes_key_id() -> None:
    cfg = RuntimeConfig(key_id=12)
    assert cfg.key_ids == [12]


def test_problem_config_slug_and_get_phase() -> None:
    p = ProblemConfig(
        title="Maze Exploration",
        level="Easy",
        phases=[_phase(1), _phase(2)],
    )
    assert p.slug == "maze-exploration"
    assert p.get_phase(2) is not None
    assert p.get_phase(3) is None


def test_problem_config_title_and_level_validation() -> None:
    with pytest.raises(ValueError):
        ProblemConfig(title="é", level="Easy", phases=[_phase(1)])
    with pytest.raises(ValueError):
        ProblemConfig(title="Mazeé", level="Easy", phases=[_phase(1)])
    with pytest.raises(ValueError):
        ProblemConfig(title="---", level="Easy", phases=[_phase(1)])
    with pytest.raises(ValueError):
        ProblemConfig(title="ValidTitle", level="Impossible", phases=[_phase(1)])


def test_phase_config_private_files_default_none() -> None:
    cfg = PhaseConfig(phase_order=1, phase_level="Easy", phase_name="p1")
    assert cfg.private_files is None


def test_phase_config_private_files_accepts_list() -> None:
    pf = ["sandbox/run.py", "sandbox/judge.py"]
    cfg = PhaseConfig(phase_order=1, phase_level="Easy", phase_name="p1", private_files=pf)
    assert cfg.private_files == pf


def test_phase_config_private_files_empty_list_means_all_public() -> None:
    cfg = PhaseConfig(phase_order=1, phase_level="Easy", phase_name="p1", private_files=[])
    assert cfg.private_files == []


def test_phase_config_model_dump_includes_private_files() -> None:
    pf = ["f.py"]
    cfg = PhaseConfig(phase_order=1, phase_level="Easy", phase_name="p1", private_files=pf)
    data = cfg.model_dump()
    assert "private_files" in data
    assert data["private_files"] == pf


def test_problem_config_open_source_defaults() -> None:
    p = ProblemConfig(title="Test", level="Easy", phases=[_phase(1)])
    assert p.is_public is False
    assert p.data_public is False
    assert p.background == ""


def test_problem_config_open_source_set() -> None:
    p = ProblemConfig(
        title="Open Problem",
        level="Medium",
        phases=[_phase(1)],
        is_public=True,
        data_public=True,
        background="# Background\nSome knowledge.",
    )
    assert p.is_public is True
    assert p.data_public is True
    assert "Background" in p.background


def test_problem_config_open_source_roundtrip() -> None:
    p = ProblemConfig(
        title="Roundtrip",
        level="Hard",
        phases=[_phase(1)],
        is_public=True,
        data_public=False,
        background="bg",
    )
    data = p.model_dump()
    assert data["is_public"] is True
    assert data["data_public"] is False
    assert data["background"] == "bg"
    restored = ProblemConfig(**data)
    assert restored.is_public is True
    assert restored.data_public is False


def test_phase_result_properties() -> None:
    r = PhaseResult(status=PhaseStatus.SUCCESS, total_cases=5, passed_cases=4)
    assert r.is_completed() is True
    assert r.is_all_passed() is True
    assert r.pass_rate == 0.8

    r2 = PhaseResult(status=PhaseStatus.RUNNING, total_cases=0, passed_cases=0)
    assert r2.is_completed() is False
    assert r2.is_all_passed() is False
    assert r2.pass_rate == 0.0

from __future__ import annotations

from pathlib import Path

import pytest

from ..local.problem_loader import LocalProblemLoader


def _write_config(path: Path, body: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "config.py").write_text(body, encoding="utf-8")


def test_load_raises_when_problem_path_missing(tmp_path: Path) -> None:
    loader = LocalProblemLoader()
    with pytest.raises(FileNotFoundError):
        loader.load(tmp_path / "missing_problem")


def test_load_raises_when_config_missing(tmp_path: Path) -> None:
    loader = LocalProblemLoader()
    problem_path = tmp_path / "problem_without_config"
    problem_path.mkdir()
    with pytest.raises(FileNotFoundError):
        loader.load(problem_path)


def test_load_prefers_class_name_ending_with_config(tmp_path: Path) -> None:
    loader = LocalProblemLoader()
    problem_path = tmp_path / "problem_prefer_config_suffix"
    _write_config(
        problem_path,
        "\n".join(
            [
                "from agent_genesis.models import PhaseConfig",
                "",
                "class AlphaPhase(PhaseConfig):",
                "    phase_name: str = 'alpha'",
                "",
                "class PreferredConfig(PhaseConfig):",
                "    phase_name: str = 'preferred'",
            ]
        ),
    )

    cfg = loader.load(problem_path)
    assert cfg.phase_name == "preferred"


def test_load_returns_first_subclass_when_no_config_suffix(tmp_path: Path) -> None:
    loader = LocalProblemLoader()
    problem_path = tmp_path / "problem_no_config_suffix"
    _write_config(
        problem_path,
        "\n".join(
            [
                "from agent_genesis.models import PhaseConfig",
                "",
                "class APhase(PhaseConfig):",
                "    phase_name: str = 'a'",
                "",
                "class ZPhase(PhaseConfig):",
                "    phase_name: str = 'z'",
            ]
        ),
    )

    cfg = loader.load(problem_path)
    assert cfg.phase_name == "a"


def test_load_raises_when_no_phase_config_subclass(tmp_path: Path) -> None:
    loader = LocalProblemLoader()
    problem_path = tmp_path / "problem_invalid_config"
    _write_config(
        problem_path,
        "\n".join(
            [
                "class NotAPhase:",
                "    pass",
            ]
        ),
    )
    with pytest.raises(ValueError):
        loader.load(problem_path)

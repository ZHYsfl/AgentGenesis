"""Local Problem Loader

Loads problem configurations from local problems/ directory without cloud registration.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from ..models import PhaseConfig


class LocalProblemLoader:
    """Local Problem Loader

    Loads from local problems/<problem_name>/ directory:
    1. config.py - PhaseConfig subclass definition
    2. sandbox/ - Evaluation code (judge runtime)
    """

    def load(self, problem_path: str | Path) -> PhaseConfig:
        """Load problem configuration

        Args:
            problem_path: Path to the problem directory, e.g., "problems/interrupt_judge"

        Returns:
            PhaseConfig instance

        Raises:
            FileNotFoundError: If config.py is not found
            ValueError: If no valid PhaseConfig subclass in config.py
        """
        problem_path = Path(problem_path).resolve()

        if not problem_path.exists():
            raise FileNotFoundError(f"Problem path not found: {problem_path}")

        config_path = problem_path / "config.py"
        if not config_path.exists():
            raise FileNotFoundError(f"config.py not found in {problem_path}")

        # Dynamically import config.py
        config_module = self._load_module_from_path("problem_config", config_path)

        # Find PhaseConfig subclass
        phase_config = self._find_phase_config(config_module)

        if phase_config is None:
            raise ValueError(
                f"No PhaseConfig subclass found in {config_path}. "
                "Please define a class that inherits from PhaseConfig."
            )

        return phase_config

    def _load_module_from_path(self, module_name: str, path: Path) -> Any:
        """Load Python module from file path"""
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load module from {path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module

    def _find_phase_config(self, module: Any) -> PhaseConfig | None:
        """Find PhaseConfig subclass in module

        Search order:
        1. Class ending with *Config (e.g., InterruptJudgeConfig)
        2. Any class inheriting from PhaseConfig
        """
        from ..models import PhaseConfig

        candidates = []

        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, PhaseConfig)
                and attr is not PhaseConfig
            ):
                candidates.append(attr)

        if not candidates:
            return None

        # Prefer class names ending with Config
        for candidate in candidates:
            if candidate.__name__.endswith("Config"):
                return candidate()

        # Otherwise return the first one found
        return candidates[0]()
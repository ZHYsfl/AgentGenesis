"""Local Artifact Builder

Builds artifacts from local problems/<problem>/sandbox/ directory,
serving as a local alternative to downloading artifacts from the cloud.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..models import PhaseConfig


class LocalArtifactBuilder:
    """Local Artifact Builder

    Packages the problems/<problem>/sandbox/ directory into an artifact_files dict
    for use with DualSandboxEvaluator.
    """

    # Default entrypoint path
    DEFAULT_ENTRYPOINT = "sandbox/run.py"

    def build(self, problem_path: str | Path, config: PhaseConfig | None = None) -> dict[str, bytes]:
        """Build artifact

        Args:
            problem_path: Path to the problem directory, e.g., "problems/interrupt_judge"
            config: Optional PhaseConfig for obtaining artifact_entry

        Returns:
            Dict mapping filenames to contents, e.g., {"sandbox/run.py": b"...", ...}

        Raises:
            FileNotFoundError: If sandbox directory does not exist
        """
        problem_path = Path(problem_path).resolve()
        sandbox_path = problem_path / "sandbox"

        if not sandbox_path.exists():
            raise FileNotFoundError(f"Sandbox directory not found: {sandbox_path}")

        artifact_files: dict[str, bytes] = {}

        # Recursively read all files in sandbox directory
        for root, _, files in os.walk(sandbox_path):
            for filename in files:
                file_path = Path(root) / filename

                # Skip __pycache__ and .pyc files
                if "__pycache__" in str(file_path) or file_path.suffix == ".pyc":
                    continue

                # Compute relative path (relative to sandbox directory)
                rel_path = file_path.relative_to(sandbox_path)
                artifact_key = f"sandbox/{rel_path}"

                try:
                    with open(file_path, "rb") as f:
                        artifact_files[artifact_key] = f.read()
                except Exception as e:
                    raise IOError(f"Failed to read {file_path}: {e}")

        # Check if entrypoint exists
        entrypoint = self._resolve_entrypoint(config)
        if entrypoint not in artifact_files:
            raise FileNotFoundError(
                f"Entrypoint not found: {entrypoint}. "
                f"Available files: {list(artifact_files.keys())[:10]}..."
            )

        return artifact_files

    def _resolve_entrypoint(self, config: PhaseConfig | None = None) -> str:
        """Resolve entrypoint path

        Priority:
        1. config.artifact_entry (if specified)
        2. DEFAULT_ENTRYPOINT
        """
        if config is not None:
            entry = getattr(config, "artifact_entry", None)
            if entry:
                return entry

        return self.DEFAULT_ENTRYPOINT

    def get_user_adapter(self, artifact_files: dict[str, bytes]) -> bytes | None:
        """Get user_adapter.py content

        Args:
            artifact_files: Artifact files dict

        Returns:
            Content of user_adapter.py, or None if not found
        """
        # Try multiple possible paths
        possible_paths = [
            "sandbox/user_adapter.py",
            "user_adapter.py",
        ]

        for path in possible_paths:
            if path in artifact_files:
                return artifact_files[path]

        return None
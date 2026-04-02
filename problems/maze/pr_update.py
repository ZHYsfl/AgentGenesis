#!/usr/bin/env python3
# problems/maze/pr_update.py
"""
Create an Internal Revision for the Maze problem (PR update flow).

Use when:
- The problem is already published and cannot be directly overwritten via register.
- Updates must go through /internal/problems/s/:slug/revisions.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent.parent

from agent_genesis import (  # noqa: E402
    ClientMode,
    DualSandboxEvaluator,
    build_artifact_from_dir,
    create_problem_revision,
    create_phase,
    create_problem,
    init_registry,
    register_problem,
)
from config import MAZE_BACKGROUND, MazeConfig, PHASE1_DESCRIPTION, PHASE1_STARTER_CODE  # noqa: E402


def main() -> None:
    load_dotenv(ROOT / ".env", override=True)
    load_dotenv(override=True)

    internal_key = "ag_5d4431257f2f896cc61dc1c7f745b36e"
    backend_url = "http://82.157.250.20"
    if not internal_key or not backend_url:
        raise RuntimeError("Missing INTERNAL_API_KEY or BACKEND_URL")

    problem_dir = Path(__file__).parent
    artifact_b64 = build_artifact_from_dir(problem_dir / "sandbox", problem_dir)

    phase = create_phase(
        DualSandboxEvaluator,
        MazeConfig(
            phase_name="Basic Maze",
            phase_type="agent",
            phase_order=1,
            phase_level="Easy",
            description=PHASE1_DESCRIPTION,
            starter_code=PHASE1_STARTER_CODE,
            artifact_base64=artifact_b64,
            artifact_entry="sandbox/run.py",
            allow_user_key=True,
        ),
    )
    problem = create_problem(
        title="Maze Exploration",
        phases=[phase],
        overview="Use an LLM Agent to navigate through random mazes and find the exit.",
        background=MAZE_BACKGROUND,
        language="en",
        is_public=True,
        data_public=True,
    )

    init_registry(mode=ClientMode.USER, api_key=internal_key, backend_url=backend_url)
    register_problem(problem)
    ok = create_problem_revision(
        title=problem.title,
        phase_order=phase.phase_order,
        revision_title=os.getenv("REVISION_TITLE", "Maze content refresh"),
        revision_description=os.getenv("REVISION_DESC", "Refresh maze phase description/starter code/artifact"),
    )
    if not ok:
        print("FAIL: Internal Revision creation failed (see logs)")
        raise SystemExit(1)

    print("OK: Internal Revision submitted (system problems will attempt auto-merge)")


if __name__ == "__main__":
    main()

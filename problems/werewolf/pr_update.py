#!/usr/bin/env python3
# problems/werewolf/pr_update.py
"""
Create an Internal Revision for the Werewolf problem (English content).

Use this when the problem is already published and updates must go through
the revision workflow.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent.parent

from agent_genesis import (  # noqa: E402
    ClientMode,
    IsolatedMultiAgentEvaluator,
    build_artifact_from_dirs,
    create_phase,
    create_problem,
    create_problem_revision,
    init_registry,
    register_problem,
)
from config import (  # noqa: E402
    WerewolfConfig,
    WEREWOLF_OVERVIEW_EN,
    WEREWOLF_BACKGROUND_EN,
    PHASE1_DESCRIPTION_EN,
    PHASE1_STARTER_CODE_EN,
)


def main() -> None:
    load_dotenv(ROOT / ".env", override=True)
    load_dotenv(override=True)

    api_key = "ag_4c7115402944dba84fc76b368e3ff84e"
    backend_url ="http://82.157.250.20"
    if not api_key or not backend_url:
        raise RuntimeError("Missing INTERNAL_API_KEY or BACKEND_URL")

    problem_dir = Path(__file__).parent
    artifact_b64 = build_artifact_from_dirs(
        [problem_dir / "sandbox", problem_dir / "wolf_agent"],
        problem_dir,
    )

    phase = create_phase(
        IsolatedMultiAgentEvaluator,
        WerewolfConfig(
            phase_name="Werewolf Multi-Agent",
            phase_type="agent",
            phase_order=1,
            phase_level="Hard",
            description=PHASE1_DESCRIPTION_EN,
            starter_code=PHASE1_STARTER_CODE_EN,
            artifact_base64=artifact_b64,
            artifact_entry="sandbox/run.py",
            allow_user_key=True,
            language="en",
        ),
    )
    problem = create_problem(
        title="Werewolf Game",
        phases=[phase],
        overview=WEREWOLF_OVERVIEW_EN,
        background=WEREWOLF_BACKGROUND_EN,
        language="en",
        is_public=True,
        data_public=True,
    )

    init_registry(mode=ClientMode.USER, api_key=api_key, backend_url=backend_url)
    register_problem(problem)
    ok = create_problem_revision(
        title=problem.title,
        phase_order=phase.phase_order,
        revision_title=os.getenv("REVISION_TITLE", "Werewolf English content refresh"),
        revision_description=os.getenv(
            "REVISION_DESC",
            "Refresh werewolf English overview/background/phase description/starter code/artifact",
        ),
    )
    if not ok:
        print("FAIL: Internal Revision creation failed (see logs)")
        raise SystemExit(1)

    print("OK: Internal Revision submitted for English content")


if __name__ == "__main__":
    main()

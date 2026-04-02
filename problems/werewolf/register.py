#!/usr/bin/env python3
"""Register the Werewolf problem (English content)."""

import os
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent

from agent_genesis import (
    create_problem,
    create_phase,
    init_registry,
    register_problem,
    sync_problem,
    build_artifact_from_dirs,
    ClientMode,
    IsolatedMultiAgentEvaluator,
)
from config import (
    WerewolfConfig,
    WEREWOLF_OVERVIEW_EN,
    WEREWOLF_BACKGROUND_EN,
    PHASE1_DESCRIPTION_EN,
    PHASE1_STARTER_CODE_EN,
)
from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)


def main():
    load_dotenv(override=True)
    api_key = "ag_4c7115402944dba84fc76b368e3ff84e"
    base_url = "http://82.157.250.20"
    if not api_key or not base_url:
        raise RuntimeError("Missing INTERNAL_API_KEY or BACKEND_URL")

    init_registry(mode=ClientMode.USER, api_key=api_key, backend_url=base_url)

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
            language="en",
            phase_level="Hard",
            description=PHASE1_DESCRIPTION_EN,
            starter_code=PHASE1_STARTER_CODE_EN,
            artifact_base64=artifact_b64,
            artifact_entry="sandbox/run.py",
            allow_user_key=True,
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

    register_problem(problem)

    try:
        results = sync_problem(problem.title)
        if results and all(results.values()):
            print("OK: werewolf problem synced")
        else:
            print(f"FAIL: sync result: {results}")
    except Exception as e:
        print(f"FAIL: sync error: {e}")


if __name__ == "__main__":
    main()

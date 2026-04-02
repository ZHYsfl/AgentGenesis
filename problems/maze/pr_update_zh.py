#!/usr/bin/env python3
# problems/maze/pr_update_zh.py
"""
Create an Internal Revision for Chinese (zh-CN) content of Maze problem.

Use this script when you want frontend language toggle to display Chinese
problem overview/background/phase description/starter code.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent.parent

from agent_genesis import (  # noqa: E402
    ClientMode,
    DualSandboxEvaluator,
    PhaseConfig,
    create_phase,
    create_problem,
    create_problem_revision,
    init_registry,
    register_problem,
)
from config import (  # noqa: E402
    MAZE_BACKGROUND_ZH,
    MAZE_OVERVIEW_ZH,
    PHASE1_DESCRIPTION_ZH,
    PHASE1_STARTER_CODE_ZH,
)


def main() -> None:
    load_dotenv(ROOT / ".env", override=True)
    load_dotenv(override=True)

    internal_key = "ag_4c7115402944dba84fc76b368e3ff84e"
    backend_url = "http://82.157.250.20"
    if not internal_key or not backend_url:
        raise RuntimeError("Missing INTERNAL_API_KEY or BACKEND_URL")

    phase = create_phase(
        DualSandboxEvaluator,
        PhaseConfig(
            phase_name="基础迷宫",
            phase_order=1,
            description=PHASE1_DESCRIPTION_ZH,
            starter_code=PHASE1_STARTER_CODE_ZH,
            language="zh-CN",
        ),
    )
    problem = create_problem(
        title="Maze Exploration",
        phases=[phase],
        overview=MAZE_OVERVIEW_ZH,
        background=MAZE_BACKGROUND_ZH,
        language="zh-CN",
    )

    init_registry(mode=ClientMode.USER, api_key=internal_key, backend_url=backend_url)
    register_problem(problem)
    ok = create_problem_revision(
        title=problem.title,
        phase_order=phase.phase_order,
        revision_title=os.getenv("REVISION_TITLE", "Maze 中文内容更新"),
        revision_description=os.getenv(
            "REVISION_DESC",
            "新增 zh-CN 题面内容（overview/background/description/starter code）",
        ),
    )
    if not ok:
        print("FAIL: Internal Revision creation failed (see logs)")
        raise SystemExit(1)

    print("OK: Internal Revision submitted for zh-CN content")


if __name__ == "__main__":
    main()


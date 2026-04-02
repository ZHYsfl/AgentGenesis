#!/usr/bin/env python3
# problems/werewolf/pr_update_zh.py
"""
Create an Internal Revision for Chinese (zh-CN) content of Werewolf problem.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent.parent

from agent_genesis import (  # noqa: E402
    ClientMode,
    IsolatedMultiAgentEvaluator,
    PhaseConfig,
    create_phase,
    create_problem,
    create_problem_revision,
    init_registry,
    register_problem,
)
from config import (  # noqa: E402
    WEREWOLF_OVERVIEW_ZH,
    WEREWOLF_BACKGROUND_ZH,
    PHASE1_DESCRIPTION_ZH,
    PHASE1_STARTER_CODE_ZH,
)


def main() -> None:
    load_dotenv(ROOT / ".env", override=True)
    load_dotenv(override=True)

    api_key = "ag_4c7115402944dba84fc76b368e3ff84e"
    backend_url ="http://82.157.250.20"
    if not api_key or not backend_url:
        raise RuntimeError("Missing INTERNAL_API_KEY or BACKEND_URL")

    phase = create_phase(
        IsolatedMultiAgentEvaluator,
        PhaseConfig(
            phase_name="狼人杀多智能体",
            phase_order=1,
            description=PHASE1_DESCRIPTION_ZH,
            starter_code=PHASE1_STARTER_CODE_ZH,
            language="zh-CN",
        ),
    )
    problem = create_problem(
        title="Werewolf Game",
        phases=[phase],
        overview=WEREWOLF_OVERVIEW_ZH,
        background=WEREWOLF_BACKGROUND_ZH,
        language="zh-CN",
    )

    init_registry(mode=ClientMode.USER, api_key=api_key, backend_url=backend_url)
    register_problem(problem)
    ok = create_problem_revision(
        title=problem.title,
        phase_order=phase.phase_order,
        revision_title=os.getenv("REVISION_TITLE", "Werewolf 中文内容更新"),
        revision_description=os.getenv(
            "REVISION_DESC",
            "更新 werewolf 的 zh-CN overview/background/description/starter code",
        ),
    )
    if not ok:
        print("FAIL: Internal Revision creation failed (see logs)")
        raise SystemExit(1)

    print("OK: Internal Revision submitted for zh-CN content")


if __name__ == "__main__":
    main()

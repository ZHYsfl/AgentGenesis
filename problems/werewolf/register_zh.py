#!/usr/bin/env python3
"""Register the Werewolf problem (Chinese zh-CN content)."""

import os
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent

from agent_genesis import (
    create_problem,
    create_phase,
    init_registry,
    register_problem,
    sync_problem,
    ClientMode,
    IsolatedMultiAgentEvaluator,
    PhaseConfig,
)
from config import (
    WEREWOLF_OVERVIEW_ZH,
    WEREWOLF_BACKGROUND_ZH,
    PHASE1_DESCRIPTION_ZH,
    PHASE1_STARTER_CODE_ZH,
)
from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)


def main() -> None:
    load_dotenv(override=True)
    api_key = "ag_4c7115402944dba84fc76b368e3ff84e"
    base_url = "http://82.157.250.20"
    if not api_key or not base_url:
        raise RuntimeError("Missing INTERNAL_API_KEY or BACKEND_URL")

    init_registry(mode=ClientMode.USER, api_key=api_key, backend_url=base_url)

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

    register_problem(problem)

    try:
        results = sync_problem(problem.title)
        if results and all(results.values()):
            print("OK: werewolf zh-CN problem synced")
        else:
            print(f"FAIL: sync result: {results}")
    except Exception as e:
        print(f"FAIL: sync error: {e}")


if __name__ == "__main__":
    main()

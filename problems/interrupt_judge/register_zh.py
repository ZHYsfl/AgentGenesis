#!/usr/bin/env python3
# problems/interrupt_judge/register_zh.py
"""
Register the interrupt_judge problem (Chinese version).
"""
import os
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent

from agent_genesis import (
    create_problem,
    create_phase,
    init_registry,
    register_problem,
    sync_problem,
    build_artifact_from_dir,
    ClientMode,
    DualSandboxEvaluator,
)
from config import (
    INTERRUPT_JUDGE_BACKGROUND_ZH,
    INTERRUPT_JUDGE_OVERVIEW_ZH,
    InterruptJudgeConfig,
    PHASE1_DESCRIPTION_ZH,
    PHASE1_STARTER_CODE_ZH,
)
from dotenv import load_dotenv

# Load .env from project root
load_dotenv(ROOT / ".env", override=True)


def main():
    load_dotenv(override=True)
    api_key = "ag_4c7115402944dba84fc76b368e3ff84e"
    base_url = "http://82.157.250.20"
    if not api_key or not base_url:
        raise RuntimeError("Missing INTERNAL_API_KEY or BACKEND_URL")

    # Internal mode: system problems use /internal/register-problem
    init_registry(mode=ClientMode.USER, api_key=api_key, backend_url=base_url)

    problem_dir = Path(__file__).parent
    artifact_b64 = build_artifact_from_dir(problem_dir / "sandbox", problem_dir)
    phase = create_phase(
        DualSandboxEvaluator,
        InterruptJudgeConfig(
            phase_name="打断判断",
            phase_type="agent",
            phase_order=1,
            language="zh-CN",
            phase_level="Easy",
            description=PHASE1_DESCRIPTION_ZH,
            starter_code=PHASE1_STARTER_CODE_ZH,
            artifact_base64=artifact_b64,
            artifact_entry="sandbox/run.py",
            allow_user_key=True,
        ),
    )
    problem = create_problem(
        title="Interrupt Judgment (Chinese Version)",
        phases=[phase],
        overview=INTERRUPT_JUDGE_OVERVIEW_ZH,
        background=INTERRUPT_JUDGE_BACKGROUND_ZH,
        language="zh-CN",
        is_public=True,
        data_public=True,
    )

    register_problem(problem)

    try:
        results = sync_problem(problem.title)
        if results and all(results.values()):
            print("OK: all phases synced (internal mode)")
        elif results:
            failed = [k for k, v in results.items() if not v]
            print(f"FAIL: phases {failed} submission failed")
        else:
            print("FAIL: problem not found or submission failed")
    except Exception as e:
        print(f"FAIL: submission error: {e}")


if __name__ == "__main__":
    main()

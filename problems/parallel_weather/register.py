#!/usr/bin/env python3
"""Register the Parallel Weather Query problem."""

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
    ParallelWeatherConfig,
    OVERVIEW_EN,
    OVERVIEW_ZH,
    BACKGROUND_EN,
    BACKGROUND_ZH,
    PHASE1_DESCRIPTION_EN,
    PHASE1_DESCRIPTION_ZH,
    PHASE1_STARTER_CODE_EN,
    PHASE1_STARTER_CODE_ZH,
)
from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)

LANGUAGES = [
    {
        "lang": "en",
        "overview": OVERVIEW_EN,
        "background": BACKGROUND_EN,
        "description": PHASE1_DESCRIPTION_EN,
        "starter_code": PHASE1_STARTER_CODE_EN,
    },
    {
        "lang": "zh-CN",
        "overview": OVERVIEW_ZH,
        "background": BACKGROUND_ZH,
        "description": PHASE1_DESCRIPTION_ZH,
        "starter_code": PHASE1_STARTER_CODE_ZH,
    },
]


def main():
    load_dotenv(override=True)
    api_key = "ag_4c7115402944dba84fc76b368e3ff84e"
    base_url = "http://82.157.250.20"
    if not api_key or not base_url:
        raise RuntimeError("Missing API_KEY or BACKEND_URL")

    init_registry(mode=ClientMode.USER, api_key=api_key, backend_url=base_url)

    artifact_b64 = build_artifact_from_dir(
        Path(__file__).parent / "sandbox",
        Path(__file__).parent,
    )

    for loc in LANGUAGES:
        phase = create_phase(
            DualSandboxEvaluator,
            ParallelWeatherConfig(
                phase_name="Parallel Weather Query",
                phase_type="agent",
                phase_order=1,
                phase_level="Hard",
                language=loc["lang"],
                description=loc["description"],
                starter_code=loc["starter_code"],
                artifact_base64=artifact_b64,
                artifact_entry="sandbox/run.py",
                allow_user_key=True,
            ),
        )

        problem = create_problem(
            title="Parallel Weather Query",
            phases=[phase],
            overview=loc["overview"],
            background=loc["background"],
            language=loc["lang"],
            is_public=True,
            data_public=True,
        )

        register_problem(problem)

        try:
            results = sync_problem(problem.title)
            ok = results and all(results.values())
            print(f"{'OK' if ok else 'FAIL'}: parallel weather query ({loc['lang']}) synced")
        except Exception as e:
            print(f"FAIL: {loc['lang']} sync error: {e}")


if __name__ == "__main__":
    main()

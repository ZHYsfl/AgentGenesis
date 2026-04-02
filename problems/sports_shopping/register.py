#!/usr/bin/env python3
"""Register the Sports Shopping Agent problem (English)."""

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
    SportsShoppingConfig,
    OVERVIEW_EN,
    BACKGROUND_EN,
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
        raise RuntimeError("Missing API_KEY or BACKEND_URL")

    init_registry(mode=ClientMode.USER, api_key=api_key, backend_url=base_url)

    artifact_b64 = build_artifact_from_dir(
        Path(__file__).parent / "sandbox",
        Path(__file__).parent,
    )

    phase = create_phase(
        DualSandboxEvaluator,
        SportsShoppingConfig(
            phase_name="Sports Shopping Agent",
            phase_type="agent",
            phase_order=1,
            phase_level="Easy",
            language="en",
            description=PHASE1_DESCRIPTION_EN,
            starter_code=PHASE1_STARTER_CODE_EN,
            artifact_base64=artifact_b64,
            artifact_entry="sandbox/run.py",
            allow_user_key=True,
        ),
    )

    problem = create_problem(
        title="Sports Shopping Agent",
        phases=[phase],
        overview=OVERVIEW_EN,
        background=BACKGROUND_EN,
        language="en",
        is_public=True,
        data_public=True,
    )

    register_problem(problem)

    try:
        results = sync_problem(problem.title)
        ok = results and all(results.values())
        print(f"{'OK' if ok else 'FAIL'}: sports shopping agent (en) synced")
    except Exception as e:
        print(f"FAIL: en sync error: {e}")


if __name__ == "__main__":
    main()

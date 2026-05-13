from __future__ import annotations

import os
from pathlib import Path

from agent_genesis import (
    ClientMode,
    DualSandboxEvaluator,
    build_artifact_from_dir,
    create_phase,
    create_problem,
    init_registry,
    register_problem,
    sync_problem,
)
from config import (
    KEYED_LABYRINTH_BACKGROUND,
    KEYED_LABYRINTH_OVERVIEW_EN,
    KeyedLabyrinthConfig,
    PHASE1_DESCRIPTION,
    STARTER_CODE,
)


PROBLEM_TITLE = "Keyed Labyrinth"


def main() -> None:
    api_key = os.environ.get("AGENT_GENESIS_API_KEY")
    backend_url = os.environ.get("AGENT_GENESIS_BACKEND_URL")
    if not api_key or not backend_url:
        raise RuntimeError("Set AGENT_GENESIS_API_KEY and AGENT_GENESIS_BACKEND_URL before registering")

    init_registry(
        mode=ClientMode.USER,
        api_key=api_key,
        backend_url=backend_url,
    )

    problem_dir = Path(__file__).parent
    artifact_b64 = build_artifact_from_dir(problem_dir / "sandbox", problem_dir)

    phase = create_phase(
        DualSandboxEvaluator,
        KeyedLabyrinthConfig(
            phase_name="Keyed Labyrinth",
            phase_level="Medium",
            description=PHASE1_DESCRIPTION,
            starter_code=STARTER_CODE,
            artifact_base64=artifact_b64,
        ),
    )
    problem = create_problem(
        title=PROBLEM_TITLE,
        overview=KEYED_LABYRINTH_OVERVIEW_EN,
        background=KEYED_LABYRINTH_BACKGROUND,
        level="Medium",
        language="en",
        is_public=True,
        data_public=False,
        phases=[phase],
    )
    register_problem(problem)
    print(sync_problem(problem.title))


if __name__ == "__main__":
    main()

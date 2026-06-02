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
    BACKGROUND_EN,
    BACKGROUND_ZH,
    MLHyperparamTunerConfig,
    OVERVIEW_EN,
    OVERVIEW_ZH,
    PHASE1_DESCRIPTION_EN,
    PHASE1_DESCRIPTION_ZH,
    PHASE1_STARTER_CODE_EN,
    PHASE1_STARTER_CODE_ZH,
)


def main():
    init_registry(
        mode=ClientMode.USER,
        api_key="dummy",
        backend_url="https://dummy",
    )

    problem_dir = Path(__file__).parent
    artifact_b64 = build_artifact_from_dir(problem_dir / "sandbox", problem_dir)

    phase = create_phase(
        DualSandboxEvaluator,
        MLHyperparamTunerConfig(
            description=PHASE1_DESCRIPTION_EN,
            starter_code=PHASE1_STARTER_CODE_EN,
            artifact_base64=artifact_b64,
        ),
    )
    problem = create_problem(
        title="ML Hyperparameter Tuner",
        overview=OVERVIEW_EN,
        background=BACKGROUND_EN,
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

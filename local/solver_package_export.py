from __future__ import annotations

import argparse
import contextlib
import json
import runpy
import sys
from pathlib import Path
from typing import Any


def _install_paths(problem_dir: Path) -> None:
    path = str(problem_dir)
    if path not in sys.path:
        sys.path.insert(0, path)


def _capture_problem(problem_dir: Path) -> Any:
    _install_paths(problem_dir)

    import agent_genesis
    import agent_genesis.api as agent_genesis_api

    captured: list[Any] = []
    names = (
        "init_registry",
        "register_problem",
        "sync_problem",
        "sync_all_problems",
    )
    originals = {
        module: {name: getattr(module, name) for name in names}
        for module in (agent_genesis, agent_genesis_api)
    }

    def init_registry(*args: Any, **kwargs: Any) -> None:
        return None

    def register_problem(problem: Any) -> None:
        captured.append(problem)

    def sync_problem(title: str) -> dict[int, bool]:
        return {1: True}

    def sync_all_problems() -> dict[str, dict[int, bool]]:
        return {}

    replacements = {
        "init_registry": init_registry,
        "register_problem": register_problem,
        "sync_problem": sync_problem,
        "sync_all_problems": sync_all_problems,
    }
    for module in (agent_genesis, agent_genesis_api):
        for name, value in replacements.items():
            setattr(module, name, value)

    try:
        namespace = runpy.run_path(str(problem_dir / "register.py"), run_name="__solverpkg__")
        main = namespace.get("main")
        if callable(main):
            with contextlib.redirect_stdout(sys.stderr):
                main()
    finally:
        for module, values in originals.items():
            for name, value in values.items():
                setattr(module, name, value)

    if len(captured) != 1:
        raise RuntimeError(f"expected register.py to register exactly one problem, got {len(captured)}")
    return captured[0]


def export_problem(problem_dir: Path, phase_order: int) -> dict[str, Any]:
    _install_paths(problem_dir)

    from agent_genesis.registry import prepare_phase_data_for_registration

    problem = _capture_problem(problem_dir)
    phase = problem.get_phase(phase_order)
    if phase is None:
        raise RuntimeError(f"phase order {phase_order} not found")

    phase_data = prepare_phase_data_for_registration(problem, phase)
    problem_data = problem.model_dump()
    problem_data.pop("phases", None)
    return {
        "problem": problem_data,
        "phase": phase_data,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Export local AgentGenesis problem data for solver package generation")
    parser.add_argument("--problem-dir", required=True)
    parser.add_argument("--phase", type=int, default=1)
    args = parser.parse_args()

    problem_dir = Path(args.problem_dir).resolve()
    if not problem_dir.is_dir():
        raise SystemExit(f"problem dir does not exist: {problem_dir}")
    if not (problem_dir / "register.py").is_file():
        raise SystemExit(f"register.py not found in problem dir: {problem_dir}")
    if args.phase < 1:
        raise SystemExit("phase must be >= 1")

    exported = export_problem(problem_dir, args.phase)
    json.dump(exported, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()

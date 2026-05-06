"""Keyed Labyrinth problem configuration."""

from typing import Optional

from agent_genesis import PhaseConfig


class KeyedLabyrinthConfig(PhaseConfig):
    language: str = "en"
    seed: Optional[int] = None
    maze_width: int = 9
    maze_height: int = 9
    wall_density: float = 0.12
    max_moves: int = 300
    num_locks: int = 2

    num_cases: int = 3
    min_passed_cases: Optional[int] = None
    parallel_cases: int = 3
    time_limit: float = 300.0
    sandbox_timeout: int = 420
    case_idle_timeout: int = 60

    pip_dependencies: list[str] = ["openai", "pydantic"]

    solve_attr_name: str = "solve"
    adapter_preset: str = "keyed_labyrinth"
    artifact_entry: str = "sandbox/run.py"
    private_files: Optional[list[str]] = ["sandbox/generator.py", "sandbox/environment.py"]

    evaluator_module: str = "agent_genesis.dual_sandbox_evaluator"
    evaluator_class: str = "DualSandboxEvaluator"


KEYED_LABYRINTH_OVERVIEW_EN = "Navigate an unknown maze with keys and locked doors using only movement feedback."
KEYED_LABYRINTH_OVERVIEW_ZH = "仅通过移动反馈，在带钥匙和锁门的未知迷宫中找到出口。"

KEYED_LABYRINTH_BACKGROUND = """
# Keyed Labyrinth Background

This problem tests whether an agent can explore an unknown environment while remembering state that changes over time.

The maze is hidden. Some passages are blocked by colored locked doors. Matching colored keys are hidden elsewhere in the maze and are collected automatically when reached. The agent must combine exploration, backtracking, inventory tracking, and robust interpretation of textual feedback.
""".strip()

PHASE1_DESCRIPTION = """
# Phase 1: Keyed Labyrinth

Implement an agent that finds the exit in an unknown maze containing walls, colored keys, and matching locked doors.

Each test case generates a fresh hidden labyrinth. You cannot read the full map, coordinates, key locations, door locations, or the generator. You can only interact through `move(direction)` and infer state from returned text.

## Interface

```python
def solve(move):
    result = move("right")
    ...
```

- `move(direction: str) -> str`
  - Executes one attempted step and blocks until the environment returns feedback.
  - `direction` must be one of `"up"`, `"down"`, `"left"`, `"right"`.
  - Returns natural-language feedback.
- `solve(move)`
  - Call `move(...)` repeatedly to explore.
  - Return immediately after feedback indicates that the exit has been reached.

## Labyrinth rules

- The outer boundary is always blocked.
- You never receive coordinates or the full grid.
- If you walk into a wall, your position does not change.
- If you try to enter a locked door without its matching key, your position does not change. The feedback tells you the door color.
- If you have the matching key, moving into that door opens it and your position changes.
- Keys are collected automatically when you enter their cell. The feedback tells you the key color.
- Door and key colors are ordinary color names in the feedback text.
- Feedback wording may vary, but it always preserves the semantic category: wall, movement, locked door, opened door, key collected, or exit reached.

## Scoring

- Reaching the exit is required to pass a case.
- Fewer moves receive a higher score.
- Successful but inefficient runs still receive at least 10 points for the case.
- Constraints per case:
  - Max `300` moves
  - Total time limit `300` seconds
  - Per-step idle timeout `60` seconds

## Important

The hidden generator and concrete labyrinth layouts are not part of the solver-visible contract. Solve by using the public interface and feedback, not by reading private files or memorizing cases.
""".strip()

STARTER_CODE = r'''
def solve(move):
    """Navigate the keyed labyrinth using move("up"/"down"/"left"/"right")."""
    # Example:
    # feedback = move("right")
    # Return immediately after the feedback says the exit was reached.
    pass
'''.strip()

from __future__ import annotations

from collections import deque
import random
from typing import Optional


DIRS = [(0, -1), (0, 1), (-1, 0), (1, 0)]
COLORS = ["红", "蓝", "绿", "黄"]


def generate_cases(
    num_cases: int,
    width: int = 9,
    height: int = 9,
    wall_density: float = 0.12,
    num_locks: int = 2,
    seed: Optional[int] = None,
) -> list[dict]:
    rng = random.Random(seed)
    return [
        _generate_case(
            case_index=i,
            width=width,
            height=height,
            wall_density=wall_density,
            num_locks=num_locks,
            rng=rng,
        )
        for i in range(num_cases)
    ]


def _generate_case(
    case_index: int,
    width: int,
    height: int,
    wall_density: float,
    num_locks: int,
    rng: random.Random,
) -> dict:
    width = max(7, width | 1)
    height = max(7, height | 1)
    num_locks = max(1, min(num_locks, len(COLORS), 3))

    for _ in range(200):
        grid = [["#" for _ in range(width)] for _ in range(height)]
        path = _carve_main_path(grid, rng)
        _carve_branches(grid, path, rng)
        _add_extra_walls(grid, path, wall_density, rng)

        start = path[0]
        goal = path[-1]
        keys, doors = _place_keys_and_doors(path, num_locks)
        optimal = _optimal_moves(grid, start, goal, keys, doors)
        if optimal is not None:
            return {
                "case_index": case_index,
                "grid": [row[:] for row in grid],
                "start": list(start),
                "goal": list(goal),
                "keys": {_pack(pos): color for pos, color in keys.items()},
                "doors": {_pack(pos): color for pos, color in doors.items()},
                "optimal_moves": optimal,
                "feedback_seed": rng.randint(0, 10_000_000),
            }

    return _fallback_case(case_index, width, height, num_locks, rng)


def _carve_main_path(grid: list[list[str]], rng: random.Random) -> list[tuple[int, int]]:
    width = len(grid[0])
    height = len(grid)
    x, y = 1, 1
    path = [(x, y)]
    grid[y][x] = "."

    while (x, y) != (width - 2, height - 2):
        choices: list[tuple[int, int]] = []
        if x < width - 2:
            choices.append((x + 1, y))
        if y < height - 2:
            choices.append((x, y + 1))
        x, y = rng.choice(choices)
        path.append((x, y))
        grid[y][x] = "."
    return path


def _carve_branches(grid: list[list[str]], path: list[tuple[int, int]], rng: random.Random) -> None:
    width = len(grid[0])
    height = len(grid)
    candidates = path[1:-1]
    rng.shuffle(candidates)
    for x, y in candidates[: max(8, len(path) // 2)]:
        length = rng.randint(1, 4)
        cx, cy = x, y
        for _ in range(length):
            dx, dy = rng.choice(DIRS)
            nx, ny = cx + dx, cy + dy
            if 1 <= nx < width - 1 and 1 <= ny < height - 1:
                grid[ny][nx] = "."
                cx, cy = nx, ny


def _add_extra_walls(
    grid: list[list[str]],
    protected_path: list[tuple[int, int]],
    wall_density: float,
    rng: random.Random,
) -> None:
    protected = set(protected_path)
    width = len(grid[0])
    height = len(grid)
    for y in range(1, height - 1):
        for x in range(1, width - 1):
            if (x, y) in protected:
                continue
            if grid[y][x] == "." and rng.random() < wall_density:
                grid[y][x] = "#"


def _place_keys_and_doors(path: list[tuple[int, int]], num_locks: int) -> tuple[dict[tuple[int, int], str], dict[tuple[int, int], str]]:
    usable = path[1:-1]
    segment = max(1, len(usable) // (num_locks * 2 + 1))
    keys: dict[tuple[int, int], str] = {}
    doors: dict[tuple[int, int], str] = {}
    for i in range(num_locks):
        key_idx = min(len(usable) - 1, (2 * i + 1) * segment)
        door_idx = min(len(usable) - 1, (2 * i + 2) * segment)
        if door_idx <= key_idx:
            door_idx = min(len(usable) - 1, key_idx + 1)
        color = COLORS[i]
        keys[usable[key_idx]] = color
        doors[usable[door_idx]] = color
    return keys, doors


def _optimal_moves(
    grid: list[list[str]],
    start: tuple[int, int],
    goal: tuple[int, int],
    keys: dict[tuple[int, int], str],
    doors: dict[tuple[int, int], str],
) -> Optional[int]:
    start_keys = frozenset([keys[start]]) if start in keys else frozenset()
    queue = deque([(start, start_keys, 0)])
    seen = {(start, start_keys)}
    while queue:
        pos, inv, dist = queue.popleft()
        if pos == goal:
            return dist
        x, y = pos
        for dx, dy in DIRS:
            nxt = (x + dx, y + dy)
            if _is_wall(grid, nxt):
                continue
            door_color = doors.get(nxt)
            if door_color is not None and door_color not in inv:
                continue
            next_inv = inv | ({keys[nxt]} if nxt in keys else set())
            state = (nxt, frozenset(next_inv))
            if state not in seen:
                seen.add(state)
                queue.append((nxt, frozenset(next_inv), dist + 1))
    return None


def _is_wall(grid: list[list[str]], pos: tuple[int, int]) -> bool:
    x, y = pos
    return y < 0 or y >= len(grid) or x < 0 or x >= len(grid[0]) or grid[y][x] == "#"


def _fallback_case(case_index: int, width: int, height: int, num_locks: int, rng: random.Random) -> dict:
    grid = [["#" for _ in range(width)] for _ in range(height)]
    path = [(x, 1) for x in range(1, width - 1)] + [(width - 2, y) for y in range(2, height - 1)]
    for x, y in path:
        grid[y][x] = "."
    keys, doors = _place_keys_and_doors(path, num_locks)
    optimal = _optimal_moves(grid, path[0], path[-1], keys, doors) or len(path) - 1
    return {
        "case_index": case_index,
        "grid": grid,
        "start": list(path[0]),
        "goal": list(path[-1]),
        "keys": {_pack(pos): color for pos, color in keys.items()},
        "doors": {_pack(pos): color for pos, color in doors.items()},
        "optimal_moves": optimal,
        "feedback_seed": rng.randint(0, 10_000_000),
    }


def _pack(pos: tuple[int, int]) -> str:
    return f"{pos[0]},{pos[1]}"

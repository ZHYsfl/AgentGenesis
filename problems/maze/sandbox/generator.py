# problems/maze/sandbox/generator.py
"""
Maze generator.

Pure algorithm module with no I/O or protocol dependencies.
Can be imported standalone for local testing or visualization.
"""

import random
from collections import deque
from typing import Optional


def generate_maze(
    rng: random.Random,
    width: int,
    height: int,
    wall_density: float = 0.15,
) -> list[list[int]]:
    """
    Generate a random maze using Prim's algorithm.

    Args:
        rng: random number generator (fix seed for reproducibility).
        width: maze width (columns).
        height: maze height (rows).
        wall_density: extra wall density (0-1, connectivity preserved).

    Returns:
        2D int matrix, 0=path 1=wall.
    """
    maze: list[list[int]] = [[1] * width for _ in range(height)]
    start_row = rng.randint(1, height - 2)
    start_col = rng.randint(1, width - 2)
    maze[start_row][start_col] = 0

    walls: list[tuple[int, int]] = []

    def add_walls(row: int, col: int) -> None:
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nr, nc = row + dr, col + dc
            if 1 <= nr < height - 1 and 1 <= nc < width - 1:
                if (nr, nc) not in walls:
                    walls.append((nr, nc))

    def can_carve(row: int, col: int) -> bool:
        if maze[row][col] == 0:
            return False
        count = 0
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nr, nc = row + dr, col + dc
            if 0 <= nr < height and 0 <= nc < width:
                if maze[nr][nc] == 0:
                    count += 1
        return count == 1

    add_walls(start_row, start_col)
    while walls:
        idx = rng.randint(0, len(walls) - 1)
        row, col = walls.pop(idx)
        if can_carve(row, col):
            maze[row][col] = 0
            add_walls(row, col)

    # Randomly add walls while preserving connectivity
    for r in range(height):
        for c in range(width):
            if maze[r][c] == 0 and rng.random() < wall_density:
                maze[r][c] = 1
                if not _is_connected(maze, height, width):
                    maze[r][c] = 0

    return maze


def pick_start_end(
    rng: random.Random,
    maze: list[list[int]],
) -> tuple[tuple[int, int], tuple[int, int]]:
    """
    Pick start and end points that are as far apart as possible.

    Returns:
        (start, end) as two (row, col) tuples.
    """
    height = len(maze)
    width = len(maze[0]) if height > 0 else 0
    empty = [(r, c) for r in range(height) for c in range(width) if maze[r][c] == 0]

    if len(empty) <= 2:
        raise RuntimeError("Maze generation error: insufficient open cells")

    max_dist = 0
    best = (empty[0], empty[-1])
    samples = min(50, len(empty) * (len(empty) - 1) // 2)
    for _ in range(samples):
        p1, p2 = rng.sample(empty, 2)
        dist = abs(p1[0] - p2[0]) + abs(p1[1] - p2[1])
        if dist > max_dist:
            max_dist = dist
            best = (p1, p2)

    return best


def find_shortest_path(
    maze: list[list[int]],
    start: tuple[int, int],
    end: tuple[int, int],
) -> Optional[list[tuple[int, int]]]:
    """BFS shortest path. Returns path list (including start and end), or None if unreachable."""
    height = len(maze)
    width = len(maze[0]) if height > 0 else 0

    if maze[start[0]][start[1]] == 1 or maze[end[0]][end[1]] == 1:
        return None

    queue = deque([(start, [start])])
    visited = {start}

    while queue:
        (row, col), path = queue.popleft()
        if (row, col) == end:
            return path
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nr, nc = row + dr, col + dc
            if 0 <= nr < height and 0 <= nc < width:
                if maze[nr][nc] == 0 and (nr, nc) not in visited:
                    visited.add((nr, nc))
                    queue.append(((nr, nc), path + [(nr, nc)]))

    return None


def generate_cases(
    num_cases: int,
    width: int = 5,
    height: int = 5,
    wall_density: float = 0.15,
    seed: Optional[int] = None,
) -> list[dict]:
    """
    Batch-generate maze test cases.

    Args:
        num_cases: number of cases.
        width: maze width.
        height: maze height.
        wall_density: extra wall density.
        seed: random seed (None = non-deterministic).

    Returns:
        List of case dicts containing maze/start/end/optimal_moves etc.
    """
    if width < 4 or height < 4:
        raise ValueError("Maze dimensions must be at least 4x4")

    rng = random.Random(seed)
    cases = []

    for _ in range(max(1, num_cases)):
        maze = generate_maze(rng, width, height, wall_density)
        start, end = pick_start_end(rng, maze)
        path = find_shortest_path(maze, start, end)
        optimal_moves = len(path) - 1 if path else (width + height)
        cases.append({
            "maze": maze,
            "start": list(start),
            "end": list(end),
            "width": width,
            "height": height,
            "optimal_moves": optimal_moves,
        })

    return cases


# ==================== Internal utilities ====================

def _is_connected(maze: list[list[int]], height: int, width: int) -> bool:
    """Check maze connectivity (BFS)."""
    start = None
    total = 0
    for r in range(height):
        for c in range(width):
            if maze[r][c] == 0:
                total += 1
                if start is None:
                    start = (r, c)
    if start is None:
        return False

    visited: set[tuple[int, int]] = {start}
    queue = deque([start])
    while queue:
        r, c = queue.popleft()
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nr, nc = r + dr, c + dc
            if 0 <= nr < height and 0 <= nc < width:
                if maze[nr][nc] == 0 and (nr, nc) not in visited:
                    visited.add((nr, nc))
                    queue.append((nr, nc))

    return len(visited) == total

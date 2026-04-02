# problems/maze/sandbox/environment.py
"""
Maze environment.

Pure game logic with no I/O or protocol dependencies.
Can be imported standalone for local testing or visualization.
"""

from __future__ import annotations
import random


class MazeEnvironment:
    """
    Interactive maze environment.

    Usage:
        env = MazeEnvironment(case_data, max_moves=200)
        result = env.move("right")  # returns text feedback
        print(env.position, env.success, env.move_count)
    """

    def __init__(self, case_data: dict, max_moves: int = 200):
        self.maze: list[list[int]] = case_data.get("maze", [[0]])
        self.start: tuple[int, int] = tuple(case_data.get("start", [0, 0]))
        self.end: tuple[int, int] = tuple(case_data.get("end", [0, 0]))
        self.position: tuple[int, int] = self.start
        self.move_count: int = 0
        self.max_moves: int = max_moves
        self.trajectory: list[tuple[int, int]] = [self.start]
        self.success: bool = False
        # Randomized feedback text: prevents hard-coded regex cheating
        self._rng = random.Random(case_data.get("text_seed"))

    @property
    def height(self) -> int:
        return len(self.maze)

    @property
    def width(self) -> int:
        return len(self.maze[0]) if self.maze else 0

    @property
    def done(self) -> bool:
        """Whether the case has ended (success or move limit reached)."""
        return self.success or self.move_count >= self.max_moves

    def _speak(self, kind: str, **kwargs) -> str:
        templates: dict[str, list[str]] = {
            "max_moves": [
                "已达到最大移动次数限制",
                "步数耗尽，本回合到此为止。",
                "行动次数已用完，无法继续前进。",
            ],
            "invalid_direction": [
                "无效方向: {direction}",
                "这个方向不合法：{direction}",
                "无法识别方向 `{direction}`，请使用 up/down/left/right",
            ],
            "wall": [
                "前面是墙，鼻子都撞酸了。",
                "好痛！这条路被墙堵死了。",
                "你撞在墙上，没能通过。",
                "哎呀，鼻子给碰得流血了。",
            ],
            "success": [
                "恭喜！你到达了终点！",
                "太好了，我们终于抵达了目的地！",
                "成功了，你已经找到出口。",
            ],
            "move_ok": [
                "移动成功，你又向前推进了一步。",
                "你向前挪了一步，四周有些变化。",
                "这一步走通了，继续探索吧。",
                "没什么大的动静！树上的乌鸦叫了一声。",
            ],
        }
        choices = templates.get(kind, [""])
        msg = self._rng.choice(choices)
        return msg.format(**kwargs)

    def move(self, direction: str) -> str:
        """
        Execute one move.

        Args:
            direction: "up" | "down" | "left" | "right"

        Returns:
            Text feedback from the environment.
        """
        if self.move_count >= self.max_moves:
            return self._speak("max_moves")

        direction = direction.lower().strip()
        deltas = {"up": (-1, 0), "down": (1, 0), "left": (0, -1), "right": (0, 1)}
        dr, dc = deltas.get(direction, (0, 0))

        if dr == 0 and dc == 0:
            return self._speak("invalid_direction", direction=direction)

        nr, nc = self.position[0] + dr, self.position[1] + dc

        # Wall check (outermost ring is always walls; out-of-bounds treated as walls defensively)
        if not (0 <= nr < self.height and 0 <= nc < self.width) or self.maze[nr][nc] == 1:
            self.move_count += 1
            return self._speak("wall")

        self.position = (nr, nc)
        self.move_count += 1
        self.trajectory.append(self.position)

        if self.position == self.end:
            self.success = True
            return self._speak("success")

        return self._speak("move_ok")

    def compute_score(self, optimal_moves: int) -> int:
        """
        Compute score (0-100) based on success and move efficiency.

        Args:
            optimal_moves: optimal solution move count.

        Returns:
            Score (0-100).
        """
        if not self.success:
            return 0
        move_over = max(0, self.move_count - optimal_moves)
        move_ratio = min(1.0, move_over / max(1, self.max_moves - optimal_moves))
        # Deduct points for inefficiency after success; minimum 10 for any success.
        return max(10, round(100 * (1 - move_ratio)))

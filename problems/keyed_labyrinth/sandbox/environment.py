from __future__ import annotations

import random
from typing import Any


DIRS: dict[str, tuple[int, int]] = {
    "up": (0, -1),
    "down": (0, 1),
    "left": (-1, 0),
    "right": (1, 0),
}


class KeyedLabyrinthEnvironment:
    def __init__(self, case_data: dict[str, Any], max_moves: int = 300):
        self.case_data = case_data
        self.grid: list[list[str]] = case_data["grid"]
        self.start: tuple[int, int] = tuple(case_data["start"])
        self.goal: tuple[int, int] = tuple(case_data["goal"])
        self.keys: dict[tuple[int, int], str] = {
            tuple(map(int, pos.split(","))): color
            for pos, color in case_data.get("keys", {}).items()
        }
        self.doors: dict[tuple[int, int], str] = {
            tuple(map(int, pos.split(","))): color
            for pos, color in case_data.get("doors", {}).items()
        }
        self.max_moves = max_moves
        self.position = self.start
        self.inventory: set[str] = set()
        self.opened_doors: set[tuple[int, int]] = set()
        self.move_count = 0
        self.trajectory: list[tuple[int, int]] = [self.position]
        self.done = False
        self.success = False
        self.error: str | None = None
        self._rng = random.Random(case_data.get("feedback_seed", case_data.get("case_index", 0)))

    def move(self, direction: str) -> str:
        if self.done:
            return "本轮已经结束：出口已找到或步数耗尽。"

        direction = str(direction).lower().strip()
        if direction not in DIRS:
            self.done = True
            self.error = f"invalid direction: {direction}"
            return "非法方向。只能使用 up、down、left、right，本 case 结束。"

        self.move_count += 1
        dx, dy = DIRS[direction]
        x, y = self.position
        target = (x + dx, y + dy)

        if self._is_wall(target):
            feedback = self._wall_feedback()
        elif target in self.doors and target not in self.opened_doors:
            color = self.doors[target]
            if color not in self.inventory:
                feedback = self._locked_feedback(color)
            else:
                self.position = target
                self.opened_doors.add(target)
                self.trajectory.append(self.position)
                feedback = self._opened_feedback(color)
                feedback = self._append_cell_event(feedback)
        else:
            self.position = target
            self.trajectory.append(self.position)
            feedback = self._moved_feedback()
            feedback = self._append_cell_event(feedback)

        if not self.success and self.move_count >= self.max_moves:
            self.done = True
            return feedback + " 步数已经耗尽，迷宫关闭，本 case 失败。"
        return feedback

    def _is_wall(self, pos: tuple[int, int]) -> bool:
        x, y = pos
        if y < 0 or y >= len(self.grid) or x < 0 or x >= len(self.grid[0]):
            return True
        return self.grid[y][x] == "#"

    def _append_cell_event(self, feedback: str) -> str:
        if self.position in self.keys:
            color = self.keys[self.position]
            if color not in self.inventory:
                self.inventory.add(color)
                feedback += " " + self._key_feedback(color)
        if self.position == self.goal:
            self.success = True
            self.done = True
            feedback += " " + self._success_feedback()
        return feedback

    def _choice(self, items: list[str]) -> str:
        return self._rng.choice(items)

    def _wall_feedback(self) -> str:
        return self._choice([
            "前方是墙，你撞了一下后仍停在原地。",
            "这一步被石墙挡住了，位置没有变化。",
            "墙壁拦住了去路，这次移动失败。",
        ])

    def _locked_feedback(self, color: str) -> str:
        return self._choice([
            f"一扇{color}色锁门挡住了你；你还没有{color}色钥匙，无法通过。",
            f"目标格是锁住的{color}门。缺少{color}钥匙，所以你仍在原地。",
            f"{color}门没有打开。需要先找到{color}钥匙。",
        ])

    def _opened_feedback(self, color: str) -> str:
        return self._choice([
            f"你用{color}钥匙打开了{color}门，并走进了门后的格子。",
            f"{color}门应声开启，你成功通过。",
            f"匹配的{color}钥匙生效了，这扇门已经被你穿过。",
        ])

    def _moved_feedback(self) -> str:
        return self._choice([
            "你向前移动了一格。",
            "通路可行，你的位置已经改变。",
            "这一步走通了，周围仍然是未知的迷宫。",
        ])

    def _key_feedback(self, color: str) -> str:
        return self._choice([
            f"你在这里捡到了{color}色钥匙。",
            f"地上有一把{color}钥匙，已经自动加入你的背包。",
            f"获得{color}钥匙；之后可以打开同色锁门。",
        ])

    def _success_feedback(self) -> str:
        return self._choice([
            "你看见出口的光，已经到达终点！",
            "恭喜，你成功走出了钥匙迷宫。",
            "出口就在脚下，本 case 成功。",
        ])

    def compute_score(self, optimal_moves: int) -> int:
        if not self.success:
            return 0
        move_over = max(0, self.move_count - optimal_moves)
        budget_over = max(1, self.max_moves - optimal_moves)
        ratio = min(1.0, move_over / budget_over)
        return max(10, round(100 * (1 - ratio)))

    def output_data(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "move_count": self.move_count,
            "inventory": sorted(self.inventory),
            "opened_doors": len(self.opened_doors),
            "error": self.error,
        }

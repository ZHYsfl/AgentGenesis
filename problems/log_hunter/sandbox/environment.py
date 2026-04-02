# problems/log_hunter/sandbox/environment.py
"""
Log Hunter environment - 5M 超长日志中找黑客 IP
"""

import time
from typing import Any


class LogHunterEnvironment:
    def __init__(self, case_data: dict):
        self.log_content = case_data.get("log_content", "")
        self.target_ips = case_data.get("target_ips", [])
        self.user_answers = None
        self._start_time = None
        self._last_result = None

    def get_problem(self) -> str:
        """返回 5M 日志内容"""
        self._start_time = time.time()
        return self.log_content

    def submit_answer(self, answers: list[str]) -> dict:
        """提交找到的 IP 列表"""
        elapsed = time.time() - self._start_time
        self.user_answers = answers

        # 计算正确率
        correct = 0
        for ans in answers:
            if ans in self.target_ips:
                correct += 1

        total = len(self.target_ips)
        accuracy = correct / total if total > 0 else 0

        # 评分：必须3个全对，否则0分
        if correct != 3:
            score = 0
        else:
            # 3个全对，按时间计分：<=10s=100分, <=75s按比例, >75s=0分
            if elapsed <= 10:
                score = 100
            elif elapsed <= 75:
                # 线性插值：10s->100分, 75s->10分
                score = int(100 - (elapsed - 10) * (90 / 65))
            else:
                score = 0

        result = {
            "accuracy": accuracy,
            "score": score,
            "correct": correct,
            "total": total,
            "target_ips": self.target_ips,
            "user_answers": answers,
            "elapsed_seconds": elapsed,
            "time_exceeded": elapsed > 75,
            "passed": correct == 3 and elapsed <= 75,
        }
        self._last_result = result
        return result

    @property
    def done(self) -> bool:
        return self.user_answers is not None

    def get_score(self) -> int:
        """Return the computed score from last submission"""
        if self._last_result:
            return self._last_result.get("score", 0)
        return 0

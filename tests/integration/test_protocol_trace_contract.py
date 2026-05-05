"""Integration tests for protocol trace contract guarantees."""

from __future__ import annotations

import json
import time

from evaluation.models import CaseStatus
from evaluation.runtime.history import (
    attach_case_history,
    record_action_history,
    record_observation_history,
)
from evaluation.runtime.results import parse_case_result
from evaluation.runtime.router import run_pair_protocol_router


def test_protocol_trace_contract_is_stable() -> None:
    judge_lines = iter(
        [
            json.dumps({"type": "case_request"}),
            json.dumps({"type": "case_start", "case_index": 0}),
            json.dumps(
                {
                    "type": "observation",
                    "data": {"obs": 1},
                    "history_events": {"kind": "observation", "payload": {"obs": 1}},
                }
            ),
            json.dumps({"type": "action_request"}),
            json.dumps({"type": "case_end", "case_index": 0, "status": "passed", "score": 7}),
            json.dumps({"type": "case_request"}),
            json.dumps({"type": "eval_complete"}),
        ]
    )

    queue = [0]
    trace: list[str] = []
    judge_sent: list[dict] = []
    user_sent: list[dict] = []
    starts: list[int] = []
    ends: list[int] = []

    def _case_provider():
        return queue.pop(0) if queue else None

    def _poll_judge_line(_deadline: float) -> tuple[str | None, bool]:
        try:
            line = next(judge_lines)
        except StopIteration:
            return None, False
        msg = json.loads(line)
        trace.append(f"judge->worker:{msg.get('type')}")
        return line, False

    def _restart_user_runtime() -> None:
        trace.append("worker:restart_user")

    def _ensure_user_runtime() -> None:
        trace.append("worker:ensure_user")

    def _request_user_action(_trigger_msg: dict) -> dict:
        trace.append("worker->user:action_request")
        return {
            "type": "action",
            "data": {"direction": "R"},
            "history_events": {"kind": "action", "payload": {"direction": "R"}},
        }

    def _send_to_judge(msg: dict, _timeout: int) -> None:
        judge_sent.append(dict(msg))
        trace.append(f"worker->judge:{msg.get('type')}")

    def _send_to_user(msg: dict, _timeout: int) -> None:
        user_sent.append(dict(msg))
        trace.append(f"worker->user:{msg.get('type')}")

    state = run_pair_protocol_router(
        submission_id=1001,
        deadline=time.time() + 30,
        case_provider=_case_provider,
        compute_step_deadline=lambda d: d,
        poll_judge_line=_poll_judge_line,
        restart_user_runtime=_restart_user_runtime,
        ensure_user_runtime=_ensure_user_runtime,
        request_user_action=_request_user_action,
        send_to_judge=_send_to_judge,
        send_to_user=_send_to_user,
        parse_case_result=parse_case_result,
        attach_case_history=attach_case_history,
        record_observation_history=record_observation_history,
        record_action_history=record_action_history,
        on_case_start=lambda idx: starts.append(idx),
        on_case_end=lambda idx, _res: ends.append(idx),
        track_per_case_usage=False,
    )

    assert trace == [
        "judge->worker:case_request",
        "worker->judge:case_assign",
        "judge->worker:case_start",
        "worker:restart_user",
        "judge->worker:observation",
        "worker:ensure_user",
        "worker->user:observation",
        "judge->worker:action_request",
        "worker:ensure_user",
        "worker->user:action_request",
        "worker->judge:action",
        "judge->worker:case_end",
        "judge->worker:case_request",
        "worker->judge:case_stop",
        "judge->worker:eval_complete",
    ]
    assert starts == [0]
    assert ends == [0]

    assert len(state.cases) == 1
    assert state.cases[0].status == CaseStatus.PASSED
    assert state.cases[0].score == 7

    obs_msgs = [m for m in user_sent if m.get("type") == "observation"]
    assert obs_msgs, "observation should be forwarded"
    assert all("history_events" not in m for m in obs_msgs)

    assert [m.get("type") for m in judge_sent] == ["case_assign", "action", "case_stop"]

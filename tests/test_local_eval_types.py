from __future__ import annotations

import pytest

from ..local.eval_types import EvalEvent, EvalEventType


def test_format_data_preview_truncates_long_text() -> None:
    event = EvalEvent(
        type=EvalEventType.OBSERVATION,
        case_index=0,
        data={"data": "x" * 200},
    )
    preview = event._format_data_preview()
    assert preview.endswith("...")
    assert len(preview) == 83


def test_format_data_preview_handles_missing_data() -> None:
    event = EvalEvent(type=EvalEventType.ERROR, case_index=0, data={})
    assert event._format_data_preview() == ""


@pytest.mark.parametrize(
    ("event_type", "payload", "expected"),
    [
        (EvalEventType.OBSERVATION, {"data": "obs"}, "Observation: obs"),
        (EvalEventType.ACTION, {"data": "act"}, "Action: act"),
        (EvalEventType.CASE_START, {}, "Started"),
        (EvalEventType.CASE_END, {"status": "passed", "score": 3}, "Ended: status=passed, score=3"),
        (EvalEventType.JUDGE_LOG, {"data": "judge"}, "[Judge Log] judge"),
        (EvalEventType.USER_LOG, {"data": "user"}, "[User Log] user"),
        (EvalEventType.PROGRESS, {"completed": 2, "total": 5}, "[Progress] 2/5 cases completed"),
        (EvalEventType.ERROR, {"error": "boom"}, "[Error] boom"),
    ],
)
def test_eval_event_string_rendering(
    event_type: EvalEventType,
    payload: dict[str, object],
    expected: str,
) -> None:
    event = EvalEvent(type=event_type, case_index=1, data=payload)
    rendered = str(event)
    assert expected in rendered

from __future__ import annotations

import json

from ..local.eval_types import EvalEvent, EvalEventType
from ..local.visualization import TerminalVisualizer
from ..models import CaseResult, CaseStatus, PhaseResult, PhaseStatus


def _event(event_type: EvalEventType, case_index: int, data: dict | None = None) -> EvalEvent:
    return EvalEvent(type=event_type, case_index=case_index, data=data or {})


def test_invalid_mode_raises_value_error() -> None:
    try:
        TerminalVisualizer(mode="invalid")  # type: ignore[arg-type]
        assert False, "Expected ValueError for invalid mode"
    except ValueError as exc:
        assert "Invalid mode" in str(exc)


def test_grouped_mode_buffers_until_case_end() -> None:
    lines: list[str] = []
    visualizer = TerminalVisualizer(
        mode="grouped",
        colorize=False,
        output=lines.append,
        show_progress=False,
        show_judge_logs=True,
    )

    visualizer.on_event(_event(EvalEventType.CASE_START, 0))
    visualizer.on_event(_event(EvalEventType.OBSERVATION, 0, {"data": {"x": 1}}))
    visualizer.on_event(_event(EvalEventType.ACTION, 0, {"data": "go"}))
    visualizer.on_event(_event(EvalEventType.USER_LOG, 0, {"data": "u-line"}))
    visualizer.on_event(_event(EvalEventType.JUDGE_LOG, 0, {"data": "j-line"}))
    assert lines == []

    visualizer.on_event(_event(EvalEventType.CASE_END, 0, {"status": "passed", "score": 1}))
    assert lines
    assert lines[0].startswith("┌── Case 1")
    assert any("[OBS]" in line for line in lines)
    assert any("[ACT]" in line for line in lines)
    assert any("[USER]" in line for line in lines)
    assert any("[JUDGE]" in line for line in lines)
    assert any("Case 1: PASSED" in line for line in lines)
    assert all(not line.startswith("[C1]") for line in lines)


def test_interleaved_mode_prefixes_case_tags() -> None:
    lines: list[str] = []
    visualizer = TerminalVisualizer(
        mode="interleaved",
        colorize=False,
        output=lines.append,
        show_progress=False,
        show_judge_logs=True,
    )

    visualizer.on_event(_event(EvalEventType.CASE_START, 1))
    visualizer.on_event(_event(EvalEventType.OBSERVATION, 1, {"data": "obs"}))
    visualizer.on_event(_event(EvalEventType.ACTION, 1, {"data": "act"}))
    visualizer.on_event(_event(EvalEventType.USER_LOG, 1, {"data": "line-a\nline-b"}))
    visualizer.on_event(_event(EvalEventType.JUDGE_LOG, 1, {"data": "line-c\nline-d"}))
    visualizer.on_event(_event(EvalEventType.CASE_END, 1, {"status": "failed", "score": 0}))

    assert lines
    assert all(line.startswith("[C2] ") for line in lines)
    assert any("[OBS]" in line for line in lines)
    assert any("[ACT]" in line for line in lines)
    assert any("[USER]" in line for line in lines)
    assert any("[JUDGE]" in line for line in lines)
    assert any("Case 2: FAILED" in line for line in lines)


def test_progress_error_and_summary_rendering() -> None:
    lines: list[str] = []
    visualizer = TerminalVisualizer(
        mode="interleaved",
        colorize=False,
        output=lines.append,
    )

    visualizer.on_event(_event(EvalEventType.PROGRESS, -1, {"completed": 1, "total": 3}))
    visualizer.on_event(_event(EvalEventType.ERROR, -1, {"error": "global error"}))
    visualizer.on_event(_event(EvalEventType.ERROR, 0, {"error": "case error"}))

    result = PhaseResult(
        status=PhaseStatus.SUCCESS,
        score=2,
        total_cases=2,
        passed_cases=1,
        total_time=123,
        cases=[
            CaseResult(case_index=0, status=CaseStatus.PASSED, score=1),
            CaseResult(case_index=1, status=CaseStatus.FAILED, score=1),
        ],
    )
    visualizer.print_summary(result)

    joined = "\n".join(lines)
    assert "Progress" in joined
    assert "global error" in joined
    assert "case error" in joined
    assert "Evaluation Summary" in joined
    assert "Case Details:" in joined


def test_visualizer_helper_branches(monkeypatch) -> None:
    lines: list[str] = []
    visualizer = TerminalVisualizer(
        mode="grouped",
        colorize=False,
        output=lines.append,
        max_content_length=10,
        show_oa_sequence=False,
    )

    # _truncate long-text branch
    assert visualizer._truncate("1234567890123").endswith("...")

    # _format_json_preview exception branch
    monkeypatch.setattr(json, "dumps", lambda *args, **kwargs: (_ for _ in ()).throw(TypeError("boom")))
    preview = visualizer._format_json_preview({"k": "v"})
    assert "{" in preview

    # no-op buffer flush branch
    visualizer._flush_case_buffer(99)

    # show_oa_sequence=False branch should suppress output
    visualizer.on_event(_event(EvalEventType.OBSERVATION, 0, {"data": "hidden"}))
    assert lines == []


def test_summary_error_and_nonstandard_case_status() -> None:
    lines: list[str] = []
    visualizer = TerminalVisualizer(mode="interleaved", colorize=False, output=lines.append)

    result = PhaseResult(
        status=PhaseStatus.ERROR,
        score=0,
        total_cases=1,
        passed_cases=0,
        total_time=1,
        cases=[CaseResult(case_index=0, status=CaseStatus.MLE, score=0)],
    )
    visualizer.print_summary(result)
    joined = "\n".join(lines)
    assert "ERROR" in joined
    assert "Case 1: CaseStatus.MLE" in joined

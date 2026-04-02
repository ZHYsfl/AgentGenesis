"""Terminal Visualization Module

Provides terminal visualization functionality as a local alternative to cloud SSE streaming.
"""

from __future__ import annotations

import shutil
import sys
import threading
from typing import Any, Callable, Optional

from .eval_types import EvalEvent, EvalEventType


class TerminalVisualizer:
    """Terminal Visualizer

    Outputs evaluation events to terminal in real-time, supporting:
    - OA (Observation-Action) sequence visualization
    - Sandbox log output
    - Progress bar display
    - Colored output
    - Output modes:
        - grouped: buffer each case and flush as a block when the case ends
        - interleaved: print events immediately with case tags like [C1], [C2]

    Example:
        visualizer = TerminalVisualizer(
            show_oa_sequence=True,
            show_user_logs=True,
            mode="grouped",
        )

        for event in evaluator.evaluate_stream():
            visualizer.on_event(event)
    """

    # ANSI color codes
    COLORS = {
        "reset": "\033[0m",
        "bold": "\033[1m",
        "dim": "\033[2m",
        "green": "\033[32m",
        "blue": "\033[34m",
        "yellow": "\033[33m",
        "red": "\033[31m",
        "cyan": "\033[36m",
        "magenta": "\033[35m",
        "gray": "\033[90m",
    }
    VALID_MODES = {"grouped", "interleaved"}

    def __init__(
        self,
        show_oa_sequence: bool = True,
        show_judge_logs: bool = False,
        show_user_logs: bool = True,
        show_progress: bool = True,
        show_case_status: bool = True,
        mode: str = "grouped",
        colorize: bool = True,
        max_content_length: int = 200,
        output: Optional[Callable[[str], None]] = None,
    ):
        """Initialize terminal visualizer.

        Args:
            show_oa_sequence: Whether to show Observation-Action sequence
            show_judge_logs: Whether to show Judge sandbox output
            show_user_logs: Whether to show User sandbox output
            show_progress: Whether to show progress bar
            show_case_status: Whether to show Case start/end status
            mode: Output mode ("grouped" or "interleaved")
            colorize: Whether to use colored output
            max_content_length: Maximum display length for content
            output: Custom output function (default: print)
        """
        if mode not in self.VALID_MODES:
            raise ValueError(
                f"Invalid mode: {mode}. Expected one of: {sorted(self.VALID_MODES)}"
            )

        self.show_oa_sequence = show_oa_sequence
        self.show_judge_logs = show_judge_logs
        self.show_user_logs = show_user_logs
        self.show_progress = show_progress
        self.show_case_status = show_case_status
        self.mode = mode
        self.colorize = colorize and sys.stdout.isatty()
        self.max_content_length = max_content_length
        self.output = output or print

        # State tracking
        self._total_cases: Optional[int] = None
        self._completed_cases: set[int] = set()
        self._current_case: Optional[int] = None

        # Thread-safe output and grouped buffering.
        self._lock = threading.Lock()
        self._buffers: dict[int, list[str]] = {}

    def _color(self, text: str, color: str) -> str:
        """Add color to text."""
        if not self.colorize:
            return text
        return f"{self.COLORS.get(color, '')}{text}{self.COLORS['reset']}"

    def _truncate(self, text: str) -> str:
        """Truncate long text."""
        if len(text) <= self.max_content_length:
            return text
        return text[: self.max_content_length - 3] + "..."

    def _format_json_preview(self, data: dict) -> str:
        """Format JSON preview."""
        import json

        try:
            text = json.dumps(data, ensure_ascii=False, default=str)
            return self._truncate(text)
        except Exception:
            return self._truncate(str(data))

    def _write_line(self, line: str) -> None:
        """Output a line using a thread-safe lock."""
        with self._lock:
            self.output(line)

    def _case_tag(self, case_index: int) -> str:
        """Build case tag used in interleaved mode."""
        return self._color(f"[C{case_index + 1}]", "gray")

    def _format_case_line(self, case_index: int, line: str) -> str:
        """Prefix case tag in interleaved mode."""
        if self.mode != "interleaved" or case_index < 0:
            return line
        return f"{self._case_tag(case_index)} {line}"

    def _emit_case_line(self, case_index: int, line: str) -> None:
        """Emit a case-scoped line according to output mode."""
        rendered = self._format_case_line(case_index, line)
        if self.mode == "grouped" and case_index >= 0:
            self._buffers.setdefault(case_index, []).append(rendered)
            return
        self._write_line(rendered)

    def _flush_case_buffer(self, case_index: int) -> None:
        """Flush and clear one case buffer."""
        lines = self._buffers.pop(case_index, [])
        if not lines:
            return
        with self._lock:
            for line in lines:
                self.output(line)

    def on_event(self, event: EvalEvent) -> None:
        """Handle evaluation event.

        Args:
            event: Evaluation event
        """
        match event.type:
            case EvalEventType.CASE_START:
                self._on_case_start(event)
            case EvalEventType.CASE_END:
                self._on_case_end(event)
            case EvalEventType.OBSERVATION:
                self._on_observation(event)
            case EvalEventType.ACTION:
                self._on_action(event)
            case EvalEventType.JUDGE_LOG:
                self._on_judge_log(event)
            case EvalEventType.USER_LOG:
                self._on_user_log(event)
            case EvalEventType.PROGRESS:
                self._on_progress(event)
            case EvalEventType.ERROR:
                self._on_error(event)

    def _on_case_start(self, event: EvalEvent) -> None:
        """Handle Case start."""
        if not self.show_case_status:
            return

        self._current_case = event.case_index
        case_num = event.case_index + 1
        msg = self._color(f"┌── Case {case_num} ", "bold")
        self._emit_case_line(event.case_index, msg)

    def _on_case_end(self, event: EvalEvent) -> None:
        """Handle Case end."""
        self._completed_cases.add(event.case_index)

        status = event.data.get("status", "unknown")
        score = event.data.get("score", 0)
        error = event.data.get("error")

        # Choose color based on status.
        if status == "passed":
            status_color = "green"
            icon = "✓"
        elif status == "failed":
            status_color = "yellow"
            icon = "✗"
        else:
            status_color = "red"
            icon = "✗"

        if self.show_case_status:
            case_num = event.case_index + 1
            status_text = self._color(f"{icon} Case {case_num}: {status.upper()}", status_color)
            if error:
                self._emit_case_line(
                    event.case_index,
                    f"│  {status_text} (score: {score}) - Error: {error}",
                )
            else:
                self._emit_case_line(
                    event.case_index,
                    f"│  {status_text} (score: {score})",
                )
            self._emit_case_line(event.case_index, self._color("└" + "─" * 40, "dim"))

        if self.mode == "grouped":
            self._flush_case_buffer(event.case_index)

    def _on_observation(self, event: EvalEvent) -> None:
        """Handle Observation (Judge -> User)."""
        if not self.show_oa_sequence:
            return

        content = event.data.get("data", "")
        if isinstance(content, dict):
            preview = self._format_json_preview(content)
        else:
            preview = self._truncate(str(content))

        arrow = self._color("───>", "green")
        prefix = self._color("[OBS]", "green")
        self._emit_case_line(event.case_index, f"│  {prefix} {arrow} {preview}")

    def _on_action(self, event: EvalEvent) -> None:
        """Handle Action (User -> Judge)."""
        if not self.show_oa_sequence:
            return

        content = event.data.get("data", "")
        if isinstance(content, dict):
            preview = self._format_json_preview(content)
        else:
            preview = self._truncate(str(content))

        arrow = self._color("<───", "blue")
        prefix = self._color("[ACT]", "blue")
        self._emit_case_line(event.case_index, f"│  {prefix} {arrow} {preview}")

    def _on_judge_log(self, event: EvalEvent) -> None:
        """Handle Judge log."""
        if not self.show_judge_logs:
            return

        content = event.data.get("data", "")
        for line in str(content).strip().split("\n"):
            if line.strip():
                prefix = self._color("[JUDGE]", "magenta")
                self._emit_case_line(event.case_index, f"│  {prefix} {self._truncate(line)}")

    def _on_user_log(self, event: EvalEvent) -> None:
        """Handle User log."""
        if not self.show_user_logs:
            return

        content = event.data.get("data", "")
        for line in str(content).strip().split("\n"):
            if line.strip():
                prefix = self._color("[USER]", "cyan")
                self._emit_case_line(event.case_index, f"│  {prefix} {self._truncate(line)}")

    def _on_progress(self, event: EvalEvent) -> None:
        """Handle progress update."""
        completed = event.data.get("completed", 0)
        total = event.data.get("total", 0)
        self._total_cases = total

        if not self.show_progress or total <= 0:
            return

        # Draw progress bar.
        terminal_width = shutil.get_terminal_size().columns
        bar_width = min(40, terminal_width - 30)

        filled = int(bar_width * completed / total)
        bar = "█" * filled + "░" * (bar_width - filled)

        percent = completed / total * 100
        progress_text = f"[{bar}] {completed}/{total} ({percent:.1f}%)"

        self._write_line(self._color(f"\n📊 Progress: {progress_text}\n", "bold"))

    def _on_error(self, event: EvalEvent) -> None:
        """Handle error."""
        error = event.data.get("error", "Unknown error")
        if event.case_index >= 0:
            prefix = self._color("❌ Error:", "red")
            self._emit_case_line(event.case_index, f"│  {prefix} {self._truncate(str(error))}")
            return
        self._write_line(self._color(f"\n❌ Error: {error}\n", "red"))

    def print_summary(self, result: Any) -> None:
        """Print evaluation summary.

        Args:
            result: PhaseResult object
        """
        self._write_line("")
        self._write_line(self._color("=" * 50, "bold"))
        self._write_line(self._color("📋 Evaluation Summary", "bold"))
        self._write_line(self._color("=" * 50, "bold"))

        status = getattr(result, "status", "unknown")
        total_cases = getattr(result, "total_cases", 0)
        passed_cases = getattr(result, "passed_cases", 0)
        score = getattr(result, "score", 0)
        total_time = getattr(result, "total_time", 0)

        # Status color.
        if status == "success":
            status_str = self._color("✓ PASSED", "green")
        elif status == "failed":
            status_str = self._color("✗ FAILED", "yellow")
        else:
            status_str = self._color(f"✗ {status.upper()}", "red")

        self._write_line(f"Status:      {status_str}")
        self._write_line(f"Cases:       {passed_cases}/{total_cases} passed")
        self._write_line(f"Score:       {score}")
        self._write_line(f"Total Time:  {total_time}ms")

        # Per-case results.
        cases = getattr(result, "cases", [])
        if cases:
            self._write_line("")
            self._write_line(self._color("Case Details:", "bold"))
            for case in cases:
                case_status = getattr(case, "status", "unknown")
                case_score = getattr(case, "score", 0)
                case_idx = getattr(case, "case_index", 0) + 1

                if case_status == "passed":
                    case_icon = self._color("✓", "green")
                elif case_status == "failed":
                    case_icon = self._color("✗", "yellow")
                else:
                    case_icon = self._color("✗", "red")

                self._write_line(
                    f"  {case_icon} Case {case_idx}: {case_status} (score: {case_score})"
                )

        self._write_line(self._color("=" * 50, "bold"))
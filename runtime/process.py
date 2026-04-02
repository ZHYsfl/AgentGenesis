"""Sandbox process start/stop/alive abstractions."""

from __future__ import annotations

import logging
import shlex
from dataclasses import dataclass
from typing import Any, Optional

from ..sandbox_backend import ExecHandle, Sandbox

logger: logging.Logger = logging.getLogger(__name__)


@dataclass
class SandboxProcessHandle:
    raw_handle: ExecHandle
    workdir: str
    script_rel: str


class SandboxProcessManager:
    @staticmethod
    def start_background_python(
        sandbox: Sandbox,
        *,
        workdir: str,
        script_rel: str,
        envs: Optional[dict[str, str]] = None,
        stderr_path: str = "/workspace/.worker_stderr.log",
        args: Optional[list[str]] = None,
    ) -> SandboxProcessHandle:
        envs = envs or {}
        argv = ["python", "-u", script_rel]
        if args:
            argv.extend([str(v) for v in args])

        workdir_literal = shlex.quote(workdir)
        stderr_literal = shlex.quote(stderr_path)
        python_cmd = " ".join(shlex.quote(v) for v in argv)
        shell_cmd = (
            f"cd {workdir_literal} && "
            "source /workspace/.venv/bin/activate && "
            f"exec {python_cmd} 2>{stderr_literal}"
        )

        raw_handle = sandbox.run_command(
            shell_cmd,
            timeout=30,
            envs=envs,
            background=True,
        )
        if not isinstance(raw_handle, ExecHandle):
            raise RuntimeError(
                f"background process start returned unexpected type: {type(raw_handle).__name__}"
            )
        return SandboxProcessHandle(
            raw_handle=raw_handle,
            workdir=workdir,
            script_rel=script_rel,
        )

    @staticmethod
    def stop_process(process: Optional[SandboxProcessHandle]) -> None:
        if not process:
            return
        try:
            process.raw_handle.kill()
        except Exception:
            logger.debug(
                "background handle kill failed for %s",
                process.script_rel,
                exc_info=True,
            )

    @staticmethod
    def is_process_alive(process: Optional[SandboxProcessHandle]) -> bool:
        if process is None:
            return False
        try:
            return process.raw_handle.is_running()
        except Exception:
            return True

    @staticmethod
    def describe_process(process: Optional[SandboxProcessHandle]) -> str:
        if process is None:
            return "none"
        running = "running" if process.raw_handle.is_running() else "stopped"
        return f"{process.script_rel}@{process.workdir} ({running})"

"""Sandbox abstraction and Docker backend implementation."""

from __future__ import annotations

import io
import logging
import os
import subprocess
import tarfile
import tempfile
import threading
import time
from pathlib import Path
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional, Union

import docker
from docker.api.client import APIClient
from docker.client import DockerClient
from docker.models.containers import Container

logger: logging.Logger = logging.getLogger(__name__)


@dataclass
class CommandResult:
    """Result of a synchronous command execution inside a sandbox."""

    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0


@dataclass
class ExecHandle:
    """Handle to a background process inside a Docker container or local subprocess."""

    _api: APIClient = field(repr=False, default=None)
    _exec_id: str = ""
    command: str = ""
    _local_proc: Optional[subprocess.Popen] = field(repr=False, default=None)

    def is_running(self) -> bool:
        if self._local_proc is not None:
            return self._local_proc.poll() is None
        try:
            info = self._api.exec_inspect(self._exec_id)
            return info.get("Running", False)
        except Exception:
            return False

    def kill(self) -> None:
        if self._local_proc is not None:
            try:
                self._local_proc.terminate()
            except Exception:
                pass
            try:
                self._local_proc.kill()
            except Exception:
                pass
            return
        """Best-effort kill: there is no direct Docker API to kill an exec.

        We rely on the container being stopped/removed to terminate all execs.
        For individual exec cleanup we can't do much — Docker doesn't expose
        a per-exec kill endpoint. The caller should stop the whole container
        when it's time to tear down.
        """


class Sandbox(ABC):
    """Abstract sandbox interface for running isolated evaluation code."""

    @property
    @abstractmethod
    def id(self) -> str:
        ...

    @abstractmethod
    def run_command(
        self,
        command: str,
        *,
        timeout: int = 30,
        envs: Optional[dict[str, str]] = None,
        background: bool = False,
    ) -> Union[CommandResult, ExecHandle]:
        ...

    @abstractmethod
    def write_files(self, files: list[dict[str, Any]]) -> None:
        ...

    @abstractmethod
    def get_host(self, port: int) -> str:
        ...

    @abstractmethod
    def get_metrics(self) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    def close(self) -> None:
        ...

    @abstractmethod
    def kill(self) -> None:
        ...


class DockerSandbox(Sandbox):
    """Docker container-backed sandbox using the official docker-py SDK."""

    def __init__(self, container: Container) -> None:
        self._container = container
        self._container.reload()
        ip: str = self._container.attrs.get("NetworkSettings", {}).get("IPAddress", "")
        if not ip:
            networks = self._container.attrs.get("NetworkSettings", {}).get("Networks", {})
            for net_info in networks.values():
                ip = net_info.get("IPAddress", "")
                if ip:
                    break
        self._ip: str = ip
        self._id: str = self._container.short_id

    @property
    def id(self) -> str:
        return self._id

    def run_command(
        self,
        command: str,
        *,
        timeout: int = 30,
        envs: Optional[dict[str, str]] = None,
        background: bool = False,
    ) -> Union[CommandResult, ExecHandle]:
        env_list: Optional[list[str]] = None
        if envs:
            env_list = [f"{k}={v}" for k, v in envs.items()]

        client: DockerClient = self._container.client
        api: APIClient = client.api

        if background:
            exec_obj = api.exec_create(
                self._container.id,
                cmd=["bash", "-lc", command],
                environment=env_list,
                stdout=True,
                stderr=True,
            )
            api.exec_start(exec_obj["Id"], detach=True)
            return ExecHandle(_api=api, _exec_id=exec_obj["Id"], command=command)

        exec_obj = api.exec_create(
            self._container.id,
            cmd=["bash", "-lc", command],
            environment=env_list,
            stdout=True,
            stderr=True,
        )

        output = api.exec_start(exec_obj["Id"], detach=False, demux=True)
        info = api.exec_inspect(exec_obj["Id"])
        exit_code = info.get("ExitCode", -1)

        stdout_bytes, stderr_bytes = b"", b""
        if isinstance(output, tuple):
            stdout_bytes = output[0] or b""
            stderr_bytes = output[1] or b""
        elif isinstance(output, bytes):
            stdout_bytes = output

        return CommandResult(
            stdout=stdout_bytes.decode("utf-8", "replace"),
            stderr=stderr_bytes.decode("utf-8", "replace"),
            exit_code=exit_code,
        )

    def write_files(self, files: list[dict[str, Any]]) -> None:
        """Write files into the container via a tar archive stream.

        Each entry in *files* must be ``{"path": "/abs/path", "data": bytes}``.
        """
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            for entry in files:
                path: str = entry["path"]
                data: bytes = entry["data"] if isinstance(entry["data"], bytes) else entry["data"].encode("utf-8")
                info = tarfile.TarInfo(name=path.lstrip("/"))
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        buf.seek(0)
        self._container.put_archive("/", buf)

    def get_host(self, port: int) -> str:
        return f"{self._ip}:{port}"

    def get_metrics(self) -> list[dict[str, Any]]:
        try:
            stats = self._container.stats(stream=False)
            mem_stats = stats.get("memory_stats", {})
            mem_used = mem_stats.get("usage", 0) / (1024 * 1024)
            return [{"mem_used_mib": round(mem_used, 2)}]
        except Exception:
            return []

    def close(self) -> None:
        try:
            self._container.stop(timeout=10)
        except Exception:
            pass
        try:
            self._container.remove(force=True)
        except Exception:
            pass

    def kill(self) -> None:
        try:
            self._container.kill()
        except Exception:
            pass
        try:
            self._container.remove(force=True)
        except Exception:
            pass


_DEFAULT_IMAGE = "genesis-sandbox-base:latest"


def pip_index_env_from_host() -> dict[str, str]:
    """Pass through PyPI mirror settings (e.g. UV_INDEX_URL) into sandbox containers."""
    import os as _os

    out: dict[str, str] = {}
    for key in ("UV_INDEX_URL", "PIP_INDEX_URL"):
        val = str(_os.environ.get(key, "") or "").strip()
        if val:
            out[key] = val
    return out


def _keepalive_cmd(seconds: int) -> list[str]:
    # Use absolute path to avoid PATH issues in minimal images.
    return ["/usr/bin/sleep", str(max(1, int(seconds)))]


def create_docker_sandbox(
    *,
    image: Optional[str] = None,
    timeout: int = 300,
    cpu_count: Optional[float] = None,
    memory_mb: Optional[int] = None,
) -> DockerSandbox:
    """Create a new Docker container and return a ``DockerSandbox`` wrapper.

    The container is started in detached mode with a long-running ``sleep``
    process so we can ``exec`` commands into it.
    """
    import os

    image = image or os.getenv("SANDBOX_DOCKER_IMAGE", _DEFAULT_IMAGE)
    client = docker.from_env()

    kwargs: dict[str, Any] = {
        "image": image,
        "command": _keepalive_cmd(timeout),
        "detach": True,
        "network_mode": "bridge",
        "stdin_open": True,
        "tty": False,
    }

    pip_env = pip_index_env_from_host()
    if pip_env:
        kwargs["environment"] = pip_env

    if cpu_count and cpu_count > 0:
        kwargs["nano_cpus"] = int(cpu_count * 1e9)
    if memory_mb and memory_mb > 0:
        kwargs["mem_limit"] = f"{memory_mb}m"

    container = client.containers.run(**kwargs)

    sandbox = DockerSandbox(container)
    logger.info("Docker sandbox created: id=%s, image=%s", sandbox.id, image)
    return sandbox


# ---------------------------------------------------------------------------
# Local sandbox implementation (no Docker)
# ---------------------------------------------------------------------------


class _LocalExecHandle:
    """Minimal ExecHandle stand-in for LocalSandbox background processes."""

    def __init__(self, proc: subprocess.Popen) -> None:
        self._proc = proc

    def is_running(self) -> bool:
        return self._proc.poll() is None

    def kill(self) -> None:
        try:
            self._proc.terminate()
        except Exception:
            pass
        try:
            self._proc.kill()
        except Exception:
            pass


class LocalSandbox(Sandbox):
    """Host-process sandbox using a temporary directory and subprocesses."""

    def __init__(self, root_dir: Path, venv_dir: Path, sandbox_id: str) -> None:
        self._root = root_dir
        self._venv = venv_dir
        self._id = sandbox_id
        self._bg_procs: list[subprocess.Popen] = []

    @property
    def id(self) -> str:
        return self._id

    def _resolve_command(self, command: str) -> str:
        """Rewrite /workspace paths to the actual sandbox root directory."""
        return command.replace("/workspace", str(self._root / "workspace"))

    def run_command(
        self,
        command: str,
        *,
        timeout: int = 30,
        envs: Optional[dict[str, str]] = None,
        background: bool = False,
    ) -> Union[CommandResult, ExecHandle]:
        env = dict(os.environ)
        env["VIRTUAL_ENV"] = str(self._venv)
        env["PATH"] = f"{self._venv}/bin:" + env.get("PATH", "")
        if envs:
            env.update(envs)

        cwd = str(self._root)
        cmd = ["bash", "-lc", self._resolve_command(command)]

        if background:
            log_dir = Path("/tmp/ag-logs")
            log_dir.mkdir(exist_ok=True)
            out = log_dir / f"local-{self._id}.out"
            err = log_dir / f"local-{self._id}.err"
            out_fh = open(out, "a")
            err_fh = open(err, "a")
            proc = subprocess.Popen(
                cmd,
                cwd=cwd,
                env=env,
                stdout=out_fh,
                stderr=err_fh,
            )
            self._bg_procs.append(proc)
            return ExecHandle(
                _api=None,
                _exec_id="",
                command=command,
                _local_proc=proc,
            )

        result = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return CommandResult(
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.returncode,
        )

    def write_files(self, files: list[dict[str, Any]]) -> None:
        for entry in files:
            path: str = entry["path"]
            data: bytes = entry["data"] if isinstance(entry["data"], bytes) else entry["data"].encode("utf-8")
            target = self._root / path.lstrip("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

    def get_host(self, port: int) -> str:
        return f"unix:/tmp/ag-sb-{self._id}-{port}.sock"

    def grpc_bind_address(self, port: int) -> str:
        return self.get_host(port)

    def get_metrics(self) -> list[dict[str, Any]]:
        return []

    def close(self) -> None:
        for proc in self._bg_procs:
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                proc.kill()
            except Exception:
                pass
        self._bg_procs.clear()
        try:
            import shutil
            shutil.rmtree(self._root, ignore_errors=True)
        except Exception:
            pass
        for sock in Path("/tmp").glob(f"ag-sb-{self._id}-*.sock"):
            try:
                sock.unlink()
            except Exception:
                pass

    def kill(self) -> None:
        self.close()


def create_local_sandbox(
    *,
    image: Optional[str] = None,
    timeout: int = 300,
    cpu_count: Optional[float] = None,
    memory_mb: Optional[int] = None,
    pip_dependencies: Optional[list[str]] = None,
) -> LocalSandbox:
    """Create a new local sandbox (temporary directory + venv).

    The *image*, *cpu_count*, and *memory_mb* arguments are ignored; they
    exist purely to match the signature of ``create_docker_sandbox``.
    """
    root_dir = Path(tempfile.mkdtemp(prefix="ag-sb-"))
    venv_dir = root_dir / "workspace" / ".venv"
    venv_dir.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["uv", "venv", str(venv_dir), "--system-site-packages"],
        check=True,
        capture_output=True,
    )
    # Install agent-genesis into the sandbox venv so bridge scripts can import it.
    repo_root = Path(__file__).resolve().parents[1]
    ag_path = repo_root / "AgentGenesis"
    subprocess.run(
        ["uv", "pip", "install", "--python", str(venv_dir / "bin" / "python"), "-e", str(ag_path)],
        check=True,
        capture_output=True,
    )

    if pip_dependencies:
        deps = " ".join(pip_dependencies)
        workspace_dir = root_dir / "workspace"
        subprocess.run(
            ["bash", "-lc", f"cd {workspace_dir} && source .venv/bin/activate && uv pip install -q {deps}"],
            check=True,
            capture_output=True,
        )
    sandbox_id = root_dir.name.replace("ag-sb-", "")
    logger.info("Local sandbox created: id=%s, root=%s", sandbox_id, root_dir)
    return LocalSandbox(root_dir, venv_dir, sandbox_id)

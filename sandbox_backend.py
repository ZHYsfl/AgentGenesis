"""Sandbox abstraction and Docker backend implementation."""

from __future__ import annotations

import io
import logging
import tarfile
import threading
import time
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
    """Handle to a background process inside a Docker container."""

    _api: APIClient = field(repr=False)
    _exec_id: str = ""
    command: str = ""

    def is_running(self) -> bool:
        try:
            info = self._api.exec_inspect(self._exec_id)
            return info.get("Running", False)
        except Exception:
            return False

    def kill(self) -> None:
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
        self._ip: str = (
            self._container.attrs.get("NetworkSettings", {}).get("IPAddress", "")
        )
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


def _keepalive_cmd(seconds: int) -> list[str]:
    # Use absolute path to avoid PATH issues in minimal images.
    return ["/usr/bin/sleep", str(max(1, int(seconds)))]


def create_docker_sandbox(
    *,
    image: Optional[str] = None,
    timeout: int = 300,
    cpu_count: Optional[int] = None,
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
        "auto_remove": True,  # Auto-remove container after stop to prevent corpse accumulation
    }

    if cpu_count and cpu_count > 0:
        kwargs["nano_cpus"] = int(cpu_count * 1e9)
    if memory_mb and memory_mb > 0:
        kwargs["mem_limit"] = f"{memory_mb}m"

    container = client.containers.run(**kwargs)

    sandbox = DockerSandbox(container)
    logger.info("Docker sandbox created: id=%s, image=%s", sandbox.id, image)
    return sandbox

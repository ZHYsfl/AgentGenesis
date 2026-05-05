"""Sandbox creation, concurrency control, and lifecycle helpers."""

from __future__ import annotations

import hashlib
import io
import logging
import os
import tarfile
import threading
import time
from typing import Any, Optional

from .config import get_config
from .sandbox_backend import (
    DockerSandbox,
    Sandbox,
    create_docker_sandbox,
    pip_index_env_from_host,
)

logger: logging.Logger = logging.getLogger(__name__)

_DEFAULT_GC_MAX_AGE = 7 * 86400  # 7 days
_DEFAULT_GC_INTERVAL = 86400  # 24 hours
_TEMPLATE_REPO = "genesis-phase-template"
_TEMPLATE_BASE_ID_LABEL = "agent_genesis.template_base_identity"


def _keepalive_cmd(seconds: int) -> list[str]:
    # Use absolute path to avoid PATH issues in minimal images.
    return ["/usr/bin/sleep", str(max(1, int(seconds)))]


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = raw.strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid integer for %s=%r; fallback to %d", name, raw, default)
        return default


def extract_image_data_files(
    artifact_files: dict[str, bytes],
    image_data_dirs: list[str],
) -> dict[str, bytes]:
    """Extract files whose paths fall under *image_data_dirs* prefixes."""
    if not image_data_dirs:
        return {}
    prefixes = [d.rstrip("/") + "/" for d in image_data_dirs]
    data_files: dict[str, bytes] = {}
    for path, content in artifact_files.items():
        for prefix in prefixes:
            if path.startswith(prefix) or path + "/" == prefix:
                data_files[path] = content
                break
    return data_files


def compute_data_content_hash(data_files: dict[str, bytes]) -> str:
    """Stable SHA-256 over sorted (path, content) pairs, truncated to 16 hex chars."""
    hasher = hashlib.sha256()
    for path in sorted(data_files.keys()):
        hasher.update(path.encode("utf-8"))
        hasher.update(data_files[path])
    return hasher.hexdigest()[:16]


class TemplateImagePool:
    """Lazily builds and caches per-phase Docker images.

    The key is a hash of the sorted pip_dependencies list so that phases
    sharing the same dependency set share one template image.

    Stale images that haven't been used within ``max_age_seconds`` are
    periodically evicted by an internal GC timer so disk usage stays bounded.
    """

    _instance: Optional[TemplateImagePool] = None
    _cls_lock: threading.Lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> TemplateImagePool:
        if cls._instance is None:
            with cls._cls_lock:
                if cls._instance is None:
                    inst = cls()
                    inst.start_gc_timer()
                    cls._instance = inst
        return cls._instance

    def __init__(self) -> None:
        # key -> built template image tag
        self._templates: dict[str, str] = {}
        # key -> last access timestamp (unix seconds), used by GC
        self._last_used: dict[str, float] = {}
        # protects template maps and stats
        self._lock = threading.Lock()
        # per-key build locks prevent duplicate concurrent builds
        self._build_locks: dict[str, threading.Lock] = {}
        # periodic GC timer handle
        self._gc_timer: Optional[threading.Timer] = None
        # how often stale template GC runs
        self._gc_interval: int = _int_env("TEMPLATE_GC_INTERVAL", _DEFAULT_GC_INTERVAL)
        # templates idle longer than this are eligible for eviction
        self._gc_max_age: int = _int_env("TEMPLATE_GC_MAX_AGE", _DEFAULT_GC_MAX_AGE)
        # observability counter for total evictions over process lifetime
        self._total_evicted: int = 0
        # startup guard: evict stale template lineage when base image changes
        self._evict_mismatched_templates_for_current_base()

    @staticmethod
    def _template_key(
        pip_dependencies: list[str],
        *,
        data_content_hash: Optional[str] = None,
        base_identity: Optional[str] = None,
    ) -> str:
        normalized = sorted(dep.strip().lower() for dep in pip_dependencies if dep.strip())
        if not normalized and not data_content_hash:
            return "base"
        parts = list(normalized)
        if data_content_hash:
            parts.append(f"__data__={data_content_hash}")
        if base_identity:
            parts.append(f"__base__={base_identity.strip()}")
        digest = hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]
        return f"phase-{digest}"

    @staticmethod
    def _resolve_base_image_identity(base_image: str) -> str:
        """Return immutable image identity when available, fallback to input string."""
        try:
            import docker as docker_lib

            img = docker_lib.from_env().images.get(base_image)
            image_id = str(getattr(img, "id", "") or "").strip()
            if image_id:
                return image_id
        except Exception:
            pass
        return str(base_image).strip()

    def _evict_mismatched_templates_for_current_base(self) -> int:
        base_image = os.getenv("SANDBOX_DOCKER_IMAGE", "genesis-sandbox-base:latest")
        current_base_identity = self._resolve_base_image_identity(base_image)
        removed = 0
        try:
            import docker as docker_lib

            client = docker_lib.from_env()
            for image in client.images.list(name=_TEMPLATE_REPO):
                labels = getattr(image, "labels", None) or {}
                template_base = str(labels.get(_TEMPLATE_BASE_ID_LABEL, "") or "").strip()
                # Legacy unlabeled templates are considered stale and are removed.
                if not template_base or template_base != current_base_identity:
                    try:
                        client.images.remove(image.id, force=True)
                        removed += 1
                    except Exception as exc:
                        logger.warning(
                            "template pool startup cleanup: failed to remove %s: %s",
                            getattr(image, "id", "<unknown>"),
                            exc,
                        )
        except Exception as exc:
            logger.warning("template pool startup cleanup error: %s", exc)
            return 0

        if removed:
            logger.info(
                "template pool startup cleanup: removed %d mismatched templates",
                removed,
            )
        return removed

    def _touch(self, key: str) -> None:
        """Update last-used timestamp (must be called under ``_lock``)."""
        self._last_used[key] = time.time()

    def get_or_create(
        self,
        pip_dependencies: list[str],
        deps_timeout_seconds: int = 120,
        *,
        data_files: Optional[dict[str, bytes]] = None,
        data_content_hash: Optional[str] = None,
    ) -> str:
        base_image = os.getenv(
            "SANDBOX_DOCKER_IMAGE", "genesis-sandbox-base:latest",
        )
        base_identity = self._resolve_base_image_identity(base_image)
        key = self._template_key(
            pip_dependencies,
            data_content_hash=data_content_hash,
            base_identity=base_identity,
        )

        with self._lock:
            if key in self._templates:
                self._touch(key)
                return self._templates[key]
            if key not in self._build_locks:
                self._build_locks[key] = threading.Lock()
            build_lock = self._build_locks[key]

        with build_lock:
            with self._lock:
                if key in self._templates:
                    self._touch(key)
                    return self._templates[key]

            if key == "base":
                with self._lock:
                    self._templates[key] = base_image
                    self._touch(key)
                logger.info("template pool: no phase deps, using base image %s", base_image)
                return base_image

            image_tag = f"genesis-phase-template:{key}"
            self._build_template(
                base_image,
                image_tag,
                pip_dependencies,
                deps_timeout_seconds,
                data_files=data_files,
            )

            with self._lock:
                self._templates[key] = image_tag
                self._touch(key)
            logger.info("template pool: built %s for key=%s", image_tag, key)
            return image_tag

    @staticmethod
    def _build_template(
        base_image: str,
        image_tag: str,
        pip_dependencies: list[str],
        deps_timeout_seconds: int,
        *,
        data_files: Optional[dict[str, bytes]] = None,
    ) -> None:
        import shlex
        import docker as docker_lib

        client = docker_lib.from_env()
        run_kw: dict[str, Any] = {
            "image": base_image,
            "command": _keepalive_cmd(deps_timeout_seconds + 30),
            "detach": True,
            "stdin_open": True,
            "tty": False,
        }
        pip_env = pip_index_env_from_host()
        if pip_env:
            run_kw["environment"] = pip_env
        container = client.containers.run(**run_kw)
        try:
            if pip_dependencies:
                install_args = " ".join(shlex.quote(d) for d in pip_dependencies)
                cmd = (
                    "bash -lc '"
                    "cd /workspace && source .venv/bin/activate && "
                    f"uv pip install -q {install_args}'"
                )
                exit_code, output = container.exec_run(cmd, demux=True)
                if exit_code != 0:
                    stderr_text = ""
                    if isinstance(output, tuple) and output[1]:
                        stderr_text = output[1].decode("utf-8", "replace")[:500]
                    raise RuntimeError(
                        f"template build failed (exit {exit_code}): {stderr_text}"
                    )

            if data_files:
                buf = io.BytesIO()
                with tarfile.open(fileobj=buf, mode="w") as tar:
                    for path, data in data_files.items():
                        info = tarfile.TarInfo(name=f"workspace/{path}")
                        info.size = len(data)
                        tar.addfile(info, io.BytesIO(data))
                buf.seek(0)
                container.put_archive("/", buf)
                logger.info(
                    "template build: wrote %d data files into image",
                    len(data_files),
                )

            base_identity = TemplateImagePool._resolve_base_image_identity(base_image)
            container.commit(
                repository=image_tag.split(":")[0],
                tag=image_tag.split(":")[-1],
                changes=[f"LABEL {_TEMPLATE_BASE_ID_LABEL}={base_identity}"],
            )
        finally:
            try:
                container.kill()
            except Exception:
                pass
            try:
                container.remove(force=True)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Garbage collection
    # ------------------------------------------------------------------

    def evict_stale(self, max_age_seconds: Optional[int] = None) -> int:
        """Remove template images that haven't been used recently.

        Returns the number of evicted entries.
        """
        max_age = max_age_seconds if max_age_seconds is not None else self._gc_max_age
        now = time.time()

        with self._lock:
            stale_keys = [
                k for k, ts in self._last_used.items()
                if k != "base" and (now - ts) > max_age
            ]
            if not stale_keys:
                return 0
            stale_items = [(k, self._templates[k]) for k in stale_keys if k in self._templates]

        evicted = 0
        for key, image_tag in stale_items:
            try:
                import docker as docker_lib
                docker_lib.from_env().images.remove(image_tag, force=True)
                logger.info("template pool GC: removed image %s (key=%s)", image_tag, key)
            except Exception as exc:
                logger.warning("template pool GC: failed to remove %s: %s", image_tag, exc)

            with self._lock:
                self._templates.pop(key, None)
                self._last_used.pop(key, None)
                self._build_locks.pop(key, None)
            evicted += 1

        self._total_evicted += evicted
        logger.info("template pool GC: evicted %d stale templates", evicted)
        return evicted

    def start_gc_timer(self, interval_seconds: Optional[int] = None) -> None:
        """Start the periodic GC daemon timer."""
        interval = interval_seconds if interval_seconds is not None else self._gc_interval
        if interval <= 0:
            return

        def _schedule_next_gc() -> None:
            self._gc_timer = threading.Timer(interval, _gc_loop)
            self._gc_timer.daemon = True
            self._gc_timer.start()

        def _gc_loop() -> None:
            try:
                self.evict_stale()
            except Exception as exc:
                logger.warning("template pool GC timer error: %s", exc)
            _schedule_next_gc()

        _schedule_next_gc()

    def stop_gc_timer(self) -> None:
        if self._gc_timer is not None:
            self._gc_timer.cancel()
            self._gc_timer = None

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "templates": dict(self._templates),
                "last_used": dict(self._last_used),
                "total_evicted": self._total_evicted,
            }


class SandboxBusyError(Exception):
    pass


class SandboxManager:
    _instance: Optional["SandboxManager"] = None
    _lock: threading.Lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "SandboxManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        cfg = get_config()

        self.max_concurrent: int = cfg.max_workers

        self._active_sandboxes: dict[str, Sandbox] = {}
        self._lock = threading.Lock()
        self._semaphore = threading.Semaphore(self.max_concurrent)
        self._stats = {
            "total_created": 0,
            "total_destroyed": 0,
            "current_active": 0,
            "max_concurrent": self.max_concurrent,
        }

        logger.info("Sandbox manager started: max_concurrent=%d", self.max_concurrent)

    def create(
        self,
        sandbox_timeout: int,
        template_id: Optional[str] = None,
        cpu_count: Optional[int] = None,
        memory_mb: Optional[int] = None,
    ) -> Sandbox:
        acquired = self._semaphore.acquire(timeout=60)
        if not acquired:
            logger.warning("Timed out acquiring sandbox: concurrency limit reached")
            raise SandboxBusyError("Sandbox is busy, please retry later")

        sandbox: Optional[Sandbox] = None
        success = False
        try:
            sandbox = create_docker_sandbox(
                image=template_id,
                timeout=sandbox_timeout,
                cpu_count=cpu_count,
                memory_mb=memory_mb,
            )

            with self._lock:
                self._active_sandboxes[sandbox.id] = sandbox
                self._stats["total_created"] += 1
                self._stats["current_active"] = len(self._active_sandboxes)

            logger.info("Sandbox created: %s", sandbox.id)
            success = True
            return sandbox

        except Exception as e:
            logger.error("Failed to create sandbox: %s", e)
            raise RuntimeError(f"Failed to create sandbox: {e}") from e
        finally:
            if not success:
                if sandbox:
                    try:
                        sandbox.kill()
                    except Exception:
                        pass
                self._semaphore.release()

    def destroy(self, sandbox: Sandbox) -> None:
        sandbox_id = sandbox.id

        try:
            sandbox.close()
        except Exception as e:
            logger.warning("Sandbox destroy exception: %s", e)

        with self._lock:
            self._active_sandboxes.pop(sandbox_id, None)
            self._stats["total_destroyed"] += 1
            self._stats["current_active"] = len(self._active_sandboxes)

        self._semaphore.release()

        logger.info("Sandbox destroyed: %s", sandbox_id)

    def get_stats(self) -> dict:
        with self._lock:
            return dict(self._stats)

    def shutdown(self) -> None:
        with self._lock:
            sandboxes = list(self._active_sandboxes.values())

        for sandbox in sandboxes:
            try:
                self.destroy(sandbox)
            except Exception as e:
                logger.warning("Sandbox shutdown exception: %s", e)

        logger.info("Sandbox manager stopped")


def create_sandbox(
    sandbox_timeout: int,
    template_id: Optional[str] = None,
    cpu_count: Optional[int] = None,
    memory_mb: Optional[int] = None,
) -> Sandbox:
    return SandboxManager.get_instance().create(
        sandbox_timeout=sandbox_timeout,
        template_id=template_id,
        cpu_count=cpu_count,
        memory_mb=memory_mb,
    )


def destroy_sandbox(sandbox: Sandbox) -> None:
    SandboxManager.get_instance().destroy(sandbox)


def get_sandbox_stats() -> dict:
    return SandboxManager.get_instance().get_stats()


def get_or_create_template(
    pip_dependencies: list[str],
    deps_timeout_seconds: int = 120,
    *,
    data_files: Optional[dict[str, bytes]] = None,
    data_content_hash: Optional[str] = None,
) -> str:
    return TemplateImagePool.get_instance().get_or_create(
        pip_dependencies=pip_dependencies,
        deps_timeout_seconds=deps_timeout_seconds,
        data_files=data_files,
        data_content_hash=data_content_hash,
    )

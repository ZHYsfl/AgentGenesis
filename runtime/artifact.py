"""Artifact download, extraction, and dependency filtering utilities."""

from __future__ import annotations

import hashlib
import io
import logging
from pathlib import Path
from typing import Optional
import zipfile

import requests

logger: logging.Logger = logging.getLogger(__name__)


def download_artifact(url: str, checksum: str, max_retries: int = 3) -> bytes:
    if not url:
        raise ValueError("artifact_url is required for dual sandbox")

    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, timeout=60)
            if 400 <= resp.status_code < 500:
                raise ValueError(f"Artifact download failed: HTTP {resp.status_code}")
            resp.raise_for_status()
            data = resp.content
            if checksum:
                digest = hashlib.sha256(data).hexdigest()
                if digest != checksum:
                    raise ValueError("Artifact checksum verification failed (SHA256 mismatch)")
            return data
        except ValueError:
            raise
        except Exception as exc:
            last_error = exc
            logger.warning(
                "Artifact download failed (attempt %s/%s): %s",
                attempt + 1,
                max_retries,
                exc,
            )
            if attempt < max_retries - 1:
                import time as _time

                _time.sleep(2**attempt)

    raise ValueError(
        f"Artifact download failed after {max_retries} retries: {last_error}"
    )


def extract_artifact(data: bytes) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for name in zf.namelist():
            if name.endswith("/"):
                continue
            normalized = name.replace("\\", "/")
            if ".." in Path(normalized).parts:
                continue
            files[normalized] = zf.read(name)
    return files


def resolve_entrypoint(config: object) -> str:
    artifact_entry = getattr(config, "artifact_entry", "")
    if artifact_entry:
        return str(artifact_entry)
    return "sandbox/run.py"


from ..models import extract_requirement_pkg_name as extract_requirement_pkg_name  # noqa: F401


def filter_requirements(requirements_text: str, allowed_packages: list[str]) -> str:
    if not allowed_packages:
        return requirements_text

    whitelist = {
        pkg.lower().replace("-", "_").replace(".", "_")
        for pkg in allowed_packages
    }

    filtered_lines: list[str] = []
    for line in requirements_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("-"):
            filtered_lines.append(line)
            continue

        pkg_name = extract_requirement_pkg_name(stripped)
        if not pkg_name:
            filtered_lines.append(line)
            continue

        if pkg_name in whitelist:
            filtered_lines.append(line)
        else:
            filtered_lines.append(
                f"# [BLOCKED] {line}  # not in allowed_packages whitelist"
            )
            logger.warning(
                "Package '%s' blocked by whitelist (allowed: %s)",
                pkg_name,
                ", ".join(sorted(allowed_packages)),
            )

    return "\n".join(filtered_lines)

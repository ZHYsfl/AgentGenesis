"""Problem registry and sync/revision flows for phase definitions."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import zipfile
from pathlib import Path
from typing import Optional

import requests
from requests import Response

from .models import PhaseConfig, ProblemConfig
from .config import get_config, ClientMode

logger: logging.Logger = logging.getLogger(__name__)


_BINARY_SUFFIXES = frozenset({
    ".zip", ".gz", ".tar", ".bz2", ".xz", ".7z", ".rar",
    ".db", ".sqlite", ".sqlite3",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".svg",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".exe", ".dll", ".so", ".dylib", ".o", ".a", ".whl", ".egg",
    ".pyc", ".pyo", ".class", ".jar",
    ".mp3", ".mp4", ".wav", ".avi", ".mov", ".flv", ".mkv",
    ".bin", ".dat", ".pickle", ".pkl", ".npy", ".npz", ".h5", ".hdf5",
    ".parquet", ".arrow", ".feather", ".avro",
    ".protobuf", ".pb",
})


def _is_binary_file(path: Path) -> bool:
    return path.suffix.lower() in _BINARY_SUFFIXES


def build_artifact_from_dir(dir_path: Path, base_path: Path | None = None) -> str:
    if not dir_path.exists() or not dir_path.is_dir():
        raise FileNotFoundError(f"Directory does not exist or is not a directory: {dir_path}")
    base = base_path if base_path is not None else dir_path.parent
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(dir_path.rglob("*")):
            if path.is_file():
                rel = path.relative_to(base)
                arcname = str(rel).replace("\\", "/")
                if _is_binary_file(path):
                    zf.write(path, arcname=arcname)
                else:
                    data = path.read_bytes().replace(b"\r\n", b"\n")
                    zf.writestr(arcname, data)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def build_artifact_from_dirs(dir_paths: list[Path], base_path: Path) -> str:
    """Package multiple subdirectories into a single artifact ZIP.

    Each directory is walked recursively; paths in the archive are relative
    to *base_path*.  Useful when a problem needs to ship both ``sandbox/``
    and extra code directories (e.g. ``wolf_agent/``) in one artifact.
    """
    buf = io.BytesIO()
    seen: set[str] = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for dir_path in dir_paths:
            if not dir_path.exists() or not dir_path.is_dir():
                raise FileNotFoundError(
                    f"Directory does not exist or is not a directory: {dir_path}"
                )
            for path in sorted(dir_path.rglob("*")):
                if path.is_file():
                    rel = path.relative_to(base_path)
                    arcname = str(rel).replace("\\", "/")
                    if arcname in seen:
                        continue
                    seen.add(arcname)
                    if _is_binary_file(path):
                        zf.write(path, arcname=arcname)
                    else:
                        data = path.read_bytes().replace(b"\r\n", b"\n")
                        zf.writestr(arcname, data)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def compute_artifact_checksum(artifact_base64: str) -> str:
    if not artifact_base64:
        return ""
    try:
        data = base64.b64decode(artifact_base64)
        return hashlib.sha256(data).hexdigest()
    except Exception:
        return ""


def inject_visibility_manifest(artifact_base64: str, private_files: list[str]) -> str:
    if not artifact_base64:
        return artifact_base64
    raw = base64.b64decode(artifact_base64)
    src = zipfile.ZipFile(io.BytesIO(raw), "r")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            if info.filename == "visibility_manifest.json":
                continue
            dst.writestr(info, src.read(info.filename))
        manifest = {"private": list(private_files)}
        dst.writestr("visibility_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    src.close()
    return base64.b64encode(buf.getvalue()).decode("utf-8")


class ProblemRegistry:
    _instance: Optional["ProblemRegistry"] = None
    
    backend_url: str
    api_key: str
    mode: ClientMode
    _problems: dict[str, ProblemConfig]
    
    def __init__(
        self,
        mode: ClientMode,
        api_key: str,
        backend_url: Optional[str] = None,
    ) -> None:
        self.mode = mode
        self.api_key = api_key
        self.backend_url = backend_url if backend_url is not None else get_config().backend_url
        self._problems = {}
        logger.info(f"ProblemRegistry initialized: mode={self.mode.value}, backend={self.backend_url}")
    
    @classmethod
    def init(cls, mode: ClientMode, api_key: str, backend_url: Optional[str] = None) -> "ProblemRegistry":
        if cls._instance is not None:
            raise RuntimeError("ProblemRegistry has already been initialized")
        cls._instance = cls(mode=mode, api_key=api_key, backend_url=backend_url)
        return cls._instance
    
    @classmethod
    def instance(cls) -> "ProblemRegistry":
        if cls._instance is None:
            raise RuntimeError("ProblemRegistry is not initialized; call init(mode, api_key) first")
        return cls._instance
    
    def register(self, problem: ProblemConfig) -> None:
        if problem.title in self._problems:
            logger.warning(f"Problem '{problem.title}' already exists and will be overwritten")
        
        self._problems[problem.title] = problem
        logger.info(f"Registered problem: '{problem.title}' (slug={problem.slug}), {len(problem.phases)} phases")
    
    def get(self, title: str) -> Optional[ProblemConfig]:
        return self._problems.get(title)
    
    def get_phase(self, title: str, phase_order: int = 1) -> Optional[PhaseConfig]:
        problem = self._problems.get(title)
        return problem.get_phase(phase_order) if problem else None
    
    def list_all(self) -> list[str]:
        return list(self._problems.keys())

    def _get_sync_endpoint(self) -> str:
        if self.mode == ClientMode.USER:
            return f"{self.backend_url}/api/v1/problems/register"
        else:
            return f"{self.backend_url}/internal/register-problem"
    
    def _get_sync_headers(self) -> dict[str, str]:
        if self.mode == ClientMode.USER:
            return {
                "X-API-Key": self.api_key,
                "Content-Type": "application/json",
            }
        else:
            return {
                "X-Internal-Key": self.api_key,
                "Content-Type": "application/json",
            }
    
    def _get_existing_checksum(self, title: str, phase_order: int) -> str:
        if self.mode != ClientMode.WORKER:
            return ""
        
        try:
            resp: Response = requests.post(
                f"{self.backend_url}/internal/get-phase-artifact",
                headers={"X-Internal-Key": self.api_key, "Content-Type": "application/json"},
                json={"title": title, "phase_order": phase_order},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                return data.get("artifact_checksum", "")
        except Exception as e:
            logger.debug(f"Failed to query existing checksum: {e}")
        return ""
    
    def _phase_exists(self, title: str, phase_order: int) -> bool:
        if self.mode != ClientMode.WORKER:
            return False
        
        try:
            resp: Response = requests.post(
                f"{self.backend_url}/internal/get-phase-artifact",
                headers={"X-Internal-Key": self.api_key, "Content-Type": "application/json"},
                json={"title": title, "phase_order": phase_order},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                return data.get("exists", False)
        except Exception as e:
            logger.debug(f"Failed to query whether phase exists: {e}")
        return False
    
    def _prepare_phase_data(self, problem: ProblemConfig, phase: PhaseConfig) -> dict:
        phase_data = phase.model_dump()

        artifact_b64 = phase_data.get("artifact_base64", "")
        private_files = phase_data.pop("private_files", None)
        if artifact_b64 and private_files is not None:
            phase_data["artifact_base64"] = inject_visibility_manifest(artifact_b64, private_files)
            artifact_b64 = phase_data["artifact_base64"]

        if artifact_b64:
            local_checksum = compute_artifact_checksum(artifact_b64)
            existing_checksum = self._get_existing_checksum(problem.title, phase.phase_order)
            if local_checksum and local_checksum == existing_checksum:
                logger.info(f"Artifact unchanged, skipping upload (checksum={local_checksum[:16]}...)")
                del phase_data["artifact_base64"]
                phase_data["artifact_checksum"] = local_checksum
        
        return phase_data
    
    def _register_phase(
        self,
        problem: ProblemConfig,
        phase: PhaseConfig,
        *,
        _allow_fallback: bool = True,
    ) -> bool:
        endpoint: str = self._get_sync_endpoint()
        headers: dict[str, str] = self._get_sync_headers()
        phase_data = self._prepare_phase_data(problem, phase)
        
        try:
            payload: dict = {
                "title": problem.title,
                "overview": problem.overview,
                "background": problem.background,
                "level": problem.level,
                "language": problem.language,
                "is_public": problem.is_public,
                "data_public": problem.data_public,
                "phase_config": phase_data,
            }
            if problem.gitattributes:
                payload["gitattributes"] = problem.gitattributes
            resp: Response = requests.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=90,
            )
            
            if resp.status_code == 200:
                if self.mode == ClientMode.WORKER:
                    logger.info(f"Published: '{problem.title}' (slug={problem.slug}) phase {phase.phase_order}")
                else:
                    logger.info(f"Submitted for review: '{problem.title}' (slug={problem.slug}) phase {phase.phase_order}")
                return True
            if _allow_fallback and resp.status_code == 400:
                body = resp.text.lower()
                code = None
                try:
                    code = (resp.json() or {}).get("code")
                except Exception:
                    code = None
                if "already published" in body or code == 41001:
                    logger.info(
                        f"Problem already exists, automatically switching to revision flow: "
                        f"'{problem.title}' phase {phase.phase_order}"
                    )
                    return self._create_revision(problem, phase)
            
            logger.error(f"Registration failed: {resp.status_code} - {resp.text}")
            return False
                
        except Exception as e:
            logger.exception(f"Registration exception: {e}")
            return False
    
    def _create_revision(
        self,
        problem: ProblemConfig,
        phase: PhaseConfig,
        *,
        title: Optional[str] = None,
        description: Optional[str] = None,
    ) -> bool:
        slug = problem.slug
        phase_data = self._prepare_phase_data(problem, phase)
        
        if self.mode == ClientMode.WORKER:
            endpoint = f"{self.backend_url}/internal/problems/s/{slug}/revisions"
            headers: dict[str, str] = {
                "X-Internal-Key": self.api_key,
                "Content-Type": "application/json",
            }
        else:
            endpoint = f"{self.backend_url}/api/v1/problems/s/{slug}/revisions"
            headers = {
                "X-API-Key": self.api_key,
                "Content-Type": "application/json",
            }
        
        try:
            payload: dict = {
                "title": title or f"Update {problem.title} phase {phase.phase_order}",
                "description": description or f"Automated update from SDK",
                "phase_config": phase_data,
                "phase_order": phase.phase_order,
            }
            problem_meta: dict[str, str] = {}
            if problem.level:
                problem_meta["level"] = problem.level
            if problem.gitattributes:
                problem_meta["gitattributes"] = problem.gitattributes
            if problem.overview:
                problem_meta["overview"] = problem.overview
            if problem.background:
                problem_meta["background"] = problem.background
            problem_meta["is_public"] = problem.is_public
            problem_meta["data_public"] = problem.data_public
            if problem_meta:
                payload["problem_meta"] = problem_meta
            resp: Response = requests.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=90,
            )
            
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                auto_merged = data.get("auto_merged", False)
                if auto_merged:
                    logger.info(f"Auto-merged: '{problem.title}' (slug={slug}) phase {phase.phase_order}")
                else:
                    logger.info(f"Revision created and pending review: '{problem.title}' (slug={slug}) phase {phase.phase_order}")
                return True
            else:
                logger.error(f"Revision creation failed: {resp.status_code} - {resp.text}")
                return False
                
        except Exception as e:
            logger.exception(f"Revision creation exception: {e}")
            return False

    def create_revision(
        self,
        problem: ProblemConfig,
        phase_order: int = 1,
        *,
        title: Optional[str] = None,
        description: Optional[str] = None,
    ) -> bool:
        phase = problem.get_phase(phase_order)
        if phase is None:
            logger.error(f"Revision creation failed: phase does not exist (title={problem.title}, phase_order={phase_order})")
            return False
        return self._create_revision(problem, phase, title=title, description=description)
    
    def sync_to_db(
        self,
        problem: ProblemConfig,
        *,
        revision_title: Optional[str] = None,
        revision_description: Optional[str] = None,
    ) -> dict[int, bool]:
        results: dict[int, bool] = {}
        
        for phase in problem.phases:
            if self._phase_exists(problem.title, phase.phase_order):
                logger.info(f"Phase already published, using revision flow: '{problem.title}' phase {phase.phase_order}")
                results[phase.phase_order] = self._create_revision(
                    problem, phase, title=revision_title, description=revision_description,
                )
            else:
                results[phase.phase_order] = self._register_phase(problem, phase)
        
        return results
    
    def sync_all(self) -> dict[str, dict[int, bool]]:
        return {title: self.sync_to_db(p) for title, p in self._problems.items()}

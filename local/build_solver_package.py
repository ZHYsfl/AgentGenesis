from __future__ import annotations

import argparse
import base64
import io
import json
import posixpath
import sys
import zipfile
from pathlib import Path
from typing import Any

DEFAULT_GITATTRIBUTES = (
    "# Binary files — stored in git for version control\n"
    "*.zip binary\n*.db binary\n*.sqlite binary\n"
    "*.sqlite3 binary\n*.tar.gz binary\n*.gz binary\n"
)

_MANIFEST = "visibility_manifest.json"


def _is_private(artifact_path: str, private_set: set[str]) -> bool:
    clean = posixpath.normpath(artifact_path.lstrip("/"))
    for p in private_set:
        cp = posixpath.normpath(p.lstrip("/"))
        if clean == cp or clean.startswith(cp + "/"):
            return True
    return False


def _safe_write(zf: zipfile.ZipFile, name: str, data: bytes | str) -> None:
    clean = posixpath.normpath(name.lstrip("/"))
    if ".." in clean.split("/"):
        raise ValueError(f"invalid zip entry: {name}")
    zf.writestr(name, data)


def _read_artifact_files(artifact_b64: str) -> dict[str, bytes]:
    raw = base64.b64decode(artifact_b64)
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        return {
            info.filename: zf.read(info.filename)
            for info in zf.infolist()
            if not info.is_dir()
        }


def build_solver_package_zip(problem_dir: Path, phase_order: int) -> bytes:
    from agent_genesis.local.solver_package_export import export_problem

    exported = export_problem(problem_dir, phase_order)
    prob: dict[str, Any] = exported["problem"]
    phase: dict[str, Any] = exported["phase"]

    language = prob.get("language", "en")
    artifact_b64: str = phase.get("artifact_base64", "")
    if not artifact_b64:
        raise RuntimeError("phase artifact_base64 is empty")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        _safe_write(zf, "problem.json", json.dumps({
            "title":       prob.get("title", ""),
            "level":       prob.get("level", "Medium"),
            "overview":    prob.get("overview", ""),
            "language":    language,
            "is_public":   prob.get("is_public", False),
            "data_public": prob.get("data_public", False),
        }, ensure_ascii=False, indent=2))

        gitattributes = (prob.get("gitattributes") or "").strip()
        _safe_write(zf, ".gitattributes", gitattributes or DEFAULT_GITATTRIBUTES)

        _safe_write(zf, f"phases/{phase_order}/phase.json", json.dumps({
            "phase_name":        phase.get("phase_name", ""),
            "phase_type":        phase.get("phase_type", "agent"),
            "level":             phase.get("phase_level", "Easy"),
            "max_code_size":     phase.get("max_code_size"),
            "artifact_checksum": phase.get("artifact_checksum", ""),
            "artifact_size":     phase.get("artifact_size"),
        }, ensure_ascii=False, indent=2))

        eval_config = {k: v for k, v in phase.items()
                       if k not in ("description", "starter_code", "artifact_base64", "private_files")}
        _safe_write(zf, f"phases/{phase_order}/evaluation_config.json",
                    json.dumps(eval_config, ensure_ascii=False, indent=2))

        _safe_write(zf, f"phases/{phase_order}/content/{language}/description.md",
                    phase.get("description", ""))
        _safe_write(zf, f"phases/{phase_order}/content/{language}/starter_code.py",
                    phase.get("starter_code", ""))
        _safe_write(zf, f"overview/{language}/overview.md",   prob.get("overview", ""))
        _safe_write(zf, f"background/{language}/background.md", prob.get("background", ""))

        artifact_files = _read_artifact_files(artifact_b64)
        if _MANIFEST not in artifact_files:
            raise RuntimeError("artifact is missing visibility_manifest.json")
        manifest = json.loads(artifact_files[_MANIFEST])
        private_set: set[str] = set(manifest.get("private", []))

        for name in sorted(artifact_files):
            if name != _MANIFEST and _is_private(name, private_set):
                continue
            _safe_write(zf, "artifact/" + name, artifact_files[name])

    return buf.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a solver-view zip package from a local problem directory")
    parser.add_argument("--problem-dir", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--phase", type=int, default=1)
    args = parser.parse_args()

    problem_dir = Path(args.problem_dir).resolve()
    if not problem_dir.is_dir():
        raise SystemExit(f"problem dir does not exist: {problem_dir}")
    if not (problem_dir / "register.py").is_file():
        raise SystemExit(f"register.py not found in: {problem_dir}")
    if args.phase < 1:
        raise SystemExit("--phase must be >= 1")

    out = Path(args.out).resolve()
    if not out.parent.is_dir():
        raise SystemExit(f"output directory does not exist: {out.parent}")

    data = build_solver_package_zip(problem_dir, args.phase)
    out.write_bytes(data)
    print(f"wrote {out} ({len(data)} bytes)")


if __name__ == "__main__":
    main()

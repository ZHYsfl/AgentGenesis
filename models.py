"""Data models for submissions, phases, and evaluation results."""

import re
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from enum import Enum


def extract_requirement_pkg_name(requirement_line: str) -> Optional[str]:
    """Extract normalized package name from a pip requirement string."""
    stripped = str(requirement_line).strip()
    if not stripped or stripped.startswith("#") or stripped.startswith("-"):
        return None
    match = re.match(r"^([A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?)", stripped)
    if not match:
        return None
    return match.group(1).lower().replace("-", "_").replace(".", "_")


def slugify(title: str) -> str:
    slug = title.lower()
    slug = slug.replace(" ", "-").replace("_", "-")
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-")
    return slug or "untitled"


class CaseStatus(str, Enum):
    PENDING: str = "pending"
    RUNNING: str = "running"
    PASSED: str = "passed"
    FAILED: str = "failed"
    SKIPPED: str = "skipped"
    TLE: str = "tle"
    MLE: str = "mle"
    ERROR: str = "error"

    def to_backend(self) -> str:
        status_map = {
            "tle": "failed",
            "mle": "failed",
            "error": "failed",
        }
        return status_map.get(self.value, self.value)


class PhaseStatus(str, Enum):
    PENDING: str = "pending"
    RUNNING: str = "running"
    SUCCESS: str = "success"
    FAILED: str = "failed"
    ERROR: str = "error"


class RuntimeConfig(BaseModel):
    model_config: ConfigDict = ConfigDict(extra="allow")
    key_id: Optional[int] = None
    key_name: Optional[str] = None
    key_ids: list[int] = []

    @model_validator(mode="after")
    def normalize_key_ids(self) -> "RuntimeConfig":
        if not self.key_ids and self.key_id is not None:
            self.key_ids = [self.key_id]
        return self


class PhaseConfig(BaseModel):
    model_config: ConfigDict = ConfigDict(extra="allow")
    phase_name: str = ""
    phase_type: str = "agent"
    phase_order: int = 1
    phase_level: str = "Easy"
    max_code_size: int = 1000000
    description: str = ""
    starter_code: str = ""
    evaluator_module: str = ""
    evaluator_class: str = ""
    num_cases: int = 10
    min_passed_cases: Optional[int] = None  # Pass when passed_cases >= this; None = all must pass
    parallel_cases: int = 1
    sandbox_cpu_count: int = 0
    memory_limit_mb: int = 0
    sandbox_timeout: int = 400
    case_idle_timeout: int = 300
    user_deps_timeout: int = 120
    chmod_timeout: int = 10
    run_timeout: int = 180
    pip_dependencies: list[str] = []
    image_data_dirs: list[str] = []
    allowed_packages: list[str] = []
    artifact_url: str = ""
    artifact_checksum: str = ""
    artifact_size: int = 0
    artifact_entry: str = ""
    judge_envs: dict[str, str] = {}
    allow_user_key: bool = False
    artifact_base64: str = ""
    user_bridge: str = ""
    adapter_preset: str = ""
    solve_attr_name: str = "solve"
    private_files: Optional[list[str]] = None
    gateway_max_chars: int = 5000000
    gateway_max_requests: int = 1000
    gateway_ttl_minutes: int = 30
    gateway_allowed_models: list[str] = []

    @model_validator(mode="after")
    def validate_pip_deps_in_whitelist(self) -> "PhaseConfig":
        if not self.pip_dependencies or not self.allowed_packages:
            return self
        whitelist = {
            str(pkg).lower().replace("-", "_").replace(".", "_")
            for pkg in self.allowed_packages
            if str(pkg).strip()
        }
        blocked: list[str] = []
        for dep in self.pip_dependencies:
            pkg_name = extract_requirement_pkg_name(dep)
            if not pkg_name or pkg_name not in whitelist:
                blocked.append(dep)
        if blocked:
            raise ValueError(
                f"pip_dependencies contains packages not in allowed_packages: {', '.join(blocked)}"
            )
        return self


class ProblemConfig(BaseModel):
    title: str
    overview: str = ""
    background: str = ""
    level: str = "Medium"
    language: str = "en"
    is_public: bool = False
    data_public: bool = False
    gitattributes: str = ""
    phases: list[PhaseConfig] = []

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        if len(v) < 2 or len(v) > 200:
            raise ValueError("title length must be between 2 and 200")
        for ch in v:
            if ord(ch) < 0x20 or ord(ch) > 0x7E:
                raise ValueError("title must be English (ASCII printable characters only)")
        if not re.search(r"[a-zA-Z0-9]", v):
            raise ValueError("title must contain at least one letter or number")
        return v

    @field_validator("level")
    @classmethod
    def validate_level(cls, v: str) -> str:
        if v not in ("Easy", "Medium", "Hard"):
            raise ValueError("level must be Easy, Medium, or Hard")
        return v

    def get_phase(self, phase_order: int = 1) -> Optional[PhaseConfig]:
        for phase in self.phases:
            if phase.phase_order == phase_order:
                return phase
        return None

    @property
    def slug(self) -> str:
        return slugify(self.title)


class TestCase(BaseModel):
    model_config: ConfigDict = ConfigDict(extra="allow")
    case_index: int = 0
    input_data: Any = None
    expected_output: Any = None
    metadata: dict[str, Any] = {}


class CaseResult(BaseModel):
    case_index: int = 0
    status: CaseStatus = CaseStatus.PENDING
    score: int = 0
    time_used: int = 0
    memory_used: int = 0
    chars_used: int = 0
    requests_used: int = 0
    input_data: Any = None
    output_data: Any = None
    expected_output: Any = None
    error: Optional[str] = None
    logs: Optional[str] = None


class PhaseResult(BaseModel):
    status: PhaseStatus = PhaseStatus.PENDING
    score: int = 0
    total_cases: int = 0
    passed_cases: int = 0
    total_time: int = 0
    peak_memory: int = 0
    total_chars: int = 0
    total_requests: int = 0
    cases: list[CaseResult] = []
    error: Optional[str] = None
    traceback: Optional[str] = None

    def is_completed(self) -> bool:
        return self.status in (PhaseStatus.SUCCESS, PhaseStatus.FAILED)

    def is_all_passed(self) -> bool:
        return self.status == PhaseStatus.SUCCESS

    @property
    def pass_rate(self) -> float:
        if self.total_cases == 0:
            return 0.0
        return self.passed_cases / self.total_cases


class UserSubmission(BaseModel):
    submit_id: int
    user_id: int
    phase_id: int
    code_url: str
    code_files: dict[str, str] = {}
    phase_config: PhaseConfig
    runtime_config: RuntimeConfig = RuntimeConfig()
    language: str = "python"
    phase_type: str = "agent"
    created_at: str = ""
    code_checksum: str = ""

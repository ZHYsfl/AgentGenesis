"""Environment-driven global configuration for evaluation services."""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import ClassVar, Optional

from pydantic import BaseModel, ConfigDict
from dotenv import load_dotenv

_ROOT_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=_ROOT_ENV_FILE, override=False)


class ClientMode(str, Enum):
    WORKER = "worker"
    USER = "user"


class SystemConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    max_workers: int = 15
    max_case_parallelism: int = 5
    poll_interval: int = 2
    health_enabled: bool = True
    health_port: int = 8081
    backend_url: str = "http://localhost:8080"
    sandbox_gateway_url: str = ""
    internal_api_key: str = ""
    user_api_key: str = ""
    request_timeout: int = 30
    
    @classmethod
    def from_env(cls) -> "SystemConfig":
        def int_env(name: str, default: int) -> int:
            raw = os.getenv(name, "").strip()
            if raw == "":
                return default
            return int(raw)

        return cls(
            max_workers=int_env("MAX_WORKERS", 15),
            max_case_parallelism=int_env("MAX_CASE_PARALLELISM", 5),
            poll_interval=int_env("POLL_INTERVAL", 2),
            health_enabled=os.getenv("HEALTH_ENABLED", "true").lower() == "true",
            health_port=int_env("HEALTH_PORT", 8081),
            backend_url=os.getenv("BACKEND_URL", "http://localhost:8080"),
            sandbox_gateway_url=os.getenv("SANDBOX_GATEWAY_URL", ""),
            internal_api_key=os.getenv("INTERNAL_API_KEY", ""),
            user_api_key=os.getenv("AGENT_GENESIS_API_KEY", ""),
            request_timeout=int_env("REQUEST_TIMEOUT", 30),
        )
    
    _instance: ClassVar[Optional["SystemConfig"]] = None
    
    @classmethod
    def get(cls) -> "SystemConfig":
        if cls._instance is None:
            cls._instance = cls.from_env()
        return cls._instance
    
    @classmethod
    def reset(cls) -> None:
        cls._instance = None
    
    @classmethod
    def override(cls, **kwargs) -> "SystemConfig":
        current = cls.get()
        cls._instance = current.model_copy(update=kwargs)
        return cls._instance

def get_config() -> SystemConfig:
    return SystemConfig.get()

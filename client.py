"""HTTP client for backend evaluation and revision APIs."""

from __future__ import annotations

import io
import json
import zipfile
import logging
from typing import Optional

import requests
from requests import Response

from .models import (
    PhaseConfig,
    RuntimeConfig,
    PhaseResult,
    CaseResult,
    UserSubmission,
    PhaseStatus,
    slugify,
)
from .config import get_config

logger: logging.Logger = logging.getLogger(__name__)


class EvaluationClient:
    base_url: str
    api_key: str
    timeout: int
    _headers: dict[str, str]
    
    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> None:
        cfg = get_config()
        
        self.base_url = base_url if base_url is not None else cfg.backend_url
        self.api_key = api_key if api_key is not None else cfg.internal_api_key
        self.timeout = timeout if timeout is not None else cfg.request_timeout

        if not self.api_key:
            raise ValueError("Missing INTERNAL_API_KEY: set INTERNAL_API_KEY for worker /internal/* endpoints")
        
        self._headers = {
            "X-Internal-Key": self.api_key,
            "Content-Type": "application/json",
        }
        user_key = cfg.user_api_key
        if user_key:
            self._api_headers = {
                "X-API-Key": user_key,
                "Content-Type": "application/json",
            }
        else:
            self._api_headers = {
                "Content-Type": "application/json",
            }
    
    @staticmethod
    def _slugify(title: str) -> str:
        return slugify(title)

    def get_pending_submissions(self, limit: int = 10) -> list[UserSubmission]:
        try:
            resp: Response = requests.post(
                f"{self.base_url}/internal/pending-submissions",
                headers=self._headers,
                json={"limit": limit},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            
            data: dict = resp.json().get("data", {})
            submissions_raw: list[dict] = data.get("submissions", [])
            
            result: list[UserSubmission] = []
            for sub in submissions_raw:
                try:
                    submission: UserSubmission = self._parse_submission(sub)
                    result.append(submission)
                except Exception as e:
                    submit_id: int = sub.get("submit_id", 0)
                    logger.error(f"Failed to parse submission {submit_id}: {type(e).__name__}: {e}")
                    continue
            
            return result
            
        except requests.RequestException as e:
            logger.error(f"Failed to fetch pending submissions: {e}")
            return []
    
    def _parse_submission(self, raw: dict) -> UserSubmission:
        config_dict: dict = raw.get("phase_config") or {}
        if isinstance(config_dict, str):
            config_dict = json.loads(config_dict)
        
        runtime_dict: dict = raw.get("runtime_config") or {}
        if isinstance(runtime_dict, str):
            runtime_dict = json.loads(runtime_dict)
        
        return UserSubmission(
            submit_id=raw["submit_id"],
            user_id=raw["user_id"],
            phase_id=raw["phase_id"],
            code_url=raw.get("code_url", ""),
            code_checksum=raw.get("code_checksum", ""),
            phase_config=PhaseConfig(**config_dict),
            runtime_config=RuntimeConfig(**runtime_dict),
            language=raw.get("language", "python"),
            phase_type=raw.get("phase_type", "agent"),
        )
    
    def claim_submission(self, submit_id: int) -> bool:
        try:
            resp: Response = requests.post(
                f"{self.base_url}/internal/claim-submission",
                headers=self._headers,
                json={"submit_id": submit_id},
                timeout=self.timeout,
            )
            return resp.status_code == 200
        except requests.RequestException as e:
            logger.error(f"Failed to claim submission {submit_id}: {e}")
            return False
    
    def unclaim_submission(self, submit_id: int) -> bool:
        try:
            resp: Response = requests.post(
                f"{self.base_url}/internal/unclaim-submission",
                headers=self._headers,
                json={"submit_id": submit_id},
                timeout=self.timeout,
            )
            return resp.status_code == 200
        except requests.RequestException as e:
            logger.error(f"Failed to unclaim submission {submit_id}: {e}")
            return False
    
    def download_code(
        self,
        signed_url: str,
        max_retries: int = 3,
        expected_checksum: str = "",
    ) -> dict[str, str]:
        last_error: Exception | None = None

        timeout: int = 30
        try:
            head_resp: Response = requests.head(signed_url, timeout=10)
            content_length: int = int(head_resp.headers.get("Content-Length", 0))
            if content_length > 0:
                timeout = min(300, max(30, 30 + (content_length // (512 * 1024))))
        except Exception:
            pass
        
        for attempt in range(max_retries):
            try:
                resp: Response = requests.get(signed_url, timeout=timeout)
                if 400 <= resp.status_code < 500:
                    logger.error(f"Code download failed: HTTP {resp.status_code}")
                    return {}
                
                resp.raise_for_status()
                content: bytes = resp.content
                if expected_checksum:
                    import hashlib
                    actual_checksum: str = hashlib.sha256(content).hexdigest()
                    if actual_checksum != expected_checksum:
                        logger.error(
                            f"Code checksum mismatch: expected={expected_checksum[:16]}..., "
                            f"actual={actual_checksum[:16]}..."
                        )
                        return {}
                
                return self._extract_code(content)
                
            except requests.Timeout as e:
                last_error = e
                logger.warning(f"Code download timeout (attempt {attempt + 1}/{max_retries})")
            except requests.ConnectionError as e:
                last_error = e
                logger.warning(f"Code download connection error (attempt {attempt + 1}/{max_retries}): {e}")
            except requests.HTTPError as e:
                if hasattr(e, 'response') and e.response is not None and e.response.status_code >= 500:
                    last_error = e
                    logger.warning(f"Code download server error (attempt {attempt + 1}/{max_retries}): {e}")
                else:
                    logger.error(f"Code download failed: {e}")
                    return {}
            except Exception as e:
                logger.error(f"Code download failed: {e}")
                return {}
            
            if attempt < max_retries - 1:
                import time
                wait_time = 2 ** attempt
                time.sleep(wait_time)
        
        logger.error(f"Code download failed after {max_retries} retries: {last_error}")
        return {}
    
    def _extract_code(self, content: bytes) -> dict[str, str]:
        try:
            files: dict[str, str] = {}
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                for name in zf.namelist():
                    if name.endswith('/'):
                        continue
                    normalized: str = name.replace('\\', '/')
                    files[normalized] = zf.read(name).decode('utf-8')
            return files
        except zipfile.BadZipFile:
            return {"solution.py": content.decode('utf-8')}

    def report_case_status(
        self,
        submit_id: int,
        case_index: int,
        status: str,
        case_id: int | None = None,
    ) -> bool:
        _BACKEND_CASE = {"tle": "failed", "mle": "failed", "error": "failed"}
        backend_status = _BACKEND_CASE.get(status, status)
        
        payload: dict = {
            "submit_id": submit_id,
            "type": "case",
            "case_index": case_index,
            "case_status": backend_status,
        }
        if case_id is not None:
            payload["case_id"] = case_id

        try:
            resp: Response = requests.post(
                f"{self.base_url}/internal/eval-update",
                headers=self._headers,
                json=payload,
                timeout=self.timeout,
            )
            return resp.status_code == 200
        except requests.RequestException:
            return False
    
    def report_result(self, submit_id: int, result: PhaseResult, max_retries: int = 3) -> bool:
        if result.status in (PhaseStatus.SUCCESS, PhaseStatus.FAILED):
            status = result.status.value
        else:
            status = "failed"
        
        payload: dict = {
            "submit_id": submit_id,
            "type": "complete",
            "status": status,
            "score": result.score,
            "passed_cases": result.passed_cases,
            "total_cases": result.total_cases,
            "total_time": result.total_time,
            "peak_memory": result.peak_memory,
            "total_chars": result.total_chars,
            "total_requests": result.total_requests,
            "error_message": result.error,
        }
        
        last_error: Exception | None = None
        for attempt in range(max_retries):
            try:
                resp: Response = requests.post(
                    f"{self.base_url}/internal/eval-update",
                    headers=self._headers,
                    json=payload,
                    timeout=self.timeout,
                )
                
                if resp.status_code == 200:
                    logger.info(
                        f"Submission {submit_id} result reported: "
                        f"{result.status.value}, score={result.score}"
                    )
                    return True
                else:
                    last_error = Exception(f"HTTP {resp.status_code}: {resp.text}")
                    logger.warning(
                        f"Result report failed (attempt {attempt + 1}/{max_retries}): "
                        f"{resp.status_code} - {resp.text}"
                    )
                    
            except requests.RequestException as e:
                last_error = e
                logger.warning(f"Result report exception (attempt {attempt + 1}/{max_retries}): {e}")
            
            if attempt < max_retries - 1:
                import time
                wait_time = 2 ** attempt
                time.sleep(wait_time)
        
        logger.error(f"Result report failed after {max_retries} retries: {last_error}")
        return False
    
    def create_case_record(
        self,
        submit_id: int,
        case: CaseResult,
    ) -> Optional[dict]:
        try:
            data_size: int = (
                len(case.input_data or "")
                + len(case.output_data or "")
                + len(case.expected_output or "")
                + len(case.logs or "")
            )
            timeout: int = min(600, max(30, 30 + (data_size // (512 * 1024))))
            
            resp: Response = requests.post(
                f"{self.base_url}/internal/create-evaluation-case",
                headers=self._headers,
                json={
                    "submit_id": submit_id,
                    "case_index": case.case_index,
                    "input_data": case.input_data,
                    "output_data": case.output_data,
                    "expected_output": case.expected_output,
                    "status": case.status.to_backend(),
                    "score": case.score,
                    "time_used": case.time_used,
                    "memory_used": case.memory_used,
                    "chars_used": case.chars_used,
                    "requests_used": case.requests_used,
                    "logs": case.logs or "",
                    "error_message": case.error or "",
                },
                timeout=timeout,
            )
            
            if resp.status_code == 200:
                return resp.json().get("data", {})
            return None
            
        except requests.RequestException as e:
            logger.error(f"Failed to create case record: {e}")
            return None

    def get_user_key(
        self,
        user_id: int,
        key_id: int,
        key_name: Optional[str] = None,
    ) -> tuple[Optional[str], Optional[str]]:
        try:
            payload = {"user_id": user_id, "key_id": key_id}
            if key_name:
                payload["key_name"] = key_name
            resp: Response = requests.post(
                f"{self.base_url}/internal/get-user-key",
                headers=self._headers,
                json=payload,
                timeout=self.timeout,
            )
            
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                api_key: str = data.get("api_key", "")
                base_url: str = data.get("base_url", "")
                return (api_key if api_key else None, base_url if base_url else None)
            return (None, None)
            
        except requests.RequestException as e:
            logger.error(f"Failed to get user key: {e}")
            return (None, None)

    def get_key_info(self, user_id: int, key_id: int) -> Optional[dict]:
        """Get key manufacturer for judge LLM_MODEL injection."""
        try:
            resp: Response = requests.post(
                f"{self.base_url}/internal/get-key-info",
                headers=self._headers,
                json={"user_id": user_id, "key_id": key_id},
                timeout=self.timeout,
            )
            if resp.status_code == 200:
                return resp.json().get("data")
            return None
        except requests.RequestException as e:
            logger.error(f"Failed to get key info: {e}")
            return None

    def get_phase_artifact_info(
        self,
        title: str,
        phase_order: int = 1,
    ) -> Optional[dict]:
        try:
            resp: Response = requests.post(
                f"{self.base_url}/internal/get-phase-artifact",
                headers=self._headers,
                json={"title": title, "phase_order": phase_order},
                timeout=self.timeout,
            )
            
            if resp.status_code == 200:
                return resp.json().get("data", {})
            return None
            
        except requests.RequestException as e:
            logger.error(f"Failed to get phase artifact info: {e}")
            return None

    def create_gateway_token(
        self,
        submit_id: int,
        user_id: int,
        key_ids: list[int],
        allowed_models: Optional[list[str]] = None,
        max_chars: int = 5000000,
        max_requests: int = 1000,
        ttl_minutes: int = 30,
    ) -> Optional[dict]:
        try:
            payload = {
                "submit_id": submit_id,
                "user_id": user_id,
                "key_ids": key_ids,
                "max_chars": max_chars,
                "max_requests": max_requests,
                "ttl_minutes": ttl_minutes,
            }
            if allowed_models:
                payload["allowed_models"] = allowed_models
            
            resp: Response = requests.post(
                f"{self.base_url}/internal/create-gateway-token",
                headers=self._headers,
                json=payload,
                timeout=self.timeout,
            )
            
            if resp.status_code == 200:
                return resp.json().get("data", {})
            logger.error(f"Failed to create gateway token: {resp.status_code} - {resp.text}")
            return None
            
        except requests.RequestException as e:
            logger.error(f"Gateway token creation exception: {e}")
            return None
    
    def revoke_gateway_token(self, submit_id: int) -> bool:
        try:
            resp: Response = requests.post(
                f"{self.base_url}/internal/revoke-gateway-token",
                headers=self._headers,
                json={"submit_id": submit_id},
                timeout=self.timeout,
            )
            return resp.status_code == 200
        except requests.RequestException as e:
            logger.error(f"Gateway token revoke exception: {e}")
            return False
    
    def reset_gateway_token_usage(self, submit_id: int) -> bool:
        try:
            resp: Response = requests.post(
                f"{self.base_url}/internal/reset-gateway-token-usage",
                headers=self._headers,
                json={"submit_id": submit_id},
                timeout=self.timeout,
            )
            return resp.status_code == 200
        except requests.RequestException as e:
            logger.error(f"Gateway token usage reset exception: {e}")
            return False
    
    def get_gateway_token_usage(self, submit_id: int) -> Optional[dict]:
        try:
            resp: Response = requests.post(
                f"{self.base_url}/internal/get-gateway-token-usage",
                headers=self._headers,
                json={"submit_id": submit_id},
                timeout=self.timeout,
            )
            if resp.status_code == 200:
                return resp.json().get("data", {})
            return None
        except requests.RequestException as e:
            logger.error(f"Gateway token usage fetch exception: {e}")
            return None
    
    def get_version_history(
        self,
        title: str,
        limit: int = 50,
        phase_order: Optional[int] = None,
    ) -> dict:
        slug = self._slugify(title)
        try:
            params: dict[str, str] = {"limit": str(limit)}
            if phase_order is not None and phase_order > 0:
                params["phase_order"] = str(phase_order)
            
            resp: Response = requests.get(
                f"{self.base_url}/api/v1/problems/s/{slug}/versions",
                headers=self._api_headers,
                params=params,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json().get("data", {})
        except requests.RequestException as e:
            logger.error(f"Failed to get version history ({title}): {e}")
            return {}
    
    def get_version_diff(
        self,
        title: str,
        from_sha: str,
        to_sha: str,
    ) -> dict:
        slug = self._slugify(title)
        try:
            resp: Response = requests.get(
                f"{self.base_url}/api/v1/problems/s/{slug}/diff",
                headers=self._api_headers,
                params={"from": from_sha, "to": to_sha},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json().get("data", {})
        except requests.RequestException as e:
            logger.error(f"Failed to get version diff ({title}): {e}")
            return {}
    
    def list_revisions(
        self,
        title: str,
        phase_order: int = 0,
        status: str = "",
    ) -> list[dict]:
        slug = self._slugify(title)
        try:
            params: dict[str, str] = {}
            if status:
                params["status"] = status
            if phase_order > 0:
                params["phase_order"] = str(phase_order)
            
            resp: Response = requests.get(
                f"{self.base_url}/api/v1/problems/s/{slug}/revisions",
                headers=self._api_headers,
                params=params,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json().get("data", {}).get("revisions", [])
        except requests.RequestException as e:
            logger.error(f"Failed to list revisions ({title}): {e}")
            return []
    
    def create_revision(
        self,
        title: str,
        revision_title: str,
        description: str,
        phase_config: dict,
        phase_order: int = 1,
        problem_meta: Optional[dict] = None,
    ) -> Optional[dict]:
        slug = self._slugify(title)
        try:
            payload: dict = {
                "title": revision_title,
                "description": description,
                "phase_config": phase_config,
                "phase_order": phase_order,
            }
            if problem_meta:
                payload["problem_meta"] = problem_meta
            
            resp: Response = requests.post(
                f"{self.base_url}/api/v1/problems/s/{slug}/revisions",
                headers=self._api_headers,
                json=payload,
                timeout=self.timeout,
            )
            
            if resp.status_code == 200:
                return resp.json().get("data", {})
            logger.error(f"Failed to create revision ({title}): {resp.status_code} - {resp.text}")
            return None
        except requests.RequestException as e:
            logger.error(f"Revision creation exception ({title}): {e}")
            return None
    
    def merge_revision(
        self,
        title: str,
        revision_id: int,
        comment: str = "",
        force: bool = False,
        resolved_files: Optional[dict[str, str]] = None,
    ) -> dict:
        slug = self._slugify(title)
        try:
            payload: dict = {"comment": comment, "force": force}
            if resolved_files:
                payload["resolved_files"] = resolved_files
            
            resp: Response = requests.put(
                f"{self.base_url}/api/v1/admin/problems/s/{slug}/revisions/{revision_id}/merge",
                headers=self._api_headers,
                json=payload,
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json().get("data", {})
        except requests.RequestException as e:
            logger.error(f"Failed to merge revision ({title} #{revision_id}): {e}")
            return {"error": str(e)}
    
    def close_revision(
        self,
        title: str,
        revision_id: int,
        comment: str = "",
    ) -> bool:
        slug = self._slugify(title)
        try:
            resp: Response = requests.put(
                f"{self.base_url}/api/v1/admin/problems/s/{slug}/revisions/{revision_id}/close",
                headers=self._api_headers,
                json={"comment": comment},
                timeout=self.timeout,
            )
            return resp.status_code == 200
        except requests.RequestException as e:
            logger.error(f"Failed to close revision ({title} #{revision_id}): {e}")
            return False
    
    def get_data_export(
        self,
        title: str,
        limit: int = 1000,
        offset: int = 0,
    ) -> dict:
        slug = self._slugify(title)
        try:
            resp: Response = requests.get(
                f"{self.base_url}/api/v1/problems/s/{slug}/data",
                headers=self._api_headers,
                params={"limit": str(limit), "offset": str(offset)},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json().get("data", {})
        except requests.RequestException as e:
            logger.error(f"Failed to export data ({title}): {e}")
            return {}
    
    def get_phase_template(
        self,
        title: str,
        phase_order: int = 1,
        lang: str = "en",
        commit: str = "",
    ) -> dict:
        slug = self._slugify(title)
        try:
            params: dict[str, str] = {"lang": lang}
            if commit:
                params["commit"] = commit
            
            resp: Response = requests.get(
                f"{self.base_url}/api/v1/problems/s/{slug}/phases/{phase_order}/template",
                headers=self._api_headers,
                params=params,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json().get("data", {})
        except requests.RequestException as e:
            logger.error(f"Failed to get phase template ({title} phase {phase_order}): {e}")
            return {}
    
    def get_phase_files(
        self,
        title: str,
        phase_order: int = 1,
        commit: str = "",
    ) -> dict:
        slug = self._slugify(title)
        try:
            params: dict[str, str] = {}
            if commit:
                params["commit"] = commit
            
            resp: Response = requests.get(
                f"{self.base_url}/api/v1/problems/s/{slug}/phases/{phase_order}/files",
                headers=self._api_headers,
                params=params,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json().get("data", {})
        except requests.RequestException as e:
            logger.error(f"Failed to get phase files ({title} phase {phase_order}): {e}")
            return {}
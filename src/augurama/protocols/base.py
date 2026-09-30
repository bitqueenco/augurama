from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
import httpx

from ..errors import DirectorError, SubmissionUncertain


class AuguramaModelProtocol(ABC):
    """Base interface for all Augurama frontier model protocols."""

    model_id: str
    display_name: str
    supports_native_audio: bool
    max_duration_seconds: int
    min_duration_seconds: int = 2
    supported_resolutions: list[str]
    supported_aspect_ratios: list[str]

    @abstractmethod
    def compile_payload(self, scene: dict[str, Any]) -> dict[str, Any]:
        """Compile an Augurama scene into provider-specific API payload."""
        pass

    @abstractmethod
    def estimate_cost(self, duration_sec: float, resolution: str) -> float:
        """Estimate generation cost in USD."""
        pass

    def execute(self, client: httpx.Client, base_url: str, key: str, payload: dict[str, Any]) -> str:
        """Submit the compiled payload to fal.ai queue API and return the request ID."""
        url = f"{base_url.rstrip('/')}/{self.model_id}"
        headers = {
            "Authorization": f"Key {key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        try:
            resp = client.post(url, json=payload, headers=headers)
        except httpx.HTTPError:
            raise SubmissionUncertain("Connection to Fal.ai timed out or failed during submission. Check dashboard.") from None

        if resp.status_code >= 500 or resp.status_code in (408, 409):
            raise SubmissionUncertain(f"Fal.ai returned a temporary server error ({resp.status_code}). Check dashboard before retrying.")

        if resp.status_code == 401:
            raise DirectorError("PROVIDER_AUTH_FAILED", "The Fal.ai API key is invalid or expired.", 502)
        if resp.status_code == 403:
            raise DirectorError("PROVIDER_ACCESS_DENIED", "This Fal.ai key lacks permissions or credits for the requested model.", 502)
        if resp.status_code >= 400:
            raise DirectorError("PROVIDER_REJECTED", f"Fal.ai rejected request ({resp.status_code}): {resp.text[:300]}", 502)

        try:
            data = resp.json()
        except Exception:
            raise SubmissionUncertain("Fal.ai returned non-JSON response.")

        req_id = data.get("request_id")
        if not req_id or not isinstance(req_id, str):
            raise SubmissionUncertain("Fal.ai response had no usable request_id.")
        return req_id

    def get_status(self, client: httpx.Client, base_url: str, key: str, task_id: str) -> dict[str, Any]:
        """Poll task status and resolve video result if completed."""
        url = f"{base_url.rstrip('/')}/{self.model_id}/requests/{task_id}/status"
        headers = {"Authorization": f"Key {key}", "Accept": "application/json"}
        resp = client.get(url, headers=headers)

        if resp.status_code == 401:
            raise DirectorError("PROVIDER_AUTH_FAILED", "The Fal.ai API key is invalid or expired.", 502)
        if resp.status_code >= 400:
            raise DirectorError("PROVIDER_REJECTED", f"Fal.ai status check failed ({resp.status_code}).", 502)

        data = resp.json()
        raw_status = (data.get("status") or "").upper()

        composite_task_id = f"fal:{self.model_id}:{task_id}"

        if raw_status in ("IN_QUEUE",):
            return {"provider_task_id": composite_task_id, "status": "queued", "model": self.model_id, "usage": {}}
        if raw_status in ("IN_PROGRESS",):
            return {"provider_task_id": composite_task_id, "status": "running", "model": self.model_id, "usage": {}}
        if raw_status in ("COMPLETED",):
            res_url = f"{base_url.rstrip('/')}/{self.model_id}/requests/{task_id}"
            res_resp = client.get(res_url, headers=headers)
            res_data = res_resp.json()

            video = res_data.get("video")
            video_url = ""
            if isinstance(video, dict):
                video_url = video.get("url", "")
            elif isinstance(res_data.get("video_url"), str):
                video_url = res_data["video_url"]

            last_frame = res_data.get("last_frame")
            last_frame_url = last_frame.get("url") if isinstance(last_frame, dict) else res_data.get("last_frame_url")

            result = {
                "provider_task_id": composite_task_id,
                "status": "succeeded",
                "model": self.model_id,
                "usage": {},
                "video_url": video_url,
            }
            if last_frame_url:
                result["last_frame_url"] = last_frame_url
            return result

        if raw_status in ("FAILED", "ERROR"):
            return {
                "provider_task_id": composite_task_id,
                "status": "failed",
                "model": self.model_id,
                "error": data.get("error", "Generation failed. Review Fal dashboard."),
                "usage": {},
            }

        return {"provider_task_id": composite_task_id, "status": "running", "model": self.model_id, "usage": {}}

    def cancel(self, client: httpx.Client, base_url: str, key: str, task_id: str):
        """Cancel queued generation task."""
        url = f"{base_url.rstrip('/')}/{self.model_id}/requests/{task_id}/cancel"
        headers = {"Authorization": f"Key {key}"}
        try:
            client.put(url, headers=headers)
        except Exception:
            pass

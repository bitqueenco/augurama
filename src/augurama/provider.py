"""Official BytePlus ModelArk task adapter. No consumer-site automation or retry of paid POSTs."""
from __future__ import annotations

import re
from typing import Callable

import httpx

from .errors import DirectorError, SubmissionUncertain

STATUSES = {"queued", "running", "succeeded", "failed", "cancelled", "expired"}
TASK_ID = re.compile(r"^[A-Za-z0-9_-]{5,160}$")


class BytePlus:
    def __init__(self, base_url: str, transport: httpx.BaseTransport | None = None):
        if base_url != "https://ark.ap-southeast.bytepluses.com/api/v3":
            raise ValueError("Only the reviewed official ModelArk endpoint is accepted")
        self.client = httpx.Client(base_url=base_url + "/", timeout=httpx.Timeout(45, connect=10), follow_redirects=False, trust_env=False, transport=transport)

    def close(self):
        self.client.close()

    def _request(self, method: str, path: str, key: str, payload: dict | None = None) -> dict:
        try:
            response = self.client.request(method, path, json=payload, headers={"Authorization": "Bearer " + key, "Accept": "application/json"})
        except httpx.HTTPError:
            if method == "POST":
                raise SubmissionUncertain() from None
            raise DirectorError("PROVIDER_UNREACHABLE", "ModelArk could not be reached. Retry the status check; do not create another generation.", 502) from None
        if response.status_code >= 500 or response.status_code in (408, 409):
            if method == "POST":
                raise SubmissionUncertain()
            raise DirectorError("PROVIDER_TEMPORARY_ERROR", "ModelArk returned a temporary error. Check this same generation again.", 502)
        if response.is_redirect:
            if method == "POST":
                raise SubmissionUncertain("The provider returned an unexpected redirect. Its submission outcome is unknown; no automatic retry was made.")
            raise DirectorError("PROVIDER_REDIRECT_REJECTED", "Unexpected provider redirect was not followed.", 502)
        if response.status_code >= 400:
            # Provider messages can echo a key, private prompt or moderation details. Never forward raw bodies.
            mapping = {400: ("PROVIDER_REJECTED", "The provider rejected this request. Review its console for the reason; reference or model access may need correction."), 401: ("PROVIDER_AUTH_FAILED", "The ModelArk key is invalid or expired."), 403: ("PROVIDER_ACCESS_DENIED", "This account is not authorized for the requested model or asset."), 404: ("PROVIDER_NOT_FOUND", "The provider task or model was not found. Check the original account and task ID."), 429: ("PROVIDER_RATE_LIMIT", "The provider rejected the request because of a rate or account limit. No automatic generation retry was made.")}
            code, message = mapping.get(response.status_code, ("PROVIDER_REJECTED", f"The provider rejected the request with HTTP {response.status_code}. Check its console."))
            raise DirectorError(code, message, 502)
        if not response.content:
            return {}
        if len(response.content) > 2 * 1024 * 1024:
            if method == "POST":
                raise SubmissionUncertain()
            raise DirectorError("PROVIDER_RESPONSE_INVALID", "The provider response was too large.", 502)
        try:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError()
            return data
        except ValueError:
            if method == "POST":
                raise SubmissionUncertain() from None
            raise DirectorError("PROVIDER_RESPONSE_INVALID", "The provider returned invalid JSON.", 502) from None

    def create(self, key: str, payload: dict) -> str:
        data = self._request("POST", "contents/generations/tasks", key, payload)
        task = data.get("id")
        if not isinstance(task, str) or not TASK_ID.fullmatch(task):
            raise SubmissionUncertain("The provider response had no usable task ID. It may have accepted the generation; check its console before any new submission.")
        return task

    def get(self, key: str, task: str) -> dict:
        if not TASK_ID.fullmatch(task):
            raise DirectorError("INVALID_TASK_ID", "Invalid provider task ID.")
        data = self._request("GET", "contents/generations/tasks/" + task, key)
        if data.get("id") != task or data.get("status") not in STATUSES:
            raise DirectorError("PROVIDER_RESPONSE_INVALID", "The provider task response was inconsistent.", 502)
        result = {"provider_task_id": task, "status": data["status"], "model": data.get("model"), "usage": {}}
        tokens = (data.get("usage") or {}).get("completion_tokens")
        if isinstance(tokens, int) and not isinstance(tokens, bool) and tokens >= 0:
            result["usage"]["completion_tokens"] = tokens
        content = data.get("content") or {}
        if isinstance(content, dict):
            for field in ("video_url", "last_frame_url"):
                if isinstance(content.get(field), str):
                    result[field] = content[field]
        if data["status"] == "failed":
            result["error"] = "Provider generation failed. Review the ModelArk console for the reason and any charge. No new generation was submitted."
        return result

    def cancel_or_delete(self, key: str, task: str):
        if not TASK_ID.fullmatch(task):
            raise DirectorError("INVALID_TASK_ID", "Invalid provider task ID.")
        self._request("DELETE", "contents/generations/tasks/" + task, key)


class FalAI:
    """Fal.ai queue adapter for Seedance and other high-fidelity video models."""

    def __init__(self, base_url: str = "https://queue.fal.run", transport: httpx.BaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(
            timeout=httpx.Timeout(45, connect=10),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    def close(self):
        self.client.close()

    def _resolve_endpoint(self, model: str) -> str:
        mapping = {
            "seedance-2.0": "bytedance/seedance-2.0/text-to-video",
            "seedance-2.5": "bytedance/seedance-2.5/text-to-video",
            "seedance-2.0-fast": "bytedance/seedance-2.0/text-to-video",
            "seedance-2.0-mini": "bytedance/seedance-2.0/text-to-video",
            "dreamina-seedance-2-0-260128": "bytedance/seedance-2.0/text-to-video",
            "dreamina-seedance-2-5-260128": "bytedance/seedance-2.5/text-to-video",
        }
        if model in mapping:
            return mapping[model]
        if "/" in model:
            return model
        return "bytedance/seedance-2.0/text-to-video"

    def _request(self, method: str, url: str, key: str, payload: dict | None = None) -> dict:
        headers = {"Authorization": f"Key {key}", "Accept": "application/json"}
        try:
            response = self.client.request(method, url, json=payload, headers=headers)
        except httpx.HTTPError:
            if method == "POST":
                raise SubmissionUncertain("Connection to Fal.ai timed out or failed during submission. Check dashboard before retrying.") from None
            raise DirectorError("PROVIDER_UNREACHABLE", "Fal.ai could not be reached. Retry the status check; do not create another generation.", 502) from None

        if response.status_code >= 500 or response.status_code in (408, 409):
            if method == "POST":
                raise SubmissionUncertain("Fal.ai returned a temporary server error. Check dashboard before retrying.")
            raise DirectorError("PROVIDER_TEMPORARY_ERROR", f"Fal.ai returned a temporary error ({response.status_code}). Check again later.", 502)

        if response.is_redirect:
            if method == "POST":
                raise SubmissionUncertain("Fal.ai returned an unexpected redirect. Submission outcome is unknown.")
            raise DirectorError("PROVIDER_REDIRECT_REJECTED", "Unexpected provider redirect was not followed.", 502)

        if response.status_code >= 400:
            mapping = {
                401: ("PROVIDER_AUTH_FAILED", "The Fal.ai API key is invalid or expired. Check your Fal.ai dashboard."),
                403: ("PROVIDER_ACCESS_DENIED", "This Fal.ai key is unauthorized or lacks credits for the requested model."),
                404: ("PROVIDER_NOT_FOUND", "The Fal.ai task or model endpoint was not found."),
                422: ("PROVIDER_REJECTED", f"Fal.ai rejected request arguments: {response.text[:300]}"),
                429: ("PROVIDER_RATE_LIMIT", "Fal.ai rate or concurrency limit reached. No automatic retry made."),
            }
            code, message = mapping.get(response.status_code, ("PROVIDER_REJECTED", f"Fal.ai rejected the request with HTTP {response.status_code}."))
            raise DirectorError(code, message, 502)

        if not response.content:
            return {}
        if len(response.content) > 5 * 1024 * 1024:
            if method == "POST":
                raise SubmissionUncertain()
            raise DirectorError("PROVIDER_RESPONSE_INVALID", "The provider response was too large.", 502)

        try:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError()
            return data
        except ValueError:
            if method == "POST":
                raise SubmissionUncertain() from None
            raise DirectorError("PROVIDER_RESPONSE_INVALID", "Fal.ai returned invalid JSON.", 502) from None

    def create(self, key: str, payload: dict) -> str:
        model = payload.get("model", "seedance-2.0")
        endpoint = self._resolve_endpoint(model)

        prompt = ""
        for item in payload.get("content", []):
            if isinstance(item, dict) and item.get("type") == "text" and "text" in item:
                prompt = item["text"]
                break
        if not prompt:
            prompt = str(payload.get("prompt", ""))

        fal_input = {
            "prompt": prompt,
            "duration": payload.get("duration", 10),
            "resolution": payload.get("resolution", "1080p"),
            "aspect_ratio": payload.get("ratio", "16:9"),
            "generate_audio": payload.get("generate_audio", True),
        }
        if payload.get("seed") is not None:
            fal_input["seed"] = payload["seed"]

        url = f"{self.base_url}/{endpoint}"
        data = self._request("POST", url, key, fal_input)
        req_id = data.get("request_id")
        if not isinstance(req_id, str) or not req_id:
            raise SubmissionUncertain("Fal.ai response had no usable request_id. Check console before retrying.")

        return f"fal:{model}:{req_id}"

    def get(self, key: str, task: str) -> dict:
        if not task.startswith("fal:"):
            raise DirectorError("INVALID_TASK_ID", "Invalid Fal.ai task identifier.")

        parts = task[4:].split(":", 1)
        if len(parts) == 2:
            model_id, req_id = parts[0], parts[1]
        else:
            model_id = "seedance-2.0"
            req_id = parts[0]

        endpoint = self._resolve_endpoint(model_id)
        status_url = f"{self.base_url}/{endpoint}/requests/{req_id}/status"
        status_data = self._request("GET", status_url, key)
        raw_status = (status_data.get("status") or "").upper()

        if raw_status in ("IN_QUEUE",):
            return {"provider_task_id": task, "status": "queued", "model": model_id, "usage": {}}
        elif raw_status in ("IN_PROGRESS",):
            return {"provider_task_id": task, "status": "running", "model": model_id, "usage": {}}
        elif raw_status in ("COMPLETED",):
            res_url = f"{self.base_url}/{endpoint}/requests/{req_id}"
            res_data = self._request("GET", res_url, key)
            video = res_data.get("video")
            video_url = ""
            if isinstance(video, dict):
                video_url = video.get("url", "")
            elif isinstance(res_data.get("video_url"), str):
                video_url = res_data["video_url"]

            last_frame_url = None
            if isinstance(res_data.get("last_frame"), dict):
                last_frame_url = res_data["last_frame"].get("url")
            elif isinstance(res_data.get("last_frame_url"), str):
                last_frame_url = res_data["last_frame_url"]

            result = {
                "provider_task_id": task,
                "status": "succeeded",
                "model": model_id,
                "usage": {},
                "video_url": video_url,
            }
            if last_frame_url:
                result["last_frame_url"] = last_frame_url
            return result
        elif raw_status in ("FAILED", "ERROR"):
            return {
                "provider_task_id": task,
                "status": "failed",
                "model": model_id,
                "error": status_data.get("error", "Fal.ai generation failed. Check Fal dashboard for details."),
                "usage": {},
            }
        else:
            return {"provider_task_id": task, "status": "running", "model": model_id, "usage": {}}

    def cancel_or_delete(self, key: str, task: str):
        if not task.startswith("fal:"):
            return
        parts = task[4:].split(":", 1)
        if len(parts) == 2:
            model_id, req_id = parts[0], parts[1]
        else:
            model_id = "seedance-2.0"
            req_id = parts[0]
        endpoint = self._resolve_endpoint(model_id)
        cancel_url = f"{self.base_url}/{endpoint}/requests/{req_id}/cancel"
        try:
            self._request("PUT", cancel_url, key)
        except DirectorError:
            pass


class ProviderRouter:
    """Routes provider actions between BytePlus ModelArk and Fal.ai based on key type or configuration."""

    def __init__(self, byteplus: BytePlus, fal: FalAI):
        self.byteplus = byteplus
        self.fal = fal

    def _resolve(self, key: str) -> tuple[BytePlus | FalAI, str]:
        import os
        env_pref = os.environ.get("DD_PROVIDER", "").lower().strip()
        if env_pref == "fal" or key.startswith("fal") or ":" in key:
            return self.fal, "fal"
        if env_pref == "byteplus":
            return self.byteplus, "byteplus"
        return self.byteplus, "byteplus"

    def create(self, key: str, payload: dict) -> str:
        provider, _ = self._resolve(key)
        return provider.create(key, payload)

    def get(self, key: str, task: str) -> dict:
        if task.startswith("fal:"):
            return self.fal.get(key, task)
        return self.byteplus.get(key, task)

    def cancel_or_delete(self, key: str, task: str):
        if task.startswith("fal:"):
            return self.fal.cancel_or_delete(key, task)
        return self.byteplus.cancel_or_delete(key, task)

    def close(self):
        self.byteplus.close()
        self.fal.close()


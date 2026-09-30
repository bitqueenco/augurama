from __future__ import annotations

import json
import httpx
import pytest

from augurama.errors import DirectorError, SubmissionUncertain
from augurama.provider import BytePlus, FalAI, ProviderRouter


class FalMockTransport:
    def __init__(self):
        self.calls = []
        self.status = "COMPLETED"
        self.error_code = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, str(request.url), dict(request.headers), body))

        if self.error_code:
            return httpx.Response(self.error_code, json={"error": "Mocked provider error"})

        if request.method == "POST" and "bytedance/seedance-2.0/text-to-video" in str(request.url):
            return httpx.Response(200, json={"request_id": "req-fal-12345", "status": "IN_QUEUE"})

        if request.method == "GET" and "/requests/req-fal-12345/status" in str(request.url):
            return httpx.Response(200, json={"status": self.status})

        if request.method == "GET" and str(request.url).endswith("/requests/req-fal-12345"):
            return httpx.Response(200, json={
                "video": {
                    "url": "https://v3.fal.media/files/corgi-stampede.mp4",
                    "content_type": "video/mp4"
                },
                "last_frame": {
                    "url": "https://v3.fal.media/files/last-frame.jpg"
                }
            })

        if request.method == "PUT" and "/cancel" in str(request.url):
            return httpx.Response(200, json={"cancelled": True})

        return httpx.Response(404, json={"error": "Not found"})


def test_fal_endpoint_resolution():
    adapter = FalAI()
    assert adapter._resolve_endpoint("seedance-2.0") == "bytedance/seedance-2.0/text-to-video"
    assert adapter._resolve_endpoint("seedance-2.5") == "bytedance/seedance-2.5/text-to-video"
    assert adapter._resolve_endpoint("fal-ai/wan/v2.1/text-to-video") == "fal-ai/wan/v2.1/text-to-video"


def test_fal_create_and_poll_lifecycle():
    transport = FalMockTransport()
    adapter = FalAI(transport=httpx.MockTransport(transport))

    payload = {
        "model": "seedance-2.0",
        "content": [{"type": "text", "text": "Giant corgi stampede"}],
        "duration": 10,
        "ratio": "16:9",
        "resolution": "1080p",
        "generate_audio": True,
        "seed": 42
    }

    task_id = adapter.create("fal_test_key_abc123", payload)
    assert task_id == "fal:seedance-2.0:req-fal-12345"

    method, url, headers, body = transport.calls[0]
    assert method == "POST"
    assert "bytedance/seedance-2.0/text-to-video" in url
    assert headers["authorization"] == "Key fal_test_key_abc123"
    assert body["prompt"] == "Giant corgi stampede"
    assert body["duration"] == 10
    assert body["aspect_ratio"] == "16:9"
    assert body["resolution"] == "1080p"
    assert body["seed"] == 42
    assert body["generate_audio"] is True

    # Check polling when COMPLETED
    result = adapter.get("fal_test_key_abc123", task_id)
    assert result["status"] == "succeeded"
    assert result["model"] == "seedance-2.0"
    assert result["video_url"] == "https://v3.fal.media/files/corgi-stampede.mp4"
    assert result["last_frame_url"] == "https://v3.fal.media/files/last-frame.jpg"


def test_fal_auth_failure_handling():
    transport = FalMockTransport()
    transport.error_code = 401
    adapter = FalAI(transport=httpx.MockTransport(transport))

    with pytest.raises(DirectorError) as exc_info:
        adapter.create("bad_key", {"model": "seedance-2.0", "content": []})
    assert exc_info.value.code == "PROVIDER_AUTH_FAILED"


def test_provider_router_selection(monkeypatch):
    fal_transport = FalMockTransport()
    byteplus_transport = FalMockTransport()

    fal_adapter = FalAI(transport=httpx.MockTransport(fal_transport))
    byteplus = BytePlus("https://ark.ap-southeast.bytepluses.com/api/v3", transport=httpx.MockTransport(byteplus_transport))
    router = ProviderRouter(byteplus, fal_adapter)

    # 1. Fal key format (starts with fal)
    p, name = router._resolve("fal_key_12345678901234")
    assert name == "fal"

    # 2. Fal key format (UUID:secret format)
    p, name = router._resolve("e1234567-89ab-cdef-0123-456789abcdef:secret_key_abcdef")
    assert name == "fal"

    # 3. BytePlus standard token
    p, name = router._resolve("standard_byteplus_token_123456789")
    assert name == "byteplus"

    # 4. Environment variable override
    monkeypatch.setenv("DD_PROVIDER", "fal")
    p, name = router._resolve("any_key_string_at_all_12345")
    assert name == "fal"

from __future__ import annotations

from typing import Any
from .base import AuguramaModelProtocol


class WanProtocol(AuguramaModelProtocol):
    """Alibaba Wan 3.0 & Wan 2.7 protocol via fal.ai.
    
    Frontier capabilities:
    - Pre-render 'Thinking' mode for spatial physics and anatomical reasoning
    - Multimodal conditioning (up to 10 images, 5 clips, 5 audio tracks)
    - Dynamic cinematic resolutions with deep prompt compliance
    """

    def __init__(self, version: str = "3.0"):
        self.version = version
        if version == "2.7":
            self.model_id = "fal-ai/wan/v2.7/text-to-video"
            self.display_name = "Alibaba Wan 2.7 (Spatial Dynamics)"
        else:
            self.model_id = "wan-3"
            self.display_name = "Alibaba Wan 3.0 (Frontier Reasoning)"

        self.supports_native_audio = True
        self.max_duration_seconds = 15
        self.min_duration_seconds = 3
        self.supported_resolutions = ["480p", "720p", "1080p"]
        self.supported_aspect_ratios = ["16:9", "9:16", "1:1", "4:3", "3:4"]

    def compile_payload(self, scene: dict[str, Any]) -> dict[str, Any]:
        prompt = scene.get("compiled_prompt") or scene.get("direction", "")
        duration = int(scene.get("duration_seconds") or scene.get("duration", 10))
        duration = min(max(duration, 3), 15)

        res = scene.get("resolution", "1080p")
        if res not in self.supported_resolutions:
            res = "1080p" if res == "4k" else "720p"

        payload = {
            "prompt": prompt,
            "duration": duration,
            "resolution": res,
            "aspect_ratio": scene.get("aspect_ratio") or scene.get("ratio", "16:9"),
            "thinking_mode": bool(scene.get("thinking_mode", True)),
        }

        # Multimodal conditioning: up to 10 images, 5 videos, 5 audios
        if scene.get("references"):
            image_urls = []
            for ref in scene["references"]:
                if ref.get("url"):
                    image_urls.append(ref["url"])
            if image_urls:
                payload["image_urls"] = image_urls[:10]

        if scene.get("seed") is not None:
            payload["seed"] = scene["seed"]
        return payload

    def estimate_cost(self, duration_sec: float, resolution: str) -> float:
        # $0.05/s (480p), $0.10/s (720p), $0.15–$0.20/s (1080p)
        rates = {
            "480p": 0.050,
            "720p": 0.100,
            "1080p": 0.180,
        }
        rate = rates.get(resolution, 0.180)
        return round(duration_sec * rate, 4)

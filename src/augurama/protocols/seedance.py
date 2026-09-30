from __future__ import annotations

from typing import Any
from .base import AuguramaModelProtocol


class SeedanceProtocol(AuguramaModelProtocol):
    """Seedance 2.0 & 2.5 protocol via fal.ai."""

    def __init__(self, variant: str = "2.0"):
        self.variant = variant
        if variant == "mini":
            self.model_id = "bytedance/seedance-2.0/mini/text-to-video"
            self.display_name = "Seedance 2.0 Mini (Fast Token Economy)"
            self.max_duration_seconds = 15
        elif variant == "fast":
            self.model_id = "bytedance/seedance-2.0/fast/text-to-video"
            self.display_name = "Seedance 2.0 Fast"
            self.max_duration_seconds = 15
        elif variant == "2.5":
            self.model_id = "bytedance/seedance-2.5/text-to-video"
            self.display_name = "Seedance 2.5 (Frontier Extended)"
            self.max_duration_seconds = 30
        else:
            self.model_id = "bytedance/seedance-2.0/text-to-video"
            self.display_name = "Seedance 2.0 (High Cinematic Fidelity)"
            self.max_duration_seconds = 15

        self.supports_native_audio = True
        self.min_duration_seconds = 4
        self.supported_resolutions = ["480p", "720p", "1080p"]
        self.supported_aspect_ratios = ["9:16", "16:9", "1:1", "4:3", "3:4", "21:9"]

    def compile_payload(self, scene: dict[str, Any]) -> dict[str, Any]:
        prompt = scene.get("compiled_prompt") or scene.get("direction", "")
        payload = {
            "prompt": prompt,
            "duration": int(scene.get("duration_seconds") or scene.get("duration", 10)),
            "resolution": scene.get("resolution", "720p"),
            "aspect_ratio": scene.get("aspect_ratio") or scene.get("ratio", "16:9"),
            "generate_audio": scene.get("audio", {}).get("enabled", True) if isinstance(scene.get("audio"), dict) else bool(scene.get("generate_audio", True)),
        }
        if scene.get("seed") is not None:
            payload["seed"] = scene["seed"]
        return payload

    def estimate_cost(self, duration_sec: float, resolution: str) -> float:
        # Mini: ~$0.072/s at 480p, ~$0.155/s at 720p
        # Fast: $0.2419/s at 720p
        # 2.0 Standard: ~$0.18/s (720p), ~$0.37/s (1080p)
        # 2.5: ~$0.20/s (720p), ~$0.39/s (1080p)
        if self.variant == "mini":
            rate = 0.072 if resolution == "480p" else 0.155
        elif self.variant == "fast":
            rate = 0.2419
        elif self.variant == "2.5":
            rate = 0.39 if resolution == "1080p" else 0.20
        else:
            rate = 0.37 if resolution == "1080p" else 0.18
        return round(duration_sec * rate, 4)

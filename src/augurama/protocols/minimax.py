from __future__ import annotations

from typing import Any
from .base import AuguramaModelProtocol


class MiniMaxProtocol(AuguramaModelProtocol):
    """MiniMax H3 Max Turbo & H3 Max protocol via fal.ai.
    
    Frontier capabilities:
    - High-velocity generation (~1.6s latency)
    - Prompt expansion modes: 'balanced' or 'quality'
    - Photorealistic texture and legible on-screen typography
    """

    def __init__(self, turbo: bool = True):
        self.turbo = turbo
        self.model_id = "minimax/h3-max-turbo" if turbo else "minimax/h3-max"
        self.display_name = "MiniMax H3 Max Turbo (Ultra Fast)" if turbo else "MiniMax H3 Max (Frontier Fidelity)"
        self.supports_native_audio = True
        self.max_duration_seconds = 10
        self.min_duration_seconds = 2
        self.supported_resolutions = ["480p", "768p", "1080p"]
        self.supported_aspect_ratios = ["16:9", "9:16", "1:1"]

    def compile_payload(self, scene: dict[str, Any]) -> dict[str, Any]:
        prompt = scene.get("compiled_prompt") or scene.get("direction", "")
        duration = int(scene.get("duration_seconds") or scene.get("duration", 6))
        # Clamp to MiniMax max 10 seconds
        duration = min(max(duration, 2), 10)

        res = scene.get("resolution", "1080p")
        if res not in self.supported_resolutions:
            res = "1080p" if res == "4k" else "768p"

        expansion = scene.get("prompt_expansion", "balanced")
        if expansion not in ("balanced", "quality", "none"):
            expansion = "balanced"

        payload = {
            "prompt": prompt,
            "duration": duration,
            "resolution": res,
            "aspect_ratio": scene.get("aspect_ratio") or scene.get("ratio", "16:9"),
            "prompt_optimizer": expansion,
        }
        if scene.get("seed") is not None:
            payload["seed"] = scene["seed"]
        return payload

    def estimate_cost(self, duration_sec: float, resolution: str) -> float:
        # $0.025/s (480p), $0.04/s (768p), $0.08/s (1080p)
        rates = {
            "480p": 0.025,
            "768p": 0.040,
            "1080p": 0.080,
        }
        rate = rates.get(resolution, 0.080)
        return round(duration_sec * rate, 4)

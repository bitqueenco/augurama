from __future__ import annotations

from typing import Any
from .base import AuguramaModelProtocol


class KlingProtocol(AuguramaModelProtocol):
    """Kuaishou Kling V3 Turbo Pro & 2.6 Pro protocol via fal.ai.
    
    Frontier capabilities:
    - Native multi-shot storyboard sequencing via `multi_prompt` (up to 6 shots in a single 15s pass)
    - Cinematic temporal continuity and dynamic camera trajectories
    - High-velocity Turbo Pro throughput
    """

    def __init__(self, version: str = "v3-turbo"):
        self.version = version
        if version == "v2.6":
            self.model_id = "fal-ai/kling-video/v2.6/pro/text-to-video"
            self.display_name = "Kling 2.6 Pro (Kinematic Motion)"
        else:
            self.model_id = "fal-ai/kling-video/v3/turbo/pro/text-to-video"
            self.display_name = "Kling V3 Turbo Pro (Multi-Shot Native)"

        self.supports_native_audio = True
        self.max_duration_seconds = 15
        self.min_duration_seconds = 3
        self.supported_resolutions = ["720p", "1080p"]
        self.supported_aspect_ratios = ["16:9", "9:16", "1:1"]

    def compile_payload(self, scene: dict[str, Any]) -> dict[str, Any]:
        duration = int(scene.get("duration_seconds") or scene.get("duration", 10))
        duration = min(max(duration, 3), 15)
        aspect_ratio = scene.get("aspect_ratio") or scene.get("ratio", "16:9")

        shots = scene.get("shots") or []
        # If multi-shot storyboard has 2 to 6 shots, leverage Kling's native multi_prompt feature!
        if len(shots) >= 2:
            multi_prompt = []
            for shot in shots[:6]:
                shot_start = float(shot.get("start", 0))
                shot_end = float(shot.get("end", shot_start + 3))
                shot_dur = max(1.0, round(shot_end - shot_start, 1))

                shot_text = shot.get("action", "")
                if shot.get("camera"):
                    shot_text += f". Camera: {shot['camera']}"
                if shot.get("sound"):
                    shot_text += f". Sound: {shot['sound']}"

                multi_prompt.append({
                    "prompt": shot_text,
                    "duration": shot_dur,
                })

            payload = {
                "multi_prompt": multi_prompt,
                "duration": duration,
                "aspect_ratio": aspect_ratio,
                "mode": "pro",
            }
        else:
            prompt = scene.get("compiled_prompt") or scene.get("direction", "")
            payload = {
                "prompt": prompt,
                "duration": duration,
                "aspect_ratio": aspect_ratio,
                "mode": "pro",
            }

        if scene.get("seed") is not None:
            payload["seed"] = scene["seed"]
        return payload

    def estimate_cost(self, duration_sec: float, resolution: str) -> float:
        # Flat $0.14/s at 1080p, $0.10/s at 720p
        rate = 0.14 if resolution == "1080p" else 0.10
        return round(duration_sec * rate, 4)

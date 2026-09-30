from __future__ import annotations

from typing import Any
from .base import AuguramaModelProtocol
from .seedance import SeedanceProtocol
from .minimax import MiniMaxProtocol
from .wan import WanProtocol
from .kling import KlingProtocol


class ModelRegistry:
    def __init__(self):
        self._protocols: dict[str, AuguramaModelProtocol] = {
            # ByteDance Seedance Family
            "seedance-2.0": SeedanceProtocol("2.0"),
            "seedance-2.5": SeedanceProtocol("2.5"),
            "seedance-2.0-mini": SeedanceProtocol("mini"),
            "seedance-2.0-fast": SeedanceProtocol("fast"),
            "bytedance/seedance-2.0/text-to-video": SeedanceProtocol("2.0"),
            "bytedance/seedance-2.5/text-to-video": SeedanceProtocol("2.5"),

            # MiniMax H3 Max Family
            "minimax-h3-max-turbo": MiniMaxProtocol(turbo=True),
            "minimax-h3-max": MiniMaxProtocol(turbo=False),
            "minimax/h3-max-turbo": MiniMaxProtocol(turbo=True),
            "minimax/h3-max": MiniMaxProtocol(turbo=False),

            # Alibaba Wan Family
            "wan-3": WanProtocol("3.0"),
            "wan-2.7": WanProtocol("2.7"),
            "fal-ai/wan-3/text-to-video": WanProtocol("3.0"),
            "fal-ai/wan/v2.7/text-to-video": WanProtocol("2.7"),

            # Kuaishou Kling Family
            "kling-v3-turbo-pro": KlingProtocol("v3-turbo"),
            "kling-v2.6-pro": KlingProtocol("v2.6"),
            "fal-ai/kling-video/v3/turbo/pro/text-to-video": KlingProtocol("v3-turbo"),
            "fal-ai/kling-video/v2.6/pro/text-to-video": KlingProtocol("v2.6"),
        }

    def get(self, profile_or_id: str) -> AuguramaModelProtocol:
        clean = (profile_or_id or "").strip().lower()
        if clean in self._protocols:
            return self._protocols[clean]
        
        # Heuristic matching for custom endpoint strings
        if "minimax" in clean:
            return MiniMaxProtocol(turbo="turbo" in clean)
        if "wan" in clean:
            return WanProtocol("2.7" if "2.7" in clean else "3.0")
        if "kling" in clean:
            return KlingProtocol("v2.6" if "2.6" in clean else "v3-turbo")
        if "seedance-2.5" in clean:
            return SeedanceProtocol("2.5")
        if "mini" in clean:
            return SeedanceProtocol("mini")
        if "fast" in clean:
            return SeedanceProtocol("fast")

        # Default fallback
        return self._protocols["seedance-2.0"]

    def list_protocols(self) -> list[dict[str, Any]]:
        unique = {}
        for p in self._protocols.values():
            if p.model_id not in unique:
                unique[p.model_id] = {
                    "model_id": p.model_id,
                    "display_name": p.display_name,
                    "supports_native_audio": p.supports_native_audio,
                    "max_duration_seconds": p.max_duration_seconds,
                    "supported_resolutions": p.supported_resolutions,
                    "supported_aspect_ratios": p.supported_aspect_ratios,
                }
        return list(unique.values())


registry = ModelRegistry()


def get_protocol(profile_or_id: str) -> AuguramaModelProtocol:
    return registry.get(profile_or_id)

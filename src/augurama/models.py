from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Short = Annotated[str, Field(min_length=1, max_length=200)]
Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{7,95}$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, validate_default=True, allow_inf_nan=False)


class Shot(StrictModel):
    start: float = Field(ge=0, le=30)
    end: float = Field(gt=0, le=30)
    action: str = Field(min_length=3, max_length=900)
    camera: str = Field(default="", max_length=400)
    sound: str = Field(default="", max_length=300)

    @model_validator(mode="after")
    def ordered(self):
        if self.end <= self.start:
            raise ValueError("A shot must end after it starts")
        return self


class Reference(StrictModel):
    asset_id: Identifier
    role: Literal["identity", "environment", "style", "object", "motion", "camera", "audio", "first_frame", "last_frame"]
    direction: str = Field(default="", max_length=400)


class AudioDirection(StrictModel):
    enabled: bool = True
    dialogue: list[Annotated[str, Field(min_length=1, max_length=300)]] = Field(default_factory=list, max_length=10)
    ambience: str = Field(default="", max_length=400)
    music: str = Field(default="No music; retain environmental sound.", max_length=300)

    @model_validator(mode="after")
    def consistent(self):
        if not self.enabled and (self.dialogue or self.ambience or self.music not in ("", "No music; retain environmental sound.")):
            raise ValueError("A silent video cannot request dialogue, music or ambience")
        return self


class GenerationPlan(StrictModel):
    title: Short
    original_request: str = Field(min_length=3, max_length=6000)
    direction: str = Field(min_length=3, max_length=6000)
    model_profile: str = Field(default="seedance-2.0", pattern=r"^[a-z0-9.-]+$", max_length=80)
    recipe: Literal["narrative", "product", "continuous"] = "narrative"
    operation: Literal["generate", "edit", "extend"] = "generate"
    duration_seconds: int = Field(default=12, ge=4, le=30)
    aspect_ratio: Literal["9:16", "16:9", "1:1", "4:3", "3:4", "21:9"] = "9:16"
    resolution: Literal["480p", "720p", "1080p", "4k"] = "720p"
    shots: list[Shot] = Field(default_factory=list, max_length=12)
    references: list[Reference] = Field(default_factory=list, max_length=50)
    audio: AudioDirection = Field(default_factory=AudioDirection)
    preserve: list[Annotated[str, Field(min_length=1, max_length=300)]] = Field(default_factory=list, max_length=15)
    avoid: list[Annotated[str, Field(min_length=1, max_length=300)]] = Field(default_factory=list, max_length=15)
    parent_generation_id: Identifier | None = None
    seed: int | None = Field(default=None, ge=0, le=4294967295)
    watermark: bool = True

    @model_validator(mode="after")
    def continuity(self):
        if self.shots:
            cursor = 0.0
            for shot in self.shots:
                if abs(shot.start - cursor) > 0.001:
                    raise ValueError("The shot timeline must start at zero and have no overlaps or gaps")
                cursor = shot.end
            if abs(cursor - self.duration_seconds) > 0.001:
                raise ValueError("Shot durations must cover the complete requested video duration")
        ids = [r.asset_id for r in self.references]
        if len(ids) != len(set(ids)):
            raise ValueError("Reference assets cannot be duplicated; assign each its intended role once")
        if self.recipe == "continuous" and len(self.shots) > 1:
            raise ValueError("The continuous-shot recipe accepts one shot, not multiple cuts")
        if self.operation in ("edit", "extend") and not self.references:
            raise ValueError("Editing or extending requires a source video reference")
        # Avoid hidden provider control flags that could conflict with reviewed settings.
        for text in (self.direction, *(s.action for s in self.shots)):
            if re.search(r"--(?:duration|resolution|ratio|seed|frames|watermark|camera_fixed)\b", text):
                raise ValueError("Set video controls in their dedicated fields, not legacy prompt flags")
        return self


class PrepareInput(StrictModel):
    plan: GenerationPlan


class ContractInput(StrictModel):
    contract_id: Identifier


class GenerationInput(StrictModel):
    generation_id: Identifier


class SubmitInput(ContractInput):
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    approval_token: str = Field(min_length=32, max_length=200)
    accept_provider_billing: Literal[True]
    rights_confirmed: Literal[True]


class FileInput(StrictModel):
    download_url: str = Field(min_length=8, max_length=8192)
    file_id: str = Field(min_length=1, max_length=200)
    mime_type: str | None = None
    file_name: str | None = None


class ImportInput(StrictModel):
    file: FileInput
    likeness: Literal["none", "synthetic", "real_person", "unknown"]
    rights_confirmed: Literal[True]


class ProviderAssetInput(StrictModel):
    uri: str = Field(pattern=r"^asset://[A-Za-z0-9_-]{4,200}$")
    name: Short
    kind: Literal["image", "video", "audio"] = "image"
    duration: float | None = Field(default=None, ge=2, le=30)
    rights_confirmed: Literal[True]


class ListInput(StrictModel):
    limit: int = Field(default=20, ge=1, le=100)


class EmptyInput(StrictModel):
    pass

class CancelInput(GenerationInput):
    accept_completed_record_deletion: Literal[True]

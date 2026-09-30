"""Private, versioned direction compiler. Never ship this module in host plugin archives."""
from __future__ import annotations

from collections import Counter
from datetime import date
import json
from pathlib import Path
import re
import time

from .db import dumps
from .errors import DirectorError
from .models import GenerationPlan
from .security import digest

DATA = Path(__file__).parent / "data"


class Registry:
    def __init__(self, root: Path = DATA):
        self.models = {p.stem: json.loads(p.read_text()) for p in (root / "models").glob("*.json")}
        self.recipes = {p.stem: json.loads(p.read_text()) for p in (root / "recipes").glob("*.json")}
        if not self.models or not self.recipes:
            raise RuntimeError("No reviewed model/recipe cards are installed")
        for slug, card in self.models.items():
            if card.get("schema_version") != 1 or card.get("profile") != slug or not re.fullmatch(r"[a-z0-9_./-]+", card.get("model_id", "")):
                raise RuntimeError(f"Invalid model card: {slug}")
            if date.fromisoformat(card["review_by"]) < date.fromisoformat(card["verified_at"]):
                raise RuntimeError(f"Invalid review period: {slug}")
        for slug, recipe in self.recipes.items():
            if recipe.get("schema_version") != 1 or recipe.get("id") != slug or not recipe.get("principles"):
                raise RuntimeError(f"Invalid recipe: {slug}")

    def public(self) -> dict:
        return {"models": [{k: c[k] for k in ("profile", "model_id", "label", "revision", "verified_at", "review_by", "minimum_duration", "maximum_duration", "maximum_images", "maximum_videos", "maximum_audio", "maximum_reference_video_seconds", "maximum_reference_audio_seconds", "audio_only_reference", "resolutions", "aspect_ratios", "raw_real_faces", "native_audio")} for _, c in sorted(self.models.items(), key=lambda item: (item[0] != "seedance-2.0", item[0]))], "recipes": [{k: r[k] for k in ("id", "version", "label", "description")} for r in self.recipes.values()]}

    def compile(self, plan: GenerationPlan, assets: list[dict], today: date | None = None) -> dict:
        card = self.models.get(plan.model_profile)
        recipe = self.recipes.get(plan.recipe)
        if not card or not recipe:
            raise DirectorError("UNSUPPORTED_PROFILE", "Select a reviewed installed model profile and recipe.")
        if (today or date.today()) > date.fromisoformat(card["review_by"]):
            raise DirectorError("MODEL_REVIEW_REQUIRED", "This model card needs a current provider review before new generations can be prepared.", 409)
        if plan.duration_seconds > card["maximum_duration"] or plan.duration_seconds < card["minimum_duration"]:
            raise DirectorError("UNSUPPORTED_DURATION", f"{card['label']} accepts {card['minimum_duration']}–{card['maximum_duration']} seconds.")
        if plan.resolution not in card["resolutions"] or plan.aspect_ratio not in card["aspect_ratios"]:
            raise DirectorError("UNSUPPORTED_FORMAT", "This model profile does not support the selected format.")
        if len(assets) != len(plan.references) or any(a["id"] != r.asset_id for a, r in zip(assets, plan.references)):
            raise DirectorError("REFERENCE_MISMATCH", "Reference order does not match the approved plan.")
        counts = Counter(a["kind"] for a in assets)
        if any(counts[k] > card[field] for k, field in (("image", "maximum_images"), ("video", "maximum_videos"), ("audio", "maximum_audio"))):
            raise DirectorError("TOO_MANY_REFERENCES", "Reference count exceeds this model's capability card.")
        for kind, field in (("video", "maximum_reference_video_seconds"), ("audio", "maximum_reference_audio_seconds")):
            durations = [a.get("duration", 0) for a in assets if a["kind"] == kind]
            if any(not 2 <= d <= card["maximum_single_reference_seconds"] + .05 for d in durations) or sum(durations) > card[field] + .05:
                raise DirectorError("REFERENCE_DURATION", f"{kind.title()} reference duration exceeds this model's limit.")
        if counts["audio"] and not counts["image"] and not counts["video"] and not card["audio_only_reference"]:
            raise DirectorError("AUDIO_ONLY_UNSUPPORTED", "This model needs an image or video alongside audio references.")
        if not plan.audio.enabled and (counts["audio"] or any(s.sound for s in plan.shots)):
            raise DirectorError("SILENT_AUDIO_CONFLICT", "Silent video cannot have audio references or shot sound directions.")
        frame_roles = [r.role for r in plan.references if r.role in ("first_frame", "last_frame")]
        if frame_roles:
            if frame_roles.count("first_frame") != 1 or frame_roles.count("last_frame") > 1 or len(frame_roles) != len(assets) or any(a["kind"] != "image" for a in assets):
                raise DirectorError("FRAME_MODE_CONFLICT", "First/last-frame mode requires exactly one first image, optionally one last image, and no omni references.")
        for ref, asset in zip(plan.references, assets):
            if (ref.role == "audio") != (asset["kind"] == "audio"):
                raise DirectorError("REFERENCE_ROLE", "Only audio files may use the audio role, and audio files must use that role.")
            if asset.get("trusted_output") and asset.get("likeness") in ("unknown", "real_person") and (not asset.get("provider_original_url") or asset.get("provider_original_expires", 0) <= time.time() + 1200):
                raise DirectorError("TRUSTED_OUTPUT_EXPIRED", "The original provider reference URL is unavailable or expiring. Use the provider-authorized asset process; rehosting does not preserve face authorization.")
            if asset["kind"] != "audio" and not card["raw_real_faces"] and asset.get("likeness") in ("real_person", "unknown") and not asset.get("trusted_output"):
                raise DirectorError("PORTRAIT_AUTHORIZATION_REQUIRED", "This API profile does not accept raw real-person face references. Use BytePlus's authorized portrait/digital-character asset process. Do not reclassify a real person as synthetic.", 422)
        if plan.operation in ("edit", "extend") and not counts["video"]:
            raise DirectorError("SOURCE_VIDEO_REQUIRED", "Editing and extension need an owned source video reference.")
        # Typed references are compiled in order; counters are per media kind, not per role.
        mapping, counters, bindings = [], Counter(), []
        for ref, asset in zip(plan.references, assets):
            counters[asset["kind"]] += 1
            token = f"[{asset['kind'].title()} {counters[asset['kind']]}]"
            role = ref.role if ref.role in ("first_frame", "last_frame") else "reference_" + asset["kind"]
            mapping.append({"asset_id": asset["id"], "token": token, "role": ref.role, "provider_role": role, "kind": asset["kind"], "name": asset["name"], "sha256": asset["sha256"]})
            bindings.append(f"{token}: {ref.role.replace('_', ' ')}. {ref.direction}".strip())
        sections = [f"CREATIVE DIRECTION\n{plan.direction}"]
        if plan.operation == "extend":
            sections.append("OPERATION\nContinue the referenced source video from its established end state into the requested new action. Output is a newly generated clip, not a lossless timeline append.")
        elif plan.operation == "edit":
            sections.append("OPERATION\nProduce a new version of the referenced source video following only the requested changes. Preserve unmodified identity, geography and action where possible.")
        if bindings:
            sections.append("REFERENCE BINDINGS\n" + "\n".join(bindings))
        if plan.shots:
            lines = []
            for shot in plan.shots:
                line = f"{shot.start:g}–{shot.end:g}s: {shot.action}"
                if shot.camera:
                    line += " Camera: " + shot.camera
                if shot.sound:
                    line += " Sound: " + shot.sound
                lines.append(line)
            sections.append("AUTHORED TIMING\n" + "\n".join(lines))
        if plan.preserve:
            sections.append("CONTINUITY LOCKS\n" + "; ".join(plan.preserve))
        if plan.avoid:
            sections.append("DO NOT INTRODUCE\n" + "; ".join(plan.avoid))
        if plan.audio.enabled:
            sound = "Dialogue (verbatim): " + " / ".join(plan.audio.dialogue) if plan.audio.dialogue else "No dialogue, narration or intelligible speech."
            if plan.audio.ambience:
                sound += " Ambience: " + plan.audio.ambience
            if plan.audio.music:
                sound += " Music: " + plan.audio.music
        else:
            sound = "Silent output. No sound, music, dialogue or narration."
        sections.append("AUDIO\n" + sound)
        sections.append("EXECUTION GUIDANCE (explicit direction takes precedence)\n" + " ".join(recipe["principles"]))
        prompt = "\n\n".join(sections)
        if re.search(r"--(?:duration|resolution|ratio|seed|frames|watermark|camera_fixed)\b", prompt):
            raise DirectorError("LEGACY_FLAGS", "Provider control flags are not allowed in direction text. Use structured controls.")
        if len(prompt) > card["max_prompt_characters"]:
            raise DirectorError("PROMPT_TOO_LONG", f"Compiled direction is {len(prompt)} characters; shorten the plan below {card['max_prompt_characters']}. Nothing was truncated.")
        input_seconds = sum(a.get("duration", 0) for a in assets if a["kind"] == "video")
        pricing = card["pricing"]
        unit = pricing.get("unit", "million_completion_tokens")
        if unit == "seconds" or "per_second_rate" in pricing or not isinstance(pricing["list_rates"].get(plan.resolution), list):
            rate_val = pricing["list_rates"][plan.resolution]
            rate = float(rate_val[0] if isinstance(rate_val, list) else rate_val)
            approx_usd = round(plan.duration_seconds * rate, 4)
            estimate = {
                "currency": "USD",
                "approximate_usd": approx_usd,
                "duration_seconds": plan.duration_seconds,
                "usd_per_second": rate,
                "pricing_snapshot": pricing["snapshot_date"],
                "not_a_quote_or_billing_cap": True,
                "excludes": pricing.get("excludes", []),
                "notice": "Approximate list-rate estimate on fal.ai. Not a quote or billing cap."
            }
        else:
            rate = pricing["list_rates"][plan.resolution][1 if counts["video"] else 0]
            area = {"480p": 864 * 480, "720p": 1280 * 720, "768p": 1366 * 768, "1080p": 1920 * 1080, "4k": 3840 * 2160}.get(plan.resolution, 1280 * 720)
            estimated_tokens = (input_seconds + plan.duration_seconds) * area * pricing.get("estimated_fps", 24) / 1024
            estimate = {
                "currency": "USD",
                "approximate_usd": round(estimated_tokens / 1e6 * rate, 4),
                "completion_tokens_approx": round(estimated_tokens),
                "usd_per_million_tokens": rate,
                "input_video_seconds": input_seconds,
                "pricing_snapshot": pricing["snapshot_date"],
                "not_a_quote_or_billing_cap": True,
                "excludes": pricing.get("excludes", []),
                "notice": "Approximate list-rate estimate on fal.ai. Provider token floors or discounts can change the bill."
            }
        return {"plan": plan.model_dump(mode="json"), "assets": assets, "compiled_prompt": prompt, "reference_map": mapping, "model_card": card, "model_digest": digest(dumps(card)), "recipe_id": recipe["id"], "recipe_version": recipe["version"], "recipe_digest": digest(dumps(recipe)), "estimate": estimate, "warnings": ["Edit/extend are model-generated interpretations, not guaranteed exact edits."] if plan.operation != "generate" else []}

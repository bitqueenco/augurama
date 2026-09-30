from __future__ import annotations

import io
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import warnings

from PIL import Image, UnidentifiedImageError

from .config import Settings
from .db import Database, dumps
from .errors import DirectorError
from .safe_fetch import SafeFetcher
from .security import Vault, digest, new_id

Image.MAX_IMAGE_PIXELS = 40_000_000


class Assets:
    def __init__(self, db: Database, settings: Settings, vault: Vault, fetcher: SafeFetcher | None = None):
        self.db, self.settings, self.vault = db, settings, vault
        self.root = settings.data_dir / "media"
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.fetcher = fetcher or SafeFetcher()

    def inspect(self, content: bytes) -> dict:
        if not content or len(content) > self.settings.max_upload_bytes:
            raise DirectorError("MEDIA_TOO_LARGE", "File is empty or exceeds 200 MB.", 413)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(content)) as image:
                    if image.format not in ("JPEG", "PNG", "WEBP") or getattr(image, "is_animated", False):
                        raise DirectorError("UNSUPPORTED_IMAGE", "Use a still JPEG, PNG, or WebP image.")
                    image.verify()
                with Image.open(io.BytesIO(content)) as image:
                    image.load()
                    w, h = image.size
                    fmt = image.format.lower()
            if len(content) > 20 * 1024 * 1024 or not 300 <= min(w, h) or max(w, h) > 6000 or not 0.4 <= w / h <= 2.5:
                raise DirectorError("INVALID_IMAGE_DIMENSIONS", "Images must be 300–6000 pixels per side, ratio 0.4–2.5, and at most 20 MB.")
            return {"kind": "image", "mime": "image/jpeg" if fmt == "jpeg" else "image/" + fmt, "width": w, "height": h, "extension": "jpg" if fmt == "jpeg" else fmt}
        except DirectorError:
            raise
        except (Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise DirectorError("IMAGE_TOO_LARGE", "Image pixel count exceeds the safe limit.") from None
        except (UnidentifiedImageError, OSError, ValueError):
            pass
        # Restrict demuxers/protocols: uploaded playlists and network URLs cannot cause fetches.
        with tempfile.NamedTemporaryFile(dir=self.root, suffix=".input") as f:
            f.write(content)
            f.flush()
            try:
                result = subprocess.run(["ffprobe", "-v", "error", "-protocol_whitelist", "file", "-format_whitelist", "mov,mp4,m4a,3gp,3g2,mj2,mp3,wav", "-show_entries", "format=format_name,duration:stream=codec_type,codec_name,width,height,r_frame_rate", "-of", "json", f.name], capture_output=True, timeout=15, check=True)
                probe = json.loads(result.stdout)
            except (OSError, subprocess.SubprocessError, ValueError):
                raise DirectorError("UNSUPPORTED_MEDIA", "Use a valid MP4/MOV video, MP3/WAV audio, or still JPEG/PNG/WebP image.") from None
        streams, fmt = probe.get("streams", []), probe.get("format", {})
        try:
            duration = float(fmt["duration"])
            if not math.isfinite(duration) or duration <= 0 or duration > 60:
                raise ValueError()
            videos = [s for s in streams if s.get("codec_type") == "video"]
            if videos:
                v = videos[0]
                w, h = int(v["width"]), int(v["height"])
                num, den = v["r_frame_rate"].split("/")
                fps = float(num) / float(den)
                if not 300 <= min(w, h) or max(w, h) > 6000 or not 0.4 <= w / h <= 2.5 or not 407696 <= w * h <= 8295044 or not 24 <= fps <= 60:
                    raise DirectorError("INVALID_VIDEO", "Use 24–60 fps video, 300–6000 pixels per side, ratio 0.4–2.5, and 407,696–8,295,044 pixels.")
                return {"kind": "video", "mime": "video/mp4", "extension": "mp4", "duration": duration, "width": w, "height": h, "fps": fps, "codec": v["codec_name"]}
            if not any(s.get("codec_type") == "audio" for s in streams) or fmt.get("format_name") not in ("mp3", "wav") or len(content) > 15 * 1024 * 1024:
                raise ValueError()
            ext = fmt["format_name"]
            return {"kind": "audio", "mime": "audio/mpeg" if ext == "mp3" else "audio/wav", "extension": ext, "duration": duration}
        except (ValueError, KeyError, ZeroDivisionError):
            raise DirectorError("INVALID_MEDIA", "Media metadata is invalid or exceeds supported size/duration limits.") from None

    def ingest(self, uid: str, content: bytes, name: str, likeness: str, *, source: str = "upload", trusted_output: bool = False, provider_original_url: str | None = None, provider_original_expires: float | None = None) -> dict:
        if likeness not in {"none", "synthetic", "real_person", "unknown"}:
            raise DirectorError("INVALID_LIKENESS", "Choose an accurate likeness declaration.")
        meta = self.inspect(content)
        aid = new_id("asset")
        clean_name = re.sub(r"[\x00-\x1f/\\]", "_", name)[:180] or "reference"
        meta.update(id=aid, name=clean_name, sha256=digest(content), bytes=len(content), likeness=likeness, source=source, trusted_output=trusted_output, created_at=time.time())
        if trusted_output and provider_original_url:
            meta.update(provider_original_url=provider_original_url, provider_original_expires=min(provider_original_expires or time.time(), time.time() + 23 * 3600))
        path = self.root / (aid + "." + meta["extension"])
        # Quota, file creation and metadata insertion are serialized per service DB.
        with self.db.transaction() as c:
            used = sum(json.loads(r[0]).get("bytes", 0) for r in c.execute("SELECT metadata FROM assets WHERE user_id=?", (uid,)))
            if used + len(content) > self.settings.max_account_bytes:
                raise DirectorError("STORAGE_QUOTA", "Your private media storage quota is full. Remove unused media first.", 413)
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as out:
                    out.write(content)
                    out.flush()
                    os.fsync(out.fileno())
                c.execute("INSERT INTO assets VALUES (?,?,?,?)", (aid, uid, dumps(meta), time.time()))
            except Exception:
                path.unlink(missing_ok=True)
                raise
        self.db.audit(uid, "asset.imported", aid, {"kind": meta["kind"], "bytes": len(content)})
        return meta

    def import_url(self, uid: str, url: str, name: str, likeness: str) -> dict:
        raw, _ = self.fetcher.download(url, self.settings.max_upload_bytes)
        return self.ingest(uid, raw, name, likeness, source="host-file")

    def register_provider_asset(self, uid: str, uri: str, name: str, kind: str, duration: float | None = None) -> dict:
        if not re.fullmatch(r"asset://[A-Za-z0-9_-]{4,200}", uri) or kind not in ("image", "video", "audio"):
            raise DirectorError("INVALID_PROVIDER_ASSET", "Enter a genuine provider-managed asset URI.")
        if kind != "image" and (duration is None or not math.isfinite(duration) or not 2 <= duration <= 30):
            raise DirectorError("DURATION_REQUIRED", "Supply the provider-verified duration for video/audio assets (2–30 seconds).")
        aid = new_id("asset")
        meta = {"id": aid, "name": name[:180], "kind": kind, "provider_uri": uri, "duration": duration, "bytes": 0, "sha256": digest(uri), "likeness": "provider_managed", "source": "provider-asset", "created_at": time.time(), "verification": "User-declared provider asset; provider validates authorization at execution."}
        self.db.execute("INSERT INTO assets VALUES (?,?,?,?)", (aid, uid, dumps(meta), time.time()))
        return meta

    def get(self, uid: str, aid: str) -> dict:
        row = self.db.one("SELECT metadata FROM assets WHERE id=? AND user_id=?", (aid, uid))
        if not row:
            raise DirectorError("ASSET_NOT_FOUND", "Reference not found in your account.", 404)
        return json.loads(row["metadata"])

    def list(self, uid: str, limit: int = 100) -> list[dict]:
        return [json.loads(r["metadata"]) for r in self.db.all("SELECT metadata FROM assets WHERE user_id=? ORDER BY created_at DESC LIMIT ?", (uid, limit))]

    def media_url(self, meta: dict, seconds: int = 900) -> str:
        if meta.get("provider_uri"):
            return meta["provider_uri"]
        return f"{self.settings.base_url}/media/{meta['id']}?{self.vault.signed_media_query(meta['id'], seconds)}"

    def path(self, meta: dict) -> Path:
        path = self.root / (meta["id"] + "." + meta["extension"])
        if not path.is_file():
            raise DirectorError("ASSET_MISSING", "Media has expired or is unavailable. Import the reference again.", 410)
        return path

    def delete(self, uid: str, aid: str):
        now = time.time()
        # Serialize against contract creation and job insertion, not merely other deletes.
        with self.db.transaction() as c:
            row = c.execute("SELECT metadata FROM assets WHERE id=? AND user_id=?", (aid, uid)).fetchone()
            if not row:
                raise DirectorError("ASSET_NOT_FOUND", "Reference not found in your account.", 404)
            meta = json.loads(row["metadata"])
            rows = c.execute("SELECT c.snapshot,c.expires_at,j.status FROM contracts c LEFT JOIN jobs j ON j.contract_id=c.id WHERE c.user_id=?", (uid,))
            for row in rows:
                snapshot = json.loads(row["snapshot"])
                if any(r["id"] == aid for r in snapshot["assets"]) and (row["expires_at"] > now or row["status"] in ("submitting", "submission_unknown", "queued", "running", "cancel_outcome_unknown")):
                    raise DirectorError("ASSET_IN_USE", "This reference is pinned by an active contract or generation.", 409)
            c.execute("DELETE FROM assets WHERE id=? AND user_id=?", (aid, uid))
        # Commit removal first: a failed filesystem operation must not roll back
        # metadata for other files already removed by a multi-file operation.
        if not meta.get("provider_uri"):
            try:
                (self.root / (aid + "." + meta["extension"])).unlink(missing_ok=True)
            except OSError:
                raise DirectorError("MEDIA_CLEANUP_PENDING", "The reference is no longer accessible, but physical file cleanup needs operator attention. Maintenance will retry.", 503) from None
        self.db.audit(uid, "asset.deleted", aid)

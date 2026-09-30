from __future__ import annotations

import base64
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


def decode_key(value: str) -> bytes:
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception as exc:
        raise ValueError("DD_ENCRYPTION_KEY must be base64url-encoded 32 bytes") from exc
    if len(raw) != 32:
        raise ValueError("DD_ENCRYPTION_KEY must decode to exactly 32 bytes")
    return raw


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    base_url: str = "http://127.0.0.1:8765"
    environment: str = "development"
    encryption_key: bytes = field(default_factory=lambda: secrets.token_bytes(32), repr=False)
    widget_origin: str | None = None
    public_contact: str = ""
    openai_challenge_token: str = field(default="", repr=False)
    legal_approved: bool = False
    max_estimated_usd_per_job: float = 10.0
    daily_generation_limit: int = 20
    retention_days: int = 30
    oauth_redirect_uris: tuple[str, ...] = (
        "https://chatgpt.com/connector_platform_oauth_redirect",
        "https://antigravity.google/oauth-callback",
    )
    provider_base_url: str = "https://ark.ap-southeast.bytepluses.com/api/v3"
    max_upload_bytes: int = 200 * 1024 * 1024
    max_account_bytes: int = 2 * 1024 * 1024 * 1024

    def __post_init__(self):
        u = urlsplit(self.base_url)
        if u.scheme not in ("https", "http") or not u.hostname or u.username or u.password or u.query or u.fragment or u.path not in ("", "/"):
            raise ValueError("DD_BASE_URL must be a clean HTTP(S) origin")
        if self.widget_origin:
            w = urlsplit(self.widget_origin)
            if w.scheme != "https" or not w.hostname or w.username or w.password or w.port not in (None, 443) or w.path not in ("", "/") or w.query or w.fragment:
                raise ValueError("DD_WIDGET_ORIGIN must be an owned, clean HTTPS origin")
        if self.environment not in ("development", "test", "production"):
            raise ValueError("Invalid DD_ENV")
        if len(self.encryption_key) != 32:
            raise ValueError("Encryption key must be 32 bytes")
        if self.environment == "production":
            if u.scheme != "https" or u.hostname in ("localhost", "127.0.0.1", "::1"):
                raise ValueError("Production requires a stable public HTTPS origin")
            if not self.public_contact or not self.legal_approved:
                raise ValueError("Production requires DD_PUBLIC_CONTACT and DD_LEGAL_APPROVED=1")
        if len(self.openai_challenge_token) > 4096 or "\n" in self.openai_challenge_token or "\r" in self.openai_challenge_token:
            raise ValueError("Use the exact single-line OpenAI domain challenge token")
        if not 1 <= self.daily_generation_limit <= 1000 or not 1 <= self.retention_days <= 365:
            raise ValueError("Invalid generation or retention limits")
        if not 0 < self.max_estimated_usd_per_job <= 1000:
            raise ValueError("Invalid per-job estimated-usage limit")

    @property
    def secure_cookies(self) -> bool:
        return self.base_url.startswith("https://")

    @property
    def resource(self) -> str:
        return self.base_url.rstrip("/") + "/mcp"

    @classmethod
    def from_env(cls) -> "Settings":
        # Do not silently load .env from arbitrary working directories.
        root = Path(os.environ.get("DD_DATA_DIR", ".director")).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(root, 0o700)
        key_value = os.environ.get("DD_ENCRYPTION_KEY", "")
        env = os.environ.get("DD_ENV", "development")
        if key_value:
            key = decode_key(key_value)
        elif env == "production":
            raise ValueError("Production requires DD_ENCRYPTION_KEY; no ephemeral encryption key is allowed")
        else:
            path = root / "encryption.key"
            if not path.exists():
                try:
                    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(fd, "wb") as out:
                        out.write(secrets.token_bytes(32))
                except FileExistsError:
                    pass
            key = path.read_bytes()
        return cls(
            data_dir=root, base_url=os.environ.get("DD_BASE_URL", "http://127.0.0.1:8765").rstrip("/"),
            environment=env, encryption_key=key,
            widget_origin=os.environ.get("DD_WIDGET_ORIGIN") or None,
            public_contact=os.environ.get("DD_PUBLIC_CONTACT", ""),
            openai_challenge_token=os.environ.get("DD_OPENAI_CHALLENGE_TOKEN", ""),
            legal_approved=os.environ.get("DD_LEGAL_APPROVED") == "1",
            max_estimated_usd_per_job=float(os.environ.get("DD_MAX_ESTIMATED_USD_PER_JOB", "10")),
            daily_generation_limit=int(os.environ.get("DD_DAILY_GENERATION_LIMIT", "20")),
            retention_days=int(os.environ.get("DD_RETENTION_DAYS", "30")),
            oauth_redirect_uris=tuple(x.strip() for x in os.environ.get("DD_OAUTH_REDIRECT_URIS", ",".join(cls.__dataclass_fields__["oauth_redirect_uris"].default)).split(",") if x.strip()),
        )

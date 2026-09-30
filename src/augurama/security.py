from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def random_token() -> str:
    return secrets.token_urlsafe(32)


def new_id(prefix: str) -> str:
    return prefix + "_" + secrets.token_hex(16)


def digest(value: str | bytes) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


class Vault:
    def __init__(self, key: bytes):
        self.key = key
        self.aes = AESGCM(key)

    def encrypt(self, plaintext: str, context: str) -> str:
        nonce = secrets.token_bytes(12)
        return base64.urlsafe_b64encode(nonce + self.aes.encrypt(nonce, plaintext.encode(), context.encode())).decode()

    def decrypt(self, ciphertext: str, context: str) -> str:
        raw = base64.urlsafe_b64decode(ciphertext)
        return self.aes.decrypt(raw[:12], raw[12:], context.encode()).decode()

    def sign(self, value: str) -> str:
        return hmac.new(self.key, value.encode(), hashlib.sha256).hexdigest()

    def signed_media_query(self, asset_id: str, seconds: int = 900) -> str:
        expires = int(time.time()) + seconds
        signature = self.sign(f"media:{asset_id}:{expires}")
        return f"expires={expires}&signature={signature}"

    def verify_media(self, asset_id: str, expires: int, signature: str) -> bool:
        return int(time.time()) <= expires <= int(time.time()) + 172900 and hmac.compare_digest(signature, self.sign(f"media:{asset_id}:{expires}"))

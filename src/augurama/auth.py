"""Invite-only accounts and OAuth authorization-code + S256 PKCE.

Opaque, hashed tokens are revocable. Provider secrets never enter OAuth tokens.
No client-credentials grants and no password grant are offered.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import re
import time
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError

from .config import Settings
from .db import Database, dumps
from .errors import DirectorError
from .security import Vault, digest, new_id, random_token

SCOPES = frozenset({"director:read", "director:write"})
PASSWORDS = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
DUMMY_HASH = PASSWORDS.hash("not-a-user-password-" + random_token())


@dataclass(frozen=True)
class Principal:
    user_id: str
    username: str
    scopes: frozenset[str]
    csrf: str | None = None

    def require(self, scope: str):
        if scope not in self.scopes:
            raise DirectorError("INSUFFICIENT_SCOPE", f"Requires {scope}.", 403)


class Auth:
    def __init__(self, db: Database, settings: Settings, vault: Vault):
        self.db, self.settings, self.vault = db, settings, vault

    def invite(self, label: str, hours: int = 48) -> str:
        code = random_token()
        self.db.execute("INSERT INTO invitations VALUES (?,?,?,NULL)", (digest(code), label[:200], time.time() + hours * 3600))
        return code

    def create_user(self, username: str, password: str, invitation: str) -> str:
        username = username.strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_.@+-]{2,119}", username):
            raise DirectorError("INVALID_USERNAME", "Use 3–120 lowercase letters, digits, or ._@+-.")
        if not 14 <= len(password) <= 200:
            raise DirectorError("INVALID_PASSWORD", "Use a unique password with 14–200 characters.")
        password_hash = PASSWORDS.hash(password)
        uid, now = new_id("usr"), time.time()
        with self.db.transaction() as c:
            invite = c.execute("SELECT * FROM invitations WHERE digest=?", (digest(invitation),)).fetchone()
            if not invite or invite["used_at"] or invite["expires_at"] < now:
                raise DirectorError("INVALID_INVITATION", "This invitation is invalid, expired, or already used.", 403)
            if c.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
                raise DirectorError("ACCOUNT_UNAVAILABLE", "That account name is unavailable.", 409)
            c.execute("INSERT INTO users VALUES (?,?,?,?,?,0)", (uid, username, password_hash, None, now))
            c.execute("UPDATE invitations SET used_at=? WHERE digest=?", (now, digest(invitation)))
        self.db.audit(uid, "account.created", uid)
        return uid

    def login(self, username: str, password: str) -> tuple[str, str]:
        user = self.db.one("SELECT * FROM users WHERE username=?", (username.strip().lower(),))
        try:
            valid = PASSWORDS.verify(user["password_hash"] if user else DUMMY_HASH, password[:201])
        except VerificationError:
            valid = False
        if not valid or not user or user["disabled"]:
            raise DirectorError("LOGIN_FAILED", "The account name or password is incorrect.", 401)
        if PASSWORDS.check_needs_rehash(user["password_hash"]):
            self.db.execute("UPDATE users SET password_hash=? WHERE id=?", (PASSWORDS.hash(password), user["id"]))
        token, csrf = random_token(), random_token()
        self.db.execute("INSERT INTO web_sessions VALUES (?,?,?,?)", (digest(token), user["id"], digest(csrf), time.time() + 12 * 3600))
        self.db.audit(user["id"], "account.login", user["id"])
        return token, csrf

    def session(self, token: str | None, csrf: str | None = None, write: bool = False) -> Principal:
        row = self.db.one("SELECT s.*,u.username,u.disabled FROM web_sessions s JOIN users u ON u.id=s.user_id WHERE s.digest=?", (digest(token or ""),))
        if not row or row["expires_at"] < time.time() or row["disabled"]:
            raise DirectorError("LOGIN_REQUIRED", "Sign in to your Corgi-Verse account.", 401)
        if write and (not csrf or not hmac.compare_digest(digest(csrf), row["csrf_digest"])):
            raise DirectorError("CSRF_REJECTED", "Refresh the page and try again.", 403)
        return Principal(row["user_id"], row["username"], SCOPES)

    def logout(self, token: str):
        self.db.execute("DELETE FROM web_sessions WHERE digest=?", (digest(token),))

    def reset_password(self, username: str, password: str):
        if not 14 <= len(password) <= 200:
            raise ValueError("Password must be 14–200 characters")
        user = self.db.one("SELECT id FROM users WHERE username=?", (username.strip().lower(),))
        if not user:
            raise ValueError("Account not found")
        with self.db.transaction() as c:
            c.execute("UPDATE users SET password_hash=? WHERE id=?", (PASSWORDS.hash(password), user["id"]))
            c.execute("DELETE FROM web_sessions WHERE user_id=?", (user["id"],))
            c.execute("UPDATE oauth_tokens SET revoked=1 WHERE user_id=?", (user["id"],))
        self.db.audit(user["id"], "account.password_reset", user["id"])

    def save_provider_key(self, uid: str, key: str):
        if key and (len(key) < 16 or len(key) > 4096 or any(ch.isspace() for ch in key)):
            raise DirectorError("INVALID_KEY", "Enter a valid API key (Fal.ai or BytePlus ModelArk) without whitespace.")
        encrypted = self.vault.encrypt(key, f"provider:{uid}") if key else None
        self.db.execute("UPDATE users SET provider_key=? WHERE id=?", (encrypted, uid))
        self.db.audit(uid, "provider.key_saved" if key else "provider.key_removed", uid)

    def provider_key(self, uid: str) -> str:
        row = self.db.one("SELECT provider_key FROM users WHERE id=? AND disabled=0", (uid,))
        if not row or not row["provider_key"]:
            raise DirectorError("PROVIDER_NOT_CONFIGURED", "Add your own Fal.ai or BytePlus ModelArk API key in the secure account settings. Dreamina consumer credits are not supported.", 409)
        return self.vault.decrypt(row["provider_key"], f"provider:{uid}")

    def validate_redirect(self, uri: str, application_type: str):
        if len(uri) > 2000 or any(x in uri for x in ("\r", "\n", "\\")):
            raise DirectorError("invalid_redirect_uri", "Invalid redirect URI.")
        try:
            u = urlsplit(uri)
            if u.username or u.password or u.fragment or not u.hostname:
                raise ValueError()
            _ = u.port
        except ValueError:
            raise DirectorError("invalid_redirect_uri", "Invalid redirect URI.") from None
        if uri in self.settings.oauth_redirect_uris:
            return
        # Exact callback registration only. Arbitrary HTTPS redirects are NOT allowed.
        if application_type == "native" and u.scheme == "http":
            try:
                if ipaddress.ip_address(u.hostname).is_loopback and u.port and not u.query:
                    return
            except ValueError:
                pass
        raise DirectorError("invalid_redirect_uri", "This callback is not allowlisted. Ask the operator to add the exact host-provided callback.")

    def register_client(self, payload: dict) -> dict:
        allowed = {"client_name", "redirect_uris", "application_type", "grant_types", "response_types", "token_endpoint_auth_method", "scope", "client_uri", "logo_uri", "contacts", "software_id", "software_version"}
        if not isinstance(payload, dict) or set(payload) - allowed:
            raise DirectorError("invalid_client_metadata", "Unrecognized client metadata.")
        uris, kind = payload.get("redirect_uris"), payload.get("application_type", "web")
        if kind not in ("web", "native") or not isinstance(uris, list) or not 1 <= len(uris) <= 8 or not all(isinstance(u, str) for u in uris):
            raise DirectorError("invalid_client_metadata", "Register 1–8 exact redirect URIs.")
        for uri in uris:
            self.validate_redirect(uri, kind)
        if payload.get("token_endpoint_auth_method", "none") != "none":
            raise DirectorError("invalid_client_metadata", "Only public clients with S256 PKCE and token_endpoint_auth_method=none are supported.")
        grants = payload.get("grant_types", ["authorization_code", "refresh_token"])
        if not isinstance(grants, list) or not all(isinstance(g, str) for g in grants) or "authorization_code" not in grants or set(grants) - {"authorization_code", "refresh_token"} or payload.get("response_types", ["code"]) != ["code"]:
            raise DirectorError("invalid_client_metadata", "Only authorization_code and refresh_token grants are supported.")
        name = payload.get("client_name", "MCP client")
        if not isinstance(name, str) or not 1 <= len(name) <= 150:
            raise DirectorError("invalid_client_metadata", "Invalid client_name.")
        scopes = set(str(payload.get("scope", "director:read director:write")).split())
        if not scopes or not scopes <= SCOPES:
            raise DirectorError("invalid_scope", "Unknown scope.")
        cid, now = new_id("client"), time.time()
        self.db.execute("INSERT INTO oauth_clients VALUES (?,?,?,?,?)", (cid, name, dumps(uris), kind, now))
        return {"client_id": cid, "client_id_issued_at": int(now), "client_name": name, "redirect_uris": uris, "application_type": kind, "token_endpoint_auth_method": "none", "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"], "scope": " ".join(sorted(scopes))}

    def authorization_request(self, params: dict) -> tuple[str, dict]:
        client = self.db.one("SELECT * FROM oauth_clients WHERE id=?", (params.get("client_id", ""),))
        if not client or params.get("redirect_uri") not in json.loads(client["redirect_uris"]):
            raise DirectorError("invalid_request", "Unknown client or exact redirect URI mismatch.")
        challenge = params.get("code_challenge", "")
        if params.get("response_type") != "code" or params.get("code_challenge_method") != "S256" or not re.fullmatch(r"[A-Za-z0-9_-]{43}", challenge):
            raise DirectorError("invalid_request", "Authorization code with S256 PKCE is required.")
        if params.get("resource") != self.settings.resource:
            raise DirectorError("invalid_target", "The resource must equal this service's exact /mcp URL.")
        scopes = set(params.get("scope", "director:read director:write").split())
        if not scopes or not scopes <= SCOPES:
            raise DirectorError("invalid_scope", "Unknown scope.")
        state = params.get("state", "")
        if len(state) > 2048:
            raise DirectorError("invalid_request", "State is too long.")
        rid = new_id("authreq")
        payload = {k: params[k] for k in ("client_id", "redirect_uri", "code_challenge", "resource")}
        payload.update(scope=" ".join(sorted(scopes)), state=state)
        self.db.execute("INSERT INTO oauth_requests VALUES (?,?,?,?,?)", (rid, client["id"], dumps(payload), "", time.time() + 600))
        return rid, {"name": client["name"], "scope": payload["scope"]}

    def consent(self, uid: str, request_id: str, allowed: bool) -> str:
        code, now = random_token(), time.time()
        with self.db.transaction() as c:
            row = c.execute("SELECT * FROM oauth_requests WHERE id=?", (request_id,)).fetchone()
            if not row or row["expires_at"] < now:
                raise DirectorError("invalid_request", "Authorization request expired. Reconnect from the host.")
            p = json.loads(row["payload"])
            c.execute("DELETE FROM oauth_requests WHERE id=?", (request_id,))
            if allowed:
                c.execute("INSERT INTO oauth_codes VALUES (?,?,?,?,?,?,?,?)", (digest(code), uid, p["client_id"], p["redirect_uri"], p["code_challenge"], p["scope"], p["resource"], now + 90))
        query = {"iss": self.settings.base_url, "state": p["state"]}
        query.update({"code": code} if allowed else {"error": "access_denied"})
        return p["redirect_uri"] + ("&" if "?" in p["redirect_uri"] else "?") + urlencode(query)

    def _tokens(self, c, uid: str, cid: str, scopes: str, resource: str, family: str | None = None) -> dict:
        access, refresh, now = random_token(), random_token(), time.time()
        family = family or new_id("family")
        for token, kind, duration in ((access, "access", 3600), (refresh, "refresh", 30 * 86400)):
            c.execute("INSERT INTO oauth_tokens VALUES (?,?,?,?,?,?,?,?,NULL,0)", (digest(token), kind, family, uid, cid, scopes, resource, now + duration))
        return {"access_token": access, "token_type": "Bearer", "expires_in": 3600, "refresh_token": refresh, "scope": scopes}

    def token(self, p: dict) -> dict:
        if p.get("resource") != self.settings.resource:
            raise DirectorError("invalid_target", "resource must match the authorized MCP resource.")
        now = time.time()
        if p.get("grant_type") == "authorization_code":
            verifier = p.get("code_verifier", "")
            if not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier):
                raise DirectorError("invalid_grant", "Invalid PKCE verifier.")
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            with self.db.transaction() as c:
                row = c.execute("SELECT * FROM oauth_codes WHERE digest=?", (digest(p.get("code", "")),)).fetchone()
                if not row or row["expires_at"] < now or row["client_id"] != p.get("client_id") or row["redirect_uri"] != p.get("redirect_uri") or row["resource"] != p.get("resource") or not hmac.compare_digest(row["challenge"], challenge):
                    raise DirectorError("invalid_grant", "Authorization code is invalid or expired.")
                c.execute("DELETE FROM oauth_codes WHERE digest=?", (row["digest"],))
                return self._tokens(c, row["user_id"], row["client_id"], row["scopes"], row["resource"])
        if p.get("grant_type") == "refresh_token":
            replay = False
            with self.db.transaction() as c:
                row = c.execute("SELECT * FROM oauth_tokens WHERE digest=? AND kind='refresh'", (digest(p.get("refresh_token", "")),)).fetchone()
                if not row or row["client_id"] != p.get("client_id") or row["resource"] != p.get("resource") or row["expires_at"] < now:
                    raise DirectorError("invalid_grant", "Refresh token is invalid or expired.")
                if row["used_at"] is not None or row["revoked"]:
                    c.execute("UPDATE oauth_tokens SET revoked=1 WHERE family=?", (row["family"],))
                    replay = True
                else:
                    if p.get("scope") and p["scope"] != row["scopes"]:
                        raise DirectorError("invalid_scope", "Scope changes require fresh consent.")
                    c.execute("UPDATE oauth_tokens SET used_at=? WHERE digest=?", (now, row["digest"]))
                    result = self._tokens(c, row["user_id"], row["client_id"], row["scopes"], row["resource"], row["family"])
            # Reuse revocation MUST commit, even though the exchange is rejected.
            if replay:
                raise DirectorError("invalid_grant", "Refresh token reuse detected. Reconnect the host.")
            return result
        raise DirectorError("unsupported_grant_type", "Unsupported grant type.")

    def bearer(self, token: str) -> Principal:
        row = self.db.one("SELECT t.*,u.username,u.disabled FROM oauth_tokens t JOIN users u ON u.id=t.user_id WHERE t.digest=? AND t.kind='access'", (digest(token),))
        if not row or row["revoked"] or row["expires_at"] < time.time() or row["resource"] != self.settings.resource or row["disabled"]:
            raise DirectorError("INVALID_TOKEN", "Reconnect the plugin to sign in.", 401)
        return Principal(row["user_id"], row["username"], frozenset(row["scopes"].split()))

    def revoke(self, token: str, client_id: str):
        row = self.db.one("SELECT family FROM oauth_tokens WHERE digest=? AND client_id=?", (digest(token), client_id))
        if row:
            self.db.execute("UPDATE oauth_tokens SET revoked=1 WHERE family=?", (row["family"],))

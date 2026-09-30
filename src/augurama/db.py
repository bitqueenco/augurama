from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .errors import DirectorError

MIGRATION_1 = """
CREATE TABLE IF NOT EXISTS schema_version(version INTEGER NOT NULL);
INSERT INTO schema_version SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM schema_version);
CREATE TABLE IF NOT EXISTS users(
 id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
 provider_key TEXT, created_at REAL NOT NULL, disabled INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS invitations(
 digest TEXT PRIMARY KEY, label TEXT NOT NULL, expires_at REAL NOT NULL, used_at REAL);
CREATE TABLE IF NOT EXISTS web_sessions(
 digest TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 csrf_digest TEXT NOT NULL, expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS oauth_clients(
 id TEXT PRIMARY KEY, name TEXT NOT NULL, redirect_uris TEXT NOT NULL,
 application_type TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS oauth_requests(
 id TEXT PRIMARY KEY, client_id TEXT NOT NULL REFERENCES oauth_clients(id),
 payload TEXT NOT NULL, csrf_digest TEXT NOT NULL, expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS oauth_codes(
 digest TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 client_id TEXT NOT NULL REFERENCES oauth_clients(id), redirect_uri TEXT NOT NULL,
 challenge TEXT NOT NULL, scopes TEXT NOT NULL, resource TEXT NOT NULL, expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS oauth_tokens(
 digest TEXT PRIMARY KEY, kind TEXT NOT NULL, family TEXT NOT NULL,
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, client_id TEXT NOT NULL,
 scopes TEXT NOT NULL, resource TEXT NOT NULL, expires_at REAL NOT NULL,
 used_at REAL, revoked INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS tokens_family ON oauth_tokens(family);
CREATE TABLE IF NOT EXISTS assets(
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 metadata TEXT NOT NULL, created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS assets_user ON assets(user_id,created_at);
CREATE TABLE IF NOT EXISTS contracts(
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 fingerprint TEXT NOT NULL, snapshot TEXT NOT NULL, approval_digest TEXT NOT NULL,
 approval_encrypted TEXT NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS contracts_user ON contracts(user_id,created_at);
CREATE TABLE IF NOT EXISTS jobs(
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 contract_id TEXT NOT NULL UNIQUE REFERENCES contracts(id), status TEXT NOT NULL,
 provider_task_id TEXT, result TEXT NOT NULL DEFAULT '{}',
 created_at REAL NOT NULL, updated_at REAL NOT NULL, last_polled_at REAL NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS jobs_user ON jobs(user_id,created_at);
CREATE TABLE IF NOT EXISTS rate_limits(
 bucket TEXT PRIMARY KEY, count INTEGER NOT NULL, resets_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS audit(
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, event TEXT NOT NULL,
 object_id TEXT, detail TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL);
"""


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        conn = self.connect()
        try:
            existing = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_version'").fetchone()
            if existing:
                previous = conn.execute("SELECT version FROM schema_version").fetchone()
                if not previous or previous[0] != 1:
                    raise RuntimeError("Unsupported database schema; no migration or downgrade was attempted")
            conn.executescript(MIGRATION_1)
            version = conn.execute("SELECT version FROM schema_version").fetchone()[0]
            if version != 1:
                raise RuntimeError(f"Unsupported database schema version {version}; do not downgrade this database")
        finally:
            conn.close()
        os.chmod(path, 0o600)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def one(self, sql: str, args: tuple = ()) -> dict | None:
        conn = self.connect()
        try:
            row = conn.execute(sql, args).fetchone()
            return dict(row) if row is not None else None
        finally:
            conn.close()

    def all(self, sql: str, args: tuple = ()) -> list[dict]:
        conn = self.connect()
        try:
            return [dict(row) for row in conn.execute(sql, args).fetchall()]
        finally:
            conn.close()

    def execute(self, sql: str, args: tuple = ()) -> int:
        with self.transaction() as conn:
            return conn.execute(sql, args).rowcount

    def audit(self, user_id: str | None, event: str, object_id: str | None = None, detail: dict | None = None):
        self.execute("INSERT INTO audit(user_id,event,object_id,detail,created_at) VALUES(?,?,?,?,?)", (user_id, event, object_id, dumps(detail or {}), time.time()))

    def rate_limit(self, bucket: str, limit: int, window: int):
        now = time.time()
        with self.transaction() as conn:
            row = conn.execute("SELECT count,resets_at FROM rate_limits WHERE bucket=?", (bucket,)).fetchone()
            if row is None or row["resets_at"] <= now:
                conn.execute("INSERT OR REPLACE INTO rate_limits VALUES(?,?,?)", (bucket, 1, now + window))
            elif row["count"] >= limit:
                raise DirectorError("RATE_LIMITED", "Too many attempts. Wait before trying again.", 429)
            else:
                conn.execute("UPDATE rate_limits SET count=count+1 WHERE bucket=?", (bucket,))

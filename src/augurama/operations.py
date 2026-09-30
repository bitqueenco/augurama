"""Operator-only lifecycle operations. No operation in this module starts a generation."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import time

from .config import Settings, decode_key
from .db import dumps
from .errors import DirectorError
from .service import ACTIVE, Director


@contextmanager
def service_lock(root: Path):
    """Single service process; backup/restore cannot race a running server.

    POSIX (Linux/macOS/WSL) is the supported operator platform for this RC.
    The lock file is intentionally retained to avoid inode replacement races.
    """
    import fcntl
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = open(root / '.service.lock', 'a+b')
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DirectorError('SERVICE_RUNNING', 'Stop the existing service before this operation. Multiple server processes are not supported.', 409) from None
        yield
    finally:
        lock.close()


def maintain(service: Director, now: float | None = None) -> dict:
    """Expire local records on a rolling retention window; pin in-flight work."""
    now = time.time() if now is None else now
    cutoff = now - service.settings.retention_days * 86400
    counts = {'jobs': 0, 'contracts': 0, 'assets': 0, 'ephemeral_records': 0, 'audit': 0}
    removed_paths = []
    with service.db.transaction() as c:
        # Unknown submissions remain pinned until an operator resolves them.
        active = tuple(sorted(ACTIVE))
        placeholders = ','.join('?' for _ in active)
        counts['jobs'] = c.execute(f"DELETE FROM jobs WHERE created_at<? AND status NOT IN ({placeholders})", (cutoff, *active)).rowcount
        counts['contracts'] = c.execute('DELETE FROM contracts WHERE created_at<? AND expires_at<=? AND id NOT IN (SELECT contract_id FROM jobs)', (cutoff, now)).rowcount
        pinned = set()
        for row in c.execute(f"SELECT c.snapshot FROM contracts c LEFT JOIN jobs j ON j.contract_id=c.id WHERE c.expires_at>? OR j.status IN ({placeholders})", (now, *active)):
            pinned.update(a['id'] for a in json.loads(row['snapshot'])['assets'])
        for row in c.execute('SELECT id,metadata FROM assets WHERE created_at<?', (cutoff,)).fetchall():
            if row['id'] in pinned:
                continue
            meta = json.loads(row['metadata'])
            if not meta.get('provider_uri'):
                removed_paths.append(service.assets.root / (meta['id'] + '.' + meta['extension']))
            counts['assets'] += c.execute('DELETE FROM assets WHERE id=?', (row['id'],)).rowcount
        for table in ('web_sessions', 'oauth_requests', 'oauth_codes', 'invitations'):
            counts['ephemeral_records'] += c.execute(f'DELETE FROM {table} WHERE expires_at<?', (now,)).rowcount
        # Preserve consumed refresh tokens until their original expiry: reuse detection depends on them.
        counts['ephemeral_records'] += c.execute('DELETE FROM oauth_tokens WHERE expires_at<?', (now,)).rowcount
        counts['ephemeral_records'] += c.execute('DELETE FROM rate_limits WHERE resets_at<?', (now,)).rowcount
        counts['audit'] = c.execute('DELETE FROM audit WHERE created_at<?', (cutoff,)).rowcount
    # Retry old orphans from interrupted/failed cleanups. New imports are left
    # alone for an hour so writing bytes before inserting metadata cannot race.
    known = {json.loads(r['metadata'])['id'] for r in service.db.all('SELECT metadata FROM assets')}
    for path in service.assets.root.iterdir():
        if re.fullmatch(r'asset_[a-zA-Z0-9_-]+\.(jpg|png|webp|mp4|mp3|wav)', path.name) and path.stem not in known:
            if path.is_file() and path.stat().st_mtime < now - 3600:
                removed_paths.append(path)
    counts['media_cleanup_pending'] = _cleanup_files(removed_paths)
    return counts


def _cleanup_files(paths: list[Path]) -> int:
    pending = 0
    for path in set(paths):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pending += 1
    return pending


def delete_account(service: Director, uid: str) -> dict:
    removed_paths = []
    with service.db.transaction() as c:
        placeholders = ','.join('?' for _ in ACTIVE)
        if c.execute(f'SELECT 1 FROM jobs WHERE user_id=? AND status IN ({placeholders})', (uid, *sorted(ACTIVE))).fetchone():
            raise DirectorError('ACCOUNT_HAS_ACTIVE_JOBS', 'Resolve in-flight or uncertain provider tasks before deleting this account. Disconnecting does not cancel provider billing.', 409)
        if not c.execute('SELECT 1 FROM users WHERE id=?', (uid,)).fetchone():
            raise DirectorError('ACCOUNT_NOT_FOUND', 'Account not found.', 404)
        for row in c.execute('SELECT metadata FROM assets WHERE user_id=?', (uid,)).fetchall():
            meta = json.loads(row['metadata'])
            if not meta.get('provider_uri'):
                removed_paths.append(service.assets.root / (meta['id'] + '.' + meta['extension']))
        c.execute('DELETE FROM jobs WHERE user_id=?', (uid,))
        c.execute('DELETE FROM audit WHERE user_id=?', (uid,))
        c.execute('DELETE FROM users WHERE id=?', (uid,))
    return {'deleted': True, 'media_cleanup_pending': _cleanup_files(removed_paths), 'provider_records_deleted': False, 'backup_notice': 'Existing operator backups must expire under the disclosed backup schedule.'}


def _hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def backup(service: Director, destination: Path) -> dict:
    destination = destination.expanduser().absolute()
    source = service.settings.data_dir.resolve()
    if destination.exists() or destination == source or source in destination.parents:
        raise DirectorError('BACKUP_DESTINATION', 'Use a new backup directory outside the live data directory.')
    with service_lock(source):
        destination.mkdir(parents=True, mode=0o700)
        try:
            db_path = destination / 'director.sqlite3'
            original, copy = service.db.connect(), sqlite3.connect(db_path)
            try:
                original.backup(copy)
                if copy.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise DirectorError('BACKUP_INTEGRITY', 'SQLite integrity check failed.')
            finally:
                original.close(); copy.close()
            (destination / 'media').mkdir(mode=0o700)
            files = ['director.sqlite3']
            for row in service.db.all('SELECT metadata FROM assets'):
                meta = json.loads(row['metadata'])
                if meta.get('provider_uri'):
                    continue
                relative = 'media/' + meta['id'] + '.' + meta['extension']
                path = source / relative
                if not path.is_file() or path.is_symlink():
                    raise DirectorError('BACKUP_MEDIA_MISSING', 'A recorded asset is missing or is a symlink. Repair before backup.')
                shutil.copyfile(path, destination / relative)
                files.append(relative)
            if (source / 'encryption.key').is_file():
                shutil.copyfile(source / 'encryption.key', destination / 'encryption.key')
                files.append('encryption.key')
            hashes = {}
            for relative in files:
                path = destination / relative
                os.chmod(path, 0o600)
                hashes[relative] = _hash(path)
            manifest = {'format': 1, 'schema_version': 1, 'created_at': time.time(), 'key_fingerprint': hashlib.sha256(service.settings.encryption_key).hexdigest(), 'files': hashes, 'warning': 'Confidential: includes personal media, prompts, account hashes and encrypted provider credentials. Protect separately from source releases.'}
            manifest_path = destination / 'backup.json'
            manifest_path.write_text(dumps(manifest))
            os.chmod(manifest_path, 0o600)
            return {'backup': str(destination), 'files': len(files), 'encryption_key_included': 'encryption.key' in files}
        except BaseException:
            shutil.rmtree(destination)
            raise


def restore(source: Path, destination: Path, external_key: str | None = None) -> dict:
    """Restore a verified directory backup into a NEW directory, never overwrite data."""
    source = source.expanduser().resolve()
    destination = destination.expanduser().absolute()
    if destination.exists():
        raise DirectorError('RESTORE_DESTINATION', 'Restore requires a new directory. Existing data will never be overwritten.')
    try:
        manifest = json.loads((source / 'backup.json').read_text())
    except (OSError, ValueError):
        raise DirectorError('INVALID_BACKUP', 'Cannot read the backup manifest.') from None
    if manifest.get('format') != 1 or manifest.get('schema_version') != 1 or not isinstance(manifest.get('files'), dict):
        raise DirectorError('INVALID_BACKUP', 'Unsupported backup format or schema.')
    if (source / 'media').is_symlink():
        raise DirectorError('INVALID_BACKUP', 'A backup media directory cannot be a symlink.')
    files = manifest['files']
    if 'director.sqlite3' not in files:
        raise DirectorError('INVALID_BACKUP', 'Backup database is missing.')
    for relative, expected in files.items():
        if relative not in ('director.sqlite3', 'encryption.key') and not re.fullmatch(r'media/asset_[a-zA-Z0-9_-]+\.(jpg|png|webp|mp4|mp3|wav)', relative):
            raise DirectorError('INVALID_BACKUP', 'Backup contains an invalid path.')
        path = source / relative
        if not path.is_file() or path.is_symlink() or path.resolve().parent not in (source, (source / 'media').resolve()) or _hash(path) != expected:
            raise DirectorError('BACKUP_INTEGRITY', 'A backup file is missing, changed, or unsafe.')
    # The source backup must be trusted; hashes detect damage, not a maliciously replaced manifest.
    key = decode_key(external_key) if external_key else ((source / 'encryption.key').read_bytes() if 'encryption.key' in files else b'')
    if len(key) != 32 or hashlib.sha256(key).hexdigest() != manifest.get('key_fingerprint'):
        raise DirectorError('RESTORE_KEY_REQUIRED', 'Provide the original DD_ENCRYPTION_KEY. A new key cannot decrypt existing accounts.')
    db = sqlite3.connect(f'file:{source / "director.sqlite3"}?mode=ro', uri=True)
    try:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or db.execute('SELECT version FROM schema_version').fetchone()[0] != 1 or db.execute('PRAGMA foreign_key_check').fetchall():
            raise DirectorError('BACKUP_INTEGRITY', 'The backup database failed integrity checks.')
    finally:
        db.close()
    destination.mkdir(parents=True, mode=0o700)
    try:
        (destination / 'media').mkdir(mode=0o700)
        for relative in files:
            shutil.copyfile(source / relative, destination / relative)
            os.chmod(destination / relative, 0o600)
        return {'restored': str(destination), 'files': len(files), 'next_step': 'Start with the original encryption key and origin; run doctor and an account read before enabling traffic.'}
    except BaseException:
        shutil.rmtree(destination)
        raise


def doctor(service: Director, production: bool = False) -> dict:
    from datetime import date
    errors, warnings = [], []
    if shutil.which('ffprobe') is None:
        errors.append('ffprobe is required for safe video/audio validation.')
    for card in service.registry.models.values():
        if date.today() > date.fromisoformat(card['review_by']):
            errors.append('Model card requires review: ' + card['profile'])
    if production:
        if service.settings.environment != 'production':
            errors.append('DD_ENV is not production.')
        if not service.settings.base_url.startswith('https://'):
            errors.append('A public HTTPS origin is not configured.')
        if any(not (service.settings.data_dir / 'policies' / (p + '.html')).is_file() for p in ('privacy', 'terms')):
            errors.append('Operator-approved legal policy fragments are not installed.')
        if not service.settings.widget_origin:
            errors.append('An owned widget origin is required for OpenAI submission.')
        if not service.settings.public_contact or not service.settings.legal_approved:
            errors.append('Operator-approved legal notices and public support contact are required.')
    count = service.db.one('SELECT COUNT(*) AS n FROM users WHERE provider_key IS NOT NULL')['n']
    if not count:
        warnings.append('No account has configured a BytePlus API key. No live generation is possible yet.')
    warnings.extend(['This check does not verify domain ownership, external connectivity, provider entitlement, a paid render, or native host installation.', 'One process with persistent local disk is supported. Do not deploy this SQLite service to an ephemeral/serverless filesystem.'])
    return {'local_configuration_ok': not errors, 'production_checks_requested': production, 'errors': errors, 'warnings': warnings, 'configured_provider_accounts': count, 'provider_api_called': False}

"""Private operator CLI; credentials are read from a secure prompt, never from flags."""
from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
from pathlib import Path
import secrets
import sys

from . import __version__
from .config import Settings
from .errors import DirectorError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='augurama', description='Augurama · Autonomous video directing and multimodal storyboard orchestration engine powered by fal.ai')
    parser.add_argument('--version', action='version', version=__version__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('keygen', help='Print a new production encryption key once. Store it in a secret manager.')
    serve = commands.add_parser('serve', help='Run one service process; no generation occurs without approval.')
    serve.add_argument('--host', default='127.0.0.1')
    serve.add_argument('--port', type=int, default=8765)
    invite = commands.add_parser('invite', help='Create a one-use account invitation.')
    invite.add_argument('--label', default='Private beta')
    invite.add_argument('--hours', type=int, choices=range(1,169), metavar='1-168', default=48)
    check = commands.add_parser('doctor', help='Validate configuration without calling the provider.')
    check.add_argument('--production', action='store_true')
    commands.add_parser('maintain', help='Apply retention; unresolved/in-flight generations stay pinned.')
    reset = commands.add_parser('reset-password', help='Operator-assisted recovery; revokes all user sessions and OAuth tokens.')
    reset.add_argument('username')
    delete = commands.add_parser('delete-account', help='Remove one account and its local media after resolving active jobs.')
    delete.add_argument('username')
    delete.add_argument('--confirm-username', required=True)
    reconcile = commands.add_parser('reconcile', help='Attach a verified provider task to an uncertain submission; no new render.')
    reconcile.add_argument('username'); reconcile.add_argument('generation_id'); reconcile.add_argument('provider_task_id')
    reconcile.add_argument('--verified-in-provider-console', action='store_true', required=True)
    b = commands.add_parser('backup', help='After stopping the server, create a confidential consistent backup.')
    b.add_argument('destination', type=Path)
    r = commands.add_parser('restore', help='Restore a trusted directory backup into a new data directory.')
    r.add_argument('source', type=Path); r.add_argument('destination', type=Path)
    args = parser.parse_args(argv)
    service = None
    try:
        if args.command == 'keygen':
            print(base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b'=').decode())
            return 0
        from . import operations
        if args.command == 'restore':
            print(json.dumps(operations.restore(args.source, args.destination, os.environ.get('DD_ENCRYPTION_KEY')), indent=2))
            return 0
        settings = Settings.from_env()
        if args.command == 'serve':
            if not 1 <= args.port <= 65535:
                raise DirectorError('INVALID_PORT', 'Port must be 1–65535.')
            if args.host not in ('127.0.0.1', 'localhost', '::1') and settings.environment != 'production':
                raise DirectorError('PUBLIC_DEVELOPMENT_BLOCKED', 'Bind development to loopback. Configure production HTTPS before exposing accounts to a network.')
            import uvicorn
            from .app import create_app
            with operations.service_lock(settings.data_dir):
                uvicorn.run(create_app(settings), host=args.host, port=args.port, workers=1, access_log=False, proxy_headers=False, log_level='warning')
            return 0
        from .service import Director
        service = Director(settings)
        if args.command == 'invite':
            print(service.auth.invite(args.label, args.hours))
        elif args.command == 'doctor':
            result = operations.doctor(service, args.production)
            print(json.dumps(result, indent=2))
            return 0 if result['local_configuration_ok'] else 2
        elif args.command == 'maintain':
            print(json.dumps(operations.maintain(service), indent=2))
        elif args.command == 'backup':
            print(json.dumps(operations.backup(service, args.destination), indent=2))
        else:
            user = service.db.one('SELECT id,username FROM users WHERE username=?', (args.username.lower().strip(),))
            if not user:
                raise DirectorError('ACCOUNT_NOT_FOUND', 'Account not found.', 404)
            if args.command == 'reset-password':
                password = getpass.getpass('New password (14–200 characters): ')
                if password != getpass.getpass('Repeat password: '):
                    raise DirectorError('PASSWORD_MISMATCH', 'Passwords do not match.')
                service.auth.reset_password(user['id'], password)
                print('Password changed. All existing sessions and OAuth tokens were revoked.')
            elif args.command == 'delete-account':
                if args.confirm_username != user['username']:
                    raise DirectorError('CONFIRMATION_MISMATCH', 'Confirmation must exactly match the account username.')
                print(json.dumps(operations.delete_account(service, user['id']), indent=2))
            elif args.command == 'reconcile':
                print(json.dumps(service.reconcile(user['id'], args.generation_id, args.provider_task_id), indent=2))
        return 0
    except (DirectorError, ValueError, OSError) as exc:
        print(f'{getattr(exc, "code", "CONFIGURATION_ERROR")}: {getattr(exc, "message", str(exc))}', file=sys.stderr)
        return 2
    finally:
        if service:
            service.provider.close()


if __name__ == '__main__':
    raise SystemExit(main())

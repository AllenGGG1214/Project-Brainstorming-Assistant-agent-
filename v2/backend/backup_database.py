"""Create a verified PostgreSQL archive before deployment, without logging credentials.

Run from v2/backend: ../.venv/Scripts/python.exe backup_database.py
Reads DATABASE_URL from the environment or v2/.env. Never migrates the database.
"""
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import make_url


def binary(name):
    found = shutil.which(name)
    if found:
        return found
    root = Path(os.getenv('ProgramFiles', 'C:/Program Files')) / 'PostgreSQL'
    candidates = list(root.glob(f'*/bin/{name}.exe'))
    if not candidates:
        raise RuntimeError(f'{name} is required. Install PostgreSQL client tools first.')
    return str(max(candidates, key=lambda path: int(path.parents[1].name)))


def backup():
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / '.env')
    url = os.getenv('DATABASE_URL', '')
    if not url.startswith(('postgres://', 'postgresql://', 'postgresql+psycopg://')):
        raise RuntimeError('Configure the PostgreSQL External Database URL in v2/.env as DATABASE_URL.')
    connection = url.replace('postgresql+psycopg://', 'postgresql://', 1)
    connection = connection.replace('postgres://', 'postgresql://', 1)
    parsed = make_url(connection)
    if not parsed.host or not parsed.username or not parsed.database:
        raise RuntimeError('The external database URL must include a hostname, username, and database.')
    env = os.environ.copy()
    # libpq does not expand a URI coming only from the PGDATABASE environment
    # variable. Split the URI into supported environment fields instead.
    env.update(PGHOST=parsed.host, PGPORT=str(parsed.port or 5432),
               PGUSER=parsed.username, PGPASSWORD=parsed.password or '', PGDATABASE=parsed.database)
    for key in ('sslmode', 'sslrootcert', 'sslcert', 'sslkey', 'connect_timeout'):
        if key in parsed.query:
            env['PG' + key.replace('_', '').upper()] = parsed.query[key]
    env.setdefault('PGCONNECT_TIMEOUT', '20')
    env.setdefault('PGSSLMODE', 'require')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    directory = root / 'data' / 'backups'
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / f'pre-v3-{stamp}.dump'
    result = subprocess.run([binary('pg_dump'), '--no-password', '--format=custom', '--file', str(archive)],
                            env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=300)
    if result.returncode:
        raise RuntimeError('Backup failed. Check database access, PostgreSQL client version, and the configured URL. Credentials were not logged.')
    verified = subprocess.run([binary('pg_restore'), '--list', str(archive)],
                              capture_output=True, timeout=30)
    if verified.returncode or not archive.stat().st_size:
        raise RuntimeError('Backup archive verification failed. Do not deploy yet.')
    manifest = {'created_at': stamp, 'archive': archive.name, 'bytes': archive.stat().st_size,
                'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
                'archive_catalog_verified': True,
                'restore_to_isolated_database_verified': False}
    archive.with_suffix('.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps({'backup': str(archive), **manifest}, indent=2))


if __name__ == '__main__':
    try:
        backup()
    except Exception as exc:
        # Only intentionally sanitized errors are printed; never subprocess stderr.
        print(str(exc) if isinstance(exc, RuntimeError) else 'Backup could not finish. No credentials were logged.')
        raise SystemExit(1)

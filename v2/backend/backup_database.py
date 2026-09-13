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
    env = os.environ.copy()
    env['PGDATABASE'] = connection  # Credentials stay out of argv and logs.
    env.setdefault('PGCONNECT_TIMEOUT', '20')
    env.setdefault('PGSSLMODE', 'require')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    directory = root / 'data' / 'backups'
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / f'pre-v3-{stamp}.dump'
    result = subprocess.run([binary('pg_dump'), '--format=custom', '--file', str(archive)],
                            env=env, capture_output=True, timeout=300)
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

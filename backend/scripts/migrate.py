"""Migration runner — ``python -m scripts.migrate`` from backend/.

Applies every .sql file in backend/migrations in filename order, once each,
recording what ran in schema_migrations. Each file runs in its own
transaction, so a failing migration leaves nothing half-applied.

The ledger format and checksum (first 16 hex chars of SHA-256 over the file's
bytes) are identical to the Node runner's, so a database migrated by the old
server is recognised as up to date and nothing is re-applied.

Never edit, comment out or skip a statement to make a migration apply (see
CLAUDE.md). Migration files must not contain their own BEGIN/COMMIT.
"""

import hashlib
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import config, is_production  # noqa: E402

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def _conninfo():
    url = config.DATABASE_URL
    if is_production and "sslmode=" not in url:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return url


def checksum_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def run_migrations():
    files = sorted(path for path in MIGRATIONS_DIR.iterdir() if path.suffix == ".sql")
    if not files:
        print(f"[migrate] no migration files found in {MIGRATIONS_DIR}")
        return 0

    applied = 0
    with psycopg.connect(_conninfo(), autocommit=True) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
              version    text PRIMARY KEY,
              checksum   text NOT NULL,
              applied_at timestamptz NOT NULL DEFAULT now()
            )
        """)
        already = dict(conn.execute("SELECT version, checksum FROM schema_migrations").fetchall())

        for path in files:
            data = path.read_bytes()
            checksum = checksum_of(data)
            previous = already.get(path.name)
            if previous:
                if previous != checksum:
                    raise RuntimeError(
                        f"Migration {path.name} was already applied but its contents changed "
                        f"({previous} -> {checksum}). Migrations are immutable once applied; "
                        "add a new migration instead of editing this one."
                    )
                print(f"[migrate] skip  {path.name} (already applied)")
                continue

            print(f"[migrate] apply {path.name}")
            try:
                with conn.transaction():
                    conn.execute(data.decode("utf-8"))
                    conn.execute("INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)",
                                 (path.name, checksum))
            except Exception as err:
                raise RuntimeError(f"Migration {path.name} failed: {err}") from err
            applied += 1

    print("[migrate] database already up to date" if applied == 0 else f"[migrate] applied {applied} migration(s)")
    return applied


if __name__ == "__main__":
    try:
        run_migrations()
    except Exception as err:
        print(f"[migrate] {err}", file=sys.stderr)
        sys.exit(1)

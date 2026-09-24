"""Migration runner — ``python -m scripts.migrate`` from backend/.

Applies every .sql file in backend/migrations in filename order, once each,
recording what ran in schema_migrations. Each file runs in its own
transaction, so a failing migration leaves nothing half-applied.

Each applied file is checksummed (first 16 hex chars of SHA-256 over its
bytes) and the runner refuses a migration whose contents changed after it was
applied: migrations are immutable once applied — add a new one instead.

Never edit, comment out or skip a statement to make a migration apply (see
CLAUDE.md). Migration files must not contain their own BEGIN/COMMIT.
"""

import hashlib
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.extensions import connection  # noqa: E402

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def checksum_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def run_migrations(conn=None):
    files = sorted(path for path in MIGRATIONS_DIR.iterdir() if path.suffix == ".sql")
    if not files:
        print(f"[migrate] no migration files found in {MIGRATIONS_DIR}")
        return 0

    conn = conn or connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
          version    TEXT PRIMARY KEY,
          checksum   TEXT NOT NULL,
          applied_at TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
    """)
    already = dict(conn.execute("SELECT version, checksum FROM schema_migrations").fetchall())

    applied = 0
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
        sql = data.decode("utf-8")
        version = path.name.replace("'", "''")
        try:
            # executescript runs the whole file; wrapping it in BEGIN/COMMIT
            # makes the file and its ledger row one atomic unit.
            conn.executescript(
                f"BEGIN;\n{sql}\n;\nINSERT INTO schema_migrations (version, checksum) "
                f"VALUES ('{version}', '{checksum}');\nCOMMIT;"
            )
        except sqlite3.Error as err:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
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

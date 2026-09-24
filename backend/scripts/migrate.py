"""Migration runner — ``python -m scripts.migrate`` from backend/.

Applies every .sql file in backend/migrations in filename order, once each,
recording what ran in schema_migrations. Each file runs in its own
transaction, so a failing migration leaves nothing half-applied.

Each applied file is checksummed (first 16 hex chars of SHA-256 over its
bytes) and the runner refuses a migration whose contents changed after it was
applied: migrations are immutable once applied — add a new one instead.

Never edit, comment out or skip a statement to make a migration apply (see
CLAUDE.md). Migration files must not contain their own BEGIN/COMMIT.

A file whose first line is ``-- migrate: foreign-keys-off`` runs with foreign
key enforcement off: SQLite's documented procedure for rebuilding a table
that other tables reference (with enforcement on, dropping the old table
would cascade-delete every child row). The pragma cannot change inside a
transaction, so it is switched around it, and ``PRAGMA foreign_key_check``
must come back empty before the file commits.
"""

import hashlib
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.extensions import connection  # noqa: E402

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
FOREIGN_KEYS_OFF = "-- migrate: foreign-keys-off"


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
        foreign_keys_off = sql.lstrip().startswith(FOREIGN_KEYS_OFF)
        if foreign_keys_off:
            conn.execute("PRAGMA foreign_keys = OFF")
        try:
            # executescript runs the whole file; wrapping it in BEGIN/COMMIT
            # makes the file and its ledger row one atomic unit. The COMMIT is
            # separate so a foreign-keys-off file is checked before it lands.
            conn.executescript(
                f"BEGIN;\n{sql}\n;\nINSERT INTO schema_migrations (version, checksum) "
                f"VALUES ('{version}', '{checksum}');"
            )
            if foreign_keys_off:
                broken = conn.execute("PRAGMA foreign_key_check").fetchall()
                if broken:
                    raise sqlite3.IntegrityError(
                        f"{len(broken)} foreign key violation(s), first: {tuple(broken[0])}")
            conn.execute("COMMIT")
        except sqlite3.Error as err:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise RuntimeError(f"Migration {path.name} failed: {err}") from err
        finally:
            if foreign_keys_off:
                conn.execute("PRAGMA foreign_keys = ON")
        applied += 1

    print("[migrate] database already up to date" if applied == 0 else f"[migrate] applied {applied} migration(s)")
    return applied


if __name__ == "__main__":
    try:
        run_migrations()
    except Exception as err:
        print(f"[migrate] {err}", file=sys.stderr)
        sys.exit(1)

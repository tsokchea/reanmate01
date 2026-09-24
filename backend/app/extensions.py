"""SQLite database access — the data layer every model module goes through.

Raw parameterized SQL, no ORM. Statements are written with numbered
placeholders (``$1``, ``$2``, reusable within a statement), which are rewritten
to SQLite's ``?1``, ``?2`` before execution.

One connection per thread, opened lazily and closed at the end of each
request. WAL mode lets readers proceed while a writer holds the lock, and
every transaction starts with ``BEGIN IMMEDIATE`` so writers queue on the
busy timeout instead of deadlocking on a lock upgrade.

The JSON the frontend receives is built straight from these rows, so column
types are converted to what the API has always returned, keyed on the declared
type names in migrations/001_initial_schema.sql:

  TIMESTAMPTZ -> aware UTC datetime   (serialised as 2026-09-24T03:15:00.123Z)
  DATE        -> local-midnight datetime (the API's historical date handling)
  JSONTEXT    -> parsed JSON
  BOOLEAN     -> bool
  DECIMAL2    -> "10.00"-style string (numeric columns were always strings)

A computed column opts in with a type tag in its alias:
``json_group_array(...) AS "items [JSONTEXT]"``.

SQL functions registered on every connection stand in for PostgreSQL
extensions: ``now()``, ``similarity()`` (pg_trgm), ``ilike()`` and
``vec_cosine_distance()`` (pgvector's ``<=>``).
"""

import array
import datetime as dt
import json
import math
import operator
import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from .config import config

BACKEND_ROOT = Path(__file__).resolve().parent.parent
_UTC = dt.timezone.utc


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------


def database_path():
    """``sqlite:///relative/path.db`` (relative to backend/), ``sqlite:////abs/path.db`` or a bare path."""
    url = config.DATABASE_URL
    if url.startswith("sqlite:///"):
        path = url[len("sqlite:///"):]
    elif url.startswith("sqlite://"):
        path = url[len("sqlite://"):]
    else:
        path = url
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = BACKEND_ROOT / candidate
    return candidate


# ---------------------------------------------------------------------------
# Type adaptation
# ---------------------------------------------------------------------------


def to_db_timestamp(value):
    """The one timestamp format stored anywhere, so text order is time order."""
    if value.tzinfo is None:
        value = value.astimezone()
    value = value.astimezone(_UTC)
    return f"{value:%Y-%m-%dT%H:%M:%S}.{value.microsecond // 1000:03d}Z"


def now_timestamp():
    return to_db_timestamp(dt.datetime.now(_UTC))


def normalize_timestamp(value):
    """An ISO-8601 string from a client, rewritten in the stored format (None passes through)."""
    if value is None:
        return None
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00") if isinstance(value, str) else value)
    return to_db_timestamp(parsed)


def _parse_timestamp(raw):
    text = raw.decode()
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=_UTC)


def _parse_date(raw):
    text = raw.decode()
    try:
        year, month, day = (int(part) for part in text[:10].split("-"))
        return dt.datetime(year, month, day).astimezone()
    except ValueError:
        return text


def _parse_decimal2(raw):
    try:
        return f"{float(raw):.2f}"
    except ValueError:
        return raw.decode()


sqlite3.register_adapter(dt.datetime, to_db_timestamp)
sqlite3.register_converter("TIMESTAMPTZ", _parse_timestamp)
sqlite3.register_converter("DATE", _parse_date)
sqlite3.register_converter("JSONTEXT", lambda raw: json.loads(raw))
sqlite3.register_converter("BOOLEAN", lambda raw: raw not in (b"0", b"", b"0.0"))
sqlite3.register_converter("DECIMAL2", _parse_decimal2)


def vector_blob(values):
    """A float list as the BLOB stored in document_chunks.embedding (1536 x float32)."""
    return array.array("f", values).tobytes() if values else None


# ---------------------------------------------------------------------------
# SQL functions standing in for PostgreSQL extensions
# ---------------------------------------------------------------------------


def _trigrams(text):
    """pg_trgm's trigram set: lower-cased alphanumeric words padded '  word '."""
    grams = set()
    for word in re.findall(r"[^\W_]+", (text or "").lower()):
        padded = f"  {word} "
        grams.update(padded[i:i + 3] for i in range(len(padded) - 2))
    return grams


def similarity(a, b):
    """pg_trgm similarity(): shared trigrams over the union of both sets."""
    if a is None or b is None:
        return None
    left, right = _trigrams(str(a)), _trigrams(str(b))
    union = left | right
    return len(left & right) / len(union) if union else 0.0


_like_cache = {}


def ilike(value, pattern):
    """PostgreSQL ILIKE: % and _ wildcards, backslash escapes, Unicode case-insensitive."""
    if value is None or pattern is None:
        return None
    regex = _like_cache.get(pattern)
    if regex is None:
        out, escaped = [], False
        for char in str(pattern):
            if escaped:
                out.append(re.escape(char))
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == "%":
                out.append(".*")
            elif char == "_":
                out.append(".")
            else:
                out.append(re.escape(char))
        regex = re.compile("".join(out), re.IGNORECASE | re.DOTALL)
        if len(_like_cache) < 1000:
            _like_cache[pattern] = regex
    return 1 if regex.fullmatch(str(value)) else 0


def vec_cosine_distance(a, b):
    """pgvector's ``<=>``: 1 - cosine similarity, over float32 BLOBs."""
    if a is None or b is None:
        return None
    left, right = array.array("f"), array.array("f")
    left.frombytes(a)
    right.frombytes(b)
    dot = sum(map(operator.mul, left, right))
    norm = math.sqrt(sum(map(operator.mul, left, left))) * math.sqrt(sum(map(operator.mul, right, right)))
    return 1.0 - dot / norm if norm else None


# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------

_local = threading.local()
_PLACEHOLDER = re.compile(r"\$(\d+)")


def _connect():
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(path),
        timeout=30,
        isolation_level=None,  # autocommit; transactions are explicit
        detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        check_same_thread=True,
    )
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.create_function("now", 0, now_timestamp)
    conn.create_function("similarity", 2, similarity, deterministic=True)
    conn.create_function("ilike", 2, ilike, deterministic=True)
    conn.create_function("vec_cosine_distance", 2, vec_cosine_distance, deterministic=True)
    return conn


def connection():
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = _connect()
        _local.conn = conn
        _local.depth = 0
    return conn


def close_connection(_exc=None):
    """Closes this thread's connection (called at the end of every request)."""
    conn = getattr(_local, "conn", None)
    if conn is not None and not getattr(_local, "depth", 0):
        conn.close()
        _local.conn = None


class Result:
    __slots__ = ("rows", "rowcount")

    def __init__(self, rows, rowcount):
        self.rows = rows
        self.rowcount = rowcount


def _execute(conn, sql, params):
    cur = conn.execute(_PLACEHOLDER.sub(r"?\1", sql), list(params or ()))
    if cur.description:
        names = [column[0] for column in cur.description]
        rows = [dict(zip(names, row)) for row in cur.fetchall()]
    else:
        rows = []
    return Result(rows, cur.rowcount)


def query(sql, params=None):
    """Run a parameterized statement. Never interpolate values into ``sql``."""
    return _execute(connection(), sql, params)


def query_one(sql, params=None):
    rows = query(sql, params).rows
    return rows[0] if rows else None


class Transaction:
    """The thread's connection inside BEGIN IMMEDIATE ... COMMIT."""

    def __init__(self, conn):
        self.conn = conn

    def query(self, sql, params=None):
        return _execute(self.conn, sql, params)

    def query_one(self, sql, params=None):
        rows = self.query(sql, params).rows
        return rows[0] if rows else None

    def rows(self, sql, params=None):
        return self.query(sql, params).rows


@contextmanager
def transaction():
    """A unit of work that commits on success and rolls back on any exception.

    BEGIN IMMEDIATE takes the write lock up front, which is what serialises
    check-then-insert sequences (the kit cap, quota counters) the way row
    locks and advisory locks did in PostgreSQL. Nested use becomes a savepoint.
    """
    conn = connection()
    depth = _local.depth
    savepoint = f"sp_{depth}"
    conn.execute(f"SAVEPOINT {savepoint}" if depth else "BEGIN IMMEDIATE")
    _local.depth = depth + 1
    try:
        yield Transaction(conn)
    except BaseException:
        _local.depth = depth
        if depth:
            conn.execute(f"ROLLBACK TO {savepoint}")
            conn.execute(f"RELEASE {savepoint}")
        else:
            conn.execute("ROLLBACK")
        raise
    else:
        _local.depth = depth
        conn.execute(f"RELEASE {savepoint}" if depth else "COMMIT")


def with_transaction(fn):
    with transaction() as tx:
        return fn(tx)


def is_unique_violation(err):
    """True for a UNIQUE / PRIMARY KEY conflict (PostgreSQL's SQLSTATE 23505)."""
    if not isinstance(err, sqlite3.IntegrityError):
        return False
    name = getattr(err, "sqlite_errorname", "")
    return name in ("SQLITE_CONSTRAINT_UNIQUE", "SQLITE_CONSTRAINT_PRIMARYKEY") or "UNIQUE constraint" in str(err)


def json_param(values):
    """A list for ``IN (SELECT value FROM json_each($n))`` — SQLite's ``= ANY($n::uuid[])``."""
    return json.dumps(list(values or []))


def init_app(app):
    app.teardown_appcontext(close_connection)
    # Keep uploads/instance paths predictable however the server was started.
    os.makedirs(database_path().parent, exist_ok=True)

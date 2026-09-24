"""Shared PostgreSQL connection pool — the counterpart of server/src/db/pool.js.

Raw parameterized SQL, no ORM, exactly as the Node server did it. Queries keep
PostgreSQL's native ``$1, $2`` placeholders (psycopg's RawCursor), so every
statement in app/models is the same SQL that ran under node-postgres.

Result types are made to match node-postgres, because the JSON the frontend
receives is built straight from these rows:

  int8 / numeric   -> str   (node-pg returns both as strings; ``byte_size`` and
                             ``points`` reach the client as "1024" / "10.00")
  uuid / inet      -> str
  date             -> local-midnight datetime (node-pg's Date semantics)
  timestamptz      -> aware datetime, serialised as ISO-8601 UTC with ms
  json / jsonb     -> parsed Python objects
"""

import datetime as dt
from contextlib import contextmanager

import psycopg
from psycopg import RawCursor
from psycopg.adapt import Loader
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import config, is_production


class _TextLoader(Loader):
    """Hands the value back exactly as PostgreSQL printed it."""

    def load(self, data):
        return bytes(data).decode()


class _NodeDateLoader(Loader):
    """node-pg parses a bare ``date`` as local midnight; this mirrors that."""

    def load(self, data):
        text = bytes(data).decode()
        try:
            year, month, day = (int(part) for part in text.split("-"))
            return dt.datetime(year, month, day).astimezone()
        except ValueError:
            return text


for _name in ("int8", "numeric", "uuid", "inet", "cidr"):
    psycopg.adapters.register_loader(_name, _TextLoader)
psycopg.adapters.register_loader("date", _NodeDateLoader)


def _conninfo():
    url = config.DATABASE_URL
    # Hosted Postgres (Neon, Render) requires TLS; node-pg used
    # ssl: { rejectUnauthorized: false } in production, i.e. sslmode=require.
    if is_production and "sslmode=" not in url:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return url


pool = ConnectionPool(
    conninfo=_conninfo(),
    min_size=1,
    max_size=10,
    timeout=5,
    max_idle=30,
    open=False,
    kwargs={"autocommit": True, "row_factory": dict_row, "cursor_factory": RawCursor},
)


def open_pool():
    if pool.closed:
        pool.open(wait=False)


def close_pool():
    pool.close()


class Result:
    __slots__ = ("rows", "rowcount")

    def __init__(self, rows, rowcount):
        self.rows = rows
        self.rowcount = rowcount


def _execute(conn, sql, params):
    cur = conn.execute(sql, list(params or ()))
    rows = cur.fetchall() if cur.description else []
    return Result(rows, cur.rowcount)


def query(sql, params=None):
    """Run a parameterized query. Never interpolate values into ``sql``."""
    open_pool()
    with pool.connection() as conn:
        return _execute(conn, sql, params)


def query_one(sql, params=None):
    """Convenience for queries that must match exactly one row."""
    rows = query(sql, params).rows
    return rows[0] if rows else None


class Transaction:
    """A dedicated connection inside BEGIN ... COMMIT. Use it for every statement."""

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
    """Run a unit of work in a transaction, rolling back on any exception."""
    open_pool()
    with pool.connection() as conn:
        with conn.transaction():
            yield Transaction(conn)


def with_transaction(fn):
    with transaction() as tx:
        return fn(tx)


def pg_code(err):
    """The SQLSTATE of a database error (node-pg's ``err.code``), else None."""
    return getattr(err, "sqlstate", None)

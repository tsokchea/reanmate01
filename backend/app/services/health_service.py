"""GET /api/health (server/src/services/health.service.js)."""

import datetime as dt
import logging
import time

from psycopg import errors as pg_errors

from ..config import config
from ..extensions import query
from ..utils.serialization import iso

log = logging.getLogger("reanmate")
_started = time.monotonic()


def check():
    database = "down"
    migrations = None
    try:
        query("SELECT 1")
        database = "up"
        # Newest applied migration, or None before the first migrate run.
        rows = query("SELECT version, applied_at FROM schema_migrations ORDER BY version DESC LIMIT 1").rows
        migrations = rows[0] if rows else None
    except pg_errors.UndefinedTable:
        migrations = None
    except Exception as err:
        if database == "down":
            log.error("[health] database unreachable: %s", err)

    return {
        "status": "ok" if database == "up" else "degraded",
        "database": database,
        "migrations": migrations,
        "env": config.NODE_ENV,
        "uptimeSeconds": round(time.monotonic() - _started),
        "timestamp": iso(dt.datetime.now(dt.timezone.utc)),
    }

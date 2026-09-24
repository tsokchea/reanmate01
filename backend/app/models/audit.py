"""SQL for ``audit_logs`` (append-only — the table rejects UPDATE and DELETE) and ``system_settings``."""

import json

from ..extensions import query, query_one

AUDIT_COLUMNS = """id, actor_user_id, actor_label, action, target_user_id, target_label, resource, resource_id,
  metadata, ip_address, user_agent, created_at"""


def insert(runner, *, actor_user_id, actor_label, action, target_user_id, target_label, resource, resource_id,
           metadata, ip_address, user_agent):
    return runner.query_one(
        f"""INSERT INTO audit_logs (actor_user_id, actor_label, action, target_user_id, target_label, resource,
                                    resource_id, metadata, ip_address, user_agent)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING {AUDIT_COLUMNS}""",
        [actor_user_id, actor_label, action, target_user_id, target_label, resource, resource_id,
         json.dumps(metadata or {}), ip_address, user_agent],
    )


def _filters(filters):
    return [
        filters.get("from"), filters.get("to"), filters.get("actorId"), filters.get("actor"),
        filters.get("action"), filters.get("targetId"), filters.get("target"),
    ]


_WHERE = """
 WHERE ($1 IS NULL OR created_at >= $1)
   AND ($2 IS NULL OR created_at < $2)
   AND ($3 IS NULL OR actor_user_id = $3)
   AND ($4 IS NULL OR ilike(COALESCE(actor_label, ''), '%' || $4 || '%'))
   AND ($5 IS NULL OR action = $5)
   AND ($6 IS NULL OR target_user_id = $6)
   AND ($7 IS NULL OR ilike(COALESCE(target_label, '') || ' ' || COALESCE(resource_id, ''), '%' || $7 || '%'))
"""


def page(filters, *, limit, offset):
    params = _filters(filters)
    rows = query(
        f"SELECT {AUDIT_COLUMNS} FROM audit_logs {_WHERE} ORDER BY created_at DESC, id LIMIT $8 OFFSET $9",
        [*params, limit, offset],
    ).rows
    total = query_one(f"SELECT count(*) AS n FROM audit_logs {_WHERE}", params)["n"]
    return rows, total


def distinct_actions():
    return [row["action"] for row in query("SELECT DISTINCT action FROM audit_logs ORDER BY action").rows]


def for_target(user_id, limit=10):
    return query(
        f"SELECT {AUDIT_COLUMNS} FROM audit_logs WHERE target_user_id = $1 ORDER BY created_at DESC LIMIT $2",
        [user_id, limit],
    ).rows


# --- system settings ---------------------------------------------------------------


def settings():
    return {row["key"]: row["value"] for row in query("SELECT key, value FROM system_settings").rows}


def setting(key):
    row = query_one("SELECT value FROM system_settings WHERE key = $1", [key])
    return row["value"] if row else None


def put_setting(tx, key, value, updated_by):
    tx.query(
        """INSERT INTO system_settings (key, value, updated_by, updated_at) VALUES ($1, $2, $3, now())
           ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_by = excluded.updated_by,
                                           updated_at = excluded.updated_at""",
        [key, json.dumps(value), updated_by],
    )

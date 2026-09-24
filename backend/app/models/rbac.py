"""SQL for roles, permissions and the permission grants on each account."""

from ..extensions import json_param, query, query_one

ACTOR_COLUMNS = """
  u.id, u.full_name, u.email, u.phone, u.role, u.role_id, u.status, u.must_change_password,
  u.last_login_at, u.created_at, r.key AS role_key, r.name AS role_name
"""


def find_actor(user_id):
    """The account behind a request, with its role — read fresh on every admin request."""
    return query_one(
        f"""SELECT {ACTOR_COLUMNS}
              FROM users u
              LEFT JOIN roles r ON r.id = u.role_id
             WHERE u.id = $1""",
        [user_id],
    )


def all_permission_keys():
    return [row["key"] for row in query("SELECT key FROM permissions ORDER BY category, key").rows]


def list_permissions():
    return query("SELECT id, key, category, description FROM permissions ORDER BY category, key").rows


def keys_for_role(role_id):
    return [row["key"] for row in query(
        """SELECT p.key FROM role_permissions rp JOIN permissions p ON p.id = rp.permission_id
            WHERE rp.role_id = $1 ORDER BY p.key""",
        [role_id],
    ).rows]


def keys_for_user(user_id):
    """Extra grants on the account itself, on top of its role."""
    return [row["key"] for row in query(
        """SELECT p.key FROM user_permissions up JOIN permissions p ON p.id = up.permission_id
            WHERE up.user_id = $1 ORDER BY p.key""",
        [user_id],
    ).rows]


def extra_keys_by_user(user_ids):
    if not user_ids:
        return {}
    out = {user_id: [] for user_id in user_ids}
    for row in query(
        """SELECT up.user_id, p.key FROM user_permissions up JOIN permissions p ON p.id = up.permission_id
            WHERE up.user_id IN (SELECT value FROM json_each($1)) ORDER BY p.key""",
        [json_param(user_ids)],
    ).rows:
        out[row["user_id"]].append(row["key"])
    return out


def keys_by_role():
    out = {}
    for row in query(
        """SELECT rp.role_id, p.key FROM role_permissions rp JOIN permissions p ON p.id = rp.permission_id
            ORDER BY p.key"""
    ).rows:
        out.setdefault(row["role_id"], []).append(row["key"])
    return out


def replace_user_permissions(tx, *, user_id, keys, granted_by):
    tx.query("DELETE FROM user_permissions WHERE user_id = $1", [user_id])
    for key in keys:
        tx.query(
            """INSERT INTO user_permissions (user_id, permission_id, granted_by)
               SELECT $1, id, $3 FROM permissions WHERE key = $2""",
            [user_id, key, granted_by],
        )


def replace_role_permissions(tx, *, role_id, keys):
    tx.query("DELETE FROM role_permissions WHERE role_id = $1", [role_id])
    for key in keys:
        tx.query(
            "INSERT INTO role_permissions (role_id, permission_id) SELECT $1, id FROM permissions WHERE key = $2",
            [role_id, key],
        )


ROLE_COLUMNS = "id, key, name, description, kind, is_system_role, created_at, updated_at"


def list_roles():
    return query(
        f"""SELECT {ROLE_COLUMNS},
                   (SELECT count(*) FROM users u WHERE u.role_id = roles.id AND u.status <> 'deleted') AS user_count
              FROM roles
             ORDER BY CASE kind WHEN 'super_admin' THEN 0 WHEN 'admin' THEN 1 WHEN 'teacher' THEN 2 ELSE 3 END,
                      is_system_role DESC, name"""
    ).rows


def find_role(role_id):
    return query_one(
        f"""SELECT {ROLE_COLUMNS},
                   (SELECT count(*) FROM users u WHERE u.role_id = roles.id AND u.status <> 'deleted') AS user_count
              FROM roles WHERE id = $1""",
        [role_id],
    )


def role_key_taken(key):
    return query_one("SELECT 1 AS taken FROM roles WHERE key = $1", [key]) is not None


def create_role(tx, *, key, name, description):
    return tx.query_one(
        f"""INSERT INTO roles (key, name, description, kind, is_system_role)
            VALUES ($1, $2, $3, 'admin', 0)
            RETURNING {ROLE_COLUMNS}""",
        [key, name, description],
    )


def update_role(tx, role_id, *, name, description):
    return tx.query_one(
        f"UPDATE roles SET name = $2, description = $3 WHERE id = $1 RETURNING {ROLE_COLUMNS}",
        [role_id, name, description],
    )


def users_holding_role(role_id):
    return query_one("SELECT count(*) AS n FROM users WHERE role_id = $1", [role_id])["n"]


def delete_role(tx, role_id):
    return tx.query_one("DELETE FROM roles WHERE id = $1 AND is_system_role = 0 RETURNING id", [role_id])

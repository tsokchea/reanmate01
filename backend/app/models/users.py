"""SQL for the ``users`` table (server/src/db/users.db.js).

Every read selects an explicit column list rather than ``*``, so password_hash
cannot leak into an API response by accident.
"""

from ..extensions import query, query_one

PUBLIC_COLUMNS = """
  id, full_name, email, phone, avatar_url, role, locale,
  plan_tier, plan_status, trial_started_at, trial_ends_at, plan_period_end,
  phone_verified_at, email_verified_at, onboarding_completed_at,
  status, last_seen_at, created_at, updated_at
"""


def create(*, full_name, email, phone, password_hash, locale=None, role, verified_at):
    # verified_at is stamped by the service while no SMS/email provider exists.
    return query_one(
        f"""INSERT INTO users (full_name, email, phone, password_hash, role, locale,
                            phone_verified_at, email_verified_at)
         VALUES ($1, $2, $3, $4, $5, $6,
                 CASE WHEN $3::text IS NULL THEN NULL ELSE $7::timestamptz END,
                 CASE WHEN $2::text IS NULL THEN NULL ELSE $7::timestamptz END)
         RETURNING {PUBLIC_COLUMNS}""",
        [full_name, email, phone, password_hash, role, locale or "km", verified_at],
    )


def find_for_login(identifier):
    """Includes password_hash — only for the login path."""
    return query_one(
        f"""SELECT {PUBLIC_COLUMNS}, password_hash
             FROM users
            WHERE (email = $1 OR phone = $1)
              AND status = 'active'
            LIMIT 1""",
        [identifier],
    )


def find_by_id(user_id):
    return query_one(f"SELECT {PUBLIC_COLUMNS} FROM users WHERE id = $1 AND status <> 'deleted'", [user_id])


def identifier_taken(*, email, phone):
    """Cheap pre-check so a duplicate signup reads as 409, not a constraint error."""
    rows = query(
        """SELECT (email = $1) AS email_taken, (phone = $2) AS phone_taken
             FROM users
            WHERE ($1::text IS NOT NULL AND email = $1)
               OR ($2::text IS NOT NULL AND phone = $2)""",
        [email, phone],
    ).rows
    return {"email": any(r["email_taken"] for r in rows), "phone": any(r["phone_taken"] for r in rows)}


def set_role(user_id, role):
    return query_one(f"UPDATE users SET role = $2 WHERE id = $1 RETURNING {PUBLIC_COLUMNS}", [user_id, role])


def mark_onboarding_complete(user_id):
    return query_one(
        f"""UPDATE users
               SET onboarding_completed_at = COALESCE(onboarding_completed_at, now())
             WHERE id = $1
             RETURNING {PUBLIC_COLUMNS}""",
        [user_id],
    )


def touch_last_seen(user_id):
    query("UPDATE users SET last_seen_at = now() WHERE id = $1", [user_id])

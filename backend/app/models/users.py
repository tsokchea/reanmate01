"""SQL for the ``users`` table.

Every read selects an explicit column list rather than ``*``, so password_hash
cannot leak into an API response by accident.
"""

import datetime as dt
import logging

from ..extensions import query, query_one

log = logging.getLogger("reanmate")

PUBLIC_COLUMNS = """
  id, full_name, email, phone, avatar_url, role, locale,
  plan_tier, plan_status, trial_started_at, trial_ends_at, plan_period_end,
  phone_verified_at, email_verified_at, onboarding_completed_at,
  status, must_change_password, last_seen_at, last_login_at, created_at, updated_at
"""

LAST_SEEN_RESOLUTION = dt.timedelta(minutes=5)


def create(*, full_name, email, phone, password_hash, locale=None, role, verified_at):
    # verified_at is stamped by the service while no SMS/email provider exists.
    return query_one(
        f"""INSERT INTO users (full_name, email, phone, password_hash, role, locale,
                            phone_verified_at, email_verified_at)
         VALUES ($1, $2, $3, $4, $5, $6,
                 CASE WHEN $3 IS NULL THEN NULL ELSE $7 END,
                 CASE WHEN $2 IS NULL THEN NULL ELSE $7 END)
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
            WHERE ($1 IS NOT NULL AND email = $1)
               OR ($2 IS NOT NULL AND phone = $2)""",
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


def record_login(user_id, ip_address, user_agent):
    query("UPDATE users SET last_seen_at = now(), last_login_at = now() WHERE id = $1", [user_id])
    query("INSERT INTO login_events (user_id, ip_address, user_agent) VALUES ($1, $2, $3)",
          [user_id, ip_address, (user_agent or "")[:400] or None])


def auth_state(user_id):
    """What require_auth checks on every request: one primary-key read."""
    return query_one("SELECT role, status, must_change_password, last_seen_at FROM users WHERE id = $1", [user_id])


def touch_last_seen_throttled(user_id, last_seen_at):
    """Keeps "active today" honest without a write on every request."""
    now = dt.datetime.now(dt.timezone.utc)
    if last_seen_at is not None and now - last_seen_at < LAST_SEEN_RESOLUTION:
        return
    try:
        query("UPDATE users SET last_seen_at = now() WHERE id = $1", [user_id])
    except Exception as err:  # a busy database must not fail the request
        log.warning("[auth] could not update last_seen_at: %s", err)


def find_with_password(user_id):
    return query_one(f"SELECT {PUBLIC_COLUMNS}, password_hash FROM users WHERE id = $1 AND status = 'active'",
                     [user_id])


def change_password(user_id, password_hash):
    query("UPDATE users SET password_hash = $2, must_change_password = 0 WHERE id = $1", [user_id, password_hash])

"""SQL for ``auth_sessions`` — the refresh-token store.

Only the SHA-256 hash of a refresh token is ever stored, so a database leak
does not hand over live sessions.
"""

from ..extensions import query, query_one, transaction


def create(*, user_id, token_hash, user_agent, ip_address, expires_at):
    return query_one(
        """INSERT INTO auth_sessions (user_id, token_hash, user_agent, ip_address, expires_at)
           VALUES ($1, $2, $3, $4, $5)
           RETURNING id, user_id, expires_at, created_at""",
        [user_id, token_hash, user_agent, ip_address, expires_at],
    )


def find_active(token_hash):
    """Live sessions only — expired or revoked rows return nothing."""
    return query_one(
        """SELECT id, user_id, expires_at
             FROM auth_sessions
            WHERE token_hash = $1
              AND revoked_at IS NULL
              AND expires_at > now()""",
        [token_hash],
    )


def revoke(token_hash):
    return query_one(
        """UPDATE auth_sessions
              SET revoked_at = now()
            WHERE token_hash = $1 AND revoked_at IS NULL
            RETURNING id""",
        [token_hash],
    )


def revoke_all_for_user(user_id):
    return query(
        "UPDATE auth_sessions SET revoked_at = now() WHERE user_id = $1 AND revoked_at IS NULL",
        [user_id],
    ).rowcount


def rotate(*, old_token_hash, user_id, token_hash, user_agent, ip_address, expires_at):
    """Revoke the old row and issue the new one atomically."""
    with transaction() as tx:
        tx.query("UPDATE auth_sessions SET revoked_at = now() WHERE token_hash = $1", [old_token_hash])
        return tx.query_one(
            """INSERT INTO auth_sessions (user_id, token_hash, user_agent, ip_address, expires_at)
               VALUES ($1, $2, $3, $4, $5)
               RETURNING id, user_id, expires_at""",
            [user_id, token_hash, user_agent, ip_address, expires_at],
        )

"""Authentication guards — server/src/middleware/requireAuth.js and guards.js.

Each guard is a "step": a callable that either returns (let the request
through) or raises an ApiError. Routes list their steps in the same order the
Express routes listed their middleware, because the order decides which error
a bad request gets (a student sending a malformed id to a teacher-only route
gets 403, not 422).
"""

from flask import g

from ..models import users as users_db
from ..services import token_service
from .errors import ApiError


def require_auth():
    """Rejects anything without a valid access-token cookie.

    Reads claims straight off the JWT — no database round trip on the common
    path. A revoked session stops working when its short-lived access token
    expires and the refresh is refused.
    """
    token = token_service.read_access_token()
    if not token:
        raise ApiError.unauthorized("Sign in to continue")

    claims = token_service.verify_access_token(token)
    if not claims or not claims.get("sub"):
        raise ApiError.unauthorized("That session has expired")

    g.auth = {
        "user_id": claims["sub"],
        "role": claims.get("role"),
        "plan": claims.get("plan") or "free",
        "phone_verified": bool(claims.get("pv")),
        "email_verified": bool(claims.get("ev")),
    }


# The guard chain every authenticated route uses instead of naming
# require_auth directly. Verification is deferred, not removed: when an
# SMS/email provider is configured, a require_verified step is appended here
# and every protected route picks it up with no route touched.
authenticated = (require_auth,)


def require_role(*roles):
    """Requires one of ``roles``. Re-reads the user when the token predates a role change."""

    def step():
        auth = g.get("auth")
        if not auth:
            raise ApiError.unauthorized("Sign in to continue")
        if auth["role"] not in roles:
            user = users_db.find_by_id(auth["user_id"])
            if user and user["role"] in roles:
                auth["role"] = user["role"]
                return
            raise ApiError.forbidden("Your account cannot do that")

    return step

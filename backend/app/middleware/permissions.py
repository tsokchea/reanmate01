"""Admin guards: ``require_admin`` and ``require_permission``.

Both run after ``authenticated`` and load the account, its role and its
permissions from the database on every request — a role or grant revoked a
second ago is already gone, whatever the access token says. The resolved
admin is left on ``g.admin`` for the controller.

Hiding a link in the React sidebar is only UX; these steps are the security.
"""

from flask import g, request

from ..services import audit_service, rbac_service
from .errors import ApiError


def require_admin():
    auth = g.get("auth")
    if not auth:
        raise ApiError.unauthorized("Sign in to continue")
    if g.get("admin") is not None:
        return
    actor = rbac_service.load_actor(auth["user_id"])
    if not actor or actor.row["status"] != "active":
        raise ApiError(401, "account_disabled", "This account is no longer active")
    if actor.role not in rbac_service.ADMIN_KINDS:
        raise ApiError(403, "admin_access_required", "This area is for administrators")
    g.admin = actor


def require_permission(*keys):
    """Passes when the admin holds at least one of ``keys`` (usually just one)."""

    def step():
        require_admin()
        actor = g.admin
        if not actor.has_any(*keys):
            audit_service.record_quietly(
                "PERMISSION_DENIED", actor=actor, resource="api",
                resource_id=f"{request.method} {request.path}", metadata={"required": list(keys)},
            )
            raise ApiError(403, "permission_denied", "You do not have permission to do that",
                           {"required": list(keys)})

    return step

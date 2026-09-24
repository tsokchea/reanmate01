"""The admin audit log. Entries are written, listed and never changed.

``record`` takes the transaction the change ran in when there is one, so an
action and its audit entry commit (or roll back) together.
"""

import logging

from flask import has_request_context, request

from ..models import audit as audit_db
from ..models.usage import DIRECT

log = logging.getLogger("reanmate")

ACTIONS = (
    "ADMIN_CREATED", "ADMIN_UPDATED", "ADMIN_DISABLED", "ADMIN_ENABLED", "ADMIN_DELETED",
    "USER_CREATED", "USER_UPDATED", "USER_DISABLED", "USER_ENABLED", "USER_DELETED",
    "ROLE_CREATED", "ROLE_UPDATED", "ROLE_DELETED", "PERMISSION_CHANGED", "LIMIT_CHANGED",
    "PASSWORD_RESET", "PASSWORD_CHANGED", "USAGE_RESET", "SYSTEM_SETTING_CHANGED", "CONTENT_DELETED",
    "PERMISSION_DENIED",
)


def _label(account):
    if not account:
        return None
    return account.get("email") or account.get("phone") or account.get("full_name") or account.get("id")


def record(action, *, actor=None, actor_row=None, target=None, resource=None, resource_id=None, metadata=None,
           tx=None):
    """``actor`` is an rbac Actor; ``actor_row`` a plain account row (for self-service actions)."""
    actor_account = actor.row if actor is not None else actor_row
    ip_address = user_agent = None
    if has_request_context():
        ip_address = request.remote_addr
        user_agent = (request.headers.get("User-Agent") or "")[:400] or None
    return audit_db.insert(
        tx or DIRECT,
        actor_user_id=(actor_account or {}).get("id"), actor_label=_label(actor_account), action=action,
        target_user_id=(target or {}).get("id"), target_label=_label(target), resource=resource,
        resource_id=resource_id, metadata=metadata or {}, ip_address=ip_address, user_agent=user_agent,
    )


def record_quietly(action, **kwargs):
    """For denials: a failed audit write must not turn a 403 into a 500."""
    try:
        record(action, **kwargs)
    except Exception as err:  # pragma: no cover - defensive
        log.warning("[audit] could not record %s: %s", action, err)


def to_api(row):
    return {
        "id": row["id"], "actorId": row["actor_user_id"], "actor": row["actor_label"], "action": row["action"],
        "targetId": row["target_user_id"], "target": row["target_label"], "resource": row["resource"],
        "resourceId": row["resource_id"], "metadata": row["metadata"], "ipAddress": row["ip_address"],
        "userAgent": row["user_agent"], "createdAt": row["created_at"],
    }

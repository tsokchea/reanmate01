"""The admin console API under /api/admin.

Every route: a session (``authenticated``), a per-admin rate limit, then
``require_permission`` — which loads the admin, its role and its permissions
from the database — before any parameter or body is read. Where an action's
exact permission depends on the account it touches (disabling a teacher
needs users.disable or teachers.manage; disabling an admin needs
admins.disable), the route requires any of them and the service applies the
precise rule to the stored account.
"""

from flask import Blueprint, g, request

from ..controllers import admin_controller as c
from ..middleware.permissions import require_admin, require_permission as perm
from ..middleware.rate_limit import rate_limit
from ..middleware.validate import validate_body, validate_params, validate_query
from ..validation import admin_schemas as s
from . import AUTH, add

bp = Blueprint("admin", __name__, url_prefix="/api/admin")


def _actor_key():
    auth = g.get("auth")
    return auth["user_id"] if auth else request.remote_addr


# Reads are generous; writes are tighter; password resets tighter still.
READ_LIMIT = rate_limit(scope="admin:read", window_ms=60_000, max_hits=240, key_from=_actor_key)
WRITE_LIMIT = rate_limit(scope="admin:write", window_ms=60_000, max_hits=60, key_from=_actor_key)
RESET_LIMIT = rate_limit(scope="admin:reset", window_ms=15 * 60_000, max_hits=20, key_from=_actor_key)

R = (*AUTH, READ_LIMIT)
W = (*AUTH, WRITE_LIMIT)

USER = validate_params(s.user_params)
ROLE = validate_params(s.role_params)

# Who am I and what may I do — any admin.
add(bp, "GET", "/me", c.me, R, require_admin)

# Dashboard: any admin; each section is filtered to what the admin may read.
add(bp, "GET", "/dashboard", c.dashboard, R, require_admin)
add(bp, "GET", "/dashboard/series", c.dashboard_series, R, perm("analytics.view", "usage.view"),
    validate_query(s.series_query))

# Accounts. Listing needs a view permission for at least one kind of account.
VIEW_ACCOUNTS = perm("users.view", "students.view", "teachers.view", "admins.view")
add(bp, "GET", "/users", c.list_users, R, VIEW_ACCOUNTS, validate_query(s.users_query))
add(bp, "POST", "/users", c.create_user, W, perm("users.create"), validate_body(s.create_user_body))
add(bp, "GET", "/users/<userId>", c.show_user, R, VIEW_ACCOUNTS, USER)
add(bp, "PATCH", "/users/<userId>", c.update_user, W, perm("users.edit", "teachers.manage", "admins.edit"), USER,
    validate_body(s.update_user_body))
add(bp, "POST", "/users/<userId>/disable", c.disable_user, W,
    perm("users.disable", "teachers.manage", "admins.disable"), USER)
add(bp, "POST", "/users/<userId>/enable", c.enable_user, W,
    perm("users.disable", "teachers.manage", "admins.disable"), USER)
add(bp, "DELETE", "/users/<userId>", c.delete_user, W, perm("users.delete", "admins.delete"), USER)
add(bp, "POST", "/users/<userId>/reset-password", c.reset_password, (*AUTH, RESET_LIMIT),
    perm("users.edit", "teachers.manage", "admins.edit"), USER)

# Admin accounts.
add(bp, "GET", "/admins", c.list_admins, R, perm("admins.view"), validate_query(s.page_query))
add(bp, "POST", "/admins", c.create_admin, W, perm("admins.create"), validate_body(s.create_admin_body))
add(bp, "GET", "/admins/<userId>", c.show_admin, R, perm("admins.view"), USER)
add(bp, "PATCH", "/admins/<userId>", c.update_admin, W, perm("admins.edit"), USER,
    validate_body(s.update_admin_body))
add(bp, "DELETE", "/admins/<userId>", c.delete_admin, W, perm("admins.delete"), USER)

# Roles and the permission catalogue. The admin forms need both to offer choices.
READ_ROLES = perm("roles.view", "roles.manage", "admins.create", "admins.edit")
add(bp, "GET", "/roles", c.list_roles, R, READ_ROLES)
add(bp, "POST", "/roles", c.create_role, W, perm("roles.manage"), validate_body(s.create_role_body))
add(bp, "PATCH", "/roles/<roleId>", c.update_role, W, perm("roles.manage"), ROLE, validate_body(s.update_role_body))
add(bp, "DELETE", "/roles/<roleId>", c.delete_role, W, perm("roles.manage"), ROLE)
add(bp, "GET", "/permissions", c.list_permissions, R, READ_ROLES)

# Usage.
add(bp, "GET", "/usage", c.usage, R, perm("usage.view"), validate_query(s.usage_query))
add(bp, "GET", "/usage/<userId>", c.account_usage, R, perm("usage.view"), USER)
add(bp, "POST", "/usage/<userId>/reset", c.reset_usage, W, perm("usage.manage"), USER)

# Limits: platform-wide role defaults, then per-account overrides.
add(bp, "GET", "/limits/defaults", c.limit_defaults, R, perm("limits.view"))
add(bp, "PATCH", "/limits/defaults/<roleId>", c.update_limit_defaults, W, perm("limits.manage"), ROLE,
    validate_body(s.limits_body))
add(bp, "GET", "/limits/<userId>", c.account_limits, R, perm("limits.view"), USER)
add(bp, "PATCH", "/limits/<userId>", c.update_account_limits, W, perm("limits.manage"), USER,
    validate_body(s.limits_body))

# Audit log — read-only by design; there is no route that changes it.
add(bp, "GET", "/audit-logs", c.audit_logs, R, perm("audit.view"), validate_query(s.audit_query))

# System settings.
add(bp, "GET", "/settings", c.settings, R, perm("settings.view", "settings.manage"))
add(bp, "PATCH", "/settings", c.update_settings, W, perm("settings.manage"), validate_body(s.settings_body))

# Content.
add(bp, "GET", "/content/sources", c.content_sources, R, perm("content.view"), validate_query(s.content_query))
add(bp, "DELETE", "/content/sources/<sourceId>", c.delete_source, W, perm("content.manage"),
    validate_params(s.source_params))
add(bp, "GET", "/content/classes", c.content_classes, R, perm("content.view"), validate_query(s.page_query))
add(bp, "GET", "/content/assignments", c.content_assignments, R, perm("assignments.view"),
    validate_query(s.page_query))
add(bp, "DELETE", "/content/assignments/<assignmentId>", c.delete_assignment, W, perm("assignments.manage"),
    validate_params(s.assignment_params))
add(bp, "GET", "/content/flashcards", c.content_flashcards, R, perm("flashcards.view"),
    validate_query(s.page_query))
add(bp, "DELETE", "/content/flashcards/<setId>", c.delete_flashcard_set, W, perm("flashcards.manage"),
    validate_params(s.flashcard_set_params))

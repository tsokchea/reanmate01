"""Who may do what in the admin console.

Permissions are always resolved server-side from the database — never from a
token claim or a request body. An account's effective permissions are:

  super_admin  every permission that exists (now and in future migrations)
  admin        its role's permissions plus any extra grants on the account
  anyone else  none

Two rules stop privilege escalation, and every grant path runs through them:

  1. An admin can only grant (to a role or an account) permissions it holds.
  2. An admin can only act on another admin whose permissions are a subset of
     its own, and never on itself or on a super admin.

Only a super admin can create, edit or promote to super admin.
"""

from ..middleware.errors import ApiError
from ..models import rbac as rbac_db

ADMIN_KINDS = ("admin", "super_admin")

# What each action on an account needs, by the account's kind; any one suffices.
ACCOUNT_ACTIONS = {
    "view": {"student": ("users.view", "students.view"), "teacher": ("users.view", "teachers.view"),
             "admin": ("admins.view",), "super_admin": ("admins.view",)},
    "edit": {"student": ("users.edit",), "teacher": ("users.edit", "teachers.manage"),
             "admin": ("admins.edit",), "super_admin": ("admins.edit",)},
    "disable": {"student": ("users.disable",), "teacher": ("users.disable", "teachers.manage"),
                "admin": ("admins.disable",), "super_admin": ("admins.disable",)},
    "delete": {"student": ("users.delete",), "teacher": ("users.delete",),
               "admin": ("admins.delete",), "super_admin": ("admins.delete",)},
}


class Actor:
    """The admin making a request, loaded fresh from the database."""

    def __init__(self, row, permissions):
        self.id = row["id"]
        self.row = row
        self.role = row["role"]
        self.is_super = row["role"] == "super_admin"
        self.permissions = frozenset(permissions)

    @property
    def label(self):
        return self.row.get("email") or self.row.get("phone") or self.row.get("full_name") or self.id

    def has(self, key):
        return key in self.permissions

    def has_any(self, *keys):
        return any(key in self.permissions for key in keys)


def kind_of(account):
    return account.get("role") or "student"


def permissions_of(account):
    """Effective permission keys for an account row (needs id, role, role_id)."""
    role = account.get("role")
    if role == "super_admin":
        return set(rbac_db.all_permission_keys())
    if role != "admin":
        return set()
    keys = set(rbac_db.keys_for_role(account["role_id"])) if account.get("role_id") else set()
    return keys | set(rbac_db.keys_for_user(account["id"]))


def load_actor(user_id):
    row = rbac_db.find_actor(user_id)
    if not row:
        return None
    return Actor(row, permissions_of(row))


def visible_kinds(actor):
    kinds = set()
    for kind, keys in ACCOUNT_ACTIONS["view"].items():
        if actor.has_any(*keys):
            kinds.add(kind)
    return kinds


def denied(message, code="permission_denied", details=None):
    return ApiError(403, code, message, details)


def require(actor, *keys):
    """At least one of ``keys``."""
    if not actor.has_any(*keys):
        raise denied("You do not have permission to do that", details={"required": list(keys)})


def assert_can_see(actor, account):
    """IDOR guard: an account outside the kinds this admin may view reads as missing."""
    if not account or kind_of(account) not in visible_kinds(actor):
        raise ApiError.not_found("That account does not exist")


def assert_can_act(actor, account, action):
    """The permission for ``action`` on this account, plus the admin-on-admin rules."""
    assert_can_see(actor, account)
    kind = kind_of(account)
    if account["id"] == actor.id:
        raise denied("You cannot change your own account from the admin console", "cannot_modify_self")
    if not actor.has_any(*ACCOUNT_ACTIONS[action][kind]):
        raise denied("You do not have permission to do that",
                     details={"required": list(ACCOUNT_ACTIONS[action][kind])})
    assert_outranks(actor, account)


def assert_outranks(actor, account):
    """A super admin is only touched by a super admin; an admin only by someone holding all its permissions."""
    kind = kind_of(account)
    if kind == "super_admin" and not actor.is_super:
        raise denied("Only a super admin can change a super admin account", "super_admin_protected")
    if kind == "admin" and not actor.is_super and not permissions_of(account) <= actor.permissions:
        raise denied("That admin holds permissions you do not have", "target_outranks_actor")


def assert_can_grant(actor, keys):
    """Rule 1: nobody hands out a permission they do not hold themselves."""
    keys = set(keys)
    unknown = keys - set(rbac_db.all_permission_keys())
    if unknown:
        raise ApiError(422, "validation_failed", "Unknown permission",
                       [{"path": "permissions", "code": "invalid_value",
                         "message": f"Unknown permission: {', '.join(sorted(unknown))}"}])
    if actor.is_super:
        return
    missing = keys - actor.permissions
    if missing:
        raise denied("You cannot grant permissions you do not hold", "permission_escalation",
                     {"permissions": sorted(missing)})


def assert_can_assign_role(actor, role):
    """Assigning a role grants everything in it."""
    if not role or role["kind"] not in ADMIN_KINDS:
        raise ApiError(422, "validation_failed", "Choose an admin role",
                       [{"path": "roleId", "code": "invalid_value", "message": "Choose an admin role"}])
    if role["kind"] == "super_admin" and not actor.is_super:
        raise denied("Only a super admin can create or promote a super admin", "super_admin_required")
    assert_can_grant(actor, rbac_db.keys_for_role(role["id"]))

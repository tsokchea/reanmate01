"""Accounts in the admin console: students, teachers and admins.

Every function takes the acting admin (an rbac_service.Actor) first. Route
guards have already required a coarse permission; the precise rule — which
permission this action needs on this particular account, and whether the
actor outranks it — is checked here, against the account as stored.
"""

import datetime as dt
import secrets
import sqlite3

from ..extensions import is_unique_violation, transaction
from ..middleware.errors import ApiError
from ..models import admin as admin_db
from ..models import audit as audit_db
from ..models import rbac as rbac_db
from ..models import usage as usage_db
from ..models.usage import LIMIT_FIELDS
from . import audit_service, rbac_service, usage_service
from .auth_service import hash_password

TABS = {
    "all": ("student", "teacher", "admin", "super_admin"),
    "students": ("student",),
    "teachers": ("teacher",),
    "admins": ("admin", "super_admin"),
    "disabled": ("student", "teacher", "admin", "super_admin"),
}


def temporary_password():
    # 16 URL-safe characters (~96 bits): readable over the phone, never guessable.
    return secrets.token_urlsafe(12)


def _page(data):
    page = max(1, int(data.get("page") or 1))
    size = min(100, max(1, int(data.get("pageSize") or 20)))
    return page, size


def _like(text):
    """User search text as a literal: % and _ are not wildcards here."""
    if not text:
        return None
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def to_api(row, *, permissions=None, extra_permissions=None):
    out = {
        "id": row["id"], "fullName": row["full_name"], "email": row["email"], "phone": row["phone"],
        "kind": row.get("kind") or rbac_service.kind_of(row),
        "role": {"id": row["role_id"], "key": row.get("role_key"), "name": row.get("role_name")},
        "status": row["status"], "mustChangePassword": bool(row.get("must_change_password")),
        "createdAt": row["created_at"], "lastLoginAt": row.get("last_login_at"),
        "lastSeenAt": row.get("last_seen_at"),
    }
    if "today_tokens" in row:
        out["aiUsage"] = {"todayTokens": row["today_tokens"], "monthTokens": row["month_tokens"]}
    if permissions is not None:
        out["permissions"] = sorted(permissions)
    if extra_permissions is not None:
        out["extraPermissions"] = sorted(extra_permissions)
    return out


def me(actor):
    return {
        "user": to_api(admin_db.find_account(actor.id)),
        "permissions": sorted(actor.permissions),
        "isSuperAdmin": actor.is_super,
    }


def _account(actor, user_id):
    account = admin_db.find_account(user_id)
    rbac_service.assert_can_see(actor, account)
    return account


# --- lists -------------------------------------------------------------------------------


def list_accounts(actor, data):
    tab = data.get("tab") or "all"
    visible = rbac_service.visible_kinds(actor)
    kinds = [kind for kind in TABS[tab] if kind in visible]
    if not kinds:
        raise rbac_service.denied("You do not have permission to view these accounts")
    page, size = _page(data)
    rows, total = admin_db.list_accounts(
        kinds=kinds, status="disabled" if tab == "disabled" else data.get("status"), q=_like(data.get("q")),
        sort=data.get("sort") or "created", limit=size, offset=(page - 1) * size,
        today=usage_service.today(), month_start=usage_service.month_start(),
    )
    return {"users": [to_api(row) for row in rows], "page": page, "pageSize": size, "total": total}


def list_admins(actor, data):
    page, size = _page(data)
    rows, total = admin_db.list_accounts(
        kinds=["admin", "super_admin"], status=data.get("status"), q=_like(data.get("q")), sort="created",
        limit=size, offset=(page - 1) * size, today=usage_service.today(), month_start=usage_service.month_start(),
    )
    extras = rbac_db.extra_keys_by_user([row["id"] for row in rows])
    by_role = rbac_db.keys_by_role()
    all_keys = rbac_db.all_permission_keys()
    admins = []
    for row in rows:
        permissions = all_keys if row["role"] == "super_admin" else {*by_role.get(row["role_id"], []),
                                                                     *extras[row["id"]]}
        item = to_api(row, permissions=permissions, extra_permissions=extras[row["id"]])
        if actor.has("limits.view"):
            limits = usage_service.effective_limits(row["id"])
            item["limits"] = {"dailyAiTokens": limits["dailyAiTokens"], "monthlyAiTokens": limits["monthlyAiTokens"]}
        admins.append(item)
    return {"admins": admins, "page": page, "pageSize": size, "total": total}


# --- detail ------------------------------------------------------------------------------


def detail(actor, user_id):
    account = _account(actor, user_id)
    permissions = rbac_service.permissions_of(account)
    out = {"user": to_api(account, permissions=permissions,
                          extra_permissions=rbac_db.keys_for_user(user_id) if account["role"] == "admin" else [])}
    if actor.has_any("usage.view", "limits.view"):
        out["usage"] = {**usage_service.usage_snapshot(user_id), "storageBytesTotal": admin_db.storage_bytes(user_id)}
    if actor.has("limits.view"):
        out["limits"] = usage_service.limits_payload(user_id)
    if actor.has_any("usage.view", "analytics.view"):
        out["activity"] = {
            "ai": [{"id": r["id"], "kind": r["kind"], "model": r["model"], "status": r["status"],
                    "totalTokens": r["total_tokens"], "createdAt": r["created_at"]} for r in admin_db.recent_ai(user_id)],
            "uploads": [{"id": r["id"], "title": r["title"], "kind": r["kind"], "status": r["status"],
                         "byteSize": r["byte_size"], "kitTitle": r["kit_title"], "createdAt": r["created_at"]}
                        for r in admin_db.recent_uploads(user_id)],
            "assignments": [{"id": r["id"], "title": r["title"], "classTitle": r["class_title"],
                             "relation": r["relation"], "status": r["status"], "at": r["at"]}
                            for r in admin_db.recent_assignments(user_id)],
            "logins": [{"id": r["id"], "ipAddress": r["ip_address"], "userAgent": r["user_agent"],
                        "createdAt": r["created_at"]} for r in admin_db.recent_logins(user_id)],
        }
    if actor.has("audit.view"):
        out["audit"] = [audit_service.to_api(row) for row in audit_db.for_target(user_id)]
    return out


# --- create ------------------------------------------------------------------------------


def _assert_identifier_free(email, phone, except_id=None):
    taken = admin_db.email_or_phone_taken(email=email, phone=phone, except_id=except_id)
    if taken["email"]:
        raise ApiError.conflict("That email is already registered", {"field": "email"})
    if taken["phone"]:
        raise ApiError.conflict("That phone number is already registered", {"field": "phone"})


def _limit_columns(limits):
    return {LIMIT_FIELDS[field]: value for field, value in (limits or {}).items() if field in LIMIT_FIELDS}


def create_user(actor, data):
    """A student or teacher account, created with a temporary password."""
    email, phone = data.get("email"), data.get("phone")
    _assert_identifier_free(email, phone)
    password = data.get("temporaryPassword") or temporary_password()
    try:
        with transaction() as tx:
            created = admin_db.create_account(
                tx, full_name=data["fullName"], email=email, phone=phone, password_hash=hash_password(password),
                role=data["role"], role_id=None, status="active", locale=data.get("locale") or "km",
                verified_at=dt.datetime.now(dt.timezone.utc),
            )
            account = admin_db.find_account(created["id"])
            audit_service.record("USER_CREATED", actor=actor, target=account, resource="user",
                                 resource_id=account["id"], metadata={"kind": data["role"]}, tx=tx)
    except sqlite3.IntegrityError as err:
        if is_unique_violation(err):
            raise ApiError.conflict("That account already exists") from err
        raise
    out = {"user": to_api(admin_db.find_account(created["id"]))}
    if not data.get("temporaryPassword"):
        out["temporaryPassword"] = password
    return out


def create_admin(actor, data):
    role = rbac_db.find_role(data["roleId"])
    rbac_service.assert_can_assign_role(actor, role)
    extra = sorted(set(data.get("permissions") or []) - set(rbac_db.keys_for_role(role["id"])))
    rbac_service.assert_can_grant(actor, extra)
    if role["kind"] == "super_admin":
        extra = []  # a super admin already holds everything
    limits = _limit_columns(data.get("limits"))
    if limits and not actor.has("limits.manage"):
        raise rbac_service.denied("You do not have permission to set usage limits", details={"required": ["limits.manage"]})

    email = data["email"]
    _assert_identifier_free(email, None)
    password = data.get("temporaryPassword") or temporary_password()
    try:
        with transaction() as tx:
            created = admin_db.create_account(
                tx, full_name=data["fullName"], email=email, phone=None, password_hash=hash_password(password),
                role=role["kind"], role_id=role["id"], status=data.get("status") or "active",
                locale=data.get("locale") or "en", verified_at=dt.datetime.now(dt.timezone.utc),
            )
            rbac_db.replace_user_permissions(tx, user_id=created["id"], keys=extra, granted_by=actor.id)
            if limits:
                usage_db.upsert_account_limits(tx, created["id"], limits, actor.id)
            account = admin_db.find_account(created["id"])
            audit_service.record(
                "ADMIN_CREATED", actor=actor, target=account, resource="user", resource_id=account["id"],
                metadata={"role": role["key"], "extraPermissions": extra, "status": account["status"]}, tx=tx)
            if limits:
                audit_service.record("LIMIT_CHANGED", actor=actor, target=account, resource="account_limits",
                                     resource_id=account["id"], metadata={"after": data.get("limits")}, tx=tx)
    except sqlite3.IntegrityError as err:
        if is_unique_violation(err):
            raise ApiError.conflict("That account already exists", {"field": "email"}) from err
        raise
    account = admin_db.find_account(created["id"])
    out = {"admin": to_api(account, permissions=rbac_service.permissions_of(account), extra_permissions=extra)}
    if not data.get("temporaryPassword"):
        out["temporaryPassword"] = password
    return out


# --- update ------------------------------------------------------------------------------


def update_user(actor, user_id, data):
    """Profile fields and the student/teacher switch. Admin accounts go through update_admin."""
    account = _account(actor, user_id)
    if account["role"] in rbac_service.ADMIN_KINDS:
        return update_admin(actor, user_id, data)
    rbac_service.assert_can_act(actor, account, "edit")

    values = {}
    if "fullName" in data:
        values["full_name"] = data["fullName"]
    if "email" in data or "phone" in data:
        email = data.get("email", account["email"])
        phone = data.get("phone", account["phone"])
        if not email and not phone:
            raise ApiError.bad_request("Provide an email address or a phone number", {"fields": ["email", "phone"]})
        _assert_identifier_free(email if "email" in data else None, phone if "phone" in data else None, user_id)
        values["email"], values["phone"] = email, phone
    if "role" in data and data["role"] != account["role"]:
        # Moving between student and teacher changes what the account can reach.
        rbac_service.require(actor, "users.edit")
        values["role"] = data["role"]

    before = {"fullName": account["full_name"], "email": account["email"], "phone": account["phone"],
              "role": account["role"]}
    with transaction() as tx:
        admin_db.update_account(tx, user_id, values)
        after_row = admin_db.find_account(user_id)
        audit_service.record("USER_UPDATED", actor=actor, target=after_row, resource="user", resource_id=user_id,
                             metadata={"before": before, "changed": sorted(data)}, tx=tx)
    return {"user": to_api(admin_db.find_account(user_id))}


def update_admin(actor, user_id, data):
    account = _account(actor, user_id)
    if account["role"] not in rbac_service.ADMIN_KINDS:
        raise ApiError.not_found("That admin does not exist")

    touches_access = "roleId" in data or "permissions" in data
    if account["id"] == actor.id:
        # Your own name and email only; never your own role or permissions.
        if touches_access:
            raise rbac_service.denied("You cannot change your own role or permissions", "cannot_modify_self")
    else:
        rbac_service.assert_can_act(actor, account, "edit")

    values = {}
    if "fullName" in data:
        values["full_name"] = data["fullName"]
    if "email" in data:
        _assert_identifier_free(data["email"], None, user_id)
        values["email"] = data["email"]

    role = None
    if "roleId" in data and data["roleId"] != account["role_id"]:
        role = rbac_db.find_role(data["roleId"])
        rbac_service.assert_can_assign_role(actor, role)
        values["role"], values["role_id"] = role["kind"], role["id"]

    new_role_id = role["id"] if role else account["role_id"]
    new_kind = role["kind"] if role else account["role"]
    old_extra = rbac_db.keys_for_user(user_id)
    new_extra = None
    if "permissions" in data or role is not None:
        wanted = set(data["permissions"]) if "permissions" in data else set(old_extra)
        new_extra = [] if new_kind == "super_admin" else sorted(wanted - set(rbac_db.keys_for_role(new_role_id)))
        rbac_service.assert_can_grant(actor, set(new_extra) - set(old_extra))

    before_permissions = rbac_service.permissions_of(account)
    try:
        with transaction() as tx:
            admin_db.update_account(tx, user_id, values)
            if new_extra is not None:
                rbac_db.replace_user_permissions(tx, user_id=user_id, keys=new_extra, granted_by=actor.id)
            updated = admin_db.find_account(user_id)
            after_permissions = rbac_service.permissions_of(updated)
            audit_service.record("ADMIN_UPDATED", actor=actor, target=updated, resource="user", resource_id=user_id,
                                 metadata={"changed": sorted(data), "role": updated["role_key"]}, tx=tx)
            if before_permissions != after_permissions:
                audit_service.record(
                    "PERMISSION_CHANGED", actor=actor, target=updated, resource="user", resource_id=user_id,
                    metadata={"added": sorted(after_permissions - before_permissions),
                              "removed": sorted(before_permissions - after_permissions)}, tx=tx)
    except sqlite3.IntegrityError as err:
        _translate_integrity(err)
        raise
    updated = admin_db.find_account(user_id)
    return {"admin": to_api(updated, permissions=rbac_service.permissions_of(updated),
                            extra_permissions=rbac_db.keys_for_user(user_id))}


def _translate_integrity(err):
    if "last_active_super_admin" in str(err):
        raise ApiError.conflict("The platform must keep at least one active super admin",
                                {"code": "last_super_admin"}) from err
    if is_unique_violation(err):
        raise ApiError.conflict("That email is already registered", {"field": "email"}) from err


# --- status, deletion, passwords -----------------------------------------------------


def _is_admin(account):
    return account["role"] in rbac_service.ADMIN_KINDS


def set_status(actor, user_id, status):
    account = _account(actor, user_id)
    rbac_service.assert_can_act(actor, account, "disable")
    if account["status"] == status:
        return {"user": to_api(account)}
    prefix = "ADMIN" if _is_admin(account) else "USER"
    action = f"{prefix}_{'ENABLED' if status == 'active' else 'DISABLED'}"
    try:
        with transaction() as tx:
            admin_db.set_status(tx, user_id, status)
            if status != "active":
                admin_db.revoke_sessions(tx, user_id)
            audit_service.record(action, actor=actor, target=account, resource="user", resource_id=user_id,
                                 metadata={"from": account["status"], "to": status}, tx=tx)
    except sqlite3.IntegrityError as err:
        _translate_integrity(err)
        raise
    return {"user": to_api(admin_db.find_account(user_id))}


def delete(actor, user_id, *, admins_only=False):
    account = _account(actor, user_id)
    if admins_only and not _is_admin(account):
        raise ApiError.not_found("That admin does not exist")
    rbac_service.assert_can_act(actor, account, "delete")
    action = "ADMIN_DELETED" if _is_admin(account) else "USER_DELETED"
    try:
        with transaction() as tx:
            if account["status"] == "active" and account["role"] == "super_admin":
                # Runs the last-super-admin trigger before anything is anonymised.
                admin_db.set_status(tx, user_id, "disabled")
            admin_db.revoke_sessions(tx, user_id)
            audit_service.record(action, actor=actor, target=account, resource="user", resource_id=user_id,
                                 metadata={"kind": rbac_service.kind_of(account)}, tx=tx)
            admin_db.soft_delete(tx, user_id)
    except sqlite3.IntegrityError as err:
        _translate_integrity(err)
        raise
    return {"deleted": True, "id": user_id}


def reset_password(actor, user_id):
    account = _account(actor, user_id)
    rbac_service.assert_can_act(actor, account, "edit")
    password = temporary_password()
    with transaction() as tx:
        admin_db.set_password(tx, user_id, hash_password(password), must_change=True)
        admin_db.revoke_sessions(tx, user_id)
        audit_service.record("PASSWORD_RESET", actor=actor, target=account, resource="user", resource_id=user_id,
                             tx=tx)
    # Returned once, to be passed on to the account holder; it is never stored in clear.
    return {"temporaryPassword": password, "mustChangePassword": True}

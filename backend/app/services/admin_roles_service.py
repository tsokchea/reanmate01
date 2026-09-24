"""Roles, the permission catalogue, and usage limits (role defaults and per-account overrides)."""

import datetime as dt
import re

from ..extensions import transaction
from ..middleware.errors import ApiError
from ..models import admin as admin_db
from ..models import rbac as rbac_db
from ..models import usage as usage_db
from ..models.usage import LIMIT_FIELDS
from . import audit_service, rbac_service, usage_service
from .admin_accounts_service import _like

# Custom roles start with the same allowance as the built-in support role.
NEW_ROLE_LIMITS = {
    "daily_ai_tokens": 50000, "monthly_ai_tokens": 1000000, "daily_pdf_uploads": 20, "monthly_pdf_uploads": 300,
    "daily_assignments": 100, "monthly_assignments": 2000, "daily_flashcards": 200, "monthly_flashcards": 5000,
    "daily_tutor_messages": 200, "monthly_tutor_messages": None,
    "daily_file_storage_bytes": 209715200, "monthly_file_storage_bytes": 2147483648,
}


def _role_api(row, permissions, limits=None):
    out = {
        "id": row["id"], "key": row["key"], "name": row["name"], "description": row["description"],
        "kind": row["kind"], "isSystemRole": bool(row["is_system_role"]), "userCount": row.get("user_count", 0),
        "permissions": sorted(permissions), "createdAt": row["created_at"], "updatedAt": row["updated_at"],
        # Teacher and student roles carry no admin permissions, and the super
        # admin role always holds all of them, so none of the three is editable.
        "editable": row["kind"] == "admin",
    }
    if limits is not None:
        out["limits"] = {field: limits.get(column) for field, column in LIMIT_FIELDS.items()}
    return out


def permissions_catalogue():
    groups = {}
    for row in rbac_db.list_permissions():
        groups.setdefault(row["category"], []).append({"key": row["key"], "description": row["description"]})
    return {"permissions": [{"category": category, "permissions": items} for category, items in groups.items()]}


def list_roles(actor):
    by_role = rbac_db.keys_by_role()
    all_keys = rbac_db.all_permission_keys()
    limits = usage_db.all_role_limits() if actor.has("limits.view") else None
    roles = []
    for row in rbac_db.list_roles():
        keys = all_keys if row["kind"] == "super_admin" else by_role.get(row["id"], [])
        roles.append(_role_api(row, keys, limits.get(row["id"], {}) if limits is not None else None))
    return {"roles": roles}


def _key_from(name):
    key = re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")
    key = key if key and key[0].isalpha() else f"ROLE_{key}"
    return key[:64]


def _editable(actor, role):
    if not role:
        raise ApiError.not_found("That role does not exist")
    if role["kind"] != "admin":
        raise rbac_service.denied("That role cannot be changed", "system_role_locked")
    if not actor.is_super:
        if actor.row["role_id"] == role["id"]:
            raise rbac_service.denied("You cannot change the role you hold", "cannot_modify_self")
        if not set(rbac_db.keys_for_role(role["id"])) <= actor.permissions:
            raise rbac_service.denied("That role holds permissions you do not have", "target_outranks_actor")
    return role


def create_role(actor, data):
    permissions = sorted(set(data.get("permissions") or []))
    rbac_service.assert_can_grant(actor, permissions)
    key = data.get("key") or _key_from(data["name"])
    if rbac_db.role_key_taken(key):
        raise ApiError.conflict("A role with that key already exists", {"field": "key"})
    with transaction() as tx:
        role = rbac_db.create_role(tx, key=key, name=data["name"], description=data.get("description"))
        rbac_db.replace_role_permissions(tx, role_id=role["id"], keys=permissions)
        usage_db.upsert_role_limits(tx, role["id"], NEW_ROLE_LIMITS, actor.id)
        audit_service.record("ROLE_CREATED", actor=actor, resource="role", resource_id=role["id"],
                             metadata={"key": key, "name": data["name"], "permissions": permissions}, tx=tx)
    return {"role": _role_api(rbac_db.find_role(role["id"]), permissions)}


def update_role(actor, role_id, data):
    role = _editable(actor, rbac_db.find_role(role_id))
    before = set(rbac_db.keys_for_role(role_id))
    after = before
    if "permissions" in data:
        after = set(data["permissions"])
        rbac_service.assert_can_grant(actor, after - before)
    with transaction() as tx:
        rbac_db.update_role(tx, role_id, name=data.get("name", role["name"]),
                            description=data.get("description", role["description"]))
        if after != before:
            rbac_db.replace_role_permissions(tx, role_id=role_id, keys=sorted(after))
        audit_service.record("ROLE_UPDATED", actor=actor, resource="role", resource_id=role_id,
                             metadata={"key": role["key"], "changed": sorted(data)}, tx=tx)
        if after != before:
            audit_service.record("PERMISSION_CHANGED", actor=actor, resource="role", resource_id=role_id,
                                 metadata={"key": role["key"], "added": sorted(after - before),
                                           "removed": sorted(before - after)}, tx=tx)
    return {"role": _role_api(rbac_db.find_role(role_id), after)}


def delete_role(actor, role_id):
    role = _editable(actor, rbac_db.find_role(role_id))
    if role["is_system_role"]:
        raise rbac_service.denied("Built-in roles cannot be deleted", "system_role_locked")
    holders = rbac_db.users_holding_role(role_id)
    if holders:
        raise ApiError.conflict("Move the accounts holding this role to another role first", {"users": holders})
    with transaction() as tx:
        rbac_db.delete_role(tx, role_id)
        audit_service.record("ROLE_DELETED", actor=actor, resource="role", resource_id=role_id,
                             metadata={"key": role["key"], "name": role["name"]}, tx=tx)
    return {"deleted": True, "id": role_id}


# --- limits -----------------------------------------------------------------------------


def _limit_values(data):
    return {LIMIT_FIELDS[field]: value for field, value in data.items() if field in LIMIT_FIELDS}


def role_limit_defaults(actor):
    limits = usage_db.all_role_limits()
    return {"roles": [
        {"id": row["id"], "key": row["key"], "name": row["name"], "kind": row["kind"],
         "limits": {field: limits.get(row["id"], {}).get(column) for field, column in LIMIT_FIELDS.items()}}
        for row in rbac_db.list_roles()
    ]}


def update_role_limits(actor, role_id, data):
    role = rbac_db.find_role(role_id)
    if not role:
        raise ApiError.not_found("That role does not exist")
    if role["kind"] == "super_admin" and not actor.is_super:
        raise rbac_service.denied("Only a super admin can change super admin limits", "super_admin_protected")
    if not actor.is_super and actor.row["role_id"] == role_id:
        raise rbac_service.denied("You cannot change the limits of the role you hold", "cannot_modify_self")
    values = _limit_values(data)
    before = usage_db.role_limits(role_id) or {}
    with transaction() as tx:
        after = usage_db.upsert_role_limits(tx, role_id, values, actor.id)
        audit_service.record(
            "LIMIT_CHANGED", actor=actor, resource="role_limits", resource_id=role_id,
            metadata={"role": role["key"],
                      "before": {f: before.get(c) for f, c in LIMIT_FIELDS.items() if c in values},
                      "after": {f: after.get(c) for f, c in LIMIT_FIELDS.items() if c in values}}, tx=tx)
    return {"role": {"id": role_id, "key": role["key"],
                     "limits": {field: after.get(column) for field, column in LIMIT_FIELDS.items()}}}


def account_limits(actor, user_id):
    account = admin_db.find_account(user_id)
    rbac_service.assert_can_see(actor, account)
    return {"userId": user_id, **usage_service.limits_payload(user_id), "usage": usage_service.usage_snapshot(user_id)}


def update_account_limits(actor, user_id, data):
    account = admin_db.find_account(user_id)
    rbac_service.assert_can_see(actor, account)
    if account["id"] == actor.id and not actor.is_super:
        raise rbac_service.denied("You cannot change your own limits", "cannot_modify_self")
    if account["id"] != actor.id:
        rbac_service.assert_outranks(actor, account)
    values = _limit_values(data)
    before = usage_service.limits_payload(user_id)["overrides"]
    with transaction() as tx:
        usage_db.upsert_account_limits(tx, user_id, values, actor.id)
        audit_service.record(
            "LIMIT_CHANGED", actor=actor, target=account, resource="account_limits", resource_id=user_id,
            metadata={"before": {f: before[f] for f in data if f in LIMIT_FIELDS},
                      "after": {f: data[f] for f in data if f in LIMIT_FIELDS}}, tx=tx)
    return account_limits(actor, user_id)


# --- usage ------------------------------------------------------------------------------


def usage_overview(actor, data):
    kinds = sorted(rbac_service.visible_kinds(actor)) or ["student"]
    if data.get("kind"):
        kinds = [kind for kind in kinds if kind == data["kind"]]
    page = max(1, int(data.get("page") or 1))
    size = min(100, max(1, int(data.get("pageSize") or 20)))
    rows, total = admin_db.usage_page(kinds=kinds, q=_like(data.get("q")), limit=size, offset=(page - 1) * size,
                                      today=usage_service.today(), month_start=usage_service.month_start())
    accounts = []
    for row in rows:
        limits = usage_service.effective_limits(row["id"])
        accounts.append({
            "id": row["id"], "fullName": row["full_name"], "email": row["email"], "phone": row["phone"],
            "kind": row["kind"], "roleName": row["role_name"], "status": row["status"],
            "today": {"aiTotalTokens": row["tokens_today"], "tutorMessages": row["tutor_today"]},
            "month": {"aiTotalTokens": row["tokens_month"], "pdfUploads": row["uploads_month"],
                      "storageBytes": row["storage_month"]},
            "limits": {"dailyAiTokens": limits["dailyAiTokens"], "monthlyAiTokens": limits["monthlyAiTokens"]},
        })
    return {"accounts": accounts, "page": page, "pageSize": size, "total": total}


def account_usage(actor, user_id):
    account = admin_db.find_account(user_id)
    rbac_service.assert_can_see(actor, account)
    since = (dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=29)).isoformat()
    daily = [{"date": row["day"], **{field: row[column] for field, column in usage_db.USAGE_FIELDS.items()}}
             for row in usage_db.daily(user_id, since)]
    out = {"userId": user_id, **usage_service.usage_snapshot(user_id), "daily": daily}
    if actor.has("limits.view"):
        out["limits"] = usage_service.limits_payload(user_id)["effective"]
    return out


def reset_usage_today(actor, user_id):
    account = admin_db.find_account(user_id)
    rbac_service.assert_can_see(actor, account)
    if account["id"] == actor.id and not actor.is_super:
        raise rbac_service.denied("You cannot reset your own usage", "cannot_modify_self")
    if account["id"] != actor.id:
        rbac_service.assert_outranks(actor, account)
    with transaction() as tx:
        previous = usage_db.reset_day(tx, user_id, usage_service.today())
        audit_service.record("USAGE_RESET", actor=actor, target=account, resource="usage_records",
                             resource_id=user_id, metadata={"date": usage_service.today(), "previous": previous or {}},
                             tx=tx)
    return {"userId": user_id, **usage_service.usage_snapshot(user_id)}

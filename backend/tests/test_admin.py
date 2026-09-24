"""RBAC, admin management, usage limits and the audit log — end to end.

Ordered and stateful like test_api.py: a super admin is bootstrapped the way
production does it (scripts.create_super_admin), then hands out narrower
admin accounts and every rule is checked from the side that should be
refused as well as the side that should be let through.
"""

import io
import sqlite3

import pytest

from app.extensions import query, query_one
from app.middleware.rate_limit import reset_rate_limits
from scripts import create_super_admin

S = {}
PASSWORD = "correct-horse-battery"
MISSING_ID = "11111111-1111-4111-8111-111111111111"


def err(response):
    return response.get_json()["error"]


@pytest.fixture(scope="module")
def clients(app):
    made = {}

    def client(name):
        if name not in made:
            made[name] = app.test_client()
        return made[name]

    return client


def login(client, email, password):
    reset_rate_limits()
    r = client.post("/api/auth/login", json={"identifier": email, "password": password})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["user"]


def settle_password(client, email, temporary):
    """Signs in with a temporary password and replaces it, as a new admin must."""
    user = login(client, email, temporary)
    assert user["must_change_password"] is True
    r = client.post("/api/auth/password", json={"currentPassword": temporary, "newPassword": PASSWORD})
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["user"]["must_change_password"] is False


def role_id(client, key):
    roles = client.get("/api/admin/roles").get_json()["roles"]
    return next(role["id"] for role in roles if role["key"] == key)


# --- bootstrap ---------------------------------------------------------------------------


def test_super_admin_bootstrap_requires_password_change(clients):
    S["super_id"] = create_super_admin.create("owner@admin-test.example", "Owner", "temporary-pass-1")
    root = clients("super")
    login(root, "owner@admin-test.example", "temporary-pass-1")

    # A temporary password opens nothing but the password change.
    r = root.get("/api/admin/me")
    assert r.status_code == 403 and err(r)["code"] == "password_change_required"
    assert root.get("/api/auth/me").status_code == 200

    wrong = root.post("/api/auth/password", json={"currentPassword": "nope-nope", "newPassword": PASSWORD})
    assert wrong.status_code == 422 and wrong.get_json()["error"]["details"][0]["path"] == "currentPassword"
    assert root.post("/api/auth/password",
                     json={"currentPassword": "temporary-pass-1", "newPassword": PASSWORD}).status_code == 200

    me = root.get("/api/admin/me").get_json()
    assert me["isSuperAdmin"] is True
    assert set(me["permissions"]) >= {"admins.create", "limits.manage", "roles.manage", "settings.manage"}
    assert me["user"]["role"]["key"] == "SUPER_ADMIN"


def test_students_and_teachers_get_their_system_roles(clients, app):
    for name, role in (("student", "student"), ("teacher", "teacher")):
        reset_rate_limits()
        r = clients(name).post("/api/auth/register", json={
            "fullName": f"RBAC {name}", "email": f"{name}@admin-test.example", "password": PASSWORD, "role": role})
        assert r.status_code == 201
        S[f"{name}_id"] = r.get_json()["user"]["id"]
    rows = {row["id"]: row["key"] for row in query(
        "SELECT u.id, r.key FROM users u JOIN roles r ON r.id = u.role_id WHERE u.id IN ($1, $2)",
        [S["student_id"], S["teacher_id"]]).rows}
    assert rows == {S["student_id"]: "STUDENT", S["teacher_id"]: "TEACHER"}


@pytest.mark.parametrize("who", ["student", "teacher"])
def test_students_and_teachers_cannot_reach_the_admin_api(clients, who):
    client = clients(who)
    for method, path in (("get", "/api/admin/me"), ("get", "/api/admin/users"), ("post", "/api/admin/admins"),
                         ("patch", f"/api/admin/limits/{MISSING_ID}"), ("get", "/api/admin/audit-logs"),
                         ("get", "/api/admin/no-such-route")):
        r = getattr(client, method)(path, json={})
        assert r.status_code == 403 and err(r)["code"] == "admin_access_required", (method, path, r.get_json())


def test_anonymous_requests_are_rejected(app):
    r = app.test_client().get("/api/admin/users")
    assert r.status_code == 401


def test_a_token_role_claim_cannot_grant_admin(clients):
    """Permissions come from the database: a forged/stale role in the JWT changes nothing."""
    import jwt

    from app.config import config
    from app.services.token_service import ACCESS_COOKIE

    token = jwt.encode({"sub": S["student_id"], "role": "super_admin", "iat": 0, "exp": 4102444800},
                       config.JWT_SECRET, algorithm="HS256")
    client = clients("forged")
    client.set_cookie(ACCESS_COOKIE, token)
    r = client.get("/api/admin/users")
    assert r.status_code == 403 and err(r)["code"] == "admin_access_required"


def test_onboarding_cannot_touch_admin_roles(clients):
    root = clients("super")
    r = root.post("/api/onboarding/role", json={"role": "student"})
    assert r.status_code == 403 and err(r)["code"] == "admin_account"
    r = clients("student").post("/api/onboarding/role", json={"role": "admin"})
    assert r.status_code == 422


# --- creating admins ---------------------------------------------------------------------


def test_super_admin_creates_a_support_admin(clients):
    root = clients("super")
    r = root.post("/api/admin/admins", json={
        "fullName": "Support Staff", "email": "support@admin-test.example",
        "roleId": role_id(root, "SUPPORT_ADMIN"),
        "limits": {"dailyAiTokens": 50000, "monthlyAiTokens": 1000000},
    })
    assert r.status_code == 201, r.get_json()
    body = r.get_json()
    S["support_id"] = body["admin"]["id"]
    assert body["admin"]["kind"] == "admin" and body["admin"]["mustChangePassword"] is True
    assert set(body["admin"]["permissions"]) == {"users.view", "students.view", "teachers.view", "usage.view"}
    settle_password(clients("support"), "support@admin-test.example", body["temporaryPassword"])

    limits = root.get(f"/api/admin/limits/{S['support_id']}").get_json()
    assert limits["effective"]["dailyAiTokens"] == 50000 and limits["source"]["dailyAiTokens"] == "account"
    assert limits["effective"]["dailyPdfUploads"] == 20 and limits["source"]["dailyPdfUploads"] == "role"


def test_a_limited_admin_sees_only_what_it_was_granted(clients):
    support = clients("support")
    me = support.get("/api/admin/me").get_json()
    assert me["isSuperAdmin"] is False
    assert sorted(me["permissions"]) == ["students.view", "teachers.view", "usage.view", "users.view"]

    students = support.get("/api/admin/users?tab=students").get_json()
    assert students["total"] >= 1 and all(u["kind"] == "student" for u in students["users"])
    # "All" quietly leaves out the kinds it cannot see.
    assert all(u["kind"] in ("student", "teacher") for u in support.get("/api/admin/users").get_json()["users"])

    r = support.get("/api/admin/users?tab=admins")
    assert r.status_code == 403
    # IDOR: an account of a kind it cannot view reads as missing, not forbidden.
    assert support.get(f"/api/admin/users/{S['super_id']}").status_code == 404
    assert support.get(f"/api/admin/users/{S['student_id']}").status_code == 200

    denied = {
        ("post", "/api/admin/admins"): {"fullName": "x", "email": "x@admin-test.example", "roleId": MISSING_ID},
        ("patch", f"/api/admin/limits/{S['student_id']}"): {"dailyAiTokens": 1},
        ("post", f"/api/admin/users/{S['student_id']}/disable"): None,
        ("delete", f"/api/admin/users/{S['student_id']}"): None,
        ("post", "/api/admin/roles"): {"name": "Sneaky", "permissions": ["settings.manage"]},
        ("patch", "/api/admin/settings"): {"signupsEnabled": False},
        ("get", "/api/admin/audit-logs"): None,
        ("get", "/api/admin/content/sources"): None,
    }
    for (method, path), body in denied.items():
        r = getattr(support, method)(path, json=body)
        assert r.status_code == 403 and err(r)["code"] == "permission_denied", (method, path, r.get_json())


def test_denied_attempts_are_audited(clients):
    rows = query("SELECT action, actor_user_id FROM audit_logs WHERE action = 'PERMISSION_DENIED' AND actor_user_id = $1",
                 [S["support_id"]]).rows
    assert len(rows) >= 5


def test_an_admin_with_admins_create_can_create_admins_within_its_own_permissions(clients):
    root = clients("super")
    r = root.post("/api/admin/roles", json={
        "name": "Hiring Admin", "description": "Onboards support staff",
        "permissions": ["admins.view", "admins.create", "admins.edit", "roles.view", "users.view", "students.view",
                        "teachers.view", "usage.view"],
    })
    assert r.status_code == 201, r.get_json()
    S["hiring_role"] = r.get_json()["role"]["id"]
    assert r.get_json()["role"]["key"] == "HIRING_ADMIN"

    r = root.post("/api/admin/admins", json={"fullName": "Hiring", "email": "hiring@admin-test.example",
                                             "roleId": S["hiring_role"]})
    S["hiring_id"] = r.get_json()["admin"]["id"]
    settle_password(clients("hiring"), "hiring@admin-test.example", r.get_json()["temporaryPassword"])
    hiring = clients("hiring")

    # Inside its own permissions: allowed.
    r = hiring.post("/api/admin/admins", json={"fullName": "Support Two", "email": "support2@admin-test.example",
                                               "roleId": role_id(hiring, "SUPPORT_ADMIN")})
    assert r.status_code == 201, r.get_json()
    S["support2_id"] = r.get_json()["admin"]["id"]

    # Anything more: refused.
    r = hiring.post("/api/admin/admins", json={"fullName": "Too much", "email": "full@admin-test.example",
                                               "roleId": role_id(hiring, "FULL_ADMIN")})
    assert r.status_code == 403 and err(r)["code"] == "permission_escalation"
    r = hiring.post("/api/admin/admins", json={"fullName": "Extra", "email": "extra@admin-test.example",
                                               "roleId": role_id(hiring, "SUPPORT_ADMIN"),
                                               "permissions": ["limits.manage"]})
    assert r.status_code == 403 and err(r)["code"] == "permission_escalation"
    r = hiring.post("/api/admin/admins", json={"fullName": "Limits", "email": "limits@admin-test.example",
                                               "roleId": role_id(hiring, "SUPPORT_ADMIN"),
                                               "limits": {"dailyAiTokens": 1}})
    assert r.status_code == 403 and err(r)["details"]["required"] == ["limits.manage"]


def test_an_admin_cannot_create_a_super_admin(clients):
    hiring = clients("hiring")
    r = hiring.post("/api/admin/admins", json={"fullName": "Boss", "email": "boss@admin-test.example",
                                               "roleId": role_id(hiring, "SUPER_ADMIN")})
    assert r.status_code == 403 and err(r)["code"] == "super_admin_required"
    # Nor promote someone to one.
    r = hiring.patch(f"/api/admin/admins/{S['support2_id']}", json={"roleId": role_id(hiring, "SUPER_ADMIN")})
    assert r.status_code == 403 and err(r)["code"] == "super_admin_required"


def test_an_admin_cannot_modify_a_super_admin(clients):
    hiring = clients("hiring")
    for method, path, body in (
        ("patch", f"/api/admin/admins/{S['super_id']}", {"fullName": "Renamed"}),
        ("post", f"/api/admin/users/{S['super_id']}/reset-password", None),
    ):
        r = getattr(hiring, method)(path, json=body)
        assert r.status_code == 403 and err(r)["code"] == "super_admin_protected", (path, r.get_json())


def test_an_admin_cannot_grant_itself_permissions(clients):
    hiring = clients("hiring")
    r = hiring.patch(f"/api/admin/admins/{S['hiring_id']}", json={"permissions": ["users.view", "limits.manage"]})
    assert r.status_code == 403 and err(r)["code"] == "cannot_modify_self"
    r = hiring.patch(f"/api/admin/admins/{S['hiring_id']}", json={"roleId": role_id(hiring, "FULL_ADMIN")})
    assert r.status_code == 403 and err(r)["code"] == "cannot_modify_self"
    # Its own name is fine.
    assert hiring.patch(f"/api/admin/admins/{S['hiring_id']}", json={"fullName": "Hiring Lead"}).status_code == 200


def test_an_admin_cannot_manage_a_more_powerful_admin(clients):
    root = clients("super")
    r = root.post("/api/admin/admins", json={"fullName": "Full", "email": "fulladmin@admin-test.example",
                                             "roleId": role_id(root, "FULL_ADMIN")})
    S["full_id"] = r.get_json()["admin"]["id"]
    r = clients("hiring").patch(f"/api/admin/admins/{S['full_id']}", json={"permissions": []})
    assert r.status_code == 403 and err(r)["code"] == "target_outranks_actor"


def test_role_escalation_is_blocked(clients):
    root = clients("super")
    # Only a super admin may edit here, and a system role outside the admin kind is locked.
    r = root.patch(f"/api/admin/roles/{role_id(root, 'STUDENT')}", json={"permissions": ["users.view"]})
    assert r.status_code == 403 and err(r)["code"] == "system_role_locked"
    r = root.delete(f"/api/admin/roles/{S['hiring_role']}")
    assert r.status_code == 409  # still held by the hiring admin
    r = root.delete(f"/api/admin/roles/{role_id(root, 'SUPPORT_ADMIN')}")
    assert r.status_code == 403 and err(r)["code"] == "system_role_locked"


def test_permission_changes_take_effect_immediately(clients):
    root, hiring = clients("super"), clients("hiring")
    assert hiring.get("/api/admin/usage").status_code == 200
    r = root.patch(f"/api/admin/roles/{S['hiring_role']}", json={
        "permissions": ["admins.view", "admins.create", "admins.edit", "roles.view", "users.view", "students.view",
                        "teachers.view"]})
    assert r.status_code == 200
    # Same access token, next request: the revoked permission is gone.
    r = hiring.get("/api/admin/usage")
    assert r.status_code == 403 and err(r)["code"] == "permission_denied"
    log = query_one("SELECT metadata FROM audit_logs WHERE action = 'PERMISSION_CHANGED' AND resource_id = $1 "
                    "ORDER BY created_at DESC LIMIT 1", [S["hiring_role"]])
    assert log["metadata"]["removed"] == ["usage.view"]


# --- disabling, deleting, passwords -----------------------------------------------------


def test_disabling_an_account_cuts_it_off_at_once(clients):
    root, support = clients("super"), clients("support")
    r = root.post(f"/api/admin/users/{S['support_id']}/disable")
    assert r.status_code == 200 and r.get_json()["user"]["status"] == "disabled"
    r = support.get("/api/admin/me")
    assert r.status_code == 401 and err(r)["code"] == "account_disabled"
    assert support.post("/api/auth/refresh").status_code == 401  # sessions were revoked
    reset_rate_limits()
    assert support.post("/api/auth/login", json={"identifier": "support@admin-test.example",
                                                 "password": PASSWORD}).status_code == 401

    assert root.post(f"/api/admin/users/{S['support_id']}/enable").get_json()["user"]["status"] == "active"
    login(support, "support@admin-test.example", PASSWORD)
    actions = [row["action"] for row in query(
        "SELECT action FROM audit_logs WHERE target_user_id = $1 ORDER BY created_at", [S["support_id"]]).rows]
    assert "ADMIN_DISABLED" in actions and "ADMIN_ENABLED" in actions


def test_nobody_disables_or_deletes_themselves(clients):
    root = clients("super")
    r = root.post(f"/api/admin/users/{S['super_id']}/disable")
    assert r.status_code == 403 and err(r)["code"] == "cannot_modify_self"
    r = root.delete(f"/api/admin/admins/{S['super_id']}")
    assert r.status_code == 403 and err(r)["code"] == "cannot_modify_self"
    r = root.delete("/api/profile")
    assert r.status_code == 403 and err(r)["code"] == "admin_account"


def test_the_last_active_super_admin_cannot_be_removed(clients):
    root = clients("super")
    r = root.post("/api/admin/admins", json={"fullName": "Second Owner", "email": "owner2@admin-test.example",
                                             "roleId": role_id(root, "SUPER_ADMIN"), "permissions": ["users.view"]})
    assert r.status_code == 201 and r.get_json()["admin"]["kind"] == "super_admin"
    assert r.get_json()["admin"]["extraPermissions"] == []  # a super admin needs no extra grants
    S["super2_id"] = r.get_json()["admin"]["id"]
    second = clients("super2")
    settle_password(second, "owner2@admin-test.example", r.get_json()["temporaryPassword"])

    # With two, one can disable the other...
    assert second.post(f"/api/admin/users/{S['super_id']}/disable").status_code == 200
    # ...and the database refuses to lose the last one, whatever the path.
    with pytest.raises(sqlite3.IntegrityError, match="last_active_super_admin"):
        query("UPDATE users SET status = 'disabled' WHERE id = $1", [S["super2_id"]])
    with pytest.raises(sqlite3.IntegrityError, match="last_active_super_admin"):
        query("UPDATE users SET role = 'admin', role_id = (SELECT id FROM roles WHERE key = 'FULL_ADMIN') "
              "WHERE id = $1", [S["super2_id"]])
    assert second.post(f"/api/admin/users/{S['super_id']}/enable").status_code == 200
    login(root, "owner@admin-test.example", PASSWORD)


def test_a_role_kind_can_never_drift(app):
    with pytest.raises(sqlite3.IntegrityError, match="role_kind_mismatch"):
        query("UPDATE users SET role_id = (SELECT id FROM roles WHERE key = 'SUPER_ADMIN') WHERE id = $1",
              [S["student_id"]])


def test_reset_password_revokes_sessions_and_forces_a_change(clients):
    root, student = clients("super"), clients("student")
    r = root.post(f"/api/admin/users/{S['student_id']}/reset-password")
    assert r.status_code == 200
    temporary = r.get_json()["temporaryPassword"]
    assert student.post("/api/auth/refresh").status_code == 401
    reset_rate_limits()
    assert student.post("/api/auth/login", json={"identifier": "student@admin-test.example",
                                                 "password": PASSWORD}).status_code == 401
    settle_password(student, "student@admin-test.example", temporary)
    assert query_one("SELECT count(*) AS n FROM audit_logs WHERE action = 'PASSWORD_RESET' AND target_user_id = $1",
                     [S["student_id"]])["n"] == 1


def test_editing_a_student_to_teacher_moves_its_role(clients):
    root = clients("super")
    r = root.patch(f"/api/admin/users/{S['student_id']}", json={"role": "teacher"})
    assert r.status_code == 200 and r.get_json()["user"]["role"]["key"] == "TEACHER"
    r = root.patch(f"/api/admin/users/{S['student_id']}", json={"role": "student"})
    assert r.get_json()["user"]["role"]["key"] == "STUDENT"
    r = root.patch(f"/api/admin/users/{S['student_id']}", json={"role": "admin"})
    assert r.status_code == 422


def test_admin_created_users_start_with_a_temporary_password(clients):
    root = clients("super")
    r = root.post("/api/admin/users", json={"fullName": "New Teacher", "email": "newteacher@admin-test.example",
                                            "role": "teacher"})
    assert r.status_code == 201 and r.get_json()["user"]["role"]["key"] == "TEACHER"
    assert r.get_json()["user"]["mustChangePassword"] is True and len(r.get_json()["temporaryPassword"]) >= 16
    r = root.post("/api/admin/users", json={"fullName": "Dup", "email": "newteacher@admin-test.example",
                                            "role": "student"})
    assert r.status_code == 409


# --- usage limits ------------------------------------------------------------------------


def test_limits_are_enforced_server_side_and_usage_is_counted(clients):
    root, student = clients("super"), clients("student")
    kit = student.post("/api/kits", json={"title": "Limits kit"}).get_json()["kit"]
    S["kit"] = kit["id"]

    r = root.patch(f"/api/admin/limits/{S['student_id']}", json={"dailyTutorMessages": 1, "dailyPdfUploads": 1})
    assert r.status_code == 200 and r.get_json()["effective"]["dailyTutorMessages"] == 1

    # Tutor: the first message goes through, the second hits the daily limit.
    first = student.post("/api/chat", json={"kitId": S["kit"], "content": "hello", "language": "en"})
    assert first.status_code == 201, first.get_json()
    second = student.post("/api/chat", json={"kitId": S["kit"], "content": "again", "language": "en"})
    assert second.status_code == 403
    assert err(second)["code"] == "DAILY_TUTOR_LIMIT_REACHED"
    assert err(second)["message"] == "Your daily tutor message limit has been reached."
    assert err(second)["details"]["limit"] == 1 and err(second)["details"]["resetsAt"].endswith("Z")

    # Uploads: counted with their bytes, and the second of the day is refused.
    text = b"Primary keys identify rows. " * 20
    ok = student.post(f"/api/kits/{S['kit']}/files", data={"file": (io.BytesIO(text), "a.txt", "text/plain")},
                      content_type="multipart/form-data")
    assert ok.status_code == 202, ok.get_json()
    refused = student.post(f"/api/kits/{S['kit']}/files", data={"file": (io.BytesIO(text), "b.txt", "text/plain")},
                           content_type="multipart/form-data")
    assert refused.status_code == 403 and err(refused)["code"] == "DAILY_UPLOAD_LIMIT_REACHED"

    usage = root.get(f"/api/admin/usage/{S['student_id']}").get_json()
    assert usage["today"]["tutorMessages"] == 1
    assert usage["today"]["pdfUploads"] == 1 and usage["today"]["storageBytes"] == len(text)


def test_ai_token_limit_blocks_generation(clients):
    root, student = clients("super"), clients("student")
    assert root.patch(f"/api/admin/limits/{S['student_id']}", json={"dailyAiTokens": 0}).status_code == 200
    r = student.post("/api/chat/explain", json={"kitId": S["kit"], "content": "Explain keys", "language": "en"})
    assert r.status_code == 403 and err(r)["code"] == "DAILY_AI_LIMIT_REACHED"
    assert err(r)["message"] == "Your daily AI usage limit has been reached."

    # null clears the override: back to the role default, and the call goes through.
    assert root.patch(f"/api/admin/limits/{S['student_id']}", json={"dailyAiTokens": None}).status_code == 200
    r = student.post("/api/chat/explain", json={"kitId": S["kit"], "content": "Explain keys", "language": "en"})
    assert r.status_code == 200, r.get_json()
    assert root.get(f"/api/admin/usage/{S['student_id']}").get_json()["today"]["aiTotalTokens"] > 0


def test_role_defaults_apply_until_an_account_overrides_them(clients):
    root = clients("super")
    teacher_role = role_id(root, "TEACHER")
    r = root.patch(f"/api/admin/limits/defaults/{teacher_role}", json={"dailyAssignments": 0})
    assert r.status_code == 200 and r.get_json()["role"]["limits"]["dailyAssignments"] == 0
    limits = root.get(f"/api/admin/limits/{S['teacher_id']}").get_json()
    assert limits["effective"]["dailyAssignments"] == 0 and limits["source"]["dailyAssignments"] == "role"
    r = root.patch(f"/api/admin/limits/{S['teacher_id']}", json={"dailyAssignments": 5})
    assert r.get_json()["effective"]["dailyAssignments"] == 5 and r.get_json()["source"]["dailyAssignments"] == "account"
    root.patch(f"/api/admin/limits/defaults/{teacher_role}", json={"dailyAssignments": 100})


def test_limits_can_be_switched_off_platform_wide(clients):
    root, student = clients("super"), clients("student")
    root.patch(f"/api/admin/limits/{S['student_id']}", json={"dailyAiTokens": 0})
    assert root.patch("/api/admin/settings", json={"usageLimitsEnabled": False}).status_code == 200
    r = student.post("/api/chat/explain", json={"kitId": S["kit"], "content": "Explain keys", "language": "en"})
    assert r.status_code == 200
    root.patch("/api/admin/settings", json={"usageLimitsEnabled": True})
    root.patch(f"/api/admin/limits/{S['student_id']}", json={"dailyAiTokens": None, "dailyTutorMessages": None,
                                                              "dailyPdfUploads": None})


def test_admins_cannot_raise_their_own_limits(clients):
    r = clients("hiring").patch(f"/api/admin/limits/{S['hiring_id']}", json={"dailyAiTokens": 10**9})
    assert r.status_code == 403  # no limits.manage — and not on itself even with it


def test_usage_reset_is_audited(clients):
    root = clients("super")
    r = root.post(f"/api/admin/usage/{S['student_id']}/reset")
    assert r.status_code == 200 and r.get_json()["today"]["tutorMessages"] == 0
    row = query_one("SELECT metadata FROM audit_logs WHERE action = 'USAGE_RESET' ORDER BY created_at DESC LIMIT 1")
    assert row["metadata"]["previous"]["tutor_messages"] == 1


# --- dashboard, audit log, settings, content -----------------------------------------------


def test_dashboard_sections_follow_permissions(clients):
    full = root_dash = clients("super").get("/api/admin/dashboard").get_json()
    assert {"overview", "aiUsage", "content", "activity"} <= set(root_dash)
    assert full["overview"]["admins"] >= 3 and full["overview"]["students"] >= 1
    support_dash = clients("support").get("/api/admin/dashboard").get_json()
    assert "overview" in support_dash and "aiUsage" in support_dash and "content" not in support_dash

    for range_key, points in (("today", 24), ("7d", 7), ("30d", 30), ("90d", 90)):
        series = clients("super").get(f"/api/admin/dashboard/series?range={range_key}").get_json()
        assert len(series["points"]) == points
    assert clients("super").get("/api/admin/dashboard/series?range=1y").status_code == 422


def test_audit_log_is_filterable_and_append_only(clients):
    root = clients("super")
    body = root.get("/api/admin/audit-logs?action=ADMIN_CREATED").get_json()
    assert body["total"] >= 4 and all(log["action"] == "ADMIN_CREATED" for log in body["logs"])
    assert "ADMIN_CREATED" in body["actions"]
    by_target = root.get("/api/admin/audit-logs?target=support@admin-test").get_json()
    assert by_target["total"] >= 1 and by_target["logs"][0]["ipAddress"]

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        query("UPDATE audit_logs SET action = 'NOTHING'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        query("DELETE FROM audit_logs")
    # And there is no API to change it either.
    assert root.delete("/api/admin/audit-logs").status_code == 404


def test_signups_can_be_paused(clients, app):
    root = clients("super")
    assert root.patch("/api/admin/settings", json={"signupsEnabled": False}).get_json()["settings"] == {
        "usageLimitsEnabled": True, "signupsEnabled": False}
    reset_rate_limits()
    r = app.test_client().post("/api/auth/register", json={
        "fullName": "Late", "email": "late@admin-test.example", "password": PASSWORD, "role": "student"})
    assert r.status_code == 403 and err(r)["code"] == "signups_disabled"
    root.patch("/api/admin/settings", json={"signupsEnabled": True})
    assert query_one("SELECT count(*) AS n FROM audit_logs WHERE action = 'SYSTEM_SETTING_CHANGED'")["n"] >= 2
    assert root.patch("/api/admin/settings", json={"maintenance": True}).status_code == 422


def test_content_lists_and_moderation(clients):
    root = clients("super")
    sources = root.get("/api/admin/content/sources").get_json()
    assert sources["total"] >= 1
    source = next(item for item in sources["items"] if item["owner"]["id"] == S["student_id"])
    assert root.delete(f"/api/admin/content/sources/{source['id']}").get_json() == {"deleted": True, "id": source["id"]}
    assert root.delete(f"/api/admin/content/sources/{source['id']}").status_code == 404
    assert root.get("/api/admin/content/classes").status_code == 200
    assert root.get("/api/admin/content/assignments").status_code == 200
    assert root.get("/api/admin/content/flashcards").status_code == 200


def test_deleting_an_admin_frees_its_email_and_keeps_the_audit_trail(clients):
    root = clients("super")
    r = root.delete(f"/api/admin/admins/{S['support2_id']}")
    assert r.status_code == 200
    assert root.get(f"/api/admin/users/{S['support2_id']}").status_code == 404
    row = query_one("SELECT email, status FROM users WHERE id = $1", [S["support2_id"]])
    assert row["status"] == "deleted" and row["email"].endswith("@deleted.invalid")
    log = query_one("SELECT target_label FROM audit_logs WHERE action = 'ADMIN_DELETED' AND target_user_id = $1",
                    [S["support2_id"]])
    assert log["target_label"] == "support2@admin-test.example"
    # A student account is not an admin: the admins endpoint will not delete it.
    assert root.delete(f"/api/admin/admins/{S['teacher_id']}").status_code == 404

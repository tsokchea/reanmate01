"""Dashboard statistics, charts, the audit log, system settings and content moderation."""

import datetime as dt

from ..extensions import normalize_timestamp, transaction
from ..middleware.errors import ApiError
from ..models import admin as admin_db
from ..models import audit as audit_db
from . import audit_service, sources_service, teacher_service, usage_service
from .admin_accounts_service import _like

RANGES = {"today": 1, "7d": 7, "30d": 30, "90d": 90}

SETTINGS = {
    # API name -> (stored key, type)
    "usageLimitsEnabled": ("usage_limits_enabled", bool),
    "signupsEnabled": ("signups_enabled", bool),
}


def _utc_now():
    return dt.datetime.now(dt.timezone.utc)


def _iso(value):
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _page(data):
    page = max(1, int(data.get("page") or 1))
    size = min(100, max(1, int(data.get("pageSize") or 20)))
    return page, size


def dashboard(actor):
    """Each section is included only for the admins allowed to read it."""
    now = _utc_now()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    out = {"generatedAt": _iso(now)}
    if actor.has_any("users.view", "analytics.view"):
        counts = admin_db.account_counts(_iso(midnight), _iso(midnight - dt.timedelta(days=6)))
        out["overview"] = {
            "totalUsers": counts["total"] or 0, "students": counts["students"] or 0,
            "teachers": counts["teachers"] or 0, "admins": counts["admins"] or 0,
            "activeUsers": counts["active"] or 0, "disabledUsers": counts["disabled"] or 0,
        }
        out["activity"] = {
            "newUsersToday": counts["new_today"] or 0, "newUsersThisWeek": counts["new_week"] or 0,
            "activeUsersToday": counts["active_today"] or 0,
        }
    if actor.has_any("usage.view", "analytics.view"):
        usage = admin_db.usage_totals(usage_service.today(), usage_service.month_start())
        content = admin_db.content_counts()
        out["aiUsage"] = {
            "tokensToday": usage["tokens_today"], "tokensThisMonth": usage["tokens_month"],
            "tutorMessagesToday": usage["tutor_today"], "uploadsToday": usage["uploads_today"],
            "processingNow": content["processing"],
        }
    if actor.has_any("content.view", "analytics.view"):
        content = admin_db.content_counts()
        out["content"] = {
            "pdfs": content["pdfs"], "files": content["files"], "assignments": content["assignments"],
            "flashcardSets": content["flashcard_sets"], "courses": content["courses"],
        }
    return out


def series(actor, data):
    """Chart points: hourly for today, daily otherwise, zero-filled."""
    range_key = data.get("range") or "7d"
    now = _utc_now()
    if range_key == "today":
        start = now.replace(minute=0, second=0, microsecond=0) - dt.timedelta(hours=23)
        buckets = [start + dt.timedelta(hours=i) for i in range(24)]
        label = lambda moment: moment.strftime("%Y-%m-%dT%H")  # noqa: E731
        chars = 13
    else:
        days = RANGES[range_key]
        start = now.replace(hour=0, minute=0, second=0, microsecond=0) - dt.timedelta(days=days - 1)
        buckets = [start + dt.timedelta(days=i) for i in range(days)]
        label = lambda moment: moment.strftime("%Y-%m-%d")  # noqa: E731
        chars = 10
    counts = admin_db.series(since=_iso(start), bucket_chars=chars)
    points = []
    for moment in buckets:
        key = label(moment)
        points.append({"bucket": _iso(moment), **{metric: values.get(key, 0) for metric, values in counts.items()}})
    return {"range": range_key, "granularity": "hour" if chars == 13 else "day", "points": points}


# --- audit log -------------------------------------------------------------------------


def audit_logs(actor, data):
    page, size = _page(data)
    filters = {
        "from": normalize_timestamp(data.get("from")) if data.get("from") else None,
        "to": normalize_timestamp(data.get("to")) if data.get("to") else None,
        "actorId": data.get("actorId"), "actor": _like(data.get("actor")), "action": data.get("action"),
        "targetId": data.get("targetId"), "target": _like(data.get("target")),
    }
    rows, total = audit_db.page(filters, limit=size, offset=(page - 1) * size)
    return {"logs": [audit_service.to_api(row) for row in rows], "page": page, "pageSize": size, "total": total,
            "actions": sorted(set(audit_db.distinct_actions()) | set(audit_service.ACTIONS))}


# --- settings -------------------------------------------------------------------------


def settings(actor):
    stored = audit_db.settings()
    return {"settings": {name: stored.get(key, True) for name, (key, _type) in SETTINGS.items()}}


def update_settings(actor, data):
    stored = audit_db.settings()
    changes = {name: value for name, value in data.items() if name in SETTINGS and stored.get(SETTINGS[name][0]) != value}
    with transaction() as tx:
        for name, value in changes.items():
            audit_db.put_setting(tx, SETTINGS[name][0], value, actor.id)
            audit_service.record("SYSTEM_SETTING_CHANGED", actor=actor, resource="system_settings",
                                 resource_id=SETTINGS[name][0],
                                 metadata={"setting": name, "from": stored.get(SETTINGS[name][0]), "to": value}, tx=tx)
    return settings(actor)


# --- content --------------------------------------------------------------------------


def _target(user_id):
    """The owner as an audit target, labelled by email while the account still exists."""
    return admin_db.find_account(user_id) or {"id": user_id}


def _owner(row, prefix="owner"):
    return {"id": row[f"{prefix}_id"], "name": row[f"{prefix}_name"], "email": row[f"{prefix}_email"]}


def content_sources(actor, data):
    page, size = _page(data)
    rows, total = admin_db.sources_page(q=_like(data.get("q")), kind=data.get("kind"), limit=size,
                                        offset=(page - 1) * size)
    return {"items": [{
        "id": r["id"], "title": r["title"], "kind": r["kind"], "status": r["status"], "byteSize": r["byte_size"],
        "pageCount": r["page_count"], "kitTitle": r["kit_title"], "owner": _owner(r), "createdAt": r["created_at"],
    } for r in rows], "page": page, "pageSize": size, "total": total}


def content_classes(actor, data):
    page, size = _page(data)
    rows, total = admin_db.classes_page(q=_like(data.get("q")), limit=size, offset=(page - 1) * size)
    return {"items": [{
        "id": r["id"], "title": r["title"], "subject": r["subject"], "status": r["status"],
        "studentCount": r["student_count"], "assignmentCount": r["assignment_count"],
        "teacher": _owner(r, "teacher"), "createdAt": r["created_at"],
    } for r in rows], "page": page, "pageSize": size, "total": total}


def content_assignments(actor, data):
    page, size = _page(data)
    rows, total = admin_db.assignments_page(q=_like(data.get("q")), limit=size, offset=(page - 1) * size)
    return {"items": [{
        "id": r["id"], "title": r["title"], "status": r["status"], "dueAt": r["due_at"],
        "classTitle": r["class_title"], "submissionCount": r["submission_count"],
        "teacher": {"id": r["teacher_id"], "name": r["teacher_name"], "email": r["teacher_email"]},
        "createdAt": r["created_at"],
    } for r in rows], "page": page, "pageSize": size, "total": total}


def content_flashcards(actor, data):
    page, size = _page(data)
    rows, total = admin_db.flashcard_sets_page(q=_like(data.get("q")), limit=size, offset=(page - 1) * size)
    return {"items": [{
        "id": r["id"], "sourceTitle": r["source_title"], "language": r["language"], "cardCount": r["card_count"],
        "owner": _owner(r), "createdAt": r["created_at"],
    } for r in rows], "page": page, "pageSize": size, "total": total}


def delete_source(actor, source_id):
    source = admin_db.find_source(source_id)
    if not source:
        raise ApiError.not_found("That material does not exist")
    # The owner's own removal path, so the file on disk and every derived row go too.
    sources_service.remove(source["user_id"], source["study_kit_id"], source_id)
    audit_service.record("CONTENT_DELETED", actor=actor, target=_target(source["user_id"]), resource="source",
                         resource_id=source_id, metadata={"title": source["title"], "kind": source["kind"]})
    return {"deleted": True, "id": source_id}


def delete_assignment(actor, assignment_id):
    assignment = admin_db.find_assignment(assignment_id)
    if not assignment:
        raise ApiError.not_found("That assignment does not exist")
    teacher_service.delete_assignment(assignment["teacher_id"], assignment_id)
    audit_service.record("CONTENT_DELETED", actor=actor, target=_target(assignment["teacher_id"]),
                         resource="assignment", resource_id=assignment_id, metadata={"title": assignment["title"]})
    return {"deleted": True, "id": assignment_id}


def delete_flashcard_set(actor, set_id):
    found = admin_db.find_flashcard_set(set_id)
    if not found:
        raise ApiError.not_found("That flashcard set does not exist")
    with transaction() as tx:
        admin_db.delete_flashcard_set(tx, set_id)
        audit_service.record("CONTENT_DELETED", actor=actor, target=_target(found["user_id"]), resource="flashcards",
                             resource_id=set_id,
                             metadata={"sourceTitle": found["source_title"], "cards": found["card_count"]}, tx=tx)
    return {"deleted": True, "id": set_id}

"""The profile screen and account deletion (server/src/services/profile.service.js)."""

import datetime as dt

from ..middleware.errors import ApiError
from ..models import profile as profile_db


def _streak_for(values):
    days = {str(value)[:10] for value in values or []}
    cursor = dt.datetime.now(dt.timezone.utc)
    streak = 0
    while cursor.strftime("%Y-%m-%d") in days:
        streak += 1
        cursor -= dt.timedelta(days=1)
    return streak


def _to_profile(row):
    return {
        "id": row["id"], "fullName": row["full_name"], "email": row["email"], "phone": row["phone"],
        "avatarUrl": row["avatar_url"], "role": row["role"], "locale": row["locale"],
        "planTier": row["plan_tier"], "planStatus": row["plan_status"],
        "summary": {"kits": row["kits"], "streak": _streak_for(row["activity_days"]), "mastery": row["mastery"]},
        "activityDays": row["activity_days"],
    }


def get(user_id):
    row = profile_db.get(user_id)
    if not row:
        raise ApiError.unauthorized()
    return {"profile": _to_profile(row)}


def update(user_id, patch):
    if not profile_db.update(user_id, patch):
        raise ApiError.unauthorized()
    return get(user_id)


def delete_account(user_id):
    if not profile_db.delete_account(user_id):
        raise ApiError.unauthorized("That account is no longer active")
    return {"deleted": True}

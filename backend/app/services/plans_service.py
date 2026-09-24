"""Plan limits, features and usage quotas (server/src/services/plans.service.js)."""

import datetime as dt

from ..middleware.errors import ApiError
from ..models import plans as plans_db


def calendar_month_utc(date=None):
    value = (date or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    return f"{value.year}-{value.month:02d}-01"


def has_plan_capacity(used, limit, amount=1):
    return limit is None or used + amount <= limit


class PlansService:
    """``db`` is injectable so the quota logic can be tested without Postgres."""

    def __init__(self, db=plans_db):
        self.db = db

    def consume_quota(self, user_id, counter_key, amount=1, now=None):
        period_start = calendar_month_utc(now)
        consumed = self.db.consume(user_id=user_id, counter_key=counter_key, period_start=period_start, amount=amount)
        if not consumed:
            configured = self.db.limit(user_id, counter_key)
            raise ApiError(429, "quota_exceeded", "Plan quota exceeded",
                           {"limit": (configured or {}).get("limit_value")})
        limit = consumed["limit_value"]
        return {
            "used": consumed["quantity"],
            "limit": limit,
            "remaining": None if limit is None else max(0, limit - consumed["quantity"]),
            "periodStart": period_start,
        }

    def get_limit(self, user_id, key):
        row = self.db.limit(user_id, key)
        if not row:
            raise ApiError(403, "feature_unavailable", "This limit is not configured for the plan",
                           {"requiredPlan": "plus"})
        return row["limit_value"]

    @staticmethod
    def assert_capacity(key, used, limit, amount=1):
        if not has_plan_capacity(used, limit, amount):
            raise ApiError(403, "quota_exceeded", "Plan quota exceeded", {"key": key, "used": used, "limit": limit})

    def require_feature(self, user_id, key):
        row = self.db.feature(user_id, key)
        if not (row or {}).get("enabled"):
            raise ApiError(403, "feature_unavailable", "This feature is unavailable on the current plan",
                           {"requiredPlan": "plus"})

    def limits(self, user_id, now=None):
        period_start = calendar_month_utc(now)
        row = self.db.all_for_user(user_id, period_start)
        if not row:
            raise ApiError.unauthorized()
        expected_limits = ["max_kits", "tutor_messages_per_month", "practice_sessions_per_week"]
        expected_features = ["chapter_summaries", "mock_exams"]
        if any(key not in row["limits"] for key in expected_limits) or any(
                key not in row["features"] for key in expected_features):
            raise ApiError(403, "feature_unavailable", "Plan configuration is incomplete", {"requiredPlan": "plus"})

        limits = {
            key: {**value, "remaining": None if value.get("limit") is None else max(0, value["limit"] - value["used"])}
            for key, value in row["limits"].items()
        }
        catalog = self.db.catalog()
        plans = {"free": {"limits": {}, "features": {}}, "plus": {"limits": {}, "features": {}}}
        for item in catalog["limits"]:
            plans[item["plan_tier"]]["limits"][item["limit_key"]] = item["limit_value"]
        for item in catalog["features"]:
            plans[item["plan_tier"]]["features"][item["feature_key"]] = item["enabled"]
        return {"planTier": row["plan_tier"], "periodStart": period_start, "limits": limits,
                "features": row["features"], "plans": plans}

    def generation_count(self, user_id, kind):
        row = self.db.tier(user_id)
        if not row:
            raise ApiError.unauthorized()
        policy = {"quiz": {"free": 10, "plus": 25}, "flashcards": {"free": 20, "plus": 40}}.get(kind)
        if not policy or row["plan_tier"] not in policy:
            raise ApiError(403, "feature_unavailable", "Generation policy is missing", {"requiredPlan": "plus"})
        return policy[row["plan_tier"]]

    def after_success(self, user_id, counter_key, handler):
        result = handler()
        quota = self.consume_quota(user_id, counter_key)
        return {"result": result, "quota": quota}


plans_service = PlansService()

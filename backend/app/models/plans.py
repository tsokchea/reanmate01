"""SQL for plan limits, features and usage counters."""

from ..extensions import query, query_one
from ._time import start_of_week

# Consumes quota atomically: the insert and the capped increment both check
# the plan's limit, so two concurrent consumes at the boundary cannot both win.
CONSUME_QUOTA_SQL = """
  INSERT INTO usage_counters (user_id, counter_key, period_start, quantity)
  SELECT $1, $2, $3, $4
   WHERE EXISTS (
     SELECT 1 FROM users u
     JOIN plan_limits pl ON pl.plan_tier = u.plan_tier AND pl.limit_key = $2
     WHERE u.id = $1 AND (pl.limit_value IS NULL OR $4 <= pl.limit_value)
   )
  ON CONFLICT (user_id, counter_key, period_start) DO UPDATE
    SET quantity = usage_counters.quantity + excluded.quantity
  WHERE EXISTS (
    SELECT 1 FROM users u
    JOIN plan_limits pl ON pl.plan_tier = u.plan_tier AND pl.limit_key = $2
    WHERE u.id = $1
      AND (pl.limit_value IS NULL OR usage_counters.quantity + excluded.quantity <= pl.limit_value)
  )
  RETURNING quantity, (
    SELECT pl.limit_value FROM users u
    JOIN plan_limits pl ON pl.plan_tier = u.plan_tier AND pl.limit_key = $2
    WHERE u.id = $1
  ) AS limit_value
"""


def tier(user_id):
    return query_one("SELECT plan_tier FROM users WHERE id = $1 AND status <> 'deleted'", [user_id])


def consume(*, user_id, counter_key, period_start, amount=1):
    return query_one(CONSUME_QUOTA_SQL, [user_id, counter_key, period_start, amount])


def limit(user_id, key):
    return query_one(
        """SELECT pl.limit_value FROM users u JOIN plan_limits pl ON pl.plan_tier = u.plan_tier
            WHERE u.id = $1 AND pl.limit_key = $2""",
        [user_id, key],
    )


def feature(user_id, key):
    return query_one(
        """SELECT pf.enabled FROM users u JOIN plan_features pf ON pf.plan_tier = u.plan_tier
            WHERE u.id = $1 AND pf.feature_key = $2""",
        [user_id, key],
    )


def all_for_user(user_id, period_start):
    return query_one(
        """SELECT u.plan_tier,
                  COALESCE((SELECT json_group_object(pl.limit_key, json_object(
                    'limit', pl.limit_value,
                    'used', CASE pl.limit_key
                      WHEN 'max_kits' THEN (SELECT count(*) FROM study_kits k WHERE k.user_id = u.id AND k.class_id IS NULL)
                      WHEN 'practice_sessions_per_week' THEN (SELECT count(*) FROM practice_sessions ps WHERE ps.user_id = u.id AND ps.started_at >= $3)
                      ELSE COALESCE((SELECT uc.quantity FROM usage_counters uc WHERE uc.user_id = u.id AND uc.counter_key = pl.limit_key AND uc.period_start = $2), 0)
                    END
                  )) FROM plan_limits pl WHERE pl.plan_tier = u.plan_tier), '{}') AS "limits [JSONTEXT]",
                  COALESCE((SELECT json_group_object(pf.feature_key, json(CASE WHEN pf.enabled THEN 'true' ELSE 'false' END))
                              FROM plan_features pf WHERE pf.plan_tier = u.plan_tier), '{}') AS "features [JSONTEXT]"
             FROM users u WHERE u.id = $1""",
        [user_id, period_start, start_of_week()],
    )


def catalog():
    limits = query("SELECT plan_tier, limit_key, limit_value FROM plan_limits ORDER BY plan_tier, limit_key").rows
    features = query("SELECT plan_tier, feature_key, enabled FROM plan_features ORDER BY plan_tier, feature_key").rows
    return {"limits": limits, "features": features}

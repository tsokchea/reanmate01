"""SQL for the profile screen and account deletion (server/src/db/profile.db.js)."""

import os
import shutil

from ..extensions import query_one
from ..middleware.upload import upload_root


def get(user_id):
    return query_one(
        """SELECT u.id, u.full_name, u.email, u.phone, u.avatar_url, u.role, u.locale,
                  u.plan_tier, u.plan_status,
                  (SELECT count(*)::int FROM study_kits k WHERE k.user_id = u.id AND k.class_id IS NULL) AS kits,
                  (SELECT count(*)::int FROM flashcard_reviews fr WHERE fr.user_id = u.id AND fr.last_reviewed_at IS NOT NULL) AS cards,
                  COALESCE((SELECT round(avg(utm.mastery_percent))::int FROM user_topic_mastery utm WHERE utm.user_id = u.id), 0) AS mastery,
                  COALESCE((SELECT jsonb_agg(days.day ORDER BY days.day) FROM (
                    SELECT DISTINCT (ps.completed_at AT TIME ZONE 'UTC')::date AS day
                      FROM practice_sessions ps WHERE ps.user_id = u.id
                  ) days), '[]'::jsonb) AS activity_days
             FROM users u WHERE u.id = $1 AND u.status <> 'deleted'""",
        [user_id],
    )


def update(user_id, patch):
    return query_one(
        """UPDATE users SET full_name = COALESCE($2, full_name), locale = COALESCE($3, locale)
            WHERE id = $1 AND status <> 'deleted' RETURNING id""",
        [user_id, patch.get("fullName"), patch.get("locale")],
    )


def delete_account(user_id):
    user_dir = os.path.join(upload_root, user_id)
    shutil.rmtree(user_dir, ignore_errors=True)
    return query_one("DELETE FROM users WHERE id = $1 AND status <> 'deleted' RETURNING id", [user_id])

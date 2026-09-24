"""SQL for the profile screen and account deletion."""

import os
import shutil

from ..extensions import query_one
from ..middleware.upload import upload_root


def get(user_id):
    return query_one(
        """SELECT u.id, u.full_name, u.email, u.phone, u.avatar_url, u.role, u.locale,
                  u.plan_tier, u.plan_status,
                  (SELECT count(*) FROM study_kits k WHERE k.user_id = u.id AND k.class_id IS NULL) AS kits,
                  (SELECT count(*) FROM flashcard_reviews fr WHERE fr.user_id = u.id AND fr.last_reviewed_at IS NOT NULL) AS cards,
                  COALESCE((SELECT CAST(round(avg(utm.mastery_percent)) AS INTEGER)
                              FROM user_topic_mastery utm WHERE utm.user_id = u.id), 0) AS mastery,
                  (SELECT json_group_array(day ORDER BY day) FROM (
                     SELECT DISTINCT date(ps.completed_at) AS day
                       FROM practice_sessions ps WHERE ps.user_id = u.id
                   )) AS "activity_days [JSONTEXT]"
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
    shutil.rmtree(os.path.join(upload_root, user_id), ignore_errors=True)
    return query_one("DELETE FROM users WHERE id = $1 AND status <> 'deleted' RETURNING id", [user_id])

"""SQL for ``onboarding_responses``. One row per user, answers held as JSONB."""

from ..extensions import query_one
from ..utils.serialization import dumps


def save_answers(*, user_id, answers, skipped=False, survey_version=1, completed=False):
    """Upsert, merging into existing answers — each survey screen submits on its own."""
    return query_one(
        """INSERT INTO onboarding_responses (user_id, survey_version, answers, skipped, completed_at)
           VALUES ($1, $2, $3::jsonb, $4, CASE WHEN $5 THEN now() ELSE NULL END)
           ON CONFLICT (user_id) DO UPDATE
             SET answers        = onboarding_responses.answers || EXCLUDED.answers,
                 skipped        = EXCLUDED.skipped,
                 survey_version = EXCLUDED.survey_version,
                 completed_at   = COALESCE(onboarding_responses.completed_at, EXCLUDED.completed_at)
           RETURNING id, user_id, survey_version, answers, skipped, completed_at, updated_at""",
        [user_id, survey_version, dumps(answers or {}), skipped, completed],
    )


def find_by_user_id(user_id):
    return query_one(
        """SELECT id, user_id, survey_version, answers, skipped, completed_at, created_at, updated_at
             FROM onboarding_responses
            WHERE user_id = $1""",
        [user_id],
    )

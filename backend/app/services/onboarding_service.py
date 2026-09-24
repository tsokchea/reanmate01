"""Role choice and the onboarding survey (server/src/services/onboarding.service.js)."""

from ..middleware.errors import ApiError
from ..models import onboarding as onboarding_db
from ..models import users as users_db

SURVEY_VERSION = 1

# The three survey questions (docs/screens/01-auth-onboarding/05-07). The
# validation schema imports this, so the vocabulary lives in one place.
SURVEY_QUESTIONS = {
    "improveFirst": ["understand_topics", "remember", "exam_prep", "daily_habit"],
    "studyStyle": ["short_sessions", "deep_study", "mix", "unsure"],
    "studyFrequency": ["every_day", "few_times_week", "once_week", "decide_later"],
}


def set_role(user_id, role):
    user = users_db.set_role(user_id, role)
    if not user:
        raise ApiError.not_found("That account no longer exists")
    return user


def submit_survey(user_id, data):
    """Partial answers merge rather than replace; ``complete`` or ``skipped`` finishes the run."""
    answers = data.get("answers") or {}
    skipped = bool(data.get("skipped"))
    complete = bool(data.get("complete"))

    unknown = [key for key in answers if key not in SURVEY_QUESTIONS]
    if unknown:
        raise ApiError.bad_request(f"Unknown survey question(s): {', '.join(unknown)}")

    response = onboarding_db.save_answers(user_id=user_id, answers=answers, skipped=skipped,
                                          survey_version=SURVEY_VERSION, completed=complete or skipped)
    user = users_db.mark_onboarding_complete(user_id) if complete or skipped else None
    return response, user


def get_survey(user_id):
    return onboarding_db.find_by_user_id(user_id)

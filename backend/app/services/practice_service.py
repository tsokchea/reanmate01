"""Practice sessions and mock exams (server/src/services/practice.service.js)."""

import datetime as dt
import logging
import math
import random as _random
import threading

from ..ai import get_ai
from ..middleware.errors import ApiError
from ..models import mock_exam as mock_exam_db
from ..models import practice as practice_db
from ..utils.js import js_round, js_string
from ..utils.serialization import iso
from . import mock_exam_service
from .ai_usage_service import detect_cost_language, track_generation
from .plans_service import plans_service

log = logging.getLogger("reanmate")


def topic_weight(mastery):
    return 1 + 4 * ((100 - (35 if mastery is None else mastery)) / 100) ** 2


def weighted_without_replacement(items, random=_random.random):
    """Leans a practice session towards what the student is worst at."""
    pool = [{**item, "weight": topic_weight(item.get("effective_mastery"))} for item in items]
    selected = []
    while pool:
        total = sum(item["weight"] for item in pool)
        cursor = random() * total
        index = len(pool) - 1
        for i, item in enumerate(pool):
            cursor -= item["weight"]
            if cursor <= 0:
                index = i
                break
        selected.append(pool.pop(index))
    return selected


def _session_api(row):
    return {
        "id": row["id"], "kitId": row["study_kit_id"], "sourceId": row.get("source_id"), "mode": row["mode"],
        "questionCount": row["question_count"], "answerFormat": row["answer_format"],
        "timerSeconds": row["timer_seconds"], "expiresAt": row["expires_at"], "status": row["status"],
        "answered": row["answered_count"], "correct": row["correct_count"],
        "mastery": row["mastery_percent"], "weakTopics": row["weak_topics"] or [],
        "durationSeconds": row["duration_seconds"], "startedAt": row["started_at"],
        "completedAt": row["completed_at"],
    }


def _question_api(row, revealed=False):
    """The answer key stays hidden until the session is over — this is polled mid-exam."""
    return {
        "id": row["id"], "position": row["position"], "prompt": row["prompt"],
        "options": row["options"], "response": row["response"], "answeredAt": row["answered_at"],
        "isCorrect": row.get("is_correct"),
        "graderNote": row.get("grader_note") if revealed else None,
        "explanation": row.get("explanation") if revealed else None,
        "correctAnswer": (row.get("expected_answer") if row.get("expected_answer") is not None
                          else row.get("correct_answer")) if revealed else None,
    }


def _streak_for(values):
    if not values:
        return 0
    days = {iso(value)[:10] if isinstance(value, dt.datetime) else str(value)[:10] for value in values}
    cursor = dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    if cursor.strftime("%Y-%m-%d") not in days:
        cursor -= dt.timedelta(days=1)
    streak = 0
    while cursor.strftime("%Y-%m-%d") in days:
        streak += 1
        cursor -= dt.timedelta(days=1)
    return streak


def _exam_draw(user_id, data, source_id):
    """Shuffled, not mastery-weighted: an exam samples the whole document evenly.

    Returns None when there is no (big enough) bank, the signal to fall back to the quiz pool.
    """
    bank = mock_exam_db.bank_questions(user_id=user_id, kit_id=data["studyKitId"], source_id=source_id)
    if len(bank) < data["questionCount"]:
        return None
    shuffled = list(bank)
    for i in range(len(shuffled) - 1, 0, -1):
        j = math.floor(_random.random() * (i + 1))
        shuffled[i], shuffled[j] = shuffled[j], shuffled[i]
    return [{
        "id": None, "topic_id": row["topic_id"], "prompt": row["prompt"], "options": row["options"],
        "correct_answer": row["correct_answer"], "expected_answer": row["expected_answer"],
        "explanation": row["explanation"], "weight": 0,
    } for row in shuffled]


def _grade_written(user_id, session_id, session):
    """Marks every written answer in one batched call, keyed by position."""
    pending = practice_db.ungraded_written(session_id)
    if not pending:
        return 0
    answers = [{
        "prompt": row["prompt"],
        "expectedAnswer": row["expected_answer"],
        "response": row["response"] if isinstance(row["response"], str)
        else ("" if row["response"] is None else js_string(row["response"])),
    } for row in pending]

    # The note is read by the student, so it is written in the answer key's language.
    language = detect_cost_language("\n".join(a["expectedAnswer"] for a in answers)) or "km"
    grades = track_generation(
        kind="mock_exam", user_id=user_id, study_kit_id=session["study_kit_id"], source_id=session.get("source_id"),
        language=language, source_text="\n".join(a["response"] for a in answers),
        request={"graded": len(answers), "mode": session["mode"]},
        describe=lambda v: {"correct": len([g for g in v if g.get("isCorrect")])},
        run=lambda ai_, on_usage: ai_.grade_written_answers(answers=answers, language=language, on_usage=on_usage),
    )
    if not isinstance(grades, list) or len(grades) != len(pending):
        got = len(grades) if isinstance(grades, list) else "nothing"
        raise RuntimeError(f"grading returned {got} marks for {len(pending)} answers")
    return practice_db.apply_grades(session_id, [
        {"position": row["position"], "isCorrect": bool(grades[i].get("isCorrect")), "note": grades[i].get("note")}
        for i, row in enumerate(pending)
    ])


def _finish_create(result, data):
    if result.get("missing"):
        raise ApiError.not_found("That study kit does not exist")
    if result.get("quotaExceeded"):
        raise ApiError(429, "quota_exceeded", "Weekly practice limit reached",
                       {"used": result["used"], "limit": result["limit"]})
    if result.get("insufficient"):
        raise ApiError.conflict("Not enough generated questions for those settings",
                                {"available": result["available"], "requested": data["questionCount"]})
    limit = result["limit"]
    return {
        "session": _session_api(result["session"]),
        "quota": None if limit is None else {"used": result["used"] + 1, "limit": limit,
                                             "remaining": max(0, limit - result["used"] - 1)},
    }


def topics(user_id, q=None, source_id=None):
    return [{
        "id": row["id"], "kitId": row["study_kit_id"], "title": row["name"], "mastery": row["mastery_percent"],
        "effectiveMastery": row["effective_mastery"], "recommended": row["effective_mastery"] < 50,
        "needsPractice": row["effective_mastery"] < 30,
    } for row in practice_db.topics(user_id=user_id, q=q, source_id=source_id)]


def _backfill_bank(source_id):
    try:
        mock_exam_service.ensure(source_id)
    except Exception as err:
        log.error("[practice] exam bank backfill failed: %s", err)


def create(user_id, _plan, data):
    weekly_limit = plans_service.get_limit(user_id, "practice_sessions_per_week")
    source_id = data.get("sourceId")
    # Mock-provider questions are excluded while a real provider is active.
    provider = get_ai().name

    if data["mode"] == "mock_exam":
        drawn = _exam_draw(user_id, data, source_id)
        if drawn:
            return _finish_create(practice_db.create(user_id=user_id, input=data, weekly_limit=weekly_limit,
                                                     weighted_order=drawn), data)
        # No bank yet: queue one for next time and fall back to the quiz pool now.
        if source_id:
            threading.Thread(target=_backfill_bank, args=(source_id,), daemon=True).start()

    candidates = practice_db.candidate_questions(user_id=user_id, kit_id=data["studyKitId"],
                                                 topic_ids=data["topicIds"], source_id=source_id, provider=provider)
    if data["topicIds"] and len(candidates) < data["questionCount"]:
        # Topping up ignores the chosen topics but never leaves the chosen file.
        everything = practice_db.candidate_questions(user_id=user_id, kit_id=data["studyKitId"], topic_ids=[],
                                                     source_id=source_id, provider=provider)
        seen = {item["id"] for item in candidates}
        candidates = candidates + [item for item in everything if item["id"] not in seen]
    return _finish_create(practice_db.create(user_id=user_id, input=data, weekly_limit=weekly_limit,
                                             weighted_order=weighted_without_replacement(candidates)), data)


def get(user_id, session_id):
    practice_db.expire(user_id=user_id, session_id=session_id)
    session = practice_db.session(user_id=user_id, session_id=session_id)
    if not session:
        raise ApiError.not_found("That practice session does not exist")
    revealed = session["status"] == "completed"
    return {"session": _session_api(session),
            "questions": [_question_api(row, revealed) for row in practice_db.questions(session_id)]}


def answer(user_id, session_id, data):
    saved = practice_db.answer(user_id=user_id, session_id=session_id, input=data)
    if not saved:
        raise ApiError.conflict("That practice session cannot accept this answer")
    return {"answer": {"position": saved["position"], "response": saved["response"],
                       "answeredAt": saved["answered_at"]}}


def submit(user_id, session_id, data=None):
    """Grades written answers first (mastery is derived from is_correct), then closes the session.

    A grading failure does not block submission — the exam was sat, and the
    multiple-choice answers are already marked.
    """
    data = data or {}
    session = practice_db.session(user_id=user_id, session_id=session_id)
    if not session:
        raise ApiError.not_found("That practice session does not exist")
    if session["status"] == "in_progress":
        try:
            _grade_written(user_id, session_id, session)
        except Exception as err:
            log.error("[practice] grading session %s failed: %s", session_id, err)

    row = practice_db.submit(user_id=user_id, session_id=session_id, duration_seconds=data.get("durationSeconds"))
    if not row:
        raise ApiError.not_found("That practice session does not exist")
    return {"result": {**_session_api(row), "total": row["question_count"],
                       "toReview": row["answered_count"] - row["correct_count"]}}


def home(user_id):
    row = practice_db.home(user_id)
    return {"continue": {"sessionId": row["id"], "kitId": row["study_kit_id"], "title": row["title"],
                         "answered": row["answered_count"], "total": row["question_count"]} if row else None}


def progress(user_id):
    data = practice_db.progress(user_id)
    return {
        "hasActivity": len(data["daily"]) > 0,
        "accuracyOverTime": [{
            "date": row["date"], "correct": row["correct"], "total": row["total"],
            "accuracy": js_round((row["correct"] / max(1, row["total"])) * 100),
        } for row in data["daily"]],
        "topics": [{"id": row["id"], "name": row["name"], "mastery": row["mastery_percent"],
                    "attempts": row["attempts"]} for row in data["topics"]],
        "activityStreak": _streak_for(data["dates"]),
    }

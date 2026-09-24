"""Pure service logic, ported from server/test/*.test.js (node:test -> pytest)."""

import datetime as dt
import hashlib

import pytest

from app.ai.mock import create_mock_provider
from app.middleware.errors import ApiError
from app.services import profile_service
from app.services.assignment_state_machine import assert_assignment_transition
from app.services.mock_exam_service import validate_generated_exam
from app.services.plans_service import PlansService, calendar_month_utc, has_plan_capacity
from app.services.quiz_service import balance_answer_positions, validate_generated_quiz
from app.services.reply_language import detect_requested_reply_language
from app.services.sm2 import schedule_sm2_review
from app.services.summaries_service import summary_cache_key

UTC = dt.timezone.utc


# --- adaptive quiz (adaptive-quiz.test.js) ---------------------------------------

def question(**overrides):
    return {
        "kind": "multiple_choice",
        "prompt": "What is a primary key?",
        "options": ["A unique row identifier", "A sort order", "A foreign table", "An index type"],
        "correctAnswer": 0,
        "explanation": "The document defines it as the column identifying each row uniquely.",
        "topic": "Keys",
        **overrides,
    }


def test_question_keeps_weak_concept():
    quiz = validate_generated_quiz({"title": "Adaptive", "questions": [question(targetedWeakConcept=" Keys ")]}, 1)
    assert quiz["questions"][0]["targetedWeakConcept"] == "Keys"


def test_no_weak_concept_is_null_not_empty():
    assert validate_generated_quiz({"title": "Q", "questions": [question()]}, 1)["questions"][0]["targetedWeakConcept"] is None
    blank = validate_generated_quiz({"title": "Q", "questions": [question(targetedWeakConcept="   ")]}, 1)
    assert blank["questions"][0]["targetedWeakConcept"] is None


def test_explanation_required():
    with pytest.raises(ValueError, match="empty explanation"):
        validate_generated_quiz({"title": "Q", "questions": [question(explanation="")]}, 1)


def test_mock_quiz_targets_weak_topics_70_percent():
    quiz = create_mock_provider().generate_quiz(text="material", language="en", count=10,
                                                weak_topics=["Normalization", "Keys"])
    targeted = [q for q in quiz["questions"] if q["targetedWeakConcept"]]
    assert len(targeted) == 7
    assert all(q["targetedWeakConcept"] in ("Normalization", "Keys") for q in targeted)
    assert all(q["kind"] == "multiple_choice" and len(q["options"]) == 4 for q in quiz["questions"])


def test_no_history_spreads_questions():
    quiz = create_mock_provider().generate_quiz(text="material", language="en", count=6)
    assert not [q for q in quiz["questions"] if q["targetedWeakConcept"]]


def test_answered_questions_not_repeated():
    ai = create_mock_provider()
    seen = [q["prompt"] for q in ai.generate_quiz(text="material", language="en", count=8)["questions"]]
    second = ai.generate_quiz(text="material", language="en", count=8, avoid_questions=seen)
    assert not [q for q in second["questions"] if q["prompt"] in seen]


def mcq(i):
    return {"kind": "multiple_choice", "prompt": f"Question {i}",
            "options": [f"right {i}", f"wrong {i}a", f"wrong {i}b", f"wrong {i}c"],
            "correctAnswer": 0, "explanation": "because the document says so", "topic": "Topic"}


def test_answers_spread_across_positions():
    counts = [0, 0, 0, 0]
    for q in balance_answer_positions([mcq(i) for i in range(10)]):
        counts[q["correctAnswer"]] += 1
    assert sum(counts) == 10
    assert all(2 <= n <= 3 for n in counts), counts


def test_shuffle_moves_index_with_answer():
    for i, q in enumerate(balance_answer_positions([mcq(i) for i in range(12)])):
        assert q["options"][q["correctAnswer"]] == f"right {i}"
        assert len(set(q["options"])) == 4


def test_written_question_left_alone():
    written = {"kind": "written", "prompt": "Explain.", "options": [], "correctAnswer": "Fixed costs.",
               "explanation": "e", "topic": "Topic"}
    assert balance_answer_positions([written]) == [written]


def test_shuffle_deterministic_with_fixed_random():
    questions = [mcq(i) for i in range(8)]
    assert balance_answer_positions(questions, lambda: 0.42) == balance_answer_positions(questions, lambda: 0.42)


# --- assignment state machine -------------------------------------------------------

def test_draft_work_can_progress():
    for from_state in ("not_started", "in_progress"):
        for to_state in ("in_progress", "submitted", "late"):
            assert_assignment_transition(from_state, to_state)


def test_only_grade_follows_submitted():
    assert_assignment_transition("submitted", "graded")
    assert_assignment_transition("late", "graded")
    with pytest.raises(ApiError):
        assert_assignment_transition("submitted", "in_progress")
    with pytest.raises(ApiError):
        assert_assignment_transition("late", "submitted")


def test_graded_is_terminal():
    for state in ("not_started", "in_progress", "submitted", "late", "graded"):
        with pytest.raises(ApiError):
            assert_assignment_transition("graded", state)


# --- generation cache key -------------------------------------------------------------

BASE = {"source_id": "11111111-1111-1111-1111-111111111111", "method": "generateQuiz"}


def test_provider_is_part_of_identity_but_not_hash():
    mock = summary_cache_key(**BASE, params={"language": "km"}, provider="mock")
    real = summary_cache_key(**BASE, params={"language": "km"}, provider="openai")
    assert (mock["provider"], real["provider"]) == ("mock", "openai")
    assert mock["paramsHash"] == real["paramsHash"]


def test_params_key_the_row_and_are_canonicalised():
    km = summary_cache_key(**BASE, params={"language": "km"}, provider="openai")
    en = summary_cache_key(**BASE, params={"language": "en"}, provider="openai")
    assert km["paramsHash"] != en["paramsHash"]
    one = summary_cache_key(**BASE, params={"language": "km", "count": 10}, provider="openai")
    two = summary_cache_key(**BASE, params={"count": 10, "language": "km"}, provider="openai")
    assert one["paramsHash"] == two["paramsHash"]


def test_params_hash_matches_node():
    # The Node server hashed JSON.stringify of the key-sorted params; the same
    # bytes must hash here or every existing cache row would be missed.
    key = summary_cache_key(**BASE, params={"language": "km", "count": 10}, provider="openai")
    assert key["paramsHash"] == hashlib.sha256(b'{"count":10,"language":"km"}').hexdigest()


# --- mock exam -------------------------------------------------------------------------

def exam_question(**overrides):
    return {
        "kind": "multiple_choice",
        "prompt": "Which reagent drives the substitution here?",
        "options": ["Sodium hydroxide", "Ethanol", "Acetone", "Water"],
        "correctAnswer": 0,
        "expectedAnswer": "Sodium hydroxide, because the hydroxide ion is the nucleophile.",
        "difficulty": "medium",
        "explanation": "The document names hydroxide as the attacking nucleophile.",
        "topic": "Substitution",
        **overrides,
    }


def exam(questions):
    return {"title": "Mock Exam - Organic Chemistry", "questions": questions}


def test_valid_exam_question_trimmed():
    result = validate_generated_exam(exam([exam_question(prompt="  Trailing space  ",
                                                         expectedAnswer="  Sodium hydroxide.  ")]), 1)
    assert result["questions"][0]["prompt"] == "Trailing space"
    assert result["questions"][0]["expectedAnswer"] == "Sodium hydroxide."


@pytest.mark.parametrize("overrides, message", [
    ({"expectedAnswer": "   "}, "no expectedAnswer"),
    ({"expectedAnswer": None}, "no expectedAnswer"),
    ({"correctAnswer": 4}, "out of range"),
    ({"options": ["Sodium hydroxide", "sodium  hydroxide", "Acetone", "Water"]}, "duplicate options"),
    ({"kind": "short_answer", "correctAnswer": "Hydroxide"}, "must not have choice options"),
    ({"difficulty": "brutal"}, "unknown difficulty"),
])
def test_invalid_exam_questions_rejected(overrides, message):
    with pytest.raises(ValueError, match=message):
        validate_generated_exam(exam([exam_question(**overrides)]), 1)


def test_short_bank_rejected():
    with pytest.raises(ValueError, match="expected exactly 30 questions, got 2"):
        validate_generated_exam(exam([exam_question(), exam_question()]), 30)


def test_mock_bank_passes_validation_with_distinct_prompts():
    generated = create_mock_provider().generate_mock_exam(text="material", title="t", language="en", count=30)
    validated = validate_generated_exam(generated, 30)
    assert len(validated["questions"]) == 30
    assert len({q["prompt"] for q in validated["questions"]}) == 30


def test_mock_bank_marked_in_both_languages():
    for language in ("km", "en"):
        generated = create_mock_provider().generate_mock_exam(text="material", language=language, count=5)
        assert "[MOCK]" in generated["title"]
        assert all("[MOCK]" in q["prompt"] for q in generated["questions"])


# --- profile ---------------------------------------------------------------------------

def test_delete_account_calls_model(monkeypatch):
    calls = []
    monkeypatch.setattr("app.models.profile.delete_account", lambda user_id: calls.append(user_id) or {"id": user_id})
    assert profile_service.delete_account("user-123") == {"deleted": True}
    assert calls == ["user-123"]


# --- quota -------------------------------------------------------------------------------

class FakePlansDb:
    def __init__(self, limit=20, initial=None):
        self.limit_value = limit
        self.counters = dict(initial or {})

    def consume(self, *, user_id, counter_key, period_start, amount=1):
        key = f"{counter_key}:{period_start}"
        used = self.counters.get(key, 0)
        if self.limit_value is not None and used + amount > self.limit_value:
            return None
        self.counters[key] = used + amount
        return {"quantity": used + amount, "limit_value": self.limit_value}

    def limit(self, user_id, key):
        return {"limit_value": self.limit_value}


def test_quota_boundary():
    db = FakePlansDb(initial={"tutor_messages_per_month:2026-09-01": 19})
    service = PlansService(db)
    at = dt.datetime(2026, 9, 30, 23, tzinfo=UTC)
    assert service.consume_quota("u", "tutor_messages_per_month", 1, at)["used"] == 20
    with pytest.raises(ApiError) as err:
        service.consume_quota("u", "tutor_messages_per_month", 1, at)
    assert err.value.code == "quota_exceeded"


def test_month_rollover_uses_fresh_counter():
    service = PlansService(FakePlansDb(initial={"tutor_messages_per_month:2026-09-01": 20}))
    quota = service.consume_quota("u", "tutor_messages_per_month", 1, dt.datetime(2026, 10, 1, tzinfo=UTC))
    assert quota["periodStart"] == "2026-10-01" and quota["used"] == 1
    assert calendar_month_utc(dt.datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC)) == "2026-09-01"


def test_capacity_and_failed_handler():
    assert has_plan_capacity(3, 3) is False
    assert has_plan_capacity(2, 3) is True
    db = FakePlansDb()

    def failing():
        raise RuntimeError("failed")

    with pytest.raises(RuntimeError):
        PlansService(db).after_success("u", "tutor_messages_per_month", failing)
    assert db.counters == {}


# --- reply language ---------------------------------------------------------------------

def test_reply_language():
    assert detect_requested_reply_language("Please explain this in Khmer", "en") == "km"
    assert detect_requested_reply_language("សូមពន្យល់អំពី OOP", "en") == "km"
    assert detect_requested_reply_language("What is OOP?", "en") == "en"


# --- SM-2 -------------------------------------------------------------------------------

START = dt.datetime(2026, 1, 1, 12, tzinfo=UTC)


def test_sm2_first_three_reviews():
    first = schedule_sm2_review(None, 5, START)
    assert first == {"easeFactor": 2.6, "intervalDays": 1, "repetitions": 1, "lapses": 0,
                     "dueAt": dt.datetime(2026, 1, 2, 12, tzinfo=UTC), "lastReviewedAt": START}
    second = schedule_sm2_review(first, 5, first["dueAt"])
    assert (second["intervalDays"], second["repetitions"], second["easeFactor"]) == (6, 2, 2.7)
    assert second["dueAt"] == dt.datetime(2026, 1, 8, 12, tzinfo=UTC)
    third = schedule_sm2_review(second, 5, second["dueAt"])
    assert (third["intervalDays"], third["repetitions"], third["easeFactor"]) == (16, 3, 2.8)
    assert third["dueAt"] == dt.datetime(2026, 1, 24, 12, tzinfo=UTC)


def test_sm2_lapse():
    result = schedule_sm2_review({"easeFactor": 2.8, "intervalDays": 16, "repetitions": 3, "lapses": 0}, 2, START)
    assert (result["intervalDays"], result["repetitions"], result["lapses"], result["easeFactor"]) == (1, 0, 1, 2.48)


def test_sm2_ease_floor():
    first = schedule_sm2_review({"easeFactor": 1.31, "intervalDays": 1, "repetitions": 0, "lapses": 4}, 0, START)
    second = schedule_sm2_review(first, 0, first["dueAt"])
    assert first["easeFactor"] == 1.3 and second["easeFactor"] == 1.3 and second["lapses"] == 6


@pytest.mark.parametrize("quality", [-1, 6, 3.5])
def test_sm2_quality_range(quality):
    with pytest.raises(ValueError):
        schedule_sm2_review(None, quality, START)


# --- written grading (written-grading.test.js) -------------------------------------------

AI = create_mock_provider()
EXPECTED = "It uniquely identifies each record in a table."


def test_grading_right_answer_different_words():
    [grade] = AI.grade_written_answers(language="en", answers=[
        {"prompt": "?", "expectedAnswer": EXPECTED, "response": "It identifies every record in a table uniquely"}])
    assert grade["isCorrect"] is True and grade["note"].strip()


def test_grading_unrelated_and_empty():
    for response in ("It stores pictures", "   "):
        [grade] = AI.grade_written_answers(language="en", answers=[
            {"prompt": "?", "expectedAnswer": EXPECTED, "response": response}])
        assert grade["isCorrect"] is False


def test_grading_khmer():
    expected = "គន្លឹះចម្បងកំណត់អត្តសញ្ញាណកំណត់ត្រា"
    grades = AI.grade_written_answers(language="km", answers=[
        {"prompt": "x", "expectedAnswer": expected, "response": "គន្លឹះចម្បងកំណត់អត្តសញ្ញាណកំណត់ត្រានីមួយៗ"},
        {"prompt": "x", "expectedAnswer": expected, "response": "រូបភាព"},
    ])
    assert [g["isCorrect"] for g in grades] == [True, False]


def test_grading_order_and_usage():
    answers = [
        {"prompt": "a", "expectedAnswer": "Sodium hydroxide is the nucleophile.", "response": "Sodium hydroxide is the nucleophile."},
        {"prompt": "b", "expectedAnswer": "Water is the solvent here.", "response": "completely unrelated text"},
        {"prompt": "c", "expectedAnswer": "Acetone is a ketone.", "response": "Acetone is a ketone."},
    ]
    assert [g["isCorrect"] for g in AI.grade_written_answers(answers=answers, language="en")] == [True, False, True]
    assert AI.grade_written_answers(answers=[], language="en") == []
    reported = []
    AI.grade_written_answers(language="en", answers=[{"prompt": "a", "expectedAnswer": "b", "response": "c"}],
                             on_usage=reported.append)
    assert len(reported) == 1

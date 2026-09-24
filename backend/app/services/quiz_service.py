"""Adaptive quizzes and attempts (server/src/services/quiz.service.js)."""

import math
import random as _random
import threading

from ..ai import get_ai
from ..jobs import queue as job_queue
from ..middleware.errors import ApiError
from ..models import quiz as quiz_db
from ..models import sources as sources_db
from ..models import summaries as summaries_db
from ..utils.js import is_integer, js_round, normalize_option
from .ai_usage_service import track_generation
from .plans_service import plans_service
from .summaries_service import ActiveSet, summary_cache_key

_active = ActiveSet()
_submissions = {}
_submissions_lock = threading.Lock()

_SUPPORTED_KINDS = {"multiple_choice", "true_false", "short_answer", "written"}


def validate_generated_quiz(quiz, expected_count):
    """Stricter than "the JSON parsed": every question must be answerable as stored."""
    if not isinstance(quiz, dict) or not isinstance(quiz.get("title"), str) or not quiz["title"].strip():
        raise ValueError("generateQuiz: quiz title must be non-empty")
    questions_in = quiz.get("questions")
    if not isinstance(questions_in, list) or len(questions_in) != expected_count:
        got = len(questions_in) if isinstance(questions_in, list) else "invalid"
        raise ValueError(f"generateQuiz: expected exactly {expected_count} questions, got {got}")

    questions = []
    for index, question in enumerate(questions_in):
        label = f"generateQuiz: question {index + 1}"
        if not isinstance(question, dict) or question.get("kind") not in _SUPPORTED_KINDS:
            raise ValueError(f"{label} has an unsupported kind")
        if not isinstance(question.get("prompt"), str) or not question["prompt"].strip():
            raise ValueError(f"{label} has an empty prompt")
        if not isinstance(question.get("explanation"), str) or not question["explanation"].strip():
            raise ValueError(f"{label} has an empty explanation")
        options = question.get("options")
        if not isinstance(options, list):
            raise ValueError(f"{label} options must be an array")

        is_choice = question["kind"] in ("multiple_choice", "true_false")
        required = 4 if question["kind"] == "multiple_choice" else 2
        if is_choice and len(options) != required:
            raise ValueError(f"{label} requires exactly {required} options")
        if not is_choice and options:
            raise ValueError(f"{label} must not have choice options")
        if any(not isinstance(option, str) or not option.strip() for option in options):
            raise ValueError(f"{label} has an empty option")
        normalized = [normalize_option(option) for option in options]
        if len(set(normalized)) != len(normalized):
            raise ValueError(f"{label} has duplicate options")
        correct = question.get("correctAnswer")
        if is_choice and (not is_integer(correct) or correct < 0 or correct >= len(options)):
            raise ValueError(f"{label} correct index is out of range")
        if not is_choice and (not isinstance(correct, str) or not correct.strip()):
            raise ValueError(f"{label} needs a non-empty written answer")

        weak = question.get("targetedWeakConcept")
        questions.append({
            **question,
            "prompt": question["prompt"].strip(),
            "options": [option.strip() for option in options],
            "explanation": question["explanation"].strip(),
            "correctAnswer": correct.strip() if isinstance(correct, str) else int(correct),
            "topic": question["topic"].strip() if isinstance(question.get("topic"), str) else "",
            "targetedWeakConcept": weak.strip() if isinstance(weak, str) and weak.strip() else None,
        })
    return {"title": quiz["title"].strip(), "questions": questions}


def balance_answer_positions(questions, random=_random.random):
    """Spreads correct answers evenly across the option slots.

    Asking the model to randomise does not work — it writes the true statement
    first and the answer lands on A far more often than chance. Dealing target
    slots from a bag that holds each slot equally often makes the distribution
    a property of the code. ``random`` is injectable for deterministic tests.
    """

    def shuffled(items):
        copy = list(items)
        for i in range(len(copy) - 1, 0, -1):
            j = math.floor(random() * (i + 1))
            copy[i], copy[j] = copy[j], copy[i]
        return copy

    bags = {}

    def take_slot(option_count, total):
        if option_count not in bags:
            base = total // option_count
            slots = [slot for slot in range(option_count) for _ in range(base)]
            # Leftovers land on randomly chosen slots rather than the first ones.
            remainder = shuffled(range(option_count))[: total - len(slots)]
            bags[option_count] = shuffled(slots + remainder)
        bag = bags[option_count]
        return bag.pop() if bag else math.floor(random() * option_count)

    counts = {}
    for question in questions:
        if is_integer(question.get("correctAnswer")) and len(question["options"]) > 1:
            counts[len(question["options"])] = counts.get(len(question["options"]), 0) + 1

    result = []
    for question in questions:
        option_count = len(question["options"])
        # Only choice questions have a position to move.
        if not is_integer(question.get("correctAnswer")) or option_count < 2:
            result.append(question)
            continue
        target = take_slot(option_count, counts.get(option_count, 1))
        correct = question["options"][question["correctAnswer"]]
        distractors = shuffled(o for i, o in enumerate(question["options"]) if i != question["correctAnswer"])
        options = [correct if slot == target else distractors.pop() for slot in range(option_count)]
        result.append({**question, "options": options, "correctAnswer": target})
    return result


def _require_source(user_id, source_id):
    source = sources_db.find_accessible_by_id(user_id=user_id, source_id=source_id)
    if not source:
        raise ApiError.not_found("That source does not exist")
    if source["status"] != "ready" or not source["extracted_text"]:
        raise ApiError.conflict("That source is not ready for a quiz")
    return source


def _question_api(row):
    return {
        "id": row["id"], "position": row["position"], "kind": row["kind"], "prompt": row["prompt"],
        "options": row["options"], "explanation": None if row["is_correct"] is None else row["explanation"],
        "topic": row["topic_label"], "response": row["response"], "isCorrect": row["is_correct"],
        "correctAnswer": row["revealed_answer"],
        # Named on screen so the student can see the quiz is aimed at their weak spots.
        "targetedWeakConcept": row.get("targeted_weak_concept"),
    }


def _attempt_api(row):
    return {
        "id": row["id"], "quizId": row["quiz_id"], "status": row["status"], "total": row["total_questions"],
        "correct": row["correct_count"], "mastery": row["mastery_percent"], "takeaways": row["takeaways"],
        "startedAt": row["started_at"], "submittedAt": row["submitted_at"],
    }


def _run_generation(payload):
    cache_id, source_id, params = payload["cacheId"], payload["sourceId"], payload["params"]
    try:
        if not summaries_db.claim_cache(cache_id):
            return
        source = sources_db.find_by_id_unscoped(source_id)
        ai = get_ai()
        # Gathered for the student the quiz is FOR — a class material is sat by
        # every enrolled student, each weak at different things.
        for_user = params.get("userId") or source["user_id"]
        avoid = quiz_db.seen_questions(user_id=for_user, source_id=source_id)
        weak = [row["topic"] for row in quiz_db.weak_topics(user_id=for_user, source_id=source_id)]

        raw = track_generation(
            kind="quiz", user_id=source["user_id"], study_kit_id=source["study_kit_id"], source_id=source_id,
            language=params["language"], source_text=source["extracted_text"],
            request={"count": params["count"], "difficulty": params["difficulty"], "reasoningEffort": "medium",
                     "round": params.get("round") or 0, "avoiding": len(avoid), "weakTopics": len(weak)},
            describe=lambda v: {"questions": len(v.get("questions") or []),
                                "targeted": len([q for q in v.get("questions") or [] if q.get("targetedWeakConcept")])},
            run=lambda ai_, on_usage: ai_.generate_quiz(
                text=source["extracted_text"], title=source["name"], language=params["language"],
                difficulty=params["difficulty"], count=params["count"], avoid_questions=avoid, weak_topics=weak,
                reasoning_effort="medium", on_usage=on_usage),
        )
        validated = validate_generated_quiz(raw, params["count"])
        # Shuffled before storing, so the stored index IS the one graded.
        quiz = {**validated, "questions": balance_answer_positions(validated["questions"])}
        quiz_db.save_generated(cache_id=cache_id, source=source, quiz=quiz, params=params, model=ai.name)
    except Exception as err:
        summaries_db.fail_cache(cache_id, str(err))
    finally:
        _active.discard(cache_id)


job_queue.register("quiz.generate", _run_generation)


def _snapshot(cache):
    current = summaries_db.find_cache(cache["id"])
    quiz = quiz_db.by_cache(cache["id"])
    return {
        "cache": {"sourceId": current["source_id"], "method": current["method"], "params": current["params"],
                  "paramsHash": current["params_hash"]},
        "status": current["status"],
        "quiz": {"id": quiz["id"], "title": quiz["title"], "language": quiz["language"],
                 "difficulty": quiz["difficulty"], "questionCount": quiz["question_count"]} if quiz else None,
    }


def prewarm(user_id, source_id, language):
    """Round 0, generated during ingest: the evenly spread quiz every student starts from."""
    params = {"count": plans_service.generation_count(user_id, "quiz"), "difficulty": "mixed",
              "language": language, "userId": user_id, "round": 0}
    cache = summaries_db.get_or_create_cache(summary_cache_key(source_id=source_id, method="generateQuiz",
                                                               params=params))
    if cache["status"] == "ready":
        return
    _run_generation({"cacheId": cache["id"], "sourceId": source_id, "params": params})


def generate(user_id, _plan, source_id, data):
    """``round`` (quizzes already finished) is in the key, so "another quiz" really is another."""
    _require_source(user_id, source_id)
    params = {
        "count": plans_service.generation_count(user_id, "quiz"),
        "difficulty": data["difficulty"],
        "language": data["language"],
        "userId": user_id,
        "round": quiz_db.completed_rounds(user_id=user_id, source_id=source_id),
    }
    cache = summaries_db.get_or_create_cache(summary_cache_key(source_id=source_id, method="generateQuiz",
                                                               params=params))
    if cache["status"] != "ready" and _active.add_if_absent(cache["id"]):
        job_queue.enqueue("quiz.generate", {"cacheId": cache["id"], "sourceId": source_id, "params": params})
    return _snapshot(cache)


def start(user_id, quiz_id):
    attempt = quiz_db.start_attempt(user_id=user_id, quiz_id=quiz_id)
    if not attempt:
        raise ApiError.not_found("That quiz does not exist")
    questions = quiz_db.questions(quiz_id, attempt["id"])
    return {"attempt": _attempt_api(attempt), "questions": [_question_api(q) for q in questions]}


def get_attempt(user_id, attempt_id):
    attempt = quiz_db.attempt(user_id=user_id, attempt_id=attempt_id)
    if not attempt:
        raise ApiError.not_found("That quiz attempt does not exist")
    questions = quiz_db.questions(attempt["quiz_id"], attempt["id"])
    return {"attempt": _attempt_api(attempt), "questions": [_question_api(q) for q in questions]}


def answer(user_id, attempt_id, data):
    saved = quiz_db.save_answer(user_id=user_id, attempt_id=attempt_id, question_id=data["questionId"],
                                response=data["response"], time_spent_seconds=data.get("timeSpentSeconds"))
    if not saved:
        raise ApiError.conflict("That attempt cannot accept this answer")
    attempt = quiz_db.attempt(user_id=user_id, attempt_id=attempt_id)
    question = next(q for q in quiz_db.questions(attempt["quiz_id"], attempt_id) if q["id"] == data["questionId"])
    return {"answer": {"questionId": data["questionId"], "response": saved["response"],
                       "isCorrect": saved["is_correct"], "correctAnswer": question["revealed_answer"],
                       "explanation": question["explanation"]}}


def _submit(user_id, attempt_id):
    stats = quiz_db.submit_stats(user_id=user_id, attempt_id=attempt_id)
    if not stats:
        raise ApiError.not_found("That quiz attempt does not exist")
    if stats["status"] == "submitted":
        return {"attempt": _attempt_api(stats)}
    correct = stats.get("computedCorrect") or 0
    mastery = js_round((correct / max(1, stats["total_questions"])) * 100)
    prose = track_generation(
        kind="takeaways", user_id=user_id, language=stats["language"],
        request={"totalQuestions": stats["total_questions"], "correctCount": correct,
                 "missedTopics": len(stats.get("missedTopics") or [])},
        describe=lambda v: {"takeaways": len(v.get("takeaways") or [])},
        run=lambda ai_, on_usage: ai_.summarize_attempt(
            correct_count=correct, total_questions=stats["total_questions"],
            missed_topics=stats.get("missedTopics") or [], quiz_title=stats["quiz_title"],
            language=stats["language"], on_usage=on_usage),
    )
    finished = quiz_db.finish_attempt(user_id=user_id, attempt_id=attempt_id, correct=correct, mastery=mastery,
                                      takeaways=prose["takeaways"])
    if not finished:
        return {"attempt": _attempt_api(quiz_db.attempt(user_id=user_id, attempt_id=attempt_id))}
    return {"attempt": _attempt_api(finished)}


def submit(user_id, attempt_id):
    """Concurrent submits of one attempt share a single piece of work (one takeaways call)."""
    with _submissions_lock:
        pending = _submissions.get(attempt_id)
        owner = pending is None
        if owner:
            pending = {"event": threading.Event(), "result": None, "error": None}
            _submissions[attempt_id] = pending
    if not owner:
        pending["event"].wait()
        if pending["error"]:
            raise pending["error"]
        return pending["result"]
    try:
        pending["result"] = _submit(user_id, attempt_id)
        return pending["result"]
    except Exception as err:
        pending["error"] = err
        raise
    finally:
        pending["event"].set()
        with _submissions_lock:
            _submissions.pop(attempt_id, None)

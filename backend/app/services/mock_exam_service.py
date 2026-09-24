"""Mock exam question banks (server/src/services/mockExam.service.js).

The bank (30) is bigger than the largest sitting (20), so a draw cannot run
short and two exams on the same material are not the same exam.
"""

from ..ai import get_ai
from ..jobs import queue as job_queue
from ..models import mock_exam as mock_exam_db
from ..models import sources as sources_db
from ..models import summaries as summaries_db
from ..utils.js import is_integer, normalize_option
from .ai_usage_service import detect_cost_language, track_generation
from .quiz_service import balance_answer_positions
from .summaries_service import ActiveSet, summary_cache_key

BANK_SIZE = 30

_active = ActiveSet()
_KINDS = {"multiple_choice", "true_false", "short_answer", "written"}
_DIFFICULTIES = {"easy", "medium", "hard"}


def validate_generated_exam(exam, expected_count):
    """Stricter than "the JSON parsed" — every stored question must be answerable and gradeable."""
    if not isinstance(exam, dict) or not isinstance(exam.get("title"), str) or not exam["title"].strip():
        raise ValueError("generateMockExam: exam title must be non-empty")
    questions_in = exam.get("questions")
    if not isinstance(questions_in, list) or len(questions_in) != expected_count:
        got = len(questions_in) if isinstance(questions_in, list) else "invalid"
        raise ValueError(f"generateMockExam: expected exactly {expected_count} questions, got {got}")

    questions = []
    for index, question in enumerate(questions_in):
        label = f"generateMockExam: question {index + 1}"
        if not isinstance(question, dict) or question.get("kind") not in _KINDS:
            raise ValueError(f"{label} has an unsupported kind")
        if not isinstance(question.get("prompt"), str) or not question["prompt"].strip():
            raise ValueError(f"{label} has an empty prompt")
        if not isinstance(question.get("explanation"), str) or not question["explanation"].strip():
            raise ValueError(f"{label} has an empty explanation")
        # A written answer is marked against this, so an empty one marks every response wrong.
        if not isinstance(question.get("expectedAnswer"), str) or not question["expectedAnswer"].strip():
            raise ValueError(f"{label} has no expectedAnswer to mark a written response against")
        if question.get("difficulty") not in _DIFFICULTIES:
            raise ValueError(f"{label} has an unknown difficulty")
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

        questions.append({
            **question,
            "prompt": question["prompt"].strip(),
            "options": [option.strip() for option in options],
            "expectedAnswer": question["expectedAnswer"].strip(),
            "explanation": question["explanation"].strip(),
            "correctAnswer": correct.strip() if isinstance(correct, str) else int(correct),
            "topic": question["topic"].strip() if isinstance(question.get("topic"), str) else "",
        })
    return {"title": exam["title"].strip(), "questions": questions}


def _run_generation(payload):
    cache_id, source_id, params = payload["cacheId"], payload["sourceId"], payload["params"]
    try:
        if not summaries_db.claim_cache(cache_id):
            return
        source = sources_db.find_by_id_unscoped(source_id)
        ai = get_ai()
        raw = track_generation(
            kind="mock_exam", user_id=source["user_id"], study_kit_id=source["study_kit_id"], source_id=source_id,
            language=params["language"], source_text=source["extracted_text"],
            request={"count": params["count"], "reasoningEffort": "medium"},
            describe=lambda v: {"questions": len(v.get("questions") or []),
                                "hard": len([q for q in v.get("questions") or [] if q.get("difficulty") == "hard"])},
            run=lambda ai_, on_usage: ai_.generate_mock_exam(
                text=source["extracted_text"], title=source["name"], language=params["language"],
                count=params["count"], reasoning_effort="medium", on_usage=on_usage),
        )
        validated = validate_generated_exam(raw, params["count"])
        # Same reasoning as quizzes: the answer would otherwise land on A far too often.
        exam = {**validated, "questions": balance_answer_positions(validated["questions"])}
        mock_exam_db.save_bank(cache_id=cache_id, source=source, exam=exam, params=params, model=ai.name)
    except Exception as err:
        summaries_db.fail_cache(cache_id, str(err))
    finally:
        _active.discard(cache_id)


job_queue.register("mockExam.generate", _run_generation)


def prewarm(source_id, language):
    """Generated during ingest, so starting an exam never waits."""
    params = {"count": BANK_SIZE, "language": language}
    cache = summaries_db.get_or_create_cache(summary_cache_key(source_id=source_id, method="generateMockExam",
                                                               params=params))
    if cache["status"] == "ready":
        return
    _run_generation({"cacheId": cache["id"], "sourceId": source_id, "params": params})


def ensure(source_id):
    """Queues a bank for a source that predates exam banks, without blocking.

    The language comes from the source text, exactly as ingest derives it —
    guessing would key a second bank the prewarmed path never looks at.
    """
    source = sources_db.find_by_id_unscoped(source_id)
    if not source or not source["extracted_text"]:
        return
    params = {"count": BANK_SIZE, "language": detect_cost_language(source["extracted_text"])}
    cache = summaries_db.get_or_create_cache(summary_cache_key(source_id=source_id, method="generateMockExam",
                                                               params=params))
    if cache["status"] == "ready" or not _active.add_if_absent(cache["id"]):
        return
    job_queue.enqueue("mockExam.generate", {"cacheId": cache["id"], "sourceId": source_id, "params": params})

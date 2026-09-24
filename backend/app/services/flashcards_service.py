"""Flashcards and SM-2 reviews (server/src/services/flashcards.service.js)."""

import datetime as dt

from ..ai import get_ai
from ..jobs import queue as job_queue
from ..middleware.errors import ApiError
from ..models import flashcards as flashcards_db
from ..models import sources as sources_db
from ..models import summaries as summaries_db
from ..utils.js import normalize_option, now_ms
from . import usage_service
from .ai_usage_service import track_generation
from .plans_service import plans_service
from .sm2 import schedule_sm2_review
from .summaries_service import ActiveSet, summary_cache_key

_active = ActiveSet()


def validate_generated_flashcards(cards, expected_count):
    if not isinstance(cards, list) or len(cards) != expected_count:
        got = len(cards) if isinstance(cards, list) else "invalid"
        raise ValueError(f"generateFlashcards: expected exactly {expected_count} cards, got {got}")
    terms = set()
    result = []
    for index, card in enumerate(cards):
        label = f"generateFlashcards: card {index + 1}"
        if not isinstance(card, dict):
            raise ValueError(f"{label} is invalid")
        if not isinstance(card.get("term"), str) or not card["term"].strip():
            raise ValueError(f"{label} has an empty term")
        if not isinstance(card.get("definition"), str) or not card["definition"].strip():
            raise ValueError(f"{label} has an empty definition")
        term = card["term"].strip()
        key = normalize_option(term)
        if key in terms:
            raise ValueError(f'{label} duplicates term "{term}"')
        terms.add(key)
        hint = card.get("hint")
        result.append({
            "term": term,
            "definition": card["definition"].strip(),
            "hint": hint.strip() if isinstance(hint, str) and hint.strip() else None,
            "topic": card["topic"].strip() if isinstance(card.get("topic"), str) else "",
        })
    return result


def _card_api(row):
    return {
        "id": row["id"], "kitId": row["study_kit_id"], "sourceId": row["source_id"], "term": row["term"],
        "definition": row["definition"], "hint": row["hint"], "language": row["language"],
        "position": row["position"], "easeFactor": row["ease_factor"], "intervalDays": row["interval_days"],
        "repetitions": row["repetitions"], "lapses": row["lapses"], "dueAt": row["due_at"],
        "lastReviewedAt": row["last_reviewed_at"],
    }


def _require_source(user_id, source_id):
    source = sources_db.find_accessible_by_id(user_id=user_id, source_id=source_id)
    if not source:
        raise ApiError.not_found("That source does not exist")
    if source["status"] != "ready" or not source["extracted_text"]:
        raise ApiError.conflict("That source is not ready for flashcards")
    return source


def _run_generation(payload):
    cache_id, source_id, params = payload["cacheId"], payload["sourceId"], payload["params"]
    try:
        if not summaries_db.claim_cache(cache_id):
            return
        source = sources_db.find_by_id_unscoped(source_id)
        usage_service.check(source["user_id"], "flashcards", params["count"])
        raw = track_generation(
            kind="flashcards", user_id=source["user_id"], study_kit_id=source["study_kit_id"], source_id=source_id,
            language=params["language"], source_text=source["extracted_text"],
            request={"count": params["count"], "reasoningEffort": "none"},
            describe=lambda v: {"cards": len(v) if isinstance(v, list) else 0},
            run=lambda ai_, on_usage: ai_.generate_flashcards(
                text=source["extracted_text"], language=params["language"], count=params["count"],
                reasoning_effort="none", on_usage=on_usage),
        )
        cards = validate_generated_flashcards(raw, params["count"])
        flashcards_db.save_generated(cache_id=cache_id, source=source, cards=cards, language=params["language"])
        usage_service.record(source["user_id"], flashcards=len(cards))
    except Exception as err:
        summaries_db.fail_cache(cache_id, str(err))
    finally:
        _active.discard(cache_id)


job_queue.register("flashcards.generate", _run_generation)


def _snapshot(cache, user_id):
    current = summaries_db.find_cache(cache["id"])
    cards = flashcards_db.by_cache(cache["id"], user_id) if current["status"] == "ready" else []
    result = {
        "cache": {"sourceId": current["source_id"], "method": current["method"], "params": current["params"],
                  "paramsHash": current["params_hash"]},
        "status": current["status"],
        "cards": [_card_api(row) for row in cards],
    }
    if current["status"] == "failed":
        result["error"] = current["error_message"]
    return result


def prewarm(user_id, source_id, language):
    params = {"count": plans_service.generation_count(user_id, "flashcards"), "language": language}
    cache = summaries_db.get_or_create_cache(summary_cache_key(source_id=source_id, method="generateFlashcards",
                                                               params=params))
    if cache["status"] == "ready":
        return
    _run_generation({"cacheId": cache["id"], "sourceId": source_id, "params": params})


def generate(user_id, _plan, source_id, data):
    _require_source(user_id, source_id)
    params = {"count": plans_service.generation_count(user_id, "flashcards"), "language": data["language"]}
    # Refused here, synchronously, so the screen gets the limit error rather than a failed deck.
    usage_service.check(user_id, "flashcards", params["count"])
    usage_service.check(user_id, "ai_tokens")
    if data.get("regenerate"):
        params["round"] = data["round"] if data.get("round") is not None else now_ms()
    cache = summaries_db.get_or_create_cache(summary_cache_key(source_id=source_id, method="generateFlashcards",
                                                               params=params))
    if cache["status"] != "ready" and _active.add_if_absent(cache["id"]):
        job_queue.enqueue("flashcards.generate", {"cacheId": cache["id"], "sourceId": source_id, "params": params})
    return _snapshot(cache, user_id)


def due(user_id, data):
    rows = flashcards_db.due(user_id=user_id, limit=data["limit"], kit_id=data.get("kitId"),
                             source_id=data.get("sourceId"))
    return {"cards": [_card_api(row) for row in rows]}


def review(user_id, flashcard_id, quality):
    row = flashcards_db.review(user_id=user_id, flashcard_id=flashcard_id, quality=quality,
                               reviewed_at=dt.datetime.now(dt.timezone.utc), calculate=schedule_sm2_review)
    if not row:
        raise ApiError.not_found("That flashcard does not exist")
    return {
        "nextDueAt": row["due_at"],
        "review": {
            "flashcardId": row["flashcard_id"], "quality": row["quality"], "easeFactor": float(row["ease_factor"]),
            "intervalDays": row["interval_days"], "repetitions": row["repetitions"], "lapses": row["lapses"],
            "dueAt": row["due_at"], "lastReviewedAt": row["last_reviewed_at"],
        },
    }

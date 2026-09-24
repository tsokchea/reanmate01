"""Summaries and chaptered summaries (server/src/services/summaries.service.js).

``prewarm`` runs a generation inline and waits (ingest uses it so a source is
only 'ready' once its materials exist); ``summarize``/``chapters`` create the
cache row and hand the work to the queue for a polling screen to collect.
"""

import hashlib
import json
import threading

from ..ai import get_ai
from ..jobs import queue as job_queue
from ..middleware.errors import ApiError
from ..models import sources as sources_db
from ..models import summaries as summaries_db
from .ai_usage_service import track_generation
from .plans_service import plans_service


def _canonicalize(value):
    if isinstance(value, list):
        return [_canonicalize(item) for item in value]
    if isinstance(value, dict):
        return {key: _canonicalize(value[key]) for key in sorted(value)}
    return value


def summary_cache_key(*, source_id, method, params, provider=None):
    """The cache identity. ``provider`` is part of it so mock output never answers for the real model.

    The params hash is byte-for-byte the Node server's (canonical JSON.stringify
    then SHA-256), so cache rows written before the migration are still found.
    """
    canonical = json.dumps(_canonicalize(params), ensure_ascii=False, separators=(",", ":"))
    return {
        "sourceId": source_id,
        "method": method,
        "provider": provider or get_ai().name,
        "params": json.loads(canonical),
        "paramsHash": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


class ActiveSet:
    """Cache ids with work queued in this process, so polling never double-queues."""

    def __init__(self):
        self._ids = set()
        self._lock = threading.Lock()

    def add_if_absent(self, cache_id):
        with self._lock:
            if cache_id in self._ids:
                return False
            self._ids.add(cache_id)
            return True

    def __contains__(self, cache_id):
        with self._lock:
            return cache_id in self._ids

    def add(self, cache_id):
        with self._lock:
            self._ids.add(cache_id)

    def discard(self, cache_id):
        with self._lock:
            self._ids.discard(cache_id)


_active = ActiveSet()


def _enqueue_once(job_type, payload):
    if _active.add_if_absent(payload["cacheId"]):
        job_queue.enqueue(job_type, payload)


def require_source(user_id, source_id, not_ready_message="That source is not ready to summarize", with_status=True):
    source = sources_db.find_accessible_by_id(user_id=user_id, source_id=source_id)
    if not source:
        raise ApiError.not_found("That source does not exist")
    if source["status"] != "ready" or not source["extracted_text"]:
        raise ApiError.conflict(not_ready_message, {"status": source["status"]} if with_status else None)
    return source


def _chapter_api(row):
    return {
        "index": row["chapter_index"], "title": row["title"], "bodyMd": row["body_md"],
        "keyPoints": row["key_points"], "startSeconds": row["start_seconds"], "endSeconds": row["end_seconds"],
        "status": row["status"], "updatedAt": row["updated_at"],
    }


def _snapshot(cache, source):
    current = summaries_db.find_cache(cache["id"])
    result = summaries_db.get_summary(cache["id"]) if current["method"] == "summarize" else None
    chapters = summaries_db.list_chapters(cache["id"]) if current["method"] == "summarizeChapters" else []
    return {
        "cache": {"sourceId": current["source_id"], "method": current["method"], "params": current["params"],
                  "paramsHash": current["params_hash"]},
        "source": {"id": source["id"], "kitId": source["study_kit_id"], "name": source["name"],
                   "kind": source["kind"], "durationSeconds": source["duration_seconds"]},
        "status": current["status"],
        "summary": {"title": result["title"], "bodyMd": result["body_md"], "keyPoints": result["key_points"],
                    "language": result["language"]} if result else None,
        "chapters": [_chapter_api(row) for row in chapters],
    }


def _run_summary(payload):
    cache_id, source_id, language = payload["cacheId"], payload["sourceId"], payload["language"]
    try:
        if not summaries_db.claim_cache(cache_id):
            return
        source = sources_db.find_by_id_unscoped(source_id)
        ai = get_ai()
        result = track_generation(
            kind="summary", user_id=source["user_id"], study_kit_id=source["study_kit_id"], source_id=source_id,
            language=language, source_text=source["extracted_text"],
            request={"method": "summarize", "serviceTier": "batch"},
            describe=lambda s: {"bodyChars": len(s.get("bodyMd") or ""), "keyPoints": len(s.get("keyPoints") or [])},
            run=lambda ai_, on_usage: ai_.summarize(text=source["extracted_text"], title=source["name"],
                                                    language=language, service_tier="batch", on_usage=on_usage),
        )
        summaries_db.save_summary(cache_id=cache_id, source=source, result={**result, "language": language},
                                  model=ai.name)
    except Exception as err:
        summaries_db.fail_cache(cache_id, str(err))
    finally:
        _active.discard(cache_id)


def _run_chapters(payload):
    cache_id, source_id = payload["cacheId"], payload["sourceId"]
    language, chapter_count = payload["language"], payload["chapterCount"]
    try:
        claimed = summaries_db.claim_cache(cache_id)
        if not claimed:
            return
        source = sources_db.find_by_id_unscoped(source_id)
        ai = get_ai()
        outline = claimed["outline"]
        if not outline:
            outlined = track_generation(
                kind="summary", user_id=source["user_id"], study_kit_id=source["study_kit_id"], source_id=source_id,
                language=language, source_text=source["extracted_text"],
                request={"method": "summarizeChapters", "phase": "outline", "chapterCount": chapter_count,
                         "serviceTier": "batch"},
                describe=lambda v: {"chapters": len(v.get("outline") or [])},
                run=lambda ai_, on_usage: ai_.summarize_chapters(
                    text=source["extracted_text"], title=source["name"], language=language,
                    duration_seconds=source["duration_seconds"], chapter_count=chapter_count, only=[],
                    service_tier="batch", on_usage=on_usage),
            )
            outline = outlined["outline"]
            summaries_db.save_outline(cache_id=cache_id, source=source, outline=outline, language=language)

        for row in [r for r in summaries_db.list_chapters(cache_id) if r["status"] != "ready"]:
            if not summaries_db.claim_chapter(cache_id, row["chapter_index"]):
                continue
            try:
                generated = track_generation(
                    kind="summary", user_id=source["user_id"], study_kit_id=source["study_kit_id"],
                    source_id=source_id, language=language, source_text=source["extracted_text"],
                    request={"method": "summarizeChapters", "phase": "body", "chapterIndex": row["chapter_index"],
                             "serviceTier": "batch"},
                    describe=lambda v: {"bodyChars": len(((v.get("chapters") or [{}])[0] or {}).get("bodyMd") or "")},
                    run=lambda ai_, on_usage, index=row["chapter_index"]: ai_.summarize_chapters(
                        text=source["extracted_text"], title=source["name"], language=language,
                        duration_seconds=source["duration_seconds"], outline=outline, only=[index],
                        service_tier="batch", on_usage=on_usage),
                )
                summaries_db.save_chapter(cache_id=cache_id, chapter=generated["chapters"][0], model=ai.name)
            except Exception:
                summaries_db.fail_chapter(cache_id, row["chapter_index"])
        summaries_db.finish_chapters(cache_id)
    except Exception as err:
        summaries_db.fail_cache(cache_id, str(err))
    finally:
        _active.discard(cache_id)


job_queue.register("summary.generate", _run_summary)
job_queue.register("chapters.generate", _run_chapters)


def prewarm(source_id, language):
    key = summary_cache_key(source_id=source_id, method="summarize", params={"language": language})
    cache = summaries_db.get_or_create_cache(key)
    if cache["status"] == "ready":
        return
    _run_summary({"cacheId": cache["id"], "sourceId": source_id, "language": language})


def summarize(user_id, source_id, data):
    source = require_source(user_id, source_id)
    key = summary_cache_key(source_id=source_id, method="summarize", params={"language": data["language"]})
    cache = summaries_db.get_or_create_cache(key)
    if cache["status"] != "ready":
        _enqueue_once("summary.generate", {"cacheId": cache["id"], "sourceId": source_id, "language": data["language"]})
    return _snapshot(cache, source)


def chapters(user_id, source_id, data):
    plans_service.require_feature(user_id, "chapter_summaries")
    source = require_source(user_id, source_id)
    params = {"chapterCount": data["chapterCount"], "language": data["language"]}
    cache = summaries_db.get_or_create_cache(
        summary_cache_key(source_id=source_id, method="summarizeChapters", params=params))
    if cache["status"] != "ready":
        _enqueue_once("chapters.generate", {"cacheId": cache["id"], "sourceId": source_id, **params})
    return _snapshot(cache, source)

"""The Study Guide: one document, taught as modules (server/src/services/studyGuide.service.js).

Single-file isolation is enforced here, not in the prompt: exactly one
kit_sources row is resolved and only its extracted_text reaches the model.
Generation mirrors chaptered summaries: outline once, then one call per module,
each claimed separately so a failure costs one module rather than the guide.
"""

from concurrent.futures import ThreadPoolExecutor

from ..ai import get_ai
from ..config import config
from ..jobs import queue as job_queue
from ..models import study_guide as study_guide_db
from ..models import summaries as summaries_db
from ..models import sources as sources_db
from .ai_usage_service import track_generation
from .summaries_service import ActiveSet, require_source, summary_cache_key

# Part of the cache key: bumping it regenerates guides written under an older prompt.
GUIDE_PROMPT_VERSION = 2

_active = ActiveSet()


def _module_api(row):
    # Section labels are NOT here — the client writes them from its own i18n dictionaries.
    return {
        "index": row["position"], "title": row["title"], "explanationMd": row["explanation_md"],
        "applicationMd": row["application_md"], "pitfallsMd": row["pitfalls_md"], "recall": row["recall"] or [],
        "status": row["status"], "updatedAt": row["updated_at"],
    }


def _snapshot(cache, source):
    current = summaries_db.find_cache(cache["id"])
    modules = study_guide_db.list_modules(cache["id"])
    return {
        "status": current["status"],
        "source": {"id": source["id"], "kitId": source["study_kit_id"], "name": source["name"], "kind": source["kind"]},
        "modules": [_module_api(row) for row in modules],
    }


def _run_study_guide(payload):
    cache_id, source_id = payload["cacheId"], payload["sourceId"]
    language, module_count = payload["language"], payload["moduleCount"]
    try:
        claimed = summaries_db.claim_cache(cache_id)
        if not claimed:
            return
        source = sources_db.find_by_id_unscoped(source_id)
        ai = get_ai()

        outline = claimed["outline"]
        if not outline:
            planned = track_generation(
                kind="summary", user_id=source["user_id"], study_kit_id=source["study_kit_id"], source_id=source_id,
                language=language, source_text=source["extracted_text"],
                request={"method": "generateStudyGuide", "phase": "outline", "moduleCount": module_count,
                         "serviceTier": "batch"},
                describe=lambda v: {"modules": len(v.get("outline") or [])},
                run=lambda ai_, on_usage: ai_.generate_study_guide(
                    text=source["extracted_text"], title=source["name"], language=language,
                    module_count=module_count, only=[], service_tier="batch", on_usage=on_usage),
            )
            outline = planned["outline"]
            study_guide_db.save_outline(cache_id=cache_id, source=source, outline=outline, language=language)

        def generate_module(row):
            if not study_guide_db.claim_module(cache_id, row["position"]):
                return
            try:
                def describe(value):
                    module = (value.get("modules") or [{}])[0] or {}
                    return {
                        "bodyChars": len(module.get("explanationMd") or "") + len(module.get("applicationMd") or "")
                        + len(module.get("pitfallsMd") or ""),
                        "recall": len(module.get("recall") or []),
                    }

                generated = track_generation(
                    kind="summary", user_id=source["user_id"], study_kit_id=source["study_kit_id"],
                    source_id=source_id, language=language, source_text=source["extracted_text"],
                    request={"method": "generateStudyGuide", "phase": "module", "moduleIndex": row["position"],
                             "serviceTier": "batch"},
                    describe=describe,
                    run=lambda ai_, on_usage: ai_.generate_study_guide(
                        text=source["extracted_text"], title=source["name"], language=language, outline=outline,
                        only=[row["position"]], service_tier="batch", on_usage=on_usage),
                )
                study_guide_db.save_module(cache_id=cache_id, module=generated["modules"][0], model=ai.name)
            except Exception:
                study_guide_db.fail_module(cache_id, row["position"])

        rows = [r for r in study_guide_db.list_modules(cache_id) if r["status"] != "ready"]
        # Every module at once (up to AI_MAX_CONCURRENCY): the guide then takes
        # as long as its slowest module rather than the sum of several rounds.
        if rows:
            with ThreadPoolExecutor(max_workers=min(config.AI_MAX_CONCURRENCY, len(rows))) as pool:
                list(pool.map(generate_module, rows))
        study_guide_db.finish(cache_id)
    except Exception as err:
        summaries_db.fail_cache(cache_id, str(err))
    finally:
        _active.discard(cache_id)


job_queue.register("studyGuide.generate", _run_study_guide)


def prewarm(source_id, language, module_count=8):
    key = summary_cache_key(source_id=source_id, method="generateStudyGuide",
                            params={"language": language, "moduleCount": module_count,
                                    "promptVersion": GUIDE_PROMPT_VERSION})
    cache = summaries_db.get_or_create_cache(key)
    if cache["status"] == "ready":
        return
    _run_study_guide({"cacheId": cache["id"], "sourceId": source_id, "language": language,
                      "moduleCount": module_count})


def generate(user_id, source_id, data):
    source = require_source(user_id, source_id, "That material is not ready to study")
    params = {"language": data["language"], "moduleCount": data["moduleCount"], "promptVersion": GUIDE_PROMPT_VERSION}
    cache = summaries_db.get_or_create_cache(
        summary_cache_key(source_id=source_id, method="generateStudyGuide", params=params))
    if cache["status"] != "ready" and _active.add_if_absent(cache["id"]):
        job_queue.enqueue("studyGuide.generate", {"cacheId": cache["id"], "sourceId": source_id,
                                                  "language": data["language"], "moduleCount": data["moduleCount"]})
    return _snapshot(cache, source)

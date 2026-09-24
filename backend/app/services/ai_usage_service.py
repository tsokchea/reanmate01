"""The per-call cost ledger in ``ai_generations`` (server/src/services/aiUsage.service.js).

Two rules: telemetry never breaks a generation (every write is wrapped), and
content is never stored — ``request`` holds the knobs that shaped the call and
``response`` holds shape counts.
"""

import logging
import re
import time

from ..ai import get_ai
from ..ai.types import create_usage_collector
from ..models import ai_generations as ai_generations_db

log = logging.getLogger("reanmate")

_KHMER_BLOCK = re.compile("[ក-៿]")


def detect_cost_language(text):
    """Cost bucketing, not language detection: >10% Khmer characters is the Khmer bucket."""
    value = str(text if text is not None else "")
    if not value:
        return None
    khmer = len(_KHMER_BLOCK.findall(value))
    return "km" if khmer / len(value) > 0.1 else "en"


def _write(row):
    try:
        return ai_generations_db.insert(**row)
    except Exception as err:
        log.warning("[ai] could not record %s generation: %s", row.get("kind"), err)
        return None


def track_generation(*, kind, user_id=None, study_kit_id=None, source_id=None, language=None, source_text=None,
                     request=None, describe=None, run):
    """Runs one AI call and records what it cost; ``run(ai, on_usage)`` must pass on_usage through."""
    ai = get_ai()
    usage = create_usage_collector()
    started = time.time()
    base = {
        "user_id": user_id, "study_kit_id": study_kit_id, "source_id": source_id, "kind": kind,
        "provider": ai.name, "language": language,
        "source_chars": len(source_text) if isinstance(source_text, str) else None,
        "request": request or {},
    }
    try:
        result = run(ai, usage.record)
    except Exception as err:
        total = usage.total()
        _write({**base, "model": total["model"], "response": {}, "status": "failed", "error_message": str(err),
                "latency_ms": int((time.time() - started) * 1000), "usage": total})
        raise

    total = usage.total()
    _write({**base, "model": total["model"], "response": describe(result) if describe else {}, "status": "ok",
            "latency_ms": int((time.time() - started) * 1000), "usage": total})
    return result


def record_streamed_generation(*, kind="tutor", user_id=None, study_kit_id=None, source_id=None, language=None,
                               source_text=None, request=None, response=None, status="ok", error_message=None,
                               usage_total=None, started_at=None):
    """The streaming counterpart: the caller drives the stream and records once it ends."""
    return _write({
        "user_id": user_id, "study_kit_id": study_kit_id, "source_id": source_id, "kind": kind,
        "provider": get_ai().name, "model": (usage_total or {}).get("model"), "language": language,
        "source_chars": len(source_text) if isinstance(source_text, str) else None,
        "request": request or {}, "response": response or {}, "status": status, "error_message": error_message,
        "latency_ms": int((time.time() - started_at) * 1000) if started_at else None, "usage": usage_total or {},
    })


def token_ratios(since_days=7):
    return ai_generations_db.token_ratios(since_days)

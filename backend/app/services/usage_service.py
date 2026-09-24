"""Usage limits and usage tracking — separate from permissions and from rate limits.

  permission   may this account use the feature at all (rbac_service)
  usage limit  how much of it this account may use per day / month (here)
  rate limit   how many requests per minute (middleware/rate_limit.py)

Limits resolve per field: the account's own override when set, otherwise its
role's default; a NULL role default means no limit. Usage is counted per
account per UTC day in usage_records, and every check happens here on the
server, before the work starts.

Counters (uploads, assignments, flashcards, tutor messages, storage) are
checked with the amount about to be added: ``used + amount > limit`` fails.
AI tokens are only known after a call, so the check is "already at or over
the limit" and the call's real usage is recorded when it returns. Between a
check and its record there is a small window where two simultaneous requests
can both pass — the overshoot is bounded by one action.
"""

import datetime as dt
import logging

from ..middleware.errors import ApiError
from ..models import audit as audit_db
from ..models import usage as usage_db
from ..models.usage import DIRECT, LIMIT_FIELDS, USAGE_FIELDS

log = logging.getLogger("reanmate")

# metric -> (usage_records column, daily limit field, monthly limit field, error-code noun, message noun)
METRICS = {
    "ai_tokens": ("ai_total_tokens", "dailyAiTokens", "monthlyAiTokens", "AI", "AI usage"),
    "uploads": ("pdf_uploads", "dailyPdfUploads", "monthlyPdfUploads", "UPLOAD", "upload"),
    "assignments": ("assignments_created", "dailyAssignments", "monthlyAssignments", "ASSIGNMENT", "assignment"),
    "flashcards": ("flashcards_created", "dailyFlashcards", "monthlyFlashcards", "FLASHCARD", "flashcard"),
    "tutor_messages": ("tutor_messages", "dailyTutorMessages", "monthlyTutorMessages", "TUTOR", "tutor message"),
    "storage": ("storage_bytes", "dailyFileStorageBytes", "monthlyFileStorageBytes", "STORAGE", "file storage"),
}

# record() keyword -> usage_records column
_RECORD_COLUMNS = {
    "ai_input": "ai_input_tokens", "ai_output": "ai_output_tokens", "ai_total": "ai_total_tokens",
    "uploads": "pdf_uploads", "assignments": "assignments_created", "flashcards": "flashcards_created",
    "tutor_messages": "tutor_messages", "storage": "storage_bytes",
}


def _now():
    return dt.datetime.now(dt.timezone.utc)


def today():
    return _now().date().isoformat()


def month_start():
    return _now().date().replace(day=1).isoformat()


def _resets_at(period):
    now = _now()
    if period == "daily":
        nxt = (now + dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        nxt = (first + dt.timedelta(days=32)).replace(day=1)
    return nxt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def enabled():
    return audit_db.setting("usage_limits_enabled") is not False


def _camel_limits(row):
    return {field: (row or {}).get(column) for field, column in LIMIT_FIELDS.items()}


def _camel_usage(row):
    return {field: int((row or {}).get(column) or 0) for field, column in USAGE_FIELDS.items()}


def _layers(user_id):
    """(role defaults, account overrides) as camelCase dicts."""
    role_row, account_row = usage_db.effective_limit_rows(user_id)
    return _camel_limits(role_row), _camel_limits(account_row)


def effective_limits(user_id):
    defaults, overrides = _layers(user_id)
    return {field: overrides[field] if overrides[field] is not None else defaults[field] for field in LIMIT_FIELDS}


def limits_payload(user_id):
    defaults, overrides = _layers(user_id)
    effective = {field: overrides[field] if overrides[field] is not None else defaults[field]
                 for field in LIMIT_FIELDS}
    source = {field: "account" if overrides[field] is not None else ("role" if defaults[field] is not None else "none")
              for field in LIMIT_FIELDS}
    return {"defaults": defaults, "overrides": overrides, "effective": effective, "source": source}


def usage_snapshot(user_id, runner=DIRECT):
    day = today()
    return {
        "today": _camel_usage(usage_db.totals(runner, user_id, day, day)),
        "month": _camel_usage(usage_db.totals(runner, user_id, month_start())),
    }


def check(user_id, metric, amount=0, runner=DIRECT):
    """Raises a 403 with DAILY_/MONTHLY_<X>_LIMIT_REACHED when ``amount`` more would exceed a limit."""
    if not user_id or not enabled():
        return
    column, daily_field, monthly_field, code_noun, message_noun = METRICS[metric]
    limits = effective_limits(user_id)
    if limits[daily_field] is None and limits[monthly_field] is None:
        return
    for period, field, since in (("daily", daily_field, today()), ("monthly", monthly_field, month_start())):
        limit = limits[field]
        if limit is None:
            continue
        used = int(usage_db.totals(runner, user_id, since)[column] or 0)
        over = used + amount > limit if amount > 0 else used >= limit
        if over:
            raise ApiError(
                403, f"{period.upper()}_{code_noun}_LIMIT_REACHED",
                f"Your {period} {message_noun} limit has been reached.",
                {"metric": metric, "period": period, "limit": limit, "used": used, "requested": amount,
                 "resetsAt": _resets_at(period)},
            )


def record(user_id, **amounts):
    """Adds to today's usage. Never raises: losing a count must not fail the action that earned it."""
    deltas = {_RECORD_COLUMNS[key]: int(value) for key, value in amounts.items() if value}
    if not user_id or not deltas:
        return
    try:
        usage_db.record(DIRECT, user_id, today(), deltas)
    except Exception as err:  # pragma: no cover - defensive
        log.warning("[usage] could not record usage for %s: %s", user_id, err)


def record_ai(user_id, usage_total):
    """From an ai.types usage collector total."""
    total = usage_total or {}
    prompt = total.get("promptTokens") or 0
    completion = total.get("completionTokens") or 0
    record(user_id, ai_input=prompt, ai_output=completion, ai_total=total.get("totalTokens") or prompt + completion)


def check_upload(user_id, byte_size):
    check(user_id, "uploads", 1)
    check(user_id, "storage", int(byte_size or 0))


def record_upload(user_id, byte_size):
    record(user_id, uploads=1, storage=int(byte_size or 0))

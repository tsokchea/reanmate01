"""One SM-2 review step, without mutating the persisted state (server/src/services/sm2.js).

Interval growth uses the ease factor from before this review, as in the
original algorithm; the adjusted ease applies to subsequent reviews.
"""

import datetime as dt
from decimal import ROUND_HALF_UP, Decimal

from ..utils.js import is_integer, js_round


def schedule_sm2_review(state, quality, reviewed_at=None):
    if not is_integer(quality) or quality < 0 or quality > 5:
        raise ValueError("SM-2 quality must be an integer from 0 to 5")
    at = reviewed_at or dt.datetime.now(dt.timezone.utc)
    if not isinstance(at, dt.datetime):
        raise TypeError("reviewedAt must be a valid date")

    state = state or {}
    ease_factor = float(state.get("easeFactor") if state.get("easeFactor") is not None else 2.5)
    repetitions = int(state.get("repetitions") or 0)
    previous_interval = float(state.get("intervalDays") or 0)
    lapses = int(state.get("lapses") or 0)

    if quality < 3:
        interval_days = 1
        next_repetitions = 0
        lapses += 1
    else:
        if repetitions == 0:
            interval_days = 1
        elif repetitions == 1:
            interval_days = 6
        else:
            interval_days = max(1, js_round(previous_interval * ease_factor))
        next_repetitions = repetitions + 1

    distance = 5 - quality
    next_ease = max(1.3, ease_factor + (0.1 - distance * (0.08 + distance * 0.02)))

    return {
        # Number(x.toFixed(2)): the exact binary value, ties rounded up.
        "easeFactor": float(Decimal(next_ease).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "intervalDays": interval_days,
        "repetitions": next_repetitions,
        "lapses": lapses,
        "dueAt": at + dt.timedelta(days=interval_days),
        "lastReviewedAt": at,
    }

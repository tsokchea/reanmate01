"""Fixed-window rate limiting, held in process memory.

Same policy and headers as server/src/middleware/rateLimit.js. Per-process
state is correct for the dev server and for a single API instance; behind more
than one instance (or several gunicorn workers) each process keeps its own
counts and the effective limit multiplies — move the buckets into Postgres
when deployment needs it.
"""

import math
import threading
import time

from flask import g, request

from ..utils.response import set_header
from .errors import ApiError

_buckets = {}
_lock = threading.Lock()

# Bounded so a flood of unique keys cannot grow the map without limit.
MAX_BUCKETS = 10_000


def _sweep(now):
    for key in [key for key, bucket in _buckets.items() if bucket["reset_at"] <= now]:
        del _buckets[key]


def _hit(key, window_ms, now):
    bucket = _buckets.get(key)
    if bucket is None or bucket["reset_at"] <= now:
        if len(_buckets) >= MAX_BUCKETS:
            _sweep(now)
        bucket = {"count": 0, "reset_at": now + window_ms}
        _buckets[key] = bucket
    bucket["count"] += 1
    return dict(bucket)


def rate_limit(*, scope, window_ms, max_hits, key_from):
    def step():
        raw = key_from()
        if not raw:
            return

        now = time.time() * 1000
        key = f"{scope}:{raw}"
        with _lock:
            bucket = _hit(key, window_ms, now)

        remaining = max(0, max_hits - bucket["count"])
        reset_seconds = math.ceil((bucket["reset_at"] - now) / 1000)
        set_header("RateLimit-Limit", str(max_hits))
        set_header("RateLimit-Remaining", str(remaining))
        set_header("RateLimit-Reset", str(reset_seconds))

        if bucket["count"] > max_hits:
            set_header("Retry-After", str(reset_seconds))
            raise ApiError.too_many_requests(f"Too many attempts. Try again in {reset_seconds} seconds.")

        # Lets a controller undo the attempt it just counted — successful
        # logins should not push a legitimate user toward the limit.
        def clear():
            with _lock:
                _buckets.pop(key, None)

        g.setdefault("rate_limit_resets", []).append(clear)

    return step


def clear_rate_limit():
    for reset in g.get("rate_limit_resets", []):
        reset()


def reset_rate_limits():
    """Test seam."""
    with _lock:
        _buckets.clear()


FIFTEEN_MINUTES = 15 * 60 * 1000


def _identifier():
    body = g.get("body")
    identifier = body.get("identifier") if isinstance(body, dict) else None
    return identifier.strip().lower() if isinstance(identifier, str) else None


# Per identifier: stops someone grinding passwords against one account, even
# from many addresses.
login_rate_limit_by_identifier = rate_limit(
    scope="login:id", window_ms=FIFTEEN_MINUTES, max_hits=5, key_from=_identifier
)

# Per IP, set higher: leaves room for a shared connection (a school or an
# internet cafe) where several students legitimately sign in from one address.
login_rate_limit_by_ip = rate_limit(
    scope="login:ip", window_ms=FIFTEEN_MINUTES, max_hits=30, key_from=lambda: request.remote_addr
)

# Registration is cheap to abuse too — bcrypt at 12 rounds is not free.
register_rate_limit_by_ip = rate_limit(
    scope="register:ip", window_ms=60 * 60 * 1000, max_hits=10, key_from=lambda: request.remote_addr
)

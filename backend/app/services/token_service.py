"""Two-token session scheme, both delivered as httpOnly cookies.

  access  — short-lived signed JWT (HS256). Carries the claims require_auth
            needs, so the common path costs no database round trip.
  refresh — opaque random string. Only its SHA-256 hash is stored, in
            auth_sessions, which is what makes a session revocable.

Cookie names, claims and the signing algorithm are unchanged from the Node
server, so sessions issued before the migration keep working afterwards as
long as JWT_SECRET is the same.
"""

import datetime as dt
import hashlib
import re
import secrets
import time

import jwt
from flask import request

from ..config import config, is_production
from ..utils.response import clear_cookie, set_cookie

ACCESS_COOKIE = "rm_at"
REFRESH_COOKIE = "rm_rt"
REFRESH_BYTES = 32
ACCESS_COOKIE_MAX_AGE = 15 * 60

_BASE_COOKIE = {
    "httponly": True,
    # 'Lax' lets the cookie ride normal top-level navigations while still
    # blocking cross-site POSTs. The client and API share a site in production.
    "samesite": "Lax",
    "secure": is_production,
    "path": "/",
}

_UNITS_MS = {
    "ms": 1, "msec": 1, "msecs": 1, "millisecond": 1, "milliseconds": 1,
    "s": 1000, "sec": 1000, "secs": 1000, "second": 1000, "seconds": 1000,
    "m": 60_000, "min": 60_000, "mins": 60_000, "minute": 60_000, "minutes": 60_000,
    "h": 3_600_000, "hr": 3_600_000, "hrs": 3_600_000, "hour": 3_600_000, "hours": 3_600_000,
    "d": 86_400_000, "day": 86_400_000, "days": 86_400_000,
    "w": 604_800_000, "week": 604_800_000, "weeks": 604_800_000,
    "y": 31_557_600_000, "yr": 31_557_600_000, "yrs": 31_557_600_000, "year": 31_557_600_000, "years": 31_557_600_000,
}


def _ttl_seconds(value):
    """jsonwebtoken's expiresIn: a string like '15m', where a bare number means ms."""
    match = re.match(r"^(-?(?:\d+)?\.?\d+) *([a-z]+)?$", str(value).strip(), re.IGNORECASE)
    if not match:
        raise ValueError(f'ACCESS_TOKEN_TTL "{value}" is not a valid timespan')
    unit = (match.group(2) or "ms").lower()
    if unit not in _UNITS_MS:
        raise ValueError(f'ACCESS_TOKEN_TTL "{value}" has an unknown unit')
    return int(float(match.group(1)) * _UNITS_MS[unit] / 1000)


def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def sign_access_token(user):
    now = int(time.time())
    payload = {
        "sub": str(user["id"]),
        "role": user.get("role"),
        "plan": user.get("plan_tier"),
        # Carried so a later require_verified can read it straight off the token.
        "pv": bool(user.get("phone_verified_at")),
        "ev": bool(user.get("email_verified_at")),
        "iat": now,
        "exp": now + _ttl_seconds(config.ACCESS_TOKEN_TTL),
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm="HS256")


def verify_access_token(token):
    try:
        return jwt.decode(token, config.JWT_SECRET, algorithms=["HS256", "HS384", "HS512"])
    except jwt.PyJWTError:
        return None


def create_refresh_token():
    token = secrets.token_hex(REFRESH_BYTES)
    expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=config.REFRESH_TOKEN_TTL_DAYS)
    return {"token": token, "token_hash": hash_token(token), "expires_at": expires_at}


def set_auth_cookies(access_token, refresh_token, refresh_expires_at):
    # Deliberately shorter-or-equal to the JWT's own exp so a browser-held
    # cookie never outlives the token inside it.
    set_cookie(ACCESS_COOKIE, access_token, max_age=ACCESS_COOKIE_MAX_AGE, **_BASE_COOKIE)
    set_cookie(REFRESH_COOKIE, refresh_token, expires=refresh_expires_at, **_BASE_COOKIE)


def set_access_cookie(access_token):
    set_cookie(ACCESS_COOKIE, access_token, max_age=ACCESS_COOKIE_MAX_AGE, **_BASE_COOKIE)


def clear_auth_cookies():
    # Options must match those used to set them or the browser keeps the cookie.
    clear_cookie(ACCESS_COOKIE, **_BASE_COOKIE)
    clear_cookie(REFRESH_COOKIE, **_BASE_COOKIE)


def read_access_token():
    return request.cookies.get(ACCESS_COOKIE) or None


def read_refresh_token():
    return request.cookies.get(REFRESH_COOKIE) or None

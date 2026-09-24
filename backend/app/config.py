"""Environment configuration — the Python counterpart of server/src/config/env.js.

Every value is read once, at import, from the process environment (populated
from backend/.env by python-dotenv). Secrets are never hard-coded: the only
fallbacks are the same development defaults the Node server shipped with.
"""

import os
import re

from dotenv import load_dotenv

load_dotenv()


def _required(name, fallback=None):
    value = os.environ.get(name, fallback)
    if value is None:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _to_int(value, fallback):
    """parseInt semantics: leading digits count, anything unparseable falls back."""
    match = re.match(r"^\s*([+-]?\d+)", value or "")
    return int(match.group(1)) if match else fallback


def _byte_limit(value, fallback):
    """Reads a body-parser style size such as '1mb', '512kb' or '1048576'."""
    match = re.match(r"^\s*(\d+(?:\.\d+)?)\s*(b|kb|mb|gb)?\s*$", (value or "").lower())
    if not match:
        return fallback
    units = {None: 1, "b": 1, "kb": 1024, "mb": 1024**2, "gb": 1024**3}
    return int(float(match.group(1)) * units[match.group(2)])


_configured_cors = [
    origin.strip() for origin in os.environ.get("CORS_ORIGINS", "").split(",") if origin.strip()
]


class Config:
    NODE_ENV = os.environ.get("NODE_ENV") or os.environ.get("FLASK_ENV") or "development"
    PORT = _to_int(os.environ.get("PORT"), 4000)

    # SQLite file. A relative path resolves against backend/.
    DATABASE_URL = _required("DATABASE_URL", "sqlite:///instance/reanmate.db")

    # Keep the deployed frontend available even when an old env value is still
    # present. Additional staging or preview origins remain configurable.
    CORS_ORIGINS = list(
        dict.fromkeys(["http://localhost:5173", "https://z-rean-mate.vercel.app", *_configured_cors])
    )

    JSON_BODY_LIMIT = _byte_limit(os.environ.get("JSON_BODY_LIMIT"), 1024 * 1024)

    JWT_SECRET = _required("JWT_SECRET", "dev-only-insecure-secret-change-me")
    ACCESS_TOKEN_TTL = os.environ.get("ACCESS_TOKEN_TTL", "15m")
    REFRESH_TOKEN_TTL_DAYS = _to_int(os.environ.get("REFRESH_TOKEN_TTL_DAYS"), 30)

    UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "uploads")
    MAX_UPLOAD_BYTES = _to_int(os.environ.get("MAX_UPLOAD_BYTES"), 25 * 1024 * 1024)

    # Absent on purpose for now — app/ai/__init__.py falls back to the mock
    # provider and logs a single warning at boot.
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY") or None
    # Any OpenAI-compatible endpoint. None means api.openai.com, the SDK default.
    OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL") or None
    OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.6-luna")
    OPENAI_EMBEDDING_MODEL = os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

    # Likewise absent — app/notify falls back to the mock notifier.
    SMS_PROVIDER = os.environ.get("SMS_PROVIDER") or None
    EMAIL_PROVIDER = os.environ.get("EMAIL_PROVIDER") or None

    OTP_TTL_MINUTES = _to_int(os.environ.get("OTP_TTL_MINUTES"), 10)


config = Config()
is_production = config.NODE_ENV == "production"
is_development = not is_production

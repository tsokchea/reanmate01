"""ReanMate REST API — Flask application factory (the port of server/src/app.js).

Owns all database and AI access; the React client talks to it over HTTP only.
"""

import json
import logging

from flask import Flask, g, request
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import config
from .extensions import open_pool
from .middleware.errors import ApiError, register_error_handlers
from .utils.response import apply_pending
from .utils.schema import MISSING
from .utils.serialization import ExpressJSONProvider

log = logging.getLogger("reanmate")


def _configure_logging():
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _has_body():
    """type-is hasBody: a Transfer-Encoding header or any numeric Content-Length (even 0)."""
    if "Transfer-Encoding" in request.headers:
        return True
    length = request.headers.get("Content-Length")
    return length is not None and length.strip().isdigit()


def _parse_body():
    """express.json() + express.urlencoded() semantics.

    The parsed body lands on ``g.body``; ``MISSING`` stands for Express's
    ``undefined`` (no body, or a content type no parser handles), which is
    what the validators see.
    """
    g.body = MISSING
    if not _has_body():
        return

    if request.mimetype == "application/json":
        if (request.content_length or 0) > config.JSON_BODY_LIMIT:
            raise ApiError(413, "payload_too_large", "Request body is too large")
        raw = request.get_data(cache=True)
        if len(raw) > config.JSON_BODY_LIMIT:
            raise ApiError(413, "payload_too_large", "Request body is too large")
        if not raw:
            g.body = {}
            return
        try:
            text = raw.decode(request.mimetype_params.get("charset", "utf-8"))
            stripped = text.lstrip(" \t\n\r")
            # body-parser's strict mode accepts only objects and arrays at the top level.
            if not stripped or stripped[0] not in "{[":
                raise ValueError("not an object or array")
            g.body = json.loads(text)
        except (ValueError, LookupError):
            raise ApiError(400, "invalid_json", "Request body is not valid JSON") from None
    elif request.mimetype == "application/x-www-form-urlencoded":
        g.body = request.form.to_dict()


def create_app():
    _configure_logging()

    app = Flask(__name__)
    app.json = ExpressJSONProvider(app)
    app.url_map.strict_slashes = False  # Express matched /api/kits and /api/kits/ alike
    # Multipart uploads are streamed to disk and size-checked; this is the outer guard.
    app.config["MAX_CONTENT_LENGTH"] = config.MAX_UPLOAD_BYTES + 1024 * 1024

    # Behind one proxy in production (Express: trust proxy 1), so secure
    # cookies and the client IP used for rate limiting behave.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # supports_credentials is required — the JWT rides in an httpOnly cookie,
    # so origins are an explicit allowlist (cookies forbid a wildcard).
    CORS(
        app,
        resources={r"/*": {"origins": config.CORS_ORIGINS}},
        supports_credentials=True,
        methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    )

    @app.before_request
    def _guard_origin():
        # Same-origin and non-browser callers (curl, health checks) send no Origin.
        origin = request.headers.get("Origin")
        if origin and origin not in config.CORS_ORIGINS:
            # Express's cors() rejected with a plain Error, which the error
            # handler rendered as a 500 — kept so a disallowed origin never
            # reaches a route.
            raise PermissionError(f"Origin not allowed by CORS: {origin}")
        _parse_body()

    @app.after_request
    def _apply_pending(response):
        return apply_pending(response)

    register_error_handlers(app)

    from .routes import register_blueprints

    register_blueprints(app)

    # Build both providers at boot so their "falling back to the mock"
    # warnings land once, here, rather than on the first request.
    from .ai import get_ai
    from .notify import get_notifier

    get_ai()
    get_notifier()
    open_pool()

    return app

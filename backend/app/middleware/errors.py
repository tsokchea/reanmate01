"""Centralised error handling — the counterpart of server/src/middleware/errors.js.

Every error response keeps the envelope the frontend already parses
(client/src/lib/api.js, toFormError):

    { "error": { "code": "...", "message": "...", "details": ... } }

``code`` is what the client maps to an i18n key, so the codes below are part
of the API contract and must not be renamed.
"""

import logging
import traceback

from flask import jsonify, request
from werkzeug.exceptions import HTTPException, MethodNotAllowed, NotFound, RequestEntityTooLarge

from ..config import config, is_production
from ..utils.schema import ValidationError

log = logging.getLogger("reanmate")


class ApiError(Exception):
    """Error with an HTTP status attached. Services raise these."""

    def __init__(self, status, code, message, details=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details

    @classmethod
    def bad_request(cls, message, details=None):
        return cls(400, "bad_request", message, details)

    @classmethod
    def unauthorized(cls, message="Authentication required"):
        return cls(401, "unauthorized", message)

    @classmethod
    def forbidden(cls, message="Not allowed"):
        return cls(403, "forbidden", message)

    @classmethod
    def not_found(cls, message="Not found"):
        return cls(404, "not_found", message)

    @classmethod
    def conflict(cls, message, details=None):
        return cls(409, "conflict", message, details)

    @classmethod
    def too_many_requests(cls, message="Too many requests"):
        return cls(429, "too_many_requests", message)

    @classmethod
    def service_unavailable(cls, message="Service temporarily unavailable"):
        return cls(503, "service_unavailable", message)


def _envelope(status, code, message, details=None):
    error = {"code": code, "message": message}
    if details is not None:  # JS `details && ...`: an empty object is still truthy
        error["details"] = details
    response = jsonify({"error": error})
    response.status_code = status
    return response


# Unauthenticated endpoints. Every other /api request that matches no route
# still passed through a router that required a session in Express (the
# root-mounted routers each ran ``router.use(...authenticated)``), so an
# anonymous request to an unknown API path answered 401, not 404.
_PUBLIC = {
    ("GET", "/api/health"),
    ("POST", "/api/auth/register"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/refresh"),
    ("POST", "/api/auth/logout"),
}


def _unmatched_route():
    from .auth import require_auth, require_role

    path = request.path.rstrip("/") or "/"
    if (path == "/api" or path.startswith("/api/")) and (request.method, path) not in _PUBLIC:
        require_auth()
        if path == "/api/teacher" or path.startswith("/api/teacher/"):
            require_role("teacher")()
    query = request.query_string.decode("latin-1")
    url = request.path + (f"?{query}" if query else "")
    raise ApiError.not_found(f"No route for {request.method} {url}")


def register_error_handlers(app):
    @app.errorhandler(ValidationError)
    def _validation(err):
        return _envelope(422, "validation_failed", "Request validation failed", err.details())

    @app.errorhandler(ApiError)
    def _api(err):
        return _envelope(err.status, err.code, err.message, err.details)

    @app.errorhandler(RequestEntityTooLarge)
    def _too_large(_err):
        if request.mimetype == "multipart/form-data":
            return _envelope(413, "file_too_large", "That file is too large", {"limit": config.MAX_UPLOAD_BYTES})
        return _envelope(413, "payload_too_large", "Request body is too large")

    @app.errorhandler(NotFound)
    @app.errorhandler(MethodNotAllowed)
    def _not_found(_err):
        # Express answers an unknown method on a known path with 404 as well.
        try:
            _unmatched_route()
        except ApiError as err:
            return _api(err)
        except ValidationError as err:  # pragma: no cover - defensive
            return _validation(err)

    @app.errorhandler(HTTPException)
    def _http(err):
        return _envelope(err.code or 500, "bad_request" if err.code == 400 else "http_error", err.description)

    @app.errorhandler(Exception)
    def _internal(err):
        log.error("[error] %s\n%s", err, traceback.format_exc())
        error = {"code": "internal_error", "message": "Something went wrong"}
        if not is_production:
            error["details"] = str(err)
        response = jsonify({"error": error})
        response.status_code = 500
        return response

"""Health, auth, onboarding, profile and plan limits."""

from flask import Blueprint

from ..controllers import auth_controller as auth
from ..controllers import profile_controller as profile
from ..middleware.rate_limit import (
    login_rate_limit_by_identifier,
    login_rate_limit_by_ip,
    register_rate_limit_by_ip,
)
from ..middleware.validate import validate_body
from ..validation import schemas as s
from . import AUTH, add

bp = Blueprint("auth", __name__, url_prefix="/api")

add(bp, "GET", "/health", profile.health)

# Validation runs first so the rate limiter keys off a trimmed, lower-cased identifier.
add(bp, "POST", "/auth/register", auth.register, validate_body(s.register_schema), register_rate_limit_by_ip)
add(bp, "POST", "/auth/login", auth.login, validate_body(s.login_schema), login_rate_limit_by_identifier,
    login_rate_limit_by_ip)
# Unauthenticated on purpose: the access token is usually expired by now; the refresh cookie is the credential.
add(bp, "POST", "/auth/refresh", auth.refresh)
# Also unauthenticated — logging out with a dead access token must still clear cookies and revoke.
add(bp, "POST", "/auth/logout", auth.logout)
add(bp, "GET", "/auth/me", auth.me, AUTH)
add(bp, "GET", "/me", auth.me, AUTH)  # top-level alias

add(bp, "POST", "/onboarding/role", auth.set_role, AUTH, validate_body(s.role_schema))
add(bp, "POST", "/onboarding/survey", auth.submit_survey, AUTH, validate_body(s.survey_schema))
add(bp, "GET", "/onboarding/survey", auth.get_survey, AUTH)

add(bp, "GET", "/profile", profile.show, AUTH)
add(bp, "PATCH", "/profile", profile.update, AUTH, validate_body(s.update_profile_body))
add(bp, "DELETE", "/profile", profile.remove, AUTH)
add(bp, "DELETE", "/account", profile.remove, AUTH)
add(bp, "GET", "/me/limits", profile.limits, AUTH)

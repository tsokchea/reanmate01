"""Registration, login, refresh rotation and logout (server/src/services/auth.service.js).

Verification is deferred, not removed: with no SMS or email provider
configured, registration stamps phone_verified_at / email_verified_at with the
account's creation time — AUTO-VERIFIED PENDING PROVIDER SETUP.
"""

import datetime as dt
import re
import threading

import bcrypt
from flask import request

from ..extensions import is_unique_violation
from ..middleware.errors import ApiError
from ..models import audit as audit_db
from ..models import auth_sessions as auth_sessions_db
from ..models import onboarding as onboarding_db
from ..models import users as users_db
from . import token_service

BCRYPT_ROUNDS = 12

_dummy_hash = None
_dummy_lock = threading.Lock()


def _password_bytes(password):
    # bcrypt reads at most 72 bytes; node-bcrypt truncated silently and the
    # Python binding raises instead, so truncate here to verify existing hashes.
    return password.encode("utf-8")[:72]


def _dummy():
    """A real hash to compare against when no user matched, so timing does not leak."""
    global _dummy_hash
    with _dummy_lock:
        if _dummy_hash is None:
            _dummy_hash = bcrypt.hashpw(b"not-a-real-password", bcrypt.gensalt(BCRYPT_ROUNDS))
    return _dummy_hash


def _normalize_phone(phone):
    if not phone:
        return None
    trimmed = re.sub(r"[\s\-().]", "", str(phone))
    return trimmed or None


def _normalize_email(email):
    return str(email).strip().lower() if email else None


def to_public_user(row):
    """Strips password_hash before anything reaches a response body."""
    if not row:
        return None
    return {key: value for key, value in row.items() if key != "password_hash"}


def _client():
    return request.headers.get("User-Agent"), request.remote_addr


def _issue_session(user):
    access_token = token_service.sign_access_token(user)
    refresh = token_service.create_refresh_token()
    user_agent, ip_address = _client()
    auth_sessions_db.create(user_id=user["id"], token_hash=refresh["token_hash"], user_agent=user_agent,
                            ip_address=ip_address, expires_at=refresh["expires_at"])
    token_service.set_auth_cookies(access_token, refresh["token"], refresh["expires_at"])
    return to_public_user(user)


def register(data):
    if audit_db.setting("signups_enabled") is False:
        raise ApiError(403, "signups_disabled", "New sign-ups are paused. Please try again later.")

    email = _normalize_email(data.get("email"))
    phone = _normalize_phone(data.get("phone"))

    # Enforced in the database too (users_needs_identifier, migration 002).
    if not email and not phone:
        raise ApiError.bad_request("Provide an email address or a phone number", {"fields": ["email", "phone"]})

    taken = users_db.identifier_taken(email=email, phone=phone)
    if taken["email"]:
        raise ApiError.conflict("That email is already registered", {"field": "email"})
    if taken["phone"]:
        raise ApiError.conflict("That phone number is already registered", {"field": "phone"})

    password_hash = bcrypt.hashpw(_password_bytes(data["password"]), bcrypt.gensalt(BCRYPT_ROUNDS)).decode()

    try:
        user = users_db.create(
            full_name=data["fullName"], email=email, phone=phone, password_hash=password_hash,
            locale=data.get("locale"), role=data["role"], verified_at=dt.datetime.now(dt.timezone.utc),
        )
    except Exception as err:
        # Two signups racing past the pre-check land here.
        if is_unique_violation(err):
            raise ApiError.conflict("That account already exists") from err
        raise

    # Signing up signs you in: it is the account's first sign-in.
    user_agent, ip_address = _client()
    users_db.record_login(user["id"], ip_address, user_agent)
    return _issue_session(user)


def login(data):
    identifier = data["identifier"]
    lookup = _normalize_email(identifier) if "@" in identifier else _normalize_phone(identifier)
    user = users_db.find_for_login(lookup)

    # Compare against a dummy hash when no user matched, so a missing account
    # and a wrong password take the same time.
    stored = (user or {}).get("password_hash")
    try:
        ok = bcrypt.checkpw(_password_bytes(data["password"]), stored.encode() if stored else _dummy())
    except ValueError:
        ok = False

    if not user or not ok:
        raise ApiError.unauthorized("Those credentials are not correct")

    user_agent, ip_address = _client()
    users_db.record_login(user["id"], ip_address, user_agent)
    return _issue_session(user)


def hash_password(password):
    return bcrypt.hashpw(_password_bytes(password), bcrypt.gensalt(BCRYPT_ROUNDS)).decode()


def change_password(user_id, data):
    """Self-service. Clears a temporary password, and signs every other device out."""
    user = users_db.find_with_password(user_id)
    if not user:
        raise ApiError(401, "account_disabled", "This account is no longer active")
    try:
        ok = bcrypt.checkpw(_password_bytes(data["currentPassword"]), user["password_hash"].encode())
    except ValueError:
        ok = False
    if not ok:
        raise ApiError(422, "validation_failed", "Request validation failed", [
            {"path": "currentPassword", "code": "invalid_value", "message": "That password is not correct"}])
    if data["currentPassword"] == data["newPassword"]:
        raise ApiError(422, "validation_failed", "Request validation failed", [
            {"path": "newPassword", "code": "invalid_value", "message": "Choose a password you have not used here"}])

    users_db.change_password(user_id, hash_password(data["newPassword"]))
    auth_sessions_db.revoke_all_for_user(user_id)
    from . import audit_service  # local: audit_service imports flask request helpers only when used

    audit_service.record("PASSWORD_CHANGED", actor_row=user, target=user, resource="user", resource_id=user_id)
    return _issue_session(users_db.find_by_id(user_id))


def logout():
    refresh_token = token_service.read_refresh_token()
    if refresh_token:
        auth_sessions_db.revoke(token_service.hash_token(refresh_token))
    token_service.clear_auth_cookies()


def refresh():
    """Rotates the refresh token on every use, so a stolen one is single-use."""
    refresh_token = token_service.read_refresh_token()
    if not refresh_token:
        raise ApiError.unauthorized("No refresh token")

    old_hash = token_service.hash_token(refresh_token)
    session = auth_sessions_db.find_active(old_hash)
    if not session:
        token_service.clear_auth_cookies()
        raise ApiError.unauthorized("That session has expired")

    user = users_db.find_by_id(session["user_id"])
    if not user or user["status"] != "active":
        token_service.clear_auth_cookies()
        raise ApiError.unauthorized("That account is no longer active")

    nxt = token_service.create_refresh_token()
    user_agent, ip_address = _client()
    auth_sessions_db.rotate(old_token_hash=old_hash, user_id=user["id"], token_hash=nxt["token_hash"],
                            user_agent=user_agent, ip_address=ip_address, expires_at=nxt["expires_at"])
    token_service.set_auth_cookies(token_service.sign_access_token(user), nxt["token"], nxt["expires_at"])
    return to_public_user(user)


def me(user_id):
    """The user plus whatever onboarding state the client needs to route on."""
    user = users_db.find_by_id(user_id)
    if not user:
        raise ApiError.unauthorized("That account no longer exists")
    survey = onboarding_db.find_by_user_id(user_id)
    return {
        "user": to_public_user(user),
        "onboarding": {
            "roleChosen": bool(user["role"]),
            "surveyAnswers": (survey or {}).get("answers") or {},
            "surveySkipped": (survey or {}).get("skipped") or False,
            "completedAt": user["onboarding_completed_at"],
        },
    }

from flask import Response, g

from ..middleware.rate_limit import clear_rate_limit
from ..services import auth_service, onboarding_service, token_service
from . import respond


def register():
    return respond({"user": auth_service.register(g.body)}, 201)


def login():
    user = auth_service.login(g.body)
    # A correct password shouldn't count toward the lockout window.
    clear_rate_limit()
    return respond({"user": user})


def logout():
    auth_service.logout()
    return Response(status=204)


def refresh():
    return respond({"user": auth_service.refresh()})


def me():
    return respond(auth_service.me(g.auth["user_id"]))


def change_password():
    return respond({"user": auth_service.change_password(g.auth["user_id"], g.body)})


# --- onboarding ---------------------------------------------------------------


def set_role():
    user = onboarding_service.set_role(g.auth["user_id"], g.body["role"])
    token_service.set_access_cookie(token_service.sign_access_token(user))
    return respond({"user": user})


def submit_survey():
    response, user = onboarding_service.submit_survey(g.auth["user_id"], g.body)
    payload = {"survey": {"answers": response["answers"], "skipped": response["skipped"],
                          "completedAt": response["completed_at"]}}
    if user:
        payload["user"] = user
    return respond(payload)


def get_survey():
    response = onboarding_service.get_survey(g.auth["user_id"]) or {}
    return respond({"survey": {
        "answers": response.get("answers") or {},
        "skipped": response.get("skipped") or False,
        "completedAt": response.get("completed_at"),
    }})

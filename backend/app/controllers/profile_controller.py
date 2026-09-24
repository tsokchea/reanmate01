from flask import g

from ..services import health_service, profile_service, token_service
from ..services.plans_service import plans_service
from . import respond


def health():
    result = health_service.check()
    return respond(result, 200 if result["database"] == "up" else 503)


def show():
    return respond(profile_service.get(g.auth["user_id"]))


def update():
    return respond(profile_service.update(g.auth["user_id"], g.body))


def remove():
    profile_service.delete_account(g.auth["user_id"])
    token_service.clear_auth_cookies()
    return respond({"deleted": True})


def limits():
    return respond(plans_service.limits(g.auth["user_id"]))

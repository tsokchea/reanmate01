"""The admin console. Every view reads the admin that require_admin resolved onto ``g.admin``."""

from flask import g

from ..services import admin_accounts_service as accounts
from ..services import admin_insights_service as insights
from ..services import admin_roles_service as roles
from . import respond


def _query():
    return g.get("query") or {}


def me():
    return respond(accounts.me(g.admin))


# --- dashboard -------------------------------------------------------------------------


def dashboard():
    return respond(insights.dashboard(g.admin))


def dashboard_series():
    return respond(insights.series(g.admin, _query()))


# --- accounts --------------------------------------------------------------------------


def list_users():
    return respond(accounts.list_accounts(g.admin, _query()))


def create_user():
    return respond(accounts.create_user(g.admin, g.body), 201)


def show_user():
    return respond(accounts.detail(g.admin, g.params["userId"]))


def update_user():
    return respond(accounts.update_user(g.admin, g.params["userId"], g.body))


def disable_user():
    return respond(accounts.set_status(g.admin, g.params["userId"], "disabled"))


def enable_user():
    return respond(accounts.set_status(g.admin, g.params["userId"], "active"))


def delete_user():
    return respond(accounts.delete(g.admin, g.params["userId"]))


def reset_password():
    return respond(accounts.reset_password(g.admin, g.params["userId"]))


def list_admins():
    return respond(accounts.list_admins(g.admin, _query()))


def create_admin():
    return respond(accounts.create_admin(g.admin, g.body), 201)


def show_admin():
    return respond(accounts.detail(g.admin, g.params["userId"]))


def update_admin():
    return respond(accounts.update_admin(g.admin, g.params["userId"], g.body))


def delete_admin():
    return respond(accounts.delete(g.admin, g.params["userId"], admins_only=True))


# --- roles and permissions -------------------------------------------------------------


def list_roles():
    return respond(roles.list_roles(g.admin))


def create_role():
    return respond(roles.create_role(g.admin, g.body), 201)


def update_role():
    return respond(roles.update_role(g.admin, g.params["roleId"], g.body))


def delete_role():
    return respond(roles.delete_role(g.admin, g.params["roleId"]))


def list_permissions():
    return respond(roles.permissions_catalogue())


# --- usage and limits ------------------------------------------------------------------


def usage():
    return respond(roles.usage_overview(g.admin, _query()))


def account_usage():
    return respond(roles.account_usage(g.admin, g.params["userId"]))


def reset_usage():
    return respond(roles.reset_usage_today(g.admin, g.params["userId"]))


def limit_defaults():
    return respond(roles.role_limit_defaults(g.admin))


def update_limit_defaults():
    return respond(roles.update_role_limits(g.admin, g.params["roleId"], g.body))


def account_limits():
    return respond(roles.account_limits(g.admin, g.params["userId"]))


def update_account_limits():
    return respond(roles.update_account_limits(g.admin, g.params["userId"], g.body))


# --- audit, settings, content ----------------------------------------------------------


def audit_logs():
    return respond(insights.audit_logs(g.admin, _query()))


def settings():
    return respond(insights.settings(g.admin))


def update_settings():
    return respond(insights.update_settings(g.admin, g.body))


def content_sources():
    return respond(insights.content_sources(g.admin, _query()))


def delete_source():
    return respond(insights.delete_source(g.admin, g.params["sourceId"]))


def content_classes():
    return respond(insights.content_classes(g.admin, _query()))


def content_assignments():
    return respond(insights.content_assignments(g.admin, _query()))


def delete_assignment():
    return respond(insights.delete_assignment(g.admin, g.params["assignmentId"]))


def content_flashcards():
    return respond(insights.content_flashcards(g.admin, _query()))


def delete_flashcard_set():
    return respond(insights.delete_flashcard_set(g.admin, g.params["setId"]))

"""API routes — Flask Blueprints mirroring server/src/routes.

Routes only wire things up: a path, a method, the steps that guard and
validate it (in the same order Express ran its middleware), and a controller.
Paths use Flask's ``<name>`` converters where Express used ``:name``; the
frontend's URLs are unchanged.
"""

from flask import g, request

from ..middleware.auth import authenticated, require_role
from ..middleware.validate import pipeline, validate_body

AUTH = authenticated
TEACHER = require_role("teacher")
STUDENT = require_role("student")


def add(bp, method, rule, view, *steps):
    """Registers ``view`` for ``method rule`` behind ``steps``."""
    bp.add_url_rule(rule, endpoint=f"{method.lower()}:{rule}", view_func=pipeline(*steps)(view), methods=[method])


def register_blueprints(app):
    from . import auth, classes, kits, study, teacher

    for module in (auth, kits, study, classes, teacher):
        app.register_blueprint(module.bp)


def validate_source_body(schema):
    """Multipart uploads carry a file, not a JSON source description."""
    body_step = validate_body(schema)

    def step():
        if request.mimetype == "multipart/form-data" or g.get("file"):
            return
        body_step()

    return step

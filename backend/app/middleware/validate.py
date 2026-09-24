"""Request validation and the per-route step pipeline.

``validate_body``/``validate_query``/``validate_params`` run a schema against
the request before the controller sees it; the parsed (trimmed, defaulted)
result replaces the raw input, so controllers never read the raw request.
A ValidationError becomes a 422 in the central error handler.

``pipeline`` runs a route's steps in order — the Flask spelling of an Express
middleware chain.
"""

from functools import wraps

from flask import g, request

from ..utils.schema import MISSING


def validate_body(schema):
    def step():
        body = g.get("body", MISSING)
        g.body = schema.parse(body)

    return step


def _query_dict():
    """Express's simple query parser: a repeated key becomes a list."""
    out = {}
    for key in request.args.keys():
        values = request.args.getlist(key)
        out[key] = values if len(values) > 1 else values[0]
    return out


def validate_query(schema):
    def step():
        g.query = schema.parse(_query_dict())

    return step


def validate_params(schema):
    def step():
        g.params = schema.parse(dict(request.view_args or {}))

    return step


def pipeline(*steps):
    """Run ``steps`` in order, then the view. Views read g.auth/g.params/g.body/g.query/g.file."""
    flat = []
    for step in steps:
        flat.extend(step if isinstance(step, (list, tuple)) else [step])

    def decorate(view):
        @wraps(view)
        def wrapper(**_kwargs):
            for step in flat:
                step()
            return view()

        return wrapper

    return decorate

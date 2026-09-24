"""Response headers and cookies that survive an error.

In Express, ``res.cookie()`` and ``res.set()`` write to the one response
object, so a cookie cleared just before an error is thrown still reaches the
browser on the error response (auth.service.js refresh does exactly that).
Flask builds a fresh response in the error handler, so those writes are queued
on ``g`` here and applied to whatever response finally goes out.
"""

from flask import g


def _pending():
    if "pending_response_ops" not in g:
        g.pending_response_ops = []
    return g.pending_response_ops


def set_header(name, value):
    _pending().append(("header", name, value))


def set_cookie(name, value, **options):
    _pending().append(("cookie", name, value, options))


def clear_cookie(name, **options):
    _pending().append(("clear", name, options))


def apply_pending(response):
    for op in g.get("pending_response_ops", []):
        if op[0] == "header":
            response.headers[op[1]] = op[2]
        elif op[0] == "cookie":
            response.set_cookie(op[1], op[2], **op[3])
        else:
            options = {key: value for key, value in op[2].items() if key in ("path", "domain", "secure", "httponly", "samesite")}
            response.delete_cookie(op[1], **options)
    return response

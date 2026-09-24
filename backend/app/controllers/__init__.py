"""Controllers translate HTTP; services hold the logic.

Each controller reads what the route's steps validated — ``g.auth``,
``g.params``, ``g.query``, ``g.body``, ``g.file`` — calls one service, and
turns the result into a response with the same status code Express used.
"""

from flask import jsonify


def respond(data, status=200):
    response = jsonify(data)
    response.status_code = status
    return response

"""Tutor chat, including the SSE stream.

The stream keeps the exact wire format the client parses
(client/src/tutor/useTutorChat.js):

    id: <n|terminal>
    event: <delta|done|error>
    data: <json>

A comment line (``: ping``) is sent while idle so a dead client is noticed;
the client already skips blocks that start with ':'.
"""

import queue

from flask import Response, g, request, stream_with_context

from ..services import chat_service
from ..utils.serialization import dumps
from . import respond

HEARTBEAT_SECONDS = 15


def explain():
    return respond(chat_service.explain(g.auth["user_id"], g.body))


def history():
    return respond(chat_service.history(g.auth["user_id"], g.query["language"]))


def conversation():
    return respond(chat_service.conversation(g.auth["user_id"], g.params["kitId"], g.query["language"],
                                             g.auth["plan"], g.query.get("sourceId")))


def create():
    return respond(chat_service.create(g.auth["user_id"], g.auth["plan"], g.body), 201)


def retry():
    return respond(chat_service.retry(g.auth["user_id"], g.auth["plan"], g.params["sessionId"]), 201)


def _frame(frame):
    return f"id: {frame['id']}\nevent: {frame['event']}\ndata: {dumps(frame['data'])}\n\n"


def stream():
    session = chat_service.prepare_stream(g.auth["user_id"], g.params["sessionId"])
    frames = queue.Queue()
    unsubscribe = chat_service.subscribe(session, g.auth["plan"], request.headers.get("Last-Event-ID"), frames.put)

    def generate():
        try:
            while True:
                try:
                    frame = frames.get(timeout=HEARTBEAT_SECONDS)
                except queue.Empty:
                    yield ": ping\n\n"
                    continue
                yield _frame(frame)
                if frame["event"] in ("done", "error"):
                    return
        finally:
            unsubscribe()

    response = Response(stream_with_context(generate()), status=200, mimetype="text/event-stream")
    response.headers["Content-Type"] = "text/event-stream; charset=utf-8"
    response.headers["Cache-Control"] = "no-cache, no-transform"
    response.headers["X-Accel-Buffering"] = "no"
    return response

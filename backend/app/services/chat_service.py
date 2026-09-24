"""The AI tutor chat (server/src/services/chat.service.js).

A reply is produced once, by a background producer thread, and fanned out to
any number of SSE subscribers. Every frame is buffered on the in-process entry,
so a client that reconnects with ``Last-Event-ID`` is replayed exactly the
deltas it missed. Frames: ``delta`` (numbered ids) then exactly one terminal
``done`` or ``error`` (id ``terminal``).

The buffer is per process: a 'streaming' row with no local producer means the
server restarted mid-reply, and is failed with ``stream_interrupted``.
"""

import threading
import time

from ..ai import get_ai
from ..ai.types import create_usage_collector
from ..middleware.errors import ApiError
from ..models import chat as chat_db
from ..models import chunks as chunks_db
from ..models import kits as kits_db
from ..utils.js import parse_int
from . import usage_service
from .ai_usage_service import detect_cost_language, record_streamed_generation, track_generation
from .plans_service import plans_service
from .reply_language import detect_requested_reply_language

_active = {}
_active_lock = threading.Lock()


class _Entry:
    def __init__(self):
        self.frames = []
        self.subscribers = set()
        self.sequence = 0
        self.terminal = False
        self.lock = threading.Lock()


def _to_message(row):
    return {"id": row["id"], "role": row["role"], "content": row["content"], "citations": row["citations"] or [],
            "status": row["status"], "createdAt": row["created_at"]}


def _publish(entry, event, data):
    with entry.lock:
        if entry.terminal:
            return
        if event == "delta":
            entry.sequence += 1
            frame_id = str(entry.sequence)
        else:
            frame_id = "terminal"
        frame = {"id": frame_id, "event": event, "data": data}
        entry.frames.append(frame)
        if event in ("done", "error"):
            entry.terminal = True
        subscribers = list(entry.subscribers)
    for subscriber in subscribers:
        subscriber(frame)


def _sources_from(matches):
    return [{"title": row["title"], "content": row["content"], "pageNumber": row["page_number"],
             "startSeconds": row["start_seconds"]} for row in matches]


def _run_producer(session, entry):
    ai = get_ai()
    answer = ""
    # Recorded even when the stream dies partway: the tokens were still spent.
    usage = create_usage_collector()
    started = time.time()
    state = {"history": [], "sources": [], "reply_language": session["language"], "logged": False}

    def log_turn(status, error_message=None):
        if state["logged"]:
            return
        state["logged"] = True
        record_streamed_generation(
            kind="tutor", user_id=session["user_id"], study_kit_id=session["study_kit_id"],
            language=state["reply_language"], source_text="\n".join(s["content"] for s in state["sources"]),
            request={"retrievedSources": len(state["sources"]), "historyTurns": len(state["history"]),
                     "maxOutputTokens": 400},
            response={"answerChars": len(answer)}, status=status, error_message=error_message,
            usage_total=usage.total(), started_at=started,
        )

    try:
        state["history"] = chat_db.recent_history(session["conversation_id"], 4)
        query_text = next((m["content"] for m in reversed(state["history"]) if m["role"] == "user"), "")
        state["reply_language"] = detect_requested_reply_language(query_text, session["language"])

        # Its own 'embedding' row: a different model from the tutor turn.
        embedded = track_generation(
            kind="embedding", user_id=session["user_id"], study_kit_id=session["study_kit_id"],
            language=detect_cost_language(query_text) or session["language"], source_text=query_text,
            request={"purpose": "tutor_retrieval", "chunks": 1},
            describe=lambda v: {"vectors": len(v.get("embeddings") or [])},
            run=lambda ai_, on_usage: ai.embed(texts=[query_text], on_usage=on_usage),
        )
        # Scoped to the file this thread is about, when it is about one.
        matches = chunks_db.cosine_search_for_kit(kit_id=session["study_kit_id"], source_id=session.get("source_id"),
                                                  embedding=embedded["embeddings"][0], limit=3)
        state["sources"] = _sources_from(matches)

        terminal_seen = False
        stream_error = None
        for chunk in ai.tutor_reply(messages=state["history"], language=state["reply_language"],
                                    sources=state["sources"], max_output_tokens=400, on_usage=usage.record):
            if terminal_seen:
                continue
            if chunk["type"] == "delta":
                answer += chunk["text"]
                _publish(entry, "delta", {"text": chunk["text"]})
            elif chunk["type"] == "done":
                terminal_seen = True
                completed = chat_db.complete(session_id=session["id"], content=answer, citations=chunk["citations"],
                                             model=ai.name)
                if not completed:
                    raise RuntimeError("The assistant message could not be completed")
                quota = plans_service.consume_quota(session["user_id"], "tutor_messages_per_month")
                _publish(entry, "done", {
                    "messageId": session["id"],
                    "citations": chunk["citations"],
                    "suggestedFollowups": chunk.get("suggestedFollowups"),
                    "quota": {"used": quota["used"], "limit": quota["limit"], "remaining": quota["remaining"]},
                })
            elif chunk["type"] == "error":
                terminal_seen = True
                stream_error = chunk["message"]
                chat_db.fail(session["id"])
                _publish(entry, "error", {"code": "generation_failed", "message": chunk["message"], "retryable": True})
        # A stream that ended without a terminal chunk falls through to the except.
        if not terminal_seen:
            raise RuntimeError("The AI stream ended without a terminal event")
        log_turn("failed" if stream_error else "ok", stream_error)
    except Exception as err:
        log_turn("failed", str(err))
        try:
            chat_db.fail(session["id"])
        except Exception:
            pass
        _publish(entry, "error", {"code": "generation_failed", "message": str(err), "retryable": True})
    finally:
        with _active_lock:
            _active.pop(session["id"], None)


def explain(user_id, data):
    if not kits_db.find_by_id(user_id=user_id, kit_id=data["kitId"]):
        raise ApiError.not_found("That study kit does not exist")
    reply_language = detect_requested_reply_language(data["content"], data["language"])

    def run(ai, on_usage):
        embedded = ai.embed(texts=[data["content"]], on_usage=on_usage)
        matches = chunks_db.cosine_search_for_kit(kit_id=data["kitId"], source_id=data.get("sourceId"),
                                                  embedding=embedded["embeddings"][0], limit=3)
        content, citations = "", []
        for chunk in ai.tutor_reply(messages=[{"role": "user", "content": data["content"]}],
                                    language=reply_language, sources=_sources_from(matches), max_output_tokens=400,
                                    on_usage=on_usage):
            if chunk["type"] == "delta":
                content += chunk["text"]
            if chunk["type"] == "done":
                citations = chunk["citations"]
            if chunk["type"] == "error":
                raise RuntimeError(chunk["message"])
        return {"content": content, "citations": citations}

    # Tracked like every other AI call, so it counts toward (and is stopped by) the AI allowance.
    result = track_generation(
        kind="tutor", user_id=user_id, study_kit_id=data["kitId"], language=reply_language,
        source_text=data["content"], request={"explain": True},
        describe=lambda v: {"answerChars": len(v["content"])}, run=run,
    )
    return {**result, "language": reply_language}


def history(user_id, language):
    rows = chat_db.history_for_user(user_id=user_id, language=language)
    return {"conversations": [{
        "id": row["id"], "kitId": row["study_kit_id"], "sourceId": row["source_id"], "language": row["language"],
        "kitTitle": row["kit_title"], "sourceTitle": row["source_title"], "preview": row["preview"],
        "lastMessageAt": row["last_message_at"] if row["last_message_at"] is not None else row["created_at"],
    } for row in rows]}


def _tutor_quota(user_id):
    quota = plans_service.limits(user_id)["limits"]["tutor_messages_per_month"]
    return {"used": quota["used"], "limit": quota["limit"], "remaining": quota["remaining"]}


def conversation(user_id, kit_id, language, _plan, source_id=None):
    convo = chat_db.conversation_for_kit(user_id=user_id, kit_id=kit_id, language=language, source_id=source_id)
    messages = chat_db.messages(convo["id"]) if convo else []
    return {
        "conversation": {
            "id": convo["id"], "kitId": convo["study_kit_id"], "sourceId": convo["source_id"],
            "sourceTitle": convo["source_title"], "language": convo["language"], "kitTitle": convo["kit_title"],
            "lastMessageAt": convo["last_message_at"],
        } if convo else None,
        "messages": [_to_message(row) for row in messages],
        "quota": _tutor_quota(user_id),
    }


def create(user_id, _plan, data):
    usage_service.check(user_id, "tutor_messages", 1)
    usage_service.check(user_id, "ai_tokens")
    limit = plans_service.get_limit(user_id, "tutor_messages_per_month")
    result = chat_db.create_session(user_id=user_id, kit_id=data["kitId"], source_id=data.get("sourceId"),
                                    language=data["language"], content=data["content"], limit=limit)
    if result.get("missing"):
        raise ApiError.not_found("That study kit does not exist")
    if result.get("quotaExceeded"):
        raise ApiError(429, "quota_exceeded", "Tutor message limit reached",
                       {"used": result["used"], "limit": result["limit"]})
    usage_service.record(user_id, tutor_messages=1)
    return {
        "sessionId": result["assistantMessage"]["id"],
        "userMessage": _to_message(result["userMessage"]),
        "assistantMessage": _to_message(result["assistantMessage"]),
        "quota": {"used": result["used"], "limit": result["limit"],
                  "remaining": None if result["limit"] is None else result["limit"] - result["used"]},
    }


def retry(user_id, _plan, session_id):
    usage_service.check(user_id, "ai_tokens")
    limit = plans_service.get_limit(user_id, "tutor_messages_per_month")
    result = chat_db.create_retry(user_id=user_id, session_id=session_id, limit=limit)
    if result.get("missing"):
        raise ApiError.not_found("That chat stream does not exist")
    if result.get("conflict"):
        raise ApiError.conflict("Only failed messages can be retried")
    if result.get("quotaExceeded"):
        raise ApiError(429, "quota_exceeded", "Tutor message limit reached",
                       {"used": result["used"], "limit": result["limit"]})
    return {"sessionId": result["assistantMessage"]["id"], "assistantMessage": _to_message(result["assistantMessage"])}


def prepare_stream(user_id, session_id):
    session = chat_db.session_for_user(user_id=user_id, session_id=session_id)
    if not session:
        raise ApiError.not_found("That chat stream does not exist")
    return session


def subscribe(session, _plan, last_event_id, on_frame):
    """Replays buffered frames after ``last_event_id`` and follows the rest. Returns an unsubscribe."""
    if session["status"] == "complete":
        quota = _tutor_quota(session["user_id"])
        on_frame({"id": "terminal", "event": "done", "data": {
            "messageId": session["id"], "citations": session["citations"], "suggestedFollowups": [], "quota": quota}})
        return lambda: None
    if session["status"] == "failed":
        on_frame({"id": "terminal", "event": "error",
                  "data": {"code": "generation_failed", "message": "The previous stream failed", "retryable": True}})
        return lambda: None

    with _active_lock:
        entry = _active.get(session["id"])
    if entry is None:
        # A streaming row with no local producer survived a process restart.
        if session["status"] == "streaming":
            chat_db.fail(session["id"])
            on_frame({"id": "terminal", "event": "error", "data": {
                "code": "stream_interrupted", "message": "The server restarted during this response",
                "retryable": True}})
            return lambda: None
        if not chat_db.claim(session["id"]):
            on_frame({"id": "terminal", "event": "error", "data": {
                "code": "stream_unavailable", "message": "This stream could not be claimed", "retryable": True}})
            return lambda: None
        entry = _Entry()
        with _active_lock:
            _active[session["id"]] = entry
        threading.Thread(target=_run_producer, args=({**session, "status": "streaming"}, entry),
                         name=f"tutor-{session['id']}", daemon=True).start()

    after = parse_int(last_event_id, 0) or 0
    # Replay and subscribe under the entry lock, so no frame falls between the
    # two and none can overtake the replay (on_frame only enqueues).
    with entry.lock:
        for frame in entry.frames:
            if frame["id"] == "terminal" or int(frame["id"]) > after:
                on_frame(frame)
        if not entry.terminal:
            entry.subscribers.add(on_frame)

    def unsubscribe():
        with entry.lock:
            entry.subscribers.discard(on_frame)

    return unsubscribe

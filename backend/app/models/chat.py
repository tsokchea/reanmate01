"""SQL for tutor chat conversations and messages.

Messages order by created_at and then insertion order (rowid), so a user
message and the assistant placeholder written in the same millisecond always
come back in the order they were written.
"""

from ..extensions import query, query_one, transaction
from ..utils.serialization import dumps
from ._time import start_of_month

MESSAGE_SELECT = """
  SELECT m.id, m.conversation_id, m.reply_to_message_id, m.role, m.content,
         m.citations, m.status, m.model, m.created_at"""

# Completed replies count against the month; queued/streaming ones are reserved.
_USAGE_SQL = """SELECT count(*) FILTER (WHERE m.status = 'complete') AS used,
                       count(*) FILTER (WHERE m.status IN ('queued', 'streaming')) AS reserved
                  FROM chat_messages m JOIN chat_conversations c ON c.id = m.conversation_id
                 WHERE c.user_id = $1 AND m.role = 'assistant'
                   AND m.created_at >= $2"""


def history_for_user(*, user_id, language, limit=50):
    return query(
        """SELECT c.id, c.study_kit_id, c.source_id, c.language, c.last_message_at, c.created_at,
                  k.title AS kit_title, s.title AS source_title,
                  (SELECT m.content FROM chat_messages m
                    WHERE m.conversation_id = c.id AND m.role = 'user'
                    ORDER BY m.created_at DESC, m.rowid DESC LIMIT 1) AS preview
             FROM chat_conversations c
             JOIN study_kits k ON k.id = c.study_kit_id
             LEFT JOIN kit_sources s ON s.id = c.source_id
            WHERE c.user_id = $1 AND c.language = $2
            ORDER BY COALESCE(c.last_message_at, c.created_at) DESC, c.id DESC
            LIMIT $3""",
        [user_id, language, limit],
    ).rows


def conversation_for_kit(*, user_id, kit_id, language, source_id=None):
    """One thread per material; ``source_id`` None is the kit-wide thread."""
    return query_one(
        """SELECT c.id, c.study_kit_id, c.source_id, c.language, c.last_message_at, c.created_at,
                  k.title AS kit_title, s.title AS source_title
             FROM chat_conversations c
             JOIN study_kits k ON k.id = c.study_kit_id
             LEFT JOIN kit_sources s ON s.id = c.source_id
            WHERE c.user_id = $1 AND c.study_kit_id = $2 AND c.language = $3
              AND c.source_id IS $4""",
        [user_id, kit_id, language, source_id],
    )


def messages(conversation_id, limit=100):
    return query(
        f"""{MESSAGE_SELECT} FROM chat_messages m
            WHERE m.conversation_id = $1
            ORDER BY m.created_at ASC, m.rowid ASC LIMIT $2""",
        [conversation_id, limit],
    ).rows


def recent_history(conversation_id, limit=4):
    return query(
        """SELECT role, content FROM (
             SELECT role, content, created_at, rowid AS seq
               FROM chat_messages
              WHERE conversation_id = $1
                AND (role = 'user' OR (role = 'assistant' AND status = 'complete'))
              ORDER BY created_at DESC, seq DESC LIMIT $2
           ) recent ORDER BY created_at ASC, seq ASC""",
        [conversation_id, limit],
    ).rows


def create_session(*, user_id, kit_id, language, content, limit, source_id=None):
    with transaction() as tx:
        kit = tx.query_one("SELECT id, title FROM study_kits WHERE id = $1 AND user_id = $2", [kit_id, user_id])
        if not kit:
            return {"missing": True}
        usage = tx.query_one(_USAGE_SQL, [user_id, start_of_month()])
        if limit is not None and usage["used"] + usage["reserved"] >= limit:
            return {"quotaExceeded": True, "used": usage["used"], "limit": limit}

        # A source that is not in this kit is ignored rather than trusted.
        source = (
            tx.query_one("SELECT id FROM kit_sources WHERE id = $1 AND study_kit_id = $2", [source_id, kit_id])
            if source_id else None
        )

        conversation = tx.query_one(
            """INSERT INTO chat_conversations (user_id, study_kit_id, source_id, title, language)
               VALUES ($1, $2, $3, $4, $5)
               ON CONFLICT (user_id, study_kit_id, COALESCE(source_id, ''), language) WHERE study_kit_id IS NOT NULL
               DO UPDATE SET title = chat_conversations.title
               RETURNING id, study_kit_id, source_id, language""",
            [user_id, kit_id, source["id"] if source else None, kit["title"], language],
        )
        user_message = tx.query_one(
            """INSERT INTO chat_messages (conversation_id, role, content, status)
               VALUES ($1, 'user', $2, 'complete') RETURNING id, role, content, citations, status, created_at""",
            [conversation["id"], content],
        )
        assistant_message = tx.query_one(
            """INSERT INTO chat_messages (conversation_id, reply_to_message_id, role, status)
               VALUES ($1, $2, 'assistant', 'queued') RETURNING id, role, content, citations, status, created_at""",
            [conversation["id"], user_message["id"]],
        )
        tx.query("UPDATE chat_conversations SET last_message_at = now() WHERE id = $1", [conversation["id"]])
        return {"conversation": conversation, "userMessage": user_message, "assistantMessage": assistant_message,
                "used": usage["used"], "limit": limit}


def create_retry(*, user_id, session_id, limit):
    with transaction() as tx:
        previous = tx.query_one(
            """SELECT m.id, m.reply_to_message_id, m.status, c.id AS conversation_id
                 FROM chat_messages m JOIN chat_conversations c ON c.id = m.conversation_id
                WHERE m.id = $1 AND c.user_id = $2 AND m.role = 'assistant'""",
            [session_id, user_id],
        )
        if not previous:
            return {"missing": True}
        if previous["status"] != "failed":
            return {"conflict": True}
        usage = tx.query_one(_USAGE_SQL, [user_id, start_of_month()])
        if limit is not None and usage["used"] + usage["reserved"] >= limit:
            return {"quotaExceeded": True, "used": usage["used"], "limit": limit}
        assistant_message = tx.query_one(
            """INSERT INTO chat_messages (conversation_id, reply_to_message_id, role, status)
               VALUES ($1, $2, 'assistant', 'queued') RETURNING id, role, content, citations, status, created_at""",
            [previous["conversation_id"], previous["reply_to_message_id"]],
        )
        return {"assistantMessage": assistant_message, "used": usage["used"], "limit": limit}


def session_for_user(*, user_id, session_id):
    return query_one(
        f"""{MESSAGE_SELECT}, c.user_id, c.study_kit_id, c.source_id, c.language
             FROM chat_messages m JOIN chat_conversations c ON c.id = m.conversation_id
            WHERE m.id = $1 AND c.user_id = $2 AND m.role = 'assistant'""",
        [session_id, user_id],
    )


def claim(session_id):
    return query_one(
        "UPDATE chat_messages SET status = 'streaming' WHERE id = $1 AND status = 'queued' RETURNING id", [session_id]
    )


def complete(*, session_id, content, citations, model):
    with transaction() as tx:
        row = tx.query_one(
            """UPDATE chat_messages SET content = $2, citations = $3, status = 'complete', model = $4
                WHERE id = $1 AND status = 'streaming' RETURNING conversation_id""",
            [session_id, content, dumps(citations), model],
        )
        if row:
            tx.query("UPDATE chat_conversations SET last_message_at = now() WHERE id = $1", [row["conversation_id"]])
        return row


def fail(session_id):
    query(
        "UPDATE chat_messages SET status = 'failed' WHERE id = $1 AND status IN ('queued', 'streaming')", [session_id]
    )

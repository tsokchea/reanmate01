"""SQL for practice sessions and mock exams (server/src/db/practice.db.js)."""

import datetime as dt

from ..extensions import query, query_one, transaction
from ..utils.js import is_integer, js_round, js_string
from ..utils.serialization import dumps


def topics(*, user_id, q=None, source_id=None):
    """``source_id`` narrows the list to the topics that one file produced questions for."""
    return query(
        """SELECT t.id, t.study_kit_id, t.name,
                  COALESCE(m.mastery_percent, 35)::int AS effective_mastery,
                  m.mastery_percent,
                  COALESCE(m.attempts, 0)::int AS attempts
             FROM topics t JOIN study_kits k ON k.id = t.study_kit_id
             LEFT JOIN user_topic_mastery m ON m.topic_id = t.id AND m.user_id = $1
            WHERE k.user_id = $1 AND ($2::text IS NULL OR t.name ILIKE '%' || $2 || '%')
              AND ($3::uuid IS NULL OR EXISTS (
                    SELECT 1 FROM quiz_questions qq
                      JOIN quizzes qz ON qz.id = qq.quiz_id
                     WHERE qq.topic_id = t.id AND qz.source_id = $3::uuid))
            ORDER BY COALESCE(m.mastery_percent, 35), t.name""",
        [user_id, q, source_id],
    ).rows


def create(*, user_id, input, weekly_limit, weighted_order):
    with transaction() as tx:
        tx.query("SELECT id FROM users WHERE id = $1 FOR UPDATE", [user_id])
        kit = tx.query_one("SELECT id FROM study_kits WHERE id = $1 AND user_id = $2", [input["studyKitId"], user_id])
        if not kit:
            return {"missing": True}
        used = tx.query_one(
            """SELECT count(*)::int AS count FROM practice_sessions
                WHERE user_id = $1 AND started_at >= date_trunc('week', now())""",
            [user_id],
        )["count"]
        if weekly_limit is not None and used >= weekly_limit:
            return {"quotaExceeded": True, "used": used, "limit": weekly_limit}
        if len(weighted_order) < input["questionCount"]:
            return {"insufficient": True, "available": len(weighted_order)}

        expires_at = (
            dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=input["timerSeconds"])
            if input["timerSeconds"] > 0 else None
        )
        session = tx.query_one(
            """INSERT INTO practice_sessions
                 (user_id, study_kit_id, source_id, mode, question_count, answer_format, timer_seconds, expires_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING *""",
            [user_id, input["studyKitId"], input.get("sourceId"), input["mode"], input["questionCount"],
             input["answerFormat"], input["timerSeconds"], expires_at],
        )
        for index, item in enumerate(weighted_order[: input["questionCount"]]):
            written = input["answerFormat"] == "written"
            options = [] if written else item["options"]
            correct = (
                item["options"][item["correct_answer"]]
                if written and is_integer(item["correct_answer"]) else item["correct_answer"]
            )
            # expected_answer is the prose answer a typed response is marked
            # against; None for a question drawn from the quiz pool.
            tx.query(
                """INSERT INTO practice_session_questions
                     (session_id, question_id, topic_id, position, prompt, options,
                      correct_answer, expected_answer, explanation, weight_at_select)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)""",
                [session["id"], item["id"], item["topic_id"], index + 1, item["prompt"], dumps(options),
                 dumps(correct), item.get("expected_answer"), item["explanation"], item["weight"]],
            )
        return {"session": session, "used": used, "limit": weekly_limit}


def candidate_questions(*, user_id, kit_id, topic_ids, source_id=None, provider):
    """Quiz-pool questions for a session; mock-provider rows are hidden while a real provider is active."""
    return query(
        """SELECT qq.id, qq.topic_id, qq.prompt, qq.options, qq.correct_answer, qq.explanation,
                  COALESCE(m.mastery_percent, 35)::int AS effective_mastery
             FROM quiz_questions qq JOIN quizzes q ON q.id = qq.quiz_id
             JOIN study_kits k ON k.id = q.study_kit_id
             LEFT JOIN ai_generation_cache c ON c.id = q.generation_cache_id
             LEFT JOIN user_topic_mastery m ON m.topic_id = qq.topic_id AND m.user_id = $1
            WHERE q.study_kit_id = $2 AND k.user_id = $1 AND q.status = 'ready'
              AND (cardinality($3::uuid[]) = 0 OR qq.topic_id = ANY($3::uuid[]))
              AND ($4::uuid IS NULL OR q.source_id = $4::uuid)
              AND ($5::text = 'mock' OR q.generation_cache_id IS NULL OR c.provider <> 'mock')""",
        [user_id, kit_id, list(topic_ids), source_id, provider],
    ).rows


def session(*, user_id, session_id):
    return query_one("SELECT * FROM practice_sessions WHERE id = $1 AND user_id = $2", [session_id, user_id])


def expire(*, user_id, session_id):
    return query_one(
        """UPDATE practice_sessions SET status = 'completed', completed_at = now(), duration_seconds = timer_seconds
           WHERE id = $1 AND user_id = $2 AND status = 'in_progress'
             AND expires_at IS NOT NULL AND expires_at <= now()
           RETURNING *""",
        [session_id, user_id],
    )


def questions(session_id):
    return query(
        """SELECT q.id, q.position, q.prompt, q.options, q.explanation, q.topic_id,
                  q.correct_answer, q.expected_answer,
                  a.response, a.is_correct, a.grader_note, a.answered_at
             FROM practice_session_questions q
             LEFT JOIN practice_answers a ON a.session_id = q.session_id AND a.position = q.position
            WHERE q.session_id = $1 ORDER BY q.position""",
        [session_id],
    ).rows


def answer(*, user_id, session_id, input):
    with transaction() as tx:
        item = tx.query_one(
            """SELECT q.*, s.status FROM practice_session_questions q
               JOIN practice_sessions s ON s.id = q.session_id
               WHERE q.session_id = $1 AND q.position = $2 AND s.user_id = $3
                 AND (s.expires_at IS NULL OR s.expires_at > now()) FOR UPDATE""",
            [session_id, input["position"], user_id],
        )
        if not item or item["status"] != "in_progress":
            return None
        expected = item["correct_answer"]
        response = input["response"]
        # A written answer with an answer key is left UNMARKED here and graded
        # at submit in one batched AI call; is_correct is nullable for this.
        grade_later = (
            isinstance(item.get("expected_answer"), str)
            and len(item["expected_answer"].strip()) > 0
            and isinstance(response, str)
        )
        if grade_later:
            correct = None
        elif isinstance(expected, str):
            correct = js_string(response).strip().lower() == expected.strip().lower()
        else:
            correct = response == expected and not isinstance(response, bool)
        saved = tx.query_one(
            """INSERT INTO practice_answers
                 (session_id, question_id, topic_id, position, prompt_snapshot, response, is_correct, time_spent_seconds)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
               ON CONFLICT (session_id, position) DO UPDATE SET response = EXCLUDED.response,
                 is_correct = EXCLUDED.is_correct, time_spent_seconds = EXCLUDED.time_spent_seconds,
                 answered_at = now() RETURNING *""",
            [session_id, item["question_id"], item["topic_id"], input["position"], item["prompt"],
             dumps(response), correct, input.get("timeSpentSeconds")],
        )
        tx.query(
            """UPDATE practice_sessions SET answered_count =
                 (SELECT count(*) FROM practice_answers WHERE session_id = $1) WHERE id = $1""",
            [session_id],
        )
        return saved


def ungraded_written(session_id):
    """Answers still waiting to be marked, ordered by position for the positional grader."""
    return query(
        """SELECT a.position, q.prompt, q.expected_answer, a.response
             FROM practice_answers a
             JOIN practice_session_questions q
               ON q.session_id = a.session_id AND q.position = a.position
            WHERE a.session_id = $1 AND a.is_correct IS NULL
              AND q.expected_answer IS NOT NULL
              AND length(trim(q.expected_answer)) > 0
            ORDER BY a.position""",
        [session_id],
    ).rows


def apply_grades(session_id, grades):
    """Keyed by position, so a grader returning the wrong count cannot shift marks."""
    updated = 0
    for grade in grades:
        updated += query(
            """UPDATE practice_answers
                  SET is_correct = $3, grader_note = $4
                WHERE session_id = $1 AND position = $2""",
            [session_id, grade["position"], grade["isCorrect"], grade.get("note") or None],
        ).rowcount
    return updated


def submit(*, user_id, session_id, duration_seconds=None):
    with transaction() as tx:
        current = tx.query_one(
            "SELECT * FROM practice_sessions WHERE id = $1 AND user_id = $2 FOR UPDATE", [session_id, user_id]
        )
        if not current:
            return None
        if current["status"] == "completed":
            return current
        stats = tx.query_one(
            """SELECT count(*)::int AS answered, count(*) FILTER (WHERE is_correct)::int AS correct,
                      array_remove(array_agg(DISTINCT t.name) FILTER (WHERE NOT a.is_correct), NULL) AS weak_topics
                 FROM practice_answers a LEFT JOIN topics t ON t.id = a.topic_id WHERE a.session_id = $1""",
            [session_id],
        )
        mastery = js_round(((stats["correct"] or 0) / max(1, current["question_count"])) * 100)
        completed = tx.query_one(
            """UPDATE practice_sessions SET status='completed', answered_count=$2, correct_count=$3,
                 mastery_percent=$4, weak_topics=$5, duration_seconds=$6, completed_at=now()
               WHERE id=$1 RETURNING *""",
            [session_id, stats["answered"], stats["correct"], mastery, dumps(stats["weak_topics"] or []),
             duration_seconds],
        )
        topic_stats = tx.rows(
            """SELECT topic_id, count(*)::int AS attempts,
                      count(*) FILTER (WHERE is_correct)::int AS correct
                 FROM practice_answers WHERE session_id=$1 AND topic_id IS NOT NULL GROUP BY topic_id""",
            [session_id],
        )
        for topic in topic_stats:
            tx.query(
                """INSERT INTO user_topic_mastery (user_id, topic_id, attempts, correct_count, mastery_percent, last_practiced_at)
                   VALUES ($1,$2,$3,$4,round($4::numeric/$3*100),now())
                   ON CONFLICT (user_id, topic_id) DO UPDATE SET
                     attempts=user_topic_mastery.attempts+EXCLUDED.attempts,
                     correct_count=user_topic_mastery.correct_count+EXCLUDED.correct_count,
                     mastery_percent=round((user_topic_mastery.correct_count+EXCLUDED.correct_count)::numeric /
                       (user_topic_mastery.attempts+EXCLUDED.attempts)*100), last_practiced_at=now()""",
                [user_id, topic["topic_id"], topic["attempts"], topic["correct"]],
            )
        return completed


def home(user_id):
    return query_one(
        """SELECT s.id, s.study_kit_id, k.title, s.answered_count, s.question_count
           FROM practice_sessions s LEFT JOIN study_kits k ON k.id=s.study_kit_id
           WHERE s.user_id=$1 AND s.status='in_progress' ORDER BY s.started_at DESC LIMIT 1""",
        [user_id],
    )


def progress(user_id):
    daily = query(
        """SELECT completed_at::date AS date, sum(correct_count)::int AS correct,
                  sum(question_count)::int AS total
             FROM practice_sessions WHERE user_id=$1 AND status='completed'
            GROUP BY completed_at::date ORDER BY date""",
        [user_id],
    ).rows
    topic_rows = query(
        """SELECT t.id, t.name, m.mastery_percent, m.attempts
             FROM user_topic_mastery m JOIN topics t ON t.id=m.topic_id
            WHERE m.user_id=$1 ORDER BY m.mastery_percent, t.name""",
        [user_id],
    ).rows
    dates = query(
        """SELECT DISTINCT completed_at::date AS date FROM practice_sessions
            WHERE user_id=$1 AND status='completed' ORDER BY date DESC""",
        [user_id],
    ).rows
    return {"daily": daily, "topics": topic_rows, "dates": [row["date"] for row in dates]}

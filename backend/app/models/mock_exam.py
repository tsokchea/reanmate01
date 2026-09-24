"""SQL for mock exam question banks (server/src/db/mockExam.db.js)."""

from ..extensions import query, query_one, transaction
from ..utils.serialization import dumps


def save_bank(*, cache_id, source, exam, params, model):
    """Replaces the bank for this cache row rather than adding to it, so a regeneration regenerates."""
    with transaction() as tx:
        bank = tx.query_one(
            """INSERT INTO mock_exam_banks
                 (study_kit_id, source_id, generation_cache_id, title, language, question_count)
               VALUES ($1, $2, $3, $4, $5, $6)
               ON CONFLICT (generation_cache_id) WHERE generation_cache_id IS NOT NULL
               DO UPDATE SET title = EXCLUDED.title,
                             language = EXCLUDED.language,
                             question_count = EXCLUDED.question_count
               RETURNING id""",
            [source["study_kit_id"], source["id"], cache_id, f"{exam['title']} ({model})", params["language"],
             len(exam["questions"])],
        )
        tx.query("DELETE FROM mock_exam_questions WHERE bank_id = $1", [bank["id"]])

        for index, question in enumerate(exam["questions"]):
            # Topics are shared with the quiz feature so mastery tracks one set of labels.
            topic = (
                tx.query_one(
                    """INSERT INTO topics (study_kit_id, name) VALUES ($1, $2)
                       ON CONFLICT (study_kit_id, name) WHERE study_kit_id IS NOT NULL
                       DO UPDATE SET name = EXCLUDED.name RETURNING id""",
                    [source["study_kit_id"], question["topic"]],
                )
                if question.get("topic") else None
            )
            tx.query(
                """INSERT INTO mock_exam_questions
                     (bank_id, topic_id, position, kind, prompt, options, correct_answer,
                      expected_answer, difficulty, explanation, topic_label)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)""",
                [bank["id"], topic["id"] if topic else None, index + 1, question["kind"], question["prompt"],
                 dumps(question["options"]), dumps(question["correctAnswer"]), question["expectedAnswer"],
                 question["difficulty"], question["explanation"], question.get("topic")],
            )

        tx.query("UPDATE ai_generation_cache SET status = 'ready', error_message = NULL WHERE id = $1", [cache_id])
        return bank


def bank_questions(*, user_id, kit_id, source_id=None):
    """Exam questions available to this student; ownership is checked through study_kits."""
    return query(
        """SELECT q.id, q.topic_id, q.prompt, q.options, q.correct_answer,
                  q.expected_answer, q.difficulty, q.explanation, q.kind
             FROM mock_exam_questions q
             JOIN mock_exam_banks b ON b.id = q.bank_id
             JOIN study_kits k ON k.id = b.study_kit_id
            WHERE b.study_kit_id = $1 AND k.user_id = $2
              AND ($3::uuid IS NULL OR b.source_id = $3::uuid)
            ORDER BY q.position""",
        [kit_id, user_id, source_id],
    ).rows


def bank_for_cache(cache_id):
    return query_one(
        "SELECT id, title, language, question_count FROM mock_exam_banks WHERE generation_cache_id = $1",
        [cache_id],
    )

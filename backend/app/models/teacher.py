"""SQL for the teacher workspace and assistant."""

from ..extensions import json_param, normalize_timestamp, query, query_one, transaction
from ..utils.serialization import dumps


def assistant_conversation(*, teacher_id, conversation_id=None, class_id=None, language):
    if conversation_id:
        return query_one(
            """SELECT id, teacher_id, class_id, language
                 FROM teacher_assistant_conversations
                WHERE id = $1 AND teacher_id = $2""",
            [conversation_id, teacher_id],
        )
    return query_one(
        """INSERT INTO teacher_assistant_conversations (teacher_id, class_id, language)
           VALUES ($1, $2, $3)
           RETURNING id, teacher_id, class_id, language""",
        [teacher_id, class_id, language],
    )


def assistant_messages(*, teacher_id, conversation_id):
    return query(
        """SELECT m.role, m.content
             FROM teacher_assistant_messages m
             JOIN teacher_assistant_conversations c ON c.id = m.conversation_id
            WHERE m.conversation_id = $1 AND c.teacher_id = $2
            ORDER BY m.created_at, m.rowid""",
        [conversation_id, teacher_id],
    ).rows


def add_assistant_message(*, teacher_id, conversation_id, role, content):
    row = query_one(
        """INSERT INTO teacher_assistant_messages (conversation_id, role, content)
           SELECT c.id, $3, $4
             FROM teacher_assistant_conversations c
            WHERE c.id = $2 AND c.teacher_id = $1
           RETURNING id""",
        [teacher_id, conversation_id, role, content],
    )
    if row:
        query(
            "UPDATE teacher_assistant_conversations SET last_message_at = now() WHERE id = $1 AND teacher_id = $2",
            [conversation_id, teacher_id],
        )
    return row


def assistant_history(teacher_id):
    return query(
        """SELECT c.id, c.class_id, c.language, c.last_message_at,
                  c.title, cl.title AS class_title,
                  (SELECT m.content FROM teacher_assistant_messages m
                    WHERE m.conversation_id = c.id
                    ORDER BY m.created_at DESC, m.rowid DESC LIMIT 1) AS last_content
             FROM teacher_assistant_conversations c
             LEFT JOIN classes cl ON cl.id = c.class_id
            WHERE c.teacher_id = $1
            ORDER BY c.last_message_at DESC
            LIMIT 50""",
        [teacher_id],
    ).rows


def clear_assistant_history(teacher_id):
    query("DELETE FROM teacher_assistant_conversations WHERE teacher_id = $1", [teacher_id])


def dashboard(teacher_id):
    summary = query_one(
        """SELECT
             (SELECT count(*) FROM classes WHERE teacher_id = $1 AND status = 'active') AS active_classes,
             (SELECT count(DISTINCT ce.user_id)
                FROM class_enrollments ce
                JOIN classes c ON c.id = ce.class_id
               WHERE c.teacher_id = $1 AND c.status = 'active' AND ce.status = 'active') AS total_students,
             (SELECT count(*)
                FROM assignment_submissions s
                JOIN assignments a ON a.id = s.assignment_id
                JOIN classes c ON c.id = a.class_id
               WHERE c.teacher_id = $1 AND s.status IN ('submitted', 'late')) AS pending_reviews,
             (SELECT count(*)
                FROM assignment_submissions s
                JOIN assignments a ON a.id = s.assignment_id
                JOIN classes c ON c.id = a.class_id
               WHERE c.teacher_id = $1 AND s.status = 'graded') AS returned_submissions""",
        [teacher_id],
    )
    classes = query(
        """SELECT c.id, c.title, c.subject, c.join_code, c.cover_image_path,
                  count(DISTINCT ce.user_id) AS student_count,
                  count(DISTINCT l.id) AS lesson_count,
                  count(DISTINCT l.id) FILTER (WHERE lp.status = 'completed') AS completed_lessons
             FROM classes c
             LEFT JOIN class_enrollments ce ON ce.class_id = c.id AND ce.status = 'active'
             LEFT JOIN lessons l ON l.class_id = c.id
             LEFT JOIN lesson_progress lp ON lp.lesson_id = l.id AND lp.status = 'completed'
            WHERE c.teacher_id = $1 AND c.status = 'active'
            GROUP BY c.id
            ORDER BY c.created_at DESC""",
        [teacher_id],
    ).rows
    assignments_rows = query(
        """SELECT a.id, a.title, a.class_id, c.title AS class_name, a.due_at,
                  count(s.id) AS submission_count,
                  count(s.id) FILTER (WHERE s.status IN ('submitted', 'late')) AS pending_count,
                  count(s.id) FILTER (WHERE s.status = 'graded') AS graded_count,
                  count(ce.user_id) AS student_count
             FROM assignments a
             JOIN classes c ON c.id = a.class_id
             LEFT JOIN class_enrollments ce ON ce.class_id = c.id AND ce.status = 'active'
             LEFT JOIN assignment_submissions s ON s.assignment_id = a.id
            WHERE c.teacher_id = $1 AND a.status <> 'draft'
            GROUP BY a.id, c.title
            ORDER BY a.due_at NULLS LAST, a.created_at DESC
            LIMIT 20""",
        [teacher_id],
    ).rows
    return {"summary": summary, "classes": classes, "assignments": assignments_rows}


def update_class(*, teacher_id, class_id, patch):
    return query_one(
        """UPDATE classes
              SET title = COALESCE($3, title),
                  description = CASE WHEN $4 THEN $5 ELSE description END,
                  subject = CASE WHEN $6 THEN $7 ELSE subject END,
                  status = COALESCE($8, status),
                  updated_at = now()
            WHERE id = $2 AND teacher_id = $1
            RETURNING id, title, description, subject, join_code, week_count, cover_color, status""",
        [teacher_id, class_id, patch.get("title"), "description" in patch, patch.get("description"),
         "subject" in patch, patch.get("subject"), patch.get("status")],
    )


def students(*, teacher_id, class_id):
    return query(
        """SELECT u.id, COALESCE(u.full_name, u.email, u.phone, 'Student') AS name,
                  ce.joined_at,
                  count(DISTINCT l.id) AS lesson_count,
                  count(DISTINCT l.id) FILTER (WHERE lp.status = 'completed') AS completed_lessons,
                  count(DISTINCT a.id) AS assignment_count,
                  count(DISTINCT s.id) FILTER (WHERE s.status IN ('submitted', 'late', 'graded')) AS submitted_assignments,
                  count(DISTINCT s.id) FILTER (WHERE s.status = 'graded') AS graded_assignments,
                  COALESCE(round(avg(s.score) FILTER (WHERE s.status = 'graded'), 2), 0) AS average_score
             FROM classes c
             JOIN class_enrollments ce ON ce.class_id = c.id AND ce.status = 'active'
             JOIN users u ON u.id = ce.user_id
             LEFT JOIN lessons l ON l.class_id = c.id
             LEFT JOIN lesson_progress lp ON lp.lesson_id = l.id AND lp.user_id = u.id
             LEFT JOIN assignments a ON a.class_id = c.id AND a.status <> 'draft'
             LEFT JOIN assignment_submissions s ON s.assignment_id = a.id AND s.user_id = u.id
            WHERE c.id = $2 AND c.teacher_id = $1
            GROUP BY u.id, ce.joined_at
            ORDER BY name""",
        [teacher_id, class_id],
    ).rows


def assignments(teacher_id):
    return query(
        """SELECT a.id, a.class_id, c.title AS class_name, a.title, a.description,
                  a.assignment_type, a.status, a.due_at, a.points, a.question_count,
                  count(ce.user_id) AS student_count,
                  count(s.id) AS submission_count,
                  count(s.id) FILTER (WHERE s.status IN ('submitted', 'late')) AS pending_count,
                  count(s.id) FILTER (WHERE s.status = 'graded') AS graded_count
             FROM assignments a
             JOIN classes c ON c.id = a.class_id
             LEFT JOIN class_enrollments ce ON ce.class_id = c.id AND ce.status = 'active'
             LEFT JOIN assignment_submissions s ON s.assignment_id = a.id
            WHERE c.teacher_id = $1
            GROUP BY a.id, c.title
            ORDER BY a.due_at NULLS LAST, a.created_at DESC""",
        [teacher_id],
    ).rows


def assignment(*, teacher_id, assignment_id):
    return query_one(
        """SELECT a.id, a.class_id, a.quiz_id, a.title, a.description, a.instructions,
                  a.due_at, a.points, a.question_count, a.allow_file_upload,
                  a.assignment_type, a.status, c.title AS class_name,
                  json_group_array(json_object(
                    'id', am.id, 'title', am.title, 'originalFilename', am.original_filename,
                    'mimeType', am.mime_type, 'byteSize', am.byte_size
                  ) ORDER BY am.created_at) FILTER (WHERE am.id IS NOT NULL) AS "materials [JSONTEXT]"
             FROM assignments a
             JOIN classes c ON c.id = a.class_id
             LEFT JOIN assignment_materials am ON am.assignment_id = a.id
            WHERE a.id = $2 AND c.teacher_id = $1
            GROUP BY a.id, c.title""",
        [teacher_id, assignment_id],
    )


def update_assignment(*, teacher_id, assignment_id, input):
    return query_one(
        """UPDATE assignments AS a
              SET title = $3,
                  description = $4,
                  instructions = $5,
                  due_at = $6,
                  points = $7,
                  status = CASE WHEN COALESCE($8, 0) THEN 'published' ELSE a.status END,
                  published_at = CASE WHEN COALESCE($8, 0) AND a.published_at IS NULL THEN now() ELSE a.published_at END
             FROM classes c
            WHERE a.id = $2 AND a.class_id = c.id AND c.teacher_id = $1
            RETURNING *""",
        [teacher_id, assignment_id, input["title"], input.get("description"), dumps(input.get("instructions") or []),
         normalize_timestamp(input.get("dueAt")), input["points"], input.get("publish") or False],
    )


def delete_assignment(*, teacher_id, assignment_id):
    with transaction() as tx:
        materials_rows = tx.rows(
            """SELECT am.storage_path
                 FROM assignment_materials am
                 JOIN assignments a ON a.id = am.assignment_id
                 JOIN classes c ON c.id = a.class_id
                WHERE am.assignment_id = $2
                  AND c.teacher_id = $1
                  AND am.storage_path IS NOT NULL""",
            [teacher_id, assignment_id],
        )
        deleted = tx.query_one(
            """DELETE FROM assignments
                WHERE id = $2
                  AND class_id IN (SELECT id FROM classes WHERE teacher_id = $1)
                RETURNING id, quiz_id""",
            [teacher_id, assignment_id],
        )
        if not deleted:
            return None
        if deleted["quiz_id"]:
            tx.query("DELETE FROM quizzes WHERE id = $1", [deleted["quiz_id"]])
        return {**deleted, "materials": materials_rows}


def create_assignment(*, teacher_id, input):
    return query_one(
        """INSERT INTO assignments
             (class_id, quiz_id, created_by, title, description, instructions, due_at,
              points, question_count, allow_file_upload, assignment_type, status, published_at)
           SELECT c.id, $3, $1, $4, $5, $6, $7, $8,
                  COALESCE(q.question_count, 0), $9 = 'file', $9,
                  CASE WHEN $10 THEN 'published' ELSE 'draft' END,
                  CASE WHEN $10 THEN now() ELSE NULL END
             FROM classes c
             LEFT JOIN quizzes q ON q.id = $3
            WHERE c.id = $2 AND c.teacher_id = $1 AND c.status = 'active'
              AND ($9 = 'file' OR (q.id IS NOT NULL AND q.class_id = c.id))
           RETURNING *""",
        [teacher_id, input["classId"], input.get("quizId"), input["title"], input.get("description"),
         dumps(input["instructions"]), normalize_timestamp(input.get("dueAt")), input.get("points"), input["type"],
         input["publish"]],
    )


def create_quiz(*, teacher_id, input, quiz):
    with transaction() as tx:
        created = tx.query_one(
            """INSERT INTO quizzes
                 (class_id, created_by, title, language, difficulty, question_count, generated_by_ai, status, description)
               SELECT c.id, $1, $3, $4, 'mixed', $5, 1, 'ready', $6
                 FROM classes c
                WHERE c.id = $2 AND c.teacher_id = $1 AND c.status = 'active'
               RETURNING id, class_id, title, language, question_count""",
            [teacher_id, input["classId"], input["title"], input["language"], len(quiz["questions"]),
             "Generated by ReanMate"],
        )
        if not created:
            return None

        for position, question in enumerate(quiz["questions"]):
            tx.query(
                """INSERT INTO quiz_questions
                     (quiz_id, position, kind, prompt, options, correct_answer, explanation)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                [created["id"], position, question["kind"], question["prompt"], dumps(question.get("options") or []),
                 dumps(question.get("correctAnswer")), question.get("explanation")],
            )

        assignment_row = tx.query_one(
            """INSERT INTO assignments
                 (class_id, quiz_id, created_by, title, due_at, points, question_count,
                  allow_file_upload, assignment_type, status, published_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, 0, 'quiz', $8,
                       CASE WHEN $8 = 'published' THEN now() ELSE NULL END)
               RETURNING id, status""",
            [created["class_id"], created["id"], teacher_id, input["title"], normalize_timestamp(input.get("dueAt")),
             input.get("points"), len(quiz["questions"]), "published" if input.get("publish") else "draft"],
        )
        return {"quiz": created, "assignment": assignment_row}


def add_assignment_attachment(*, teacher_id, assignment_id, file):
    return query_one(
        """INSERT INTO assignment_materials
             (assignment_id, title, original_filename, storage_path, mime_type, byte_size)
           SELECT a.id, $3, $3, $4, $5, $6
             FROM assignments a
             JOIN classes c ON c.id = a.class_id
            WHERE a.id = $2 AND c.teacher_id = $1
           RETURNING id, assignment_id, title, original_filename, mime_type, byte_size""",
        [teacher_id, assignment_id, file["originalname"], file["storagePath"], file["mimetype"], file["byteSize"]],
    )


def class_context(*, teacher_id, class_id):
    # NULLS LAST keeps PostgreSQL's ordering for lessons without items.
    return query(
        """SELECT c.title AS class_title, c.subject,
                  l.title AS lesson_title, l.content_md,
                  li.title AS item_title, li.content_md AS item_content
             FROM classes c
             LEFT JOIN lessons l ON l.class_id = c.id
             LEFT JOIN lesson_items li ON li.lesson_id = l.id
            WHERE c.id = $2 AND c.teacher_id = $1
            ORDER BY l.week_number NULLS LAST, l.position NULLS LAST, li.position NULLS LAST""",
        [teacher_id, class_id],
    ).rows


def materials(*, teacher_id, class_id):
    return query(
        """SELECT m.id, m.title, m.original_filename, m.mime_type, m.byte_size, m.week_number,
                  m.storage_path, m.lesson_id, m.created_at
             FROM class_materials m
             JOIN classes c ON c.id = m.class_id
            WHERE m.class_id = $2 AND c.teacher_id = $1
            ORDER BY m.created_at DESC""",
        [teacher_id, class_id],
    ).rows


def selected_materials(*, teacher_id, class_id, material_ids):
    if not material_ids:
        return []
    return query(
        """SELECT m.id, m.title, m.original_filename, m.storage_path, m.mime_type
             FROM class_materials m
             JOIN classes c ON c.id = m.class_id
            WHERE c.teacher_id = $1 AND m.class_id = $2 AND m.id IN (SELECT value FROM json_each($3))""",
        [teacher_id, class_id, json_param(material_ids)],
    ).rows


def material_file(*, teacher_id, class_id, material_id):
    return query_one(
        """SELECT m.storage_path, m.mime_type, m.original_filename
             FROM class_materials m
             JOIN classes c ON c.id = m.class_id
            WHERE m.id = $3 AND m.class_id = $2 AND c.teacher_id = $1""",
        [teacher_id, class_id, material_id],
    )


def remove_material(*, teacher_id, class_id, material_id):
    return query_one(
        """DELETE FROM class_materials
            WHERE id = $3 AND class_id = $2
              AND class_id IN (SELECT id FROM classes WHERE teacher_id = $1)
            RETURNING storage_path""",
        [teacher_id, class_id, material_id],
    )


def add_material(*, teacher_id, class_id, title, week_number, file):
    return query_one(
        """INSERT INTO class_materials
             (class_id, uploaded_by, title, week_number, original_filename, storage_path, mime_type, byte_size)
           SELECT c.id, $1, $3, $4, $5, $6, $7, $8
             FROM classes c
            WHERE c.id = $2 AND c.teacher_id = $1 AND c.status = 'active'
           RETURNING *""",
        [teacher_id, class_id, title, week_number, file["originalname"], file["storagePath"], file["mimetype"],
         file["byteSize"]],
    )

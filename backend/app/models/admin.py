"""SQL behind the admin console: account lists, account detail, statistics and content lists.

Kinds are always passed as a JSON list of the kinds the requesting admin may
see, so a query can never return a row the service did not mean to expose.
A NULL users.role (an account that has not picked a role yet) is treated as
a student.
"""

from ..extensions import json_param, query, query_one

KIND = "COALESCE(u.role, 'student')"

ACCOUNT_COLUMNS = f"""
  u.id, u.full_name, u.email, u.phone, u.role, {KIND} AS kind, u.role_id, r.key AS role_key, r.name AS role_name,
  u.status, u.locale, u.plan_tier, u.must_change_password, u.created_at, u.updated_at, u.last_login_at,
  u.last_seen_at
"""

SORTS = {
    "created": "u.created_at DESC",
    "name": "lower(COALESCE(u.full_name, u.email, u.phone)) ASC",
    "lastLogin": "u.last_login_at IS NULL, u.last_login_at DESC",
    "aiUsage": "month_tokens DESC",
}


def list_accounts(*, kinds, status, q, sort, limit, offset, today, month_start):
    """``status``: 'active' | 'disabled' | None (any but deleted). ``today``/``month_start`` are server dates."""
    params = [json_param(kinds), status, q]
    where = f"""
     WHERE {KIND} IN (SELECT value FROM json_each($1))
       AND u.status <> 'deleted'
       AND ($2 IS NULL OR u.status = $2)
       AND ($3 IS NULL OR ilike(COALESCE(u.full_name, '') || ' ' || COALESCE(u.email, '') || ' '
                                 || COALESCE(u.phone, ''), '%' || $3 || '%'))"""
    rows = query(
        f"""SELECT {ACCOUNT_COLUMNS},
                   COALESCE(ur.today_tokens, 0) AS today_tokens, COALESCE(ur.month_tokens, 0) AS month_tokens
              FROM users u
              LEFT JOIN roles r ON r.id = u.role_id
              LEFT JOIN (SELECT user_id,
                                sum(CASE WHEN date = $6 THEN ai_total_tokens ELSE 0 END) AS today_tokens,
                                sum(ai_total_tokens) AS month_tokens
                           FROM usage_records WHERE date >= $7 GROUP BY user_id) ur ON ur.user_id = u.id
              {where}
             ORDER BY {SORTS.get(sort, SORTS['created'])}, u.id
             LIMIT $4 OFFSET $5""",
        [*params, limit, offset, today, month_start],
    ).rows
    total = query_one(f"SELECT count(*) AS n FROM users u {where}", params)["n"]
    return rows, total


def find_account(user_id):
    return query_one(
        f"""SELECT {ACCOUNT_COLUMNS}
              FROM users u LEFT JOIN roles r ON r.id = u.role_id
             WHERE u.id = $1 AND u.status <> 'deleted'""",
        [user_id],
    )


def email_or_phone_taken(*, email, phone, except_id=None):
    row = query_one(
        """SELECT max(CASE WHEN $1 IS NOT NULL AND email = $1 THEN 1 ELSE 0 END) AS email,
                  max(CASE WHEN $2 IS NOT NULL AND phone = $2 THEN 1 ELSE 0 END) AS phone
             FROM users
            WHERE (($1 IS NOT NULL AND email = $1) OR ($2 IS NOT NULL AND phone = $2))
              AND ($3 IS NULL OR id <> $3)""",
        [email, phone, except_id],
    )
    return {"email": bool(row and row["email"]), "phone": bool(row and row["phone"])}


def create_account(tx, *, full_name, email, phone, password_hash, role, role_id, status, locale, verified_at):
    return tx.query_one(
        """INSERT INTO users (full_name, email, phone, password_hash, role, role_id, status, locale,
                              must_change_password, phone_verified_at, email_verified_at)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 1,
                   CASE WHEN $3 IS NULL THEN NULL ELSE $9 END,
                   CASE WHEN $2 IS NULL THEN NULL ELSE $9 END)
           RETURNING id""",
        [full_name, email, phone, password_hash, role, role_id, status, locale, verified_at],
    )


def update_account(tx, user_id, values):
    """``values`` maps column -> value (columns come from the service's whitelist)."""
    if not values:
        return
    assignments = ", ".join(f"{column} = ${i + 2}" for i, column in enumerate(values))
    tx.query(f"UPDATE users SET {assignments} WHERE id = $1", [user_id, *values.values()])


def set_status(tx, user_id, status):
    tx.query("UPDATE users SET status = $2 WHERE id = $1", [user_id, status])


def set_password(tx, user_id, password_hash, must_change):
    tx.query("UPDATE users SET password_hash = $2, must_change_password = $3 WHERE id = $1",
             [user_id, password_hash, 1 if must_change else 0])


def soft_delete(tx, user_id):
    """Keeps the row (content and history stay attributable) but frees the email/phone and drops the name."""
    tx.query(
        """UPDATE users
              SET status = 'deleted', email = 'deleted+' || id || '@deleted.invalid', phone = NULL,
                  full_name = NULL, avatar_url = NULL
            WHERE id = $1""",
        [user_id],
    )
    tx.query("DELETE FROM user_permissions WHERE user_id = $1", [user_id])
    tx.query("DELETE FROM account_limits WHERE user_id = $1", [user_id])


def revoke_sessions(tx, user_id):
    tx.query("UPDATE auth_sessions SET revoked_at = now() WHERE user_id = $1 AND revoked_at IS NULL", [user_id])


# --- account activity ----------------------------------------------------------


def recent_ai(user_id, limit=10):
    return query(
        """SELECT id, kind, provider, model, status, total_tokens, prompt_tokens, completion_tokens, created_at
             FROM ai_generations WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2""",
        [user_id, limit],
    ).rows


def recent_uploads(user_id, limit=10):
    return query(
        """SELECT s.id, s.title, s.kind, s.status, s.byte_size, s.created_at, k.title AS kit_title
             FROM kit_sources s JOIN study_kits k ON k.id = s.study_kit_id
            WHERE s.user_id = $1 ORDER BY s.created_at DESC LIMIT $2""",
        [user_id, limit],
    ).rows


def recent_assignments(user_id, limit=10):
    """Assignments a teacher created, or a student's submissions."""
    return query(
        """SELECT a.id, a.title, c.title AS class_title, a.created_at AS at, 'created' AS relation, NULL AS status
             FROM assignments a JOIN classes c ON c.id = a.class_id
            WHERE a.created_by = $1
           UNION ALL
           SELECT a.id, a.title, c.title, s.updated_at, 'submission', s.status
             FROM assignment_submissions s
             JOIN assignments a ON a.id = s.assignment_id
             JOIN classes c ON c.id = a.class_id
            WHERE s.user_id = $1
            ORDER BY at DESC LIMIT $2""",
        [user_id, limit],
    ).rows


def recent_logins(user_id, limit=10):
    return query(
        "SELECT id, ip_address, user_agent, created_at FROM login_events WHERE user_id = $1 "
        "ORDER BY created_at DESC LIMIT $2",
        [user_id, limit],
    ).rows


def storage_bytes(user_id):
    return query_one(
        "SELECT COALESCE(sum(byte_size), 0) AS n FROM kit_sources WHERE user_id = $1 AND storage_path IS NOT NULL",
        [user_id],
    )["n"]


# --- statistics ----------------------------------------------------------------


def account_counts(today, week_start):
    return query_one(
        """SELECT count(*) AS total,
                  sum(CASE WHEN COALESCE(role, 'student') = 'student' THEN 1 ELSE 0 END) AS students,
                  sum(CASE WHEN role = 'teacher' THEN 1 ELSE 0 END) AS teachers,
                  sum(CASE WHEN role IN ('admin', 'super_admin') THEN 1 ELSE 0 END) AS admins,
                  sum(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS active,
                  sum(CASE WHEN status = 'disabled' THEN 1 ELSE 0 END) AS disabled,
                  sum(CASE WHEN created_at >= $1 THEN 1 ELSE 0 END) AS new_today,
                  sum(CASE WHEN created_at >= $2 THEN 1 ELSE 0 END) AS new_week,
                  sum(CASE WHEN last_seen_at >= $1 THEN 1 ELSE 0 END) AS active_today
             FROM users WHERE status <> 'deleted'""",
        [today, week_start],
    )


def usage_totals(today, month_start):
    return query_one(
        """SELECT COALESCE(sum(CASE WHEN date = $1 THEN ai_total_tokens END), 0) AS tokens_today,
                  COALESCE(sum(ai_total_tokens), 0) AS tokens_month,
                  COALESCE(sum(CASE WHEN date = $1 THEN tutor_messages END), 0) AS tutor_today,
                  COALESCE(sum(CASE WHEN date = $1 THEN pdf_uploads END), 0) AS uploads_today
             FROM usage_records WHERE date >= $2""",
        [today, month_start],
    )


def content_counts():
    return query_one(
        """SELECT (SELECT count(*) FROM kit_sources WHERE kind = 'pdf') AS pdfs,
                  (SELECT count(*) FROM kit_sources WHERE storage_path IS NOT NULL) AS files,
                  (SELECT count(*) FROM kit_sources WHERE status IN ('pending', 'processing')) AS processing,
                  (SELECT count(*) FROM assignments) AS assignments,
                  (SELECT count(DISTINCT generation_cache_id) FROM flashcards
                    WHERE generation_cache_id IS NOT NULL) AS flashcard_sets,
                  (SELECT count(*) FROM classes) AS courses"""
    )


def series(*, since, bucket_chars):
    """Event counts per bucket since ``since`` (an ISO timestamp); buckets are timestamp prefixes."""
    n = bucket_chars
    tokens = query(
        f"""SELECT substr(created_at, 1, {n}) AS b, COALESCE(sum(total_tokens), 0) AS v
              FROM ai_generations WHERE created_at >= $1 GROUP BY b""", [since]).rows
    uploads = query(
        f"""SELECT substr(created_at, 1, {n}) AS b, count(*) AS v
              FROM kit_sources WHERE created_at >= $1 AND storage_path IS NOT NULL GROUP BY b""", [since]).rows
    assignments = query(
        f"""SELECT substr(created_at, 1, {n}) AS b, count(*) AS v
              FROM assignments WHERE created_at >= $1 GROUP BY b""", [since]).rows
    flashcards = query(
        f"""SELECT substr(created_at, 1, {n}) AS b, count(*) AS v
              FROM flashcards WHERE created_at >= $1 GROUP BY b""", [since]).rows
    active = query(
        f"""SELECT b, count(DISTINCT user_id) AS v FROM (
              SELECT substr(created_at, 1, {n}) AS b, user_id FROM login_events WHERE created_at >= $1
              UNION ALL
              SELECT substr(created_at, 1, {n}), user_id FROM ai_generations
               WHERE created_at >= $1 AND user_id IS NOT NULL
              UNION ALL
              SELECT substr(created_at, 1, {n}), user_id FROM kit_sources WHERE created_at >= $1
            ) GROUP BY b""", [since]).rows
    return {
        "aiTokens": {r["b"]: r["v"] for r in tokens},
        "uploads": {r["b"]: r["v"] for r in uploads},
        "assignments": {r["b"]: r["v"] for r in assignments},
        "flashcards": {r["b"]: r["v"] for r in flashcards},
        "activeUsers": {r["b"]: r["v"] for r in active},
    }


def usage_page(*, kinds, q, limit, offset, today, month_start):
    params = [json_param(kinds), q, today, month_start]
    where = f"""
     WHERE {KIND} IN (SELECT value FROM json_each($1)) AND u.status <> 'deleted'
       AND ($2 IS NULL OR ilike(COALESCE(u.full_name, '') || ' ' || COALESCE(u.email, ''), '%' || $2 || '%'))"""
    rows = query(
        f"""SELECT u.id, u.full_name, u.email, u.phone, {KIND} AS kind, r.name AS role_name, u.status,
                   COALESCE(sum(CASE WHEN ur.date = $3 THEN ur.ai_total_tokens END), 0) AS tokens_today,
                   COALESCE(sum(ur.ai_total_tokens), 0) AS tokens_month,
                   COALESCE(sum(CASE WHEN ur.date = $3 THEN ur.tutor_messages END), 0) AS tutor_today,
                   COALESCE(sum(ur.pdf_uploads), 0) AS uploads_month,
                   COALESCE(sum(ur.storage_bytes), 0) AS storage_month
              FROM users u
              LEFT JOIN roles r ON r.id = u.role_id
              LEFT JOIN usage_records ur ON ur.user_id = u.id AND ur.date >= $4
              {where}
             GROUP BY u.id
             ORDER BY tokens_month DESC, u.created_at DESC
             LIMIT $5 OFFSET $6""",
        [*params, limit, offset],
    ).rows
    total = query_one(f"SELECT count(*) AS n FROM users u {where}", params[:2])["n"]
    return rows, total


# --- content -------------------------------------------------------------------


def sources_page(*, q, kind, limit, offset):
    params = [q, kind]
    where = """
     WHERE ($1 IS NULL OR ilike(s.title || ' ' || COALESCE(u.email, ''), '%' || $1 || '%'))
       AND ($2 IS NULL OR s.kind = $2)"""
    rows = query(
        f"""SELECT s.id, s.title, s.kind, s.status, s.byte_size, s.page_count, s.created_at, s.study_kit_id,
                   k.title AS kit_title, u.id AS owner_id, u.full_name AS owner_name, u.email AS owner_email
              FROM kit_sources s
              JOIN study_kits k ON k.id = s.study_kit_id
              JOIN users u ON u.id = s.user_id
              {where}
             ORDER BY s.created_at DESC LIMIT $3 OFFSET $4""",
        [*params, limit, offset],
    ).rows
    total = query_one(
        f"SELECT count(*) AS n FROM kit_sources s JOIN users u ON u.id = s.user_id {where}", params)["n"]
    return rows, total


def find_source(source_id):
    return query_one(
        "SELECT id, title, kind, user_id, study_kit_id, storage_path FROM kit_sources WHERE id = $1", [source_id])


def classes_page(*, q, limit, offset):
    params = [q]
    where = "WHERE ($1 IS NULL OR ilike(c.title || ' ' || COALESCE(u.email, ''), '%' || $1 || '%'))"
    rows = query(
        f"""SELECT c.id, c.title, c.subject, c.status, c.created_at, u.id AS teacher_id,
                   u.full_name AS teacher_name, u.email AS teacher_email,
                   (SELECT count(*) FROM class_enrollments e WHERE e.class_id = c.id AND e.status = 'active')
                     AS student_count,
                   (SELECT count(*) FROM assignments a WHERE a.class_id = c.id) AS assignment_count
              FROM classes c JOIN users u ON u.id = c.teacher_id
              {where}
             ORDER BY c.created_at DESC LIMIT $2 OFFSET $3""",
        [*params, limit, offset],
    ).rows
    total = query_one(f"SELECT count(*) AS n FROM classes c JOIN users u ON u.id = c.teacher_id {where}",
                      params)["n"]
    return rows, total


def assignments_page(*, q, limit, offset):
    params = [q]
    where = "WHERE ($1 IS NULL OR ilike(a.title || ' ' || c.title, '%' || $1 || '%'))"
    rows = query(
        f"""SELECT a.id, a.title, a.status, a.due_at, a.created_at, c.id AS class_id, c.title AS class_title,
                   c.teacher_id, u.full_name AS teacher_name, u.email AS teacher_email,
                   (SELECT count(*) FROM assignment_submissions s WHERE s.assignment_id = a.id
                     AND s.status IN ('submitted', 'graded', 'late')) AS submission_count
              FROM assignments a
              JOIN classes c ON c.id = a.class_id
              JOIN users u ON u.id = c.teacher_id
              {where}
             ORDER BY a.created_at DESC LIMIT $2 OFFSET $3""",
        [*params, limit, offset],
    ).rows
    total = query_one(f"SELECT count(*) AS n FROM assignments a JOIN classes c ON c.id = a.class_id {where}",
                      params)["n"]
    return rows, total


def find_assignment(assignment_id):
    return query_one(
        """SELECT a.id, a.title, c.teacher_id FROM assignments a JOIN classes c ON c.id = a.class_id
            WHERE a.id = $1""",
        [assignment_id],
    )


def flashcard_sets_page(*, q, limit, offset):
    params = [q]
    where = """
     WHERE f.generation_cache_id IS NOT NULL
       AND ($1 IS NULL OR ilike(COALESCE(s.title, '') || ' ' || COALESCE(u.email, ''), '%' || $1 || '%'))"""
    base = """
      FROM flashcards f
      JOIN users u ON u.id = f.user_id
      LEFT JOIN kit_sources s ON s.id = f.source_id"""
    rows = query(
        f"""SELECT f.generation_cache_id AS id, min(s.title) AS source_title, min(f.language) AS language,
                   count(*) AS card_count, min(f.created_at) AS created_at, u.id AS owner_id,
                   u.full_name AS owner_name, u.email AS owner_email
              {base} {where}
             GROUP BY f.generation_cache_id, u.id
             ORDER BY created_at DESC LIMIT $2 OFFSET $3""",
        [*params, limit, offset],
    ).rows
    total = query_one(
        f"SELECT count(*) AS n FROM (SELECT 1 {base} {where} GROUP BY f.generation_cache_id, u.id)", params)["n"]
    return rows, total


def find_flashcard_set(cache_id):
    return query_one(
        """SELECT c.id, c.source_id, s.title AS source_title, s.user_id,
                  (SELECT count(*) FROM flashcards f WHERE f.generation_cache_id = c.id) AS card_count
             FROM ai_generation_cache c JOIN kit_sources s ON s.id = c.source_id
            WHERE c.id = $1 AND c.method = 'generateFlashcards'""",
        [cache_id],
    )


def delete_flashcard_set(tx, cache_id):
    # Cards cascade from the cache row; the next request for this deck generates it afresh.
    tx.query("DELETE FROM ai_generation_cache WHERE id = $1 AND method = 'generateFlashcards'", [cache_id])

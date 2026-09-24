"""SQL for usage limits (role defaults, account overrides) and daily usage records."""

from ..extensions import query, query_one


class _Direct:
    """Runs outside a transaction; lets one function serve both cases."""

    query = staticmethod(query)
    query_one = staticmethod(query_one)


DIRECT = _Direct()

# API name -> column. The same twelve columns exist on role_limits and account_limits.
LIMIT_FIELDS = {
    "dailyAiTokens": "daily_ai_tokens",
    "monthlyAiTokens": "monthly_ai_tokens",
    "dailyPdfUploads": "daily_pdf_uploads",
    "monthlyPdfUploads": "monthly_pdf_uploads",
    "dailyAssignments": "daily_assignments",
    "monthlyAssignments": "monthly_assignments",
    "dailyFlashcards": "daily_flashcards",
    "monthlyFlashcards": "monthly_flashcards",
    "dailyTutorMessages": "daily_tutor_messages",
    "monthlyTutorMessages": "monthly_tutor_messages",
    "dailyFileStorageBytes": "daily_file_storage_bytes",
    "monthlyFileStorageBytes": "monthly_file_storage_bytes",
}

# API name -> usage_records column.
USAGE_FIELDS = {
    "aiInputTokens": "ai_input_tokens",
    "aiOutputTokens": "ai_output_tokens",
    "aiTotalTokens": "ai_total_tokens",
    "pdfUploads": "pdf_uploads",
    "assignmentsCreated": "assignments_created",
    "flashcardsCreated": "flashcards_created",
    "tutorMessages": "tutor_messages",
    "storageBytes": "storage_bytes",
}

_LIMIT_COLUMNS = ", ".join(LIMIT_FIELDS.values())
_USAGE_SUMS = ", ".join(f"COALESCE(sum({column}), 0) AS {column}" for column in USAGE_FIELDS.values())


def role_limits(role_id):
    return query_one(f"SELECT role_id, {_LIMIT_COLUMNS}, updated_at FROM role_limits WHERE role_id = $1", [role_id])


def all_role_limits():
    return {row["role_id"]: row for row in query(
        f"SELECT role_id, {_LIMIT_COLUMNS}, updated_at FROM role_limits").rows}


def account_limits(user_id):
    return query_one(f"SELECT user_id, {_LIMIT_COLUMNS}, updated_at FROM account_limits WHERE user_id = $1",
                     [user_id])


def effective_limit_rows(user_id):
    """Both layers for one account: (role row or None, account row or None).

    An account that has not picked a role yet gets the student defaults.
    """
    role_row = query_one(
        f"""SELECT rl.role_id, {", ".join("rl." + c for c in LIMIT_FIELDS.values())}, rl.updated_at
              FROM users u
              JOIN role_limits rl
                ON rl.role_id = COALESCE(u.role_id, (SELECT id FROM roles WHERE kind = 'student'))
             WHERE u.id = $1""",
        [user_id],
    )
    return role_row, account_limits(user_id)


def upsert_role_limits(tx, role_id, values, updated_by):
    """``values`` maps column -> value; only those columns change."""
    tx.query("INSERT INTO role_limits (role_id) VALUES ($1) ON CONFLICT (role_id) DO NOTHING", [role_id])
    if values:
        assignments = ", ".join(f"{column} = ${i + 3}" for i, column in enumerate(values))
        tx.query(f"UPDATE role_limits SET {assignments}, updated_by = $2 WHERE role_id = $1",
                 [role_id, updated_by, *values.values()])
    return tx.query_one(f"SELECT role_id, {_LIMIT_COLUMNS}, updated_at FROM role_limits WHERE role_id = $1",
                        [role_id])


def upsert_account_limits(tx, user_id, values, updated_by):
    tx.query("INSERT INTO account_limits (user_id) VALUES ($1) ON CONFLICT (user_id) DO NOTHING", [user_id])
    if values:
        assignments = ", ".join(f"{column} = ${i + 3}" for i, column in enumerate(values))
        tx.query(f"UPDATE account_limits SET {assignments}, updated_by = $2 WHERE user_id = $1",
                 [user_id, updated_by, *values.values()])
    return tx.query_one(f"SELECT user_id, {_LIMIT_COLUMNS}, updated_at FROM account_limits WHERE user_id = $1",
                        [user_id])


def clear_account_limits(tx, user_id):
    tx.query("DELETE FROM account_limits WHERE user_id = $1", [user_id])


def record(runner, user_id, date, deltas):
    """Adds ``deltas`` (column -> amount) to one account's row for ``date``."""
    columns = list(deltas)
    inserts = ", ".join(columns)
    values = ", ".join(f"${i + 3}" for i in range(len(columns)))
    updates = ", ".join(f"{column} = usage_records.{column} + excluded.{column}" for column in columns)
    runner.query(
        f"""INSERT INTO usage_records (user_id, date, {inserts}) VALUES ($1, $2, {values})
            ON CONFLICT (user_id, date) DO UPDATE SET {updates}""",
        [user_id, date, *deltas.values()],
    )


def totals(runner, user_id, since_date, until_date=None):
    """Summed usage for one account over [since_date, until_date]."""
    row = runner.query_one(
        f"""SELECT {_USAGE_SUMS} FROM usage_records
             WHERE user_id = $1 AND date >= $2 AND ($3 IS NULL OR date <= $3)""",
        [user_id, since_date, until_date],
    )
    return row


def daily(user_id, since_date):
    return query(
        # substr() so the DATE converter does not turn the day into a datetime.
        f"""SELECT substr(date, 1, 10) AS day, {", ".join(USAGE_FIELDS.values())} FROM usage_records
             WHERE user_id = $1 AND date >= $2 ORDER BY date""",
        [user_id, since_date],
    ).rows


def reset_day(tx, user_id, date):
    previous = tx.query_one(
        f"SELECT {', '.join(USAGE_FIELDS.values())} FROM usage_records WHERE user_id = $1 AND date = $2",
        [user_id, date],
    )
    zeroes = ", ".join(f"{column} = 0" for column in USAGE_FIELDS.values())
    tx.query(f"UPDATE usage_records SET {zeroes} WHERE user_id = $1 AND date = $2", [user_id, date])
    return previous

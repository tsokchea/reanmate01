"""SQL for ``study_kits`` (server/src/db/kits.db.js).

Reads shape the row for docs/API-CONTRACT.md §3: cardCount, sourceKind and
titleKm are not columns, and the lateral subqueries are indexed so the list
stays one round trip.
"""

from ..extensions import query, query_one

# title_km mirrors title until contract decision D1 is settled.
KIT_SELECT = """
  SELECT
    k.id,
    k.title,
    k.title              AS title_km,
    k.description,
    k.subject,
    k.icon,
    k.accent_color       AS accent,
    k.status,
    k.progress_percent   AS progress,
    k.folder_id,
    k.last_studied_at,
    k.created_at,
    k.updated_at,
    (SELECT count(*) FROM flashcards f WHERE f.study_kit_id = k.id)::int AS card_count,
    (SELECT count(*) FROM kit_sources s WHERE s.study_kit_id = k.id)::int AS file_count,
    (SELECT s.kind FROM kit_sources s
      WHERE s.study_kit_id = k.id
      ORDER BY s.created_at ASC, s.id ASC
      LIMIT 1) AS source_kind
  FROM study_kits k
"""


def list_for_user(*, user_id, status=None, q=None):
    """Searched with pg_trgm similarity + ILIKE, never to_tsvector (Khmer has no word spaces)."""
    return query(
        f"""{KIT_SELECT}
            WHERE k.user_id = $1
              AND ($2::text IS NULL OR k.status = $2)
              AND (
                $3::text IS NULL
                OR k.title ILIKE '%' || $3 || '%'
                OR similarity(k.title, $3) > 0.15
              )
            ORDER BY k.last_studied_at DESC NULLS LAST, k.created_at DESC""",
        [user_id, status, q],
    ).rows


def find_by_id(*, user_id, kit_id):
    return query_one(f"{KIT_SELECT} WHERE k.id = $1 AND k.user_id = $2", [kit_id, user_id])


def count_for_user(user_id, tx=None):
    """Personal kits only — a kit shared into a class is exempt from the cap."""
    sql = "SELECT count(*)::int AS count FROM study_kits WHERE user_id = $1 AND class_id IS NULL"
    row = tx.query_one(sql, [user_id]) if tx else query_one(sql, [user_id])
    return row["count"]


def create(tx, *, user_id, title, folder_id, icon, accent, description, subject):
    return tx.query_one(
        """INSERT INTO study_kits (user_id, folder_id, title, description, subject, icon, accent_color)
           VALUES ($1, $2, $3, $4, $5, $6, $7)
           RETURNING id""",
        [user_id, folder_id, title, description, subject, icon, accent],
    )["id"]


def update(*, user_id, kit_id, patch):
    """COALESCE keeps omitted fields; folderId is explicitly nullable ("move to no folder")."""
    return query_one(
        """UPDATE study_kits SET
             title            = COALESCE($3, title),
             description      = COALESCE($4, description),
             subject          = COALESCE($5, subject),
             icon             = COALESCE($6, icon),
             accent_color     = COALESCE($7, accent_color),
             status           = COALESCE($8, status),
             progress_percent = COALESCE($9, progress_percent),
             folder_id        = CASE WHEN $10::boolean THEN $11::uuid ELSE folder_id END
           WHERE id = $1 AND user_id = $2
           RETURNING id""",
        [
            kit_id, user_id,
            patch.get("title"), patch.get("description"), patch.get("subject"),
            patch.get("icon"), patch.get("accent"), patch.get("status"), patch.get("progress"),
            "folderId" in patch, patch.get("folderId"),
        ],
    )


def delete_returning_paths(tx, *, user_id, kit_id):
    """Storage paths of everything the cascade is about to remove, or None when not owned."""
    owned = tx.rows("SELECT id FROM study_kits WHERE id = $1 AND user_id = $2", [kit_id, user_id])
    if not owned:
        return None
    paths = tx.rows(
        "SELECT storage_path FROM kit_sources WHERE study_kit_id = $1 AND storage_path IS NOT NULL", [kit_id]
    )
    tx.query("DELETE FROM study_kits WHERE id = $1 AND user_id = $2", [kit_id, user_id])
    return [row["storage_path"] for row in paths]

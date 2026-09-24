"""SQL for ``study_folders``.

No screen reads folders yet (docs/API-CONTRACT.md §3); this exists so the
table has a front door.
"""

from ..extensions import query, query_one

FOLDER_SELECT = """
  SELECT
    f.id, f.name, f.color, f.icon, f.sort_order, f.created_at, f.updated_at,
    (SELECT count(*) FROM study_kits k WHERE k.folder_id = f.id) AS kit_count
  FROM study_folders f
"""


def list_for_user(user_id):
    return query(f"{FOLDER_SELECT} WHERE f.user_id = $1 ORDER BY f.sort_order ASC, f.created_at ASC", [user_id]).rows


def find_by_id(*, user_id, folder_id):
    return query_one(f"{FOLDER_SELECT} WHERE f.id = $1 AND f.user_id = $2", [folder_id, user_id])


def create(*, user_id, name, color=None, icon=None, sortOrder=None):
    return query_one(
        """INSERT INTO study_folders (user_id, name, color, icon, sort_order)
           VALUES ($1, $2, $3, $4, COALESCE($5, 0))
           RETURNING id""",
        [user_id, name, color, icon, sortOrder],
    )


def update(*, user_id, folder_id, patch):
    return query_one(
        """UPDATE study_folders SET
             name       = COALESCE($3, name),
             color      = COALESCE($4, color),
             icon       = COALESCE($5, icon),
             sort_order = COALESCE($6, sort_order)
           WHERE id = $1 AND user_id = $2
           RETURNING id""",
        [folder_id, user_id, patch.get("name"), patch.get("color"), patch.get("icon"), patch.get("sortOrder")],
    )


def remove(*, user_id, folder_id):
    """study_kits.folder_id is ON DELETE SET NULL: deleting a folder unfiles its kits."""
    return query_one("DELETE FROM study_folders WHERE id = $1 AND user_id = $2 RETURNING id", [folder_id, user_id])

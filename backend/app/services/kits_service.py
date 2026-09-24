"""Study kits (server/src/services/kits.service.js)."""

import logging

from ..extensions import transaction
from ..middleware.errors import ApiError
from ..middleware.upload import absolute_upload_path, remove_uploaded_file
from ..models import kits as kits_db
from ..models import users as users_db
from .plans_service import plans_service

log = logging.getLogger("reanmate")

# Round-robin defaults, matching what KitsContext did client-side.
ICONS = ["document", "database", "code", "share"]
ACCENTS = ["blue", "violet", "amber", "teal"]


def to_api_kit(row):
    """One shape for every kit the API returns, so list, detail and create cannot drift."""
    return {
        "id": row["id"], "title": row["title"], "titleKm": row["title_km"], "description": row["description"],
        "subject": row["subject"], "icon": row["icon"], "accent": row["accent"], "status": row["status"],
        "progress": row["progress"], "cardCount": row["card_count"], "fileCount": row["file_count"],
        "sourceKind": row["source_kind"], "folderId": row["folder_id"], "lastStudiedAt": row["last_studied_at"],
        "createdAt": row["created_at"], "updatedAt": row["updated_at"],
    }


def list_kits(user_id, status=None, q=None):
    return [to_api_kit(row) for row in kits_db.list_for_user(user_id=user_id, status=status, q=q)]


def get(user_id, kit_id):
    row = kits_db.find_by_id(user_id=user_id, kit_id=kit_id)
    # 404 rather than 403 for someone else's kit: a 403 would confirm the id exists.
    if not row:
        raise ApiError.not_found("That study kit does not exist")
    return to_api_kit(row)


def quota(user_id):
    user = users_db.find_by_id(user_id)
    if not user:
        raise ApiError.unauthorized("That account no longer exists")
    limit = plans_service.get_limit(user_id, "max_kits")
    used = kits_db.count_for_user(user_id)
    return {"used": used, "limit": limit, "planTier": user["plan_tier"]}


def create(user_id, data):
    """The cap is counted inside the insert's write transaction."""
    user = users_db.find_by_id(user_id)
    if not user:
        raise ApiError.unauthorized("That account no longer exists")
    limit = plans_service.get_limit(user_id, "max_kits")

    # BEGIN IMMEDIATE holds the database write lock from the count to the
    # insert, so two simultaneous creates cannot both read "2 of 3".
    with transaction() as tx:
        used = kits_db.count_for_user(user_id, tx)
        plans_service.assert_capacity("max_kits", used, limit)
        kit_id = kits_db.create(
            tx, user_id=user_id, title=data["title"], folder_id=data.get("folderId"),
            description=data.get("description"), subject=data.get("subject"),
            icon=data.get("icon") or ICONS[used % len(ICONS)],
            accent=data.get("accent") or ACCENTS[used % len(ACCENTS)],
        )
    return get(user_id, kit_id)


def update(user_id, kit_id, patch):
    if not kits_db.update(user_id=user_id, kit_id=kit_id, patch=patch):
        raise ApiError.not_found("That study kit does not exist")
    return get(user_id, kit_id)


def remove(user_id, kit_id):
    """Rows first (in one transaction), then files — a disk error leaves an orphan, never a half-deleted kit."""
    with transaction() as tx:
        paths = kits_db.delete_returning_paths(tx, user_id=user_id, kit_id=kit_id)
    if paths is None:
        raise ApiError.not_found("That study kit does not exist")

    failed = []
    for storage_path in paths:
        try:
            remove_uploaded_file(absolute_upload_path(storage_path))
        except OSError as err:
            failed.append(storage_path)
            log.error("[kits] deleted the kit but could not remove %s %s", storage_path, err)
    return {"deleted": True, "filesRemoved": len(paths) - len(failed), "filesOrphaned": len(failed)}

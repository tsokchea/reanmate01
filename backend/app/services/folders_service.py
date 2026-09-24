"""Study folders (server/src/services/folders.service.js). No screen calls this yet."""

from ..middleware.errors import ApiError
from ..models import folders as folders_db


def _to_api(row):
    return {
        "id": row["id"], "name": row["name"], "color": row["color"], "icon": row["icon"],
        "sortOrder": row["sort_order"], "kitCount": row["kit_count"],
        "createdAt": row["created_at"], "updatedAt": row["updated_at"],
    }


def list_folders(user_id):
    return [_to_api(row) for row in folders_db.list_for_user(user_id)]


def get(user_id, folder_id):
    row = folders_db.find_by_id(user_id=user_id, folder_id=folder_id)
    if not row:
        raise ApiError.not_found("That folder does not exist")
    return _to_api(row)


def create(user_id, data):
    created = folders_db.create(user_id=user_id, name=data["name"], color=data.get("color"), icon=data.get("icon"),
                                sortOrder=data.get("sortOrder"))
    return get(user_id, created["id"])


def update(user_id, folder_id, patch):
    if not folders_db.update(user_id=user_id, folder_id=folder_id, patch=patch):
        raise ApiError.not_found("That folder does not exist")
    return get(user_id, folder_id)


def remove(user_id, folder_id):
    """Kits inside are unfiled, not deleted — study_kits.folder_id is SET NULL."""
    if not folders_db.remove(user_id=user_id, folder_id=folder_id):
        raise ApiError.not_found("That folder does not exist")
    return {"deleted": True}

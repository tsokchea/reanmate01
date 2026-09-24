"""SQL for ``kit_sources`` — uploaded files, YouTube links, typed topics."""

from ..extensions import query, query_one
from ..utils.serialization import dumps

SOURCE_SELECT = """
  SELECT
    s.id, s.study_kit_id, s.user_id,
    s.title              AS name,
    s.kind, s.original_filename, s.mime_type, s.byte_size, s.page_count,
    s.duration_seconds, s.source_url, s.youtube_video_id, s.thumbnail_url,
    s.extracted_text, s.status, s.error_message, s.storage_path, s.metadata,
    s.processed_at, s.created_at, s.updated_at
  FROM kit_sources s
"""

_UNSET = object()


def list_for_kit(*, user_id, kit_id):
    return query(
        f"""{SOURCE_SELECT}
            JOIN study_kits k ON k.id = s.study_kit_id
            WHERE s.study_kit_id = $1 AND k.user_id = $2
            ORDER BY s.created_at DESC, s.id DESC""",
        [kit_id, user_id],
    ).rows


def find_by_id(*, user_id, kit_id, source_id):
    return query_one(
        f"""{SOURCE_SELECT}
            JOIN study_kits k ON k.id = s.study_kit_id
            WHERE s.id = $1 AND s.study_kit_id = $2 AND k.user_id = $3""",
        [source_id, kit_id, user_id],
    )


def find_by_id_unscoped(source_id):
    return query_one(f"{SOURCE_SELECT} WHERE s.id = $1", [source_id])


def find_accessible_by_id(*, user_id, source_id):
    """The owner, or any student actively enrolled in the class the kit is shared to."""
    return query_one(
        f"""{SOURCE_SELECT}
            JOIN study_kits k ON k.id = s.study_kit_id
            WHERE s.id = $1 AND (
              k.user_id = $2 OR EXISTS (
                SELECT 1 FROM class_enrollments ce
                 WHERE ce.class_id = k.class_id AND ce.user_id = $2 AND ce.status = 'active'
              )
            )""",
        [source_id, user_id],
    )


def create(*, kit_id, user_id, kind, title, original_filename=None, storage_path=None, mime_type=None,
           byte_size=None, source_url=None, youtube_video_id=None, duration_seconds=None,
           thumbnail_url=None, metadata=None):
    return query_one(
        """INSERT INTO kit_sources
             (study_kit_id, user_id, kind, title, original_filename,
              storage_path, mime_type, byte_size, source_url,
              youtube_video_id, duration_seconds, thumbnail_url,
              status, metadata)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, 'pending', $13)
           RETURNING id""",
        [kit_id, user_id, kind, title, original_filename, storage_path, mime_type, byte_size, source_url,
         youtube_video_id, duration_seconds, thumbnail_url, dumps(metadata or {})],
    )


def update_status(source_id, *, status=None, error_message=_UNSET, page_count=None, duration_seconds=None,
                  extracted_text=None, thumbnail_url=None, stage=_UNSET, progress_percent=_UNSET, metadata=None,
                  **_ignored):
    """Updates status, progress, stage metadata and extracted metrics."""
    current = find_by_id_unscoped(source_id)
    if not current:
        return None

    merged = {**(current["metadata"] or {}), **(metadata or {})}
    if stage is not _UNSET:
        merged["stage"] = stage
    if progress_percent is not _UNSET:
        merged["progressPercent"] = progress_percent

    return query_one(
        """UPDATE kit_sources SET
             status           = COALESCE($2, status),
             error_message    = $3,
             page_count       = COALESCE($4, page_count),
             duration_seconds = COALESCE($5, duration_seconds),
             extracted_text   = COALESCE($6, extracted_text),
             thumbnail_url    = COALESCE($7, thumbnail_url),
             processed_at     = CASE WHEN $8::boolean THEN now() ELSE processed_at END,
             metadata         = $9
           WHERE id = $1
           RETURNING id""",
        [
            source_id, status,
            current["error_message"] if error_message is _UNSET else error_message,
            page_count, duration_seconds, extracted_text, thumbnail_url,
            status == "ready",
            dumps(merged),
        ],
    )


def delete_returning_path(*, user_id, kit_id, source_id):
    return query_one(
        """DELETE FROM kit_sources s
            USING study_kits k
            WHERE s.id = $1
              AND s.study_kit_id = $2
              AND k.id = s.study_kit_id
              AND k.user_id = $3
            RETURNING s.storage_path""",
        [source_id, kit_id, user_id],
    )

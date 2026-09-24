"""Kit sources: uploads, YouTube links and topics (server/src/services/sources.service.js)."""

import logging
import os

from ..ingest.youtube import extract_video_id
from ..middleware.errors import ApiError
from ..middleware.upload import absolute_upload_path, relative_upload_path, remove_uploaded_file, verify_uploaded_file
from ..models import kits as kits_db
from ..models import sources as sources_db
from ..utils.serialization import UNDEFINED
from . import ingest_service

log = logging.getLogger("reanmate")


def to_api_source(row, include_content=False):
    metadata = row["metadata"] or {}
    status = row["status"]
    stage = metadata.get("stage")
    if stage is None:
        stage = "ready" if status == "ready" else "extracting" if status == "processing" else "reading"
    progress = metadata.get("progressPercent")
    if progress is None:
        progress = 100 if status == "ready" else 50 if status == "processing" else 0
    source = {
        "id": row["id"],
        "kitId": row["study_kit_id"],
        "name": row["name"] or UNDEFINED,
        "kind": row["kind"],
        "originalFilename": row["original_filename"],
        "mimeType": row["mime_type"],
        "byteSize": None if row["byte_size"] is None else int(row["byte_size"]),
        "pageCount": row["page_count"],
        "durationSeconds": row["duration_seconds"],
        "sourceUrl": row["source_url"],
        "thumbnailUrl": row["thumbnail_url"],
        "status": status,
        "stage": stage,
        "progressPercent": progress,
        "errorMessage": row["error_message"],
    }
    if include_content:
        source["extractedText"] = row["extracted_text"]
    source["createdAt"] = row["created_at"]
    return source


def list_for_kit(user_id, kit_id):
    if not kits_db.find_by_id(user_id=user_id, kit_id=kit_id):
        raise ApiError.not_found("That study kit does not exist")
    return [to_api_source(row) for row in sources_db.list_for_kit(user_id=user_id, kit_id=kit_id)]


def get(user_id, kit_id, source_id):
    row = sources_db.find_by_id(user_id=user_id, kit_id=kit_id, source_id=source_id)
    if not row:
        raise ApiError.not_found("That file does not exist")
    return to_api_source(row, include_content=True)


def create_from_upload(user_id, kit_id, file):
    """File upload creation (PDFs, images, Office documents, text)."""
    if not file:
        raise ApiError.bad_request("No file was uploaded")
    try:
        if not kits_db.find_by_id(user_id=user_id, kit_id=kit_id):
            raise ApiError.not_found("That study kit does not exist")
        verified = verify_uploaded_file(file)  # magic-byte check
        name = os.path.basename(file["originalname"])
        inserted = sources_db.create(
            kit_id=kit_id, user_id=user_id, kind=verified["kind"], title=name, original_filename=name,
            storage_path=relative_upload_path(file["path"]), mime_type=file["mimetype"],
            byte_size=verified["byteSize"], metadata={"stage": "reading", "progressPercent": 10},
        )
        ingest_service.enqueue(inserted["id"])
        return to_api_source(sources_db.find_by_id_unscoped(inserted["id"]))
    except Exception:
        try:
            remove_uploaded_file(file["path"])
        except OSError:
            pass
        raise


def create_from_input(user_id, kit_id, data=None):
    """JSON source creation: a YouTube URL or a typed topic."""
    data = data or {}
    if not kits_db.find_by_id(user_id=user_id, kit_id=kit_id):
        raise ApiError.not_found("That study kit does not exist")

    title = (data.get("title") or "").strip()
    if data.get("kind") == "youtube":
        video_id = extract_video_id(data.get("url"))
        inserted = sources_db.create(
            kit_id=kit_id, user_id=user_id, kind="youtube", title=title or "YouTube study kit",
            source_url=data.get("url"), youtube_video_id=video_id,
            metadata={"stage": "reading", "progressPercent": 10},
        )
    elif data.get("kind") == "topic":
        inserted = sources_db.create(kit_id=kit_id, user_id=user_id, kind="topic", title=title or "Topic",
                                     metadata={"stage": "reading", "progressPercent": 10})
    else:
        raise ApiError.bad_request(f'Unsupported source kind: "{data.get("kind")}"')

    ingest_service.enqueue(inserted["id"])
    return to_api_source(sources_db.find_by_id_unscoped(inserted["id"]))


def remove(user_id, kit_id, source_id):
    row = sources_db.delete_returning_path(user_id=user_id, kit_id=kit_id, source_id=source_id)
    if not row:
        raise ApiError.not_found("That file does not exist")
    if row["storage_path"]:
        try:
            remove_uploaded_file(absolute_upload_path(row["storage_path"]))
        except OSError as err:
            log.error("[sources] deleted the row but could not remove %s %s", row["storage_path"], err)
    return {"deleted": True}

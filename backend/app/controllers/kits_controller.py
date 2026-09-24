from flask import g

from ..services import folders_service, kits_service, sources_service
from . import respond


def list_kits():
    query = g.get("query") or {}
    return respond({"kits": kits_service.list_kits(g.auth["user_id"], query.get("status"), query.get("q"))})


def create():
    return respond({"kit": kits_service.create(g.auth["user_id"], g.body)}, 201)


def show():
    kit = kits_service.get(g.auth["user_id"], g.params["kitId"])
    # fileCount is on the kit, but the contract names it alongside.
    return respond({"kit": kit, "fileCount": kit["fileCount"]})


def update():
    return respond({"kit": kits_service.update(g.auth["user_id"], g.params["kitId"], g.body)})


def destroy():
    return respond(kits_service.remove(g.auth["user_id"], g.params["kitId"]))


def quota():
    return respond(kits_service.quota(g.auth["user_id"]))


def list_sources():
    return respond({"sources": sources_service.list_for_kit(g.auth["user_id"], g.params["kitId"])})


def create_source():
    """202, not 201: the row exists but processing runs in the background."""
    kit_id = g.params["kitId"]
    if g.get("file"):
        source = sources_service.create_from_upload(g.auth["user_id"], kit_id, g.file)
    else:
        body = g.get("body")
        source = sources_service.create_from_input(g.auth["user_id"], kit_id, body if isinstance(body, dict) else {})
    return respond({"source": source}, 202)


def show_source():
    return respond({"source": sources_service.get(g.auth["user_id"], g.params["kitId"], g.params["sourceId"])})


def destroy_source():
    return respond(sources_service.remove(g.auth["user_id"], g.params["kitId"], g.params["sourceId"]))


# --- folders ------------------------------------------------------------------


def list_folders():
    return respond({"folders": folders_service.list_folders(g.auth["user_id"])})


def create_folder():
    return respond({"folder": folders_service.create(g.auth["user_id"], g.body)}, 201)


def show_folder():
    return respond({"folder": folders_service.get(g.auth["user_id"], g.params["folderId"])})


def update_folder():
    return respond({"folder": folders_service.update(g.auth["user_id"], g.params["folderId"], g.body)})


def destroy_folder():
    return respond(folders_service.remove(g.auth["user_id"], g.params["folderId"]))

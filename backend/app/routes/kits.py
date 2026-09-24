"""Study kits, their sources (files, YouTube, topics) and folders.

Ownership is enforced in SQL (app/models/kits.py), not by a check the next
query could forget. Params are validated before the upload is written, so a
bad kit id is rejected without touching the disk.
"""

from flask import Blueprint

from ..controllers import kits_controller as kits
from ..middleware.upload import handle_upload
from ..middleware.validate import validate_body, validate_params, validate_query
from ..validation import schemas as s
from . import AUTH, add, validate_source_body

bp = Blueprint("kits", __name__, url_prefix="/api")

KIT = validate_params(s.kit_id_params)
SOURCE = validate_params(s.source_id_params)
FOLDER = validate_params(s.folder_id_params)

add(bp, "GET", "/kits", kits.list_kits, AUTH, validate_query(s.kit_list_query))
add(bp, "POST", "/kits", kits.create, AUTH, validate_body(s.create_kit_schema))
add(bp, "GET", "/kits/quota", kits.quota, AUTH)
add(bp, "GET", "/kits/<kitId>", kits.show, AUTH, KIT)
add(bp, "PATCH", "/kits/<kitId>", kits.update, AUTH, KIT, validate_body(s.update_kit_schema))
add(bp, "DELETE", "/kits/<kitId>", kits.destroy, AUTH, KIT)

# "sources" and "files" are aliases for the same resource.
for collection in ("sources", "files"):
    add(bp, "GET", f"/kits/<kitId>/{collection}", kits.list_sources, AUTH, KIT)
    add(bp, "POST", f"/kits/<kitId>/{collection}", kits.create_source, AUTH, KIT, handle_upload,
        validate_source_body(s.create_source_schema))
    add(bp, "GET", f"/kits/<kitId>/{collection}/<sourceId>", kits.show_source, AUTH, SOURCE)
    add(bp, "DELETE", f"/kits/<kitId>/{collection}/<sourceId>", kits.destroy_source, AUTH, SOURCE)

add(bp, "GET", "/folders", kits.list_folders, AUTH)
add(bp, "POST", "/folders", kits.create_folder, AUTH, validate_body(s.create_folder_schema))
add(bp, "GET", "/folders/<folderId>", kits.show_folder, AUTH, FOLDER)
add(bp, "PATCH", "/folders/<folderId>", kits.update_folder, AUTH, FOLDER, validate_body(s.update_folder_schema))
add(bp, "DELETE", "/folders/<folderId>", kits.destroy_folder, AUTH, FOLDER)

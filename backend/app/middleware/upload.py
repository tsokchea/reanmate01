"""File uploads: local disk, relative path in the database.

The port of server/src/middleware/upload.js (multer). PDFs, images, Office
documents and plain text. Three checks, because the first two are cheap and
the third is the only honest one:

  1. mimetype   — the browser's Content-Type. Client-supplied, so advisory.
  2. extension  — also client-supplied, but catches the ordinary mistake.
  3. magic bytes — read off disk after the write, and the only check a
                   deliberately mislabelled file cannot walk past.

Every rejection after the write unlinks the file.
"""

import logging
import os
import shutil
import uuid

from flask import g, request

from ..config import config
from .errors import ApiError

log = logging.getLogger("reanmate")

# The local file header every ZIP, and so every OOXML file, starts with.
ZIP_MAGIC = bytes([0x50, 0x4B, 0x03, 0x04])

# Extensions and signatures we accept, keyed by the mime type we store.
ACCEPTED = {
    "application/pdf": {"kind": "pdf", "extensions": [".pdf"], "magic": [b"%PDF"]},
    "image/jpeg": {"kind": "image", "extensions": [".jpg", ".jpeg"], "magic": [bytes([0xFF, 0xD8, 0xFF])]},
    "image/png": {"kind": "image", "extensions": [".png"], "magic": [bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])]},
    # RIFF....WEBP — bytes 8-11 carry the format, so this one is checked below.
    "image/webp": {"kind": "image", "extensions": [".webp"], "magic": [b"RIFF"]},
    # Word, Excel and PowerPoint are all ZIP containers: magic bytes prove
    # "this is a zip" (catching a renamed .exe) but cannot tell them apart.
    # The extractor identifies the package by its contents instead.
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {
        "kind": "document", "extensions": [".docx"], "magic": [ZIP_MAGIC]},
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {
        "kind": "document", "extensions": [".xlsx"], "magic": [ZIP_MAGIC]},
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": {
        "kind": "document", "extensions": [".pptx"], "magic": [ZIP_MAGIC]},
    # Plain text has no signature — any byte sequence is a legal text file.
    # `magic: []` says that explicitly rather than reading as an oversight.
    "text/plain": {"kind": "document", "extensions": [".txt", ".text"], "magic": []},
    "text/markdown": {"kind": "document", "extensions": [".md", ".markdown"], "magic": []},
    "text/csv": {"kind": "document", "extensions": [".csv"], "magic": []},
}

# Formats a student is likely to try, that this app cannot read, and what to
# tell them instead. Keyed by extension because that is what a student
# recognises, and because browsers disagree about the mime type of a .doc.
LEGACY_FORMAT_ADVICE = {
    ".doc": {"convertTo": ".docx", "advice": "Open it in Word and choose File → Save As → Word Document (.docx)."},
    ".xls": {"convertTo": ".xlsx", "advice": "Open it in Excel and choose File → Save As → Excel Workbook (.xlsx)."},
    ".ppt": {"convertTo": ".pptx", "advice": "Open it in PowerPoint and choose File → Save As → PowerPoint Presentation (.pptx)."},
    ".pages": {"convertTo": ".docx", "advice": "Open it in Pages and choose File → Export To → Word (.docx)."},
    ".numbers": {"convertTo": ".xlsx", "advice": "Open it in Numbers and choose File → Export To → Excel (.xlsx)."},
    ".key": {"convertTo": ".pptx", "advice": "Open it in Keynote and choose File → Export To → PowerPoint (.pptx)."},
    ".odt": {"convertTo": ".docx", "advice": "Open it and choose File → Save As → Word Document (.docx)."},
    ".ods": {"convertTo": ".xlsx", "advice": "Open it and choose File → Save As → Excel Workbook (.xlsx)."},
    ".odp": {"convertTo": ".pptx", "advice": "Open it and choose File → Save As → PowerPoint Presentation (.pptx)."},
    ".rtf": {"convertTo": ".docx", "advice": "Open it in Word and choose File → Save As → Word Document (.docx)."},
}

ACCEPTED_MIME_TYPES = list(ACCEPTED.keys())

# Absolute root every upload must stay inside. A relative UPLOAD_DIR resolves
# against the backend directory, not the shell's working directory, so the
# server finds its files however it was started.
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
upload_root = os.path.realpath(os.path.join(_BACKEND_ROOT, config.UPLOAD_DIR))


def _extname(name):
    """node:path extname — '' for dotfiles and names without a dot."""
    base = os.path.basename(name or "")
    index = base.rfind(".")
    return base[index:].lower() if index > 0 else ""


def relative_upload_path(absolute_path):
    """kit_sources.storage_path is stored RELATIVE to upload_root, with POSIX separators."""
    target = os.path.realpath(absolute_path)
    if not target.startswith(upload_root + os.sep):
        raise RuntimeError(f"Upload landed outside the upload root: {target}")
    return target[len(upload_root) + 1:].replace(os.sep, "/")


def absolute_upload_path(storage_path):
    return os.path.join(upload_root, *storage_path.split("/"))


def file_filter(originalname, mimetype):
    """Raises the 415 a student sees for a file this app cannot read."""
    ext = _extname(originalname)
    accepted = ACCEPTED.get(mimetype)

    if not accepted:
        legacy = LEGACY_FORMAT_ADVICE.get(ext)
        if legacy:
            raise ApiError(415, "unsupported_file_type", f"ReanMate cannot read {ext} files. {legacy['advice']}",
                           {"received": ext, "convertTo": legacy["convertTo"]})
        raise ApiError(415, "unsupported_file_type",
                       "You can upload a PDF, a photo, a Word, Excel or PowerPoint file, or a text file",
                       {"received": mimetype, "accepted": ACCEPTED_MIME_TYPES})

    if ext not in accepted["extensions"]:
        raise ApiError(415, "unsupported_file_type",
                       f"A {mimetype} upload must be named {' or '.join(accepted['extensions'])}",
                       {"received": ext or "(none)", "accepted": accepted["extensions"]})


def remove_uploaded_file(absolute_path):
    """Removes a file, refusing any path that escapes the upload root."""
    if not absolute_path:
        return
    target = os.path.realpath(absolute_path)
    if target != upload_root and not target.startswith(upload_root + os.sep):
        log.error("[upload] refusing to delete outside the upload root: %s", target)
        return
    if os.path.isdir(target):
        shutil.rmtree(target, ignore_errors=True)
    elif os.path.exists(target):
        os.remove(target)


def verify_uploaded_file(file):
    """Confirms the bytes on disk match the claimed type. Raises (after unlinking) when not.

    Returns ``{"kind", "byteSize"}`` — kind is a legal kit_sources.kind value.
    """
    accepted = ACCEPTED[file["mimetype"]]
    size = os.path.getsize(file["path"])
    if size == 0:
        remove_uploaded_file(file["path"])
        raise ApiError.bad_request("That file is empty")
    if size > config.MAX_UPLOAD_BYTES:
        remove_uploaded_file(file["path"])
        raise ApiError(413, "file_too_large", "That file is too large",
                       {"byteSize": size, "limit": config.MAX_UPLOAD_BYTES})

    with open(file["path"], "rb") as handle:
        header = handle.read(12)

    # An empty signature list means "no signature" (plain text), not "nothing
    # matched" — any() over an empty list is False and would reject every .txt.
    matches = not accepted["magic"] or any(header.startswith(sig) for sig in accepted["magic"])
    # WEBP is RIFF with the format tag at bytes 8-11; RIFF alone is also WAV/AVI.
    webp_ok = file["mimetype"] != "image/webp" or header[8:12] == b"WEBP"
    # A NUL byte in the first block means this is not text, whatever its name.
    text_ok = bool(accepted["magic"]) or b"\x00" not in header

    if not (matches and webp_ok and text_ok):
        remove_uploaded_file(file["path"])
        raise ApiError(415, "unsupported_file_type", "That file is not the type its name and Content-Type claim",
                       {"declared": file["mimetype"]})

    return {"kind": accepted["kind"], "byteSize": size}


def _save(storage, user_id):
    """Streams one part to <upload_root>/<userId>/<uuid><ext>, enforcing the size limit."""
    directory = os.path.join(upload_root, user_id)
    os.makedirs(directory, exist_ok=True)
    ext = _extname(storage.filename)
    safe_ext = ext if ext in ACCEPTED[storage.mimetype]["extensions"] else ""
    path = os.path.join(directory, f"{uuid.uuid4()}{safe_ext}")

    written = 0
    with open(path, "wb") as out:
        while True:
            chunk = storage.stream.read(64 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > config.MAX_UPLOAD_BYTES:
                out.close()
                remove_uploaded_file(path)
                raise ApiError(413, "file_too_large", "That file is too large", {"limit": config.MAX_UPLOAD_BYTES})
            out.write(chunk)
    return {"originalname": storage.filename, "mimetype": storage.mimetype, "path": path, "size": written}


def handle_upload():
    """Single-file upload under the field name ``file`` (multer ``.single('file')``).

    Non-multipart requests pass straight through, exactly as before, so JSON
    and upload share one route.
    """
    g.file = None
    if request.mimetype != "multipart/form-data":
        return

    parts = [(field, storage) for field, storage in request.files.items(multi=True) if storage.filename]
    if any(field != "file" for field, _ in parts) or len(parts) > 1:
        raise ApiError.bad_request('Upload one file at a time, in a field named "file"')

    # Text fields arrive as the body, as multer populated req.body.
    g.body = request.form.to_dict()

    if not parts:
        return
    storage = parts[0][1]
    file_filter(storage.filename, storage.mimetype)
    g.file = _save(storage, g.auth["user_id"])

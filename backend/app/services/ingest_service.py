"""The ingest pipeline (server/src/services/ingest.service.js).

1. Text extraction with citation preservation (PDF page, slide/sheet/section,
   YouTube timestamp), vision OCR for photos, an OOXML reader for Office files
2. Free-plan limits (50 pages/slides/sheets; 30-minute videos)
3. Token-aware chunking (~500 tokens with overlap)
4. Batched embeddings, recorded in ai_generations
5. Vector persistence in document_chunks
6. The study materials a student can open straight afterwards
"""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from ..extensions import transaction
from ..ingest.chunker import chunk_document_sections, chunk_pdf_pages, chunk_text, chunk_youtube_transcript
from ..ingest.errors import INGEST_ERROR_CODES, IngestError
from ..ingest.office import extract_document
from ..ingest.pdf import extract_pdf
from ..ingest.youtube import ingest_youtube
from ..jobs import queue as job_queue
from ..middleware.upload import absolute_upload_path
from ..models import chunks as chunks_db
from ..models import sources as sources_db
from ..models import users as users_db
from . import flashcards_service, mock_exam_service, quiz_service, study_guide_service, summaries_service
from .ai_usage_service import detect_cost_language, track_generation

log = logging.getLogger("reanmate")

# The generations a source is not "ready" without. Running them here moves the
# wait into the progress bar the student is already watching. ``percent`` is
# reported before the step runs, so the bar moves with the work.
STUDY_MATERIALS = [
    {"name": "study guide", "run": lambda c: study_guide_service.prewarm(c["sourceId"], c["language"])},
    {"name": "summary", "run": lambda c: summaries_service.prewarm(c["sourceId"], c["language"])},
    {"name": "quiz", "run": lambda c: quiz_service.prewarm(c["userId"], c["sourceId"], c["language"])},
    {"name": "mock exam", "run": lambda c: mock_exam_service.prewarm(c["sourceId"], c["language"])},
    {"name": "flashcards", "run": lambda c: flashcards_service.prewarm(c["userId"], c["sourceId"], c["language"])},
]

# Progress while generating: 65% at the start, climbing evenly to 90% as each
# material lands (the last 10% is marking the source ready).
GENERATING_START_PERCENT = 65
GENERATING_END_PERCENT = 90


def _generate_study_materials(context):
    """Every material is generated at once, so ingest waits for the slowest one
    rather than the sum of all five. A failed generation is logged and stepped
    over; the screen that needs it generates on demand."""
    source_id = context["sourceId"]
    sources_db.update_status(source_id, stage="generating", progress_percent=GENERATING_START_PERCENT)
    done = 0
    lock = threading.Lock()

    def run(step):
        nonlocal done
        try:
            step["run"](context)
        except Exception as err:
            log.error("[ingest] source %s: %s generation failed: %s", source_id, step["name"], err)
        with lock:
            done += 1
            span = GENERATING_END_PERCENT - GENERATING_START_PERCENT
            percent = GENERATING_START_PERCENT + span * done // len(STUDY_MATERIALS)
            sources_db.update_status(source_id, stage="generating", progress_percent=percent)

    with ThreadPoolExecutor(max_workers=len(STUDY_MATERIALS)) as pool:
        list(pool.map(run, STUDY_MATERIALS))


def enqueue(source_id):
    job_queue.enqueue("source:ingest", {"sourceId": source_id})


def _extract(source, plan_tier):
    kind = source["kind"]
    if kind == "pdf":
        if not source["storage_path"]:
            raise IngestError(INGEST_ERROR_CODES["EXTRACT_FAILED"], "File path is missing for PDF")
        extracted = extract_pdf(absolute_upload_path(source["storage_path"]), plan_tier=plan_tier)
        return chunk_pdf_pages(extracted["pages"]), {"page_count": extracted["pageCount"],
                                                    "extracted_text": extracted["fullText"][:5000]}

    if kind == "youtube":
        url_or_id = source["source_url"] or source["youtube_video_id"]
        if not url_or_id:
            raise IngestError(INGEST_ERROR_CODES["INVALID_URL"], "YouTube URL is missing")
        video = ingest_youtube(url_or_id, plan_tier=plan_tier)
        return chunk_youtube_transcript(video["cues"]), {
            # Kept for parity with the Node pipeline; update_status has no title column to write.
            "title": video["title"] if source["name"] in ("YouTube study kit", None, "") else source["name"],
            "duration_seconds": video["durationSeconds"],
            "thumbnail_url": video["thumbnailUrl"],
            "extracted_text": video["fullText"][:5000],
        }

    if kind == "document":
        if not source["storage_path"]:
            raise IngestError(INGEST_ERROR_CODES["EXTRACT_FAILED"], "File path is missing for document")
        doc = extract_document(absolute_upload_path(source["storage_path"]), mime_type=source["mime_type"],
                               plan_tier=plan_tier)
        # Recorded under page_count: a slide count and a page count answer the same question.
        return chunk_document_sections(doc["sections"], unit=doc["unit"], format=doc["format"]), {
            "page_count": doc["sectionCount"], "extracted_text": doc["fullText"][:5000]}

    if kind in ("topic", "text"):
        text = source["extracted_text"] or source["name"] or ""
        return chunk_text(text, kind=kind), {"extracted_text": text[:5000]}

    if kind == "image":
        if not source["storage_path"]:
            raise IngestError(INGEST_ERROR_CODES["EXTRACT_FAILED"], "File path is missing for image")
        label = source["original_filename"] or source["name"] or "Image material"
        try:
            with open(absolute_upload_path(source["storage_path"]), "rb") as handle:
                data = handle.read()
        except OSError as err:
            raise IngestError(INGEST_ERROR_CODES["EXTRACT_FAILED"], f"Could not read the uploaded image: {err}") from err
        if not data:
            raise IngestError(INGEST_ERROR_CODES["EXTRACT_FAILED"], "This image file is empty. Please upload it again.")

        # Labelled from the OUTPUT: a photo's language is unknowable before it is read.
        extracted = track_generation(
            kind="ocr", user_id=source["user_id"], study_kit_id=source["study_kit_id"], source_id=source["id"],
            language=None, source_text=None, request={"mimeType": source["mime_type"], "bytes": len(data)},
            describe=lambda v: {"hasText": v["hasText"], "chars": len(v["text"])},
            run=lambda ai, on_usage: ai.extract_image_text(
                images=[{"data": data, "mimeType": source["mime_type"] or "image/jpeg", "name": label}],
                on_usage=on_usage),
        )
        if not extracted["hasText"]:
            description = extracted["description"]
            looks_like = f"{description[0].lower()}{description[1:]}" if description else ""
            message = " ".join(part for part in [
                "No readable text was found in this photo.",
                f"It looks like {looks_like[:-1] if looks_like.endswith('.') else looks_like}." if looks_like else "",
                "Try a straight-on, well-lit shot of the page.",
            ] if part)
            raise IngestError(INGEST_ERROR_CODES["EMPTY_CONTENT"], message)

        # The description rides along: on a diagram it is the only account of what it shows.
        text = f"{extracted['description']}\n\n{extracted['text']}" if extracted["description"] else extracted["text"]
        return chunk_text(text, kind="image"), {"extracted_text": text[:5000]}

    return [], {}


def process_source(source_id):
    source = sources_db.find_by_id_unscoped(source_id)
    if not source:
        log.warning('[ingest] source "%s" not found, skipping', source_id)
        return
    user = users_db.find_by_id(source["user_id"])
    plan_tier = (user or {}).get("plan_tier") or "free"

    try:
        sources_db.update_status(source_id, status="processing", stage="extracting", progress_percent=20,
                                 error_message=None)
        chunks, metrics = _extract(source, plan_tier)
        if not chunks:
            raise IngestError(INGEST_ERROR_CODES["EMPTY_CONTENT"],
                              "No readable content could be found in this material.")

        sources_db.update_status(source_id, stage="embedding", progress_percent=60, **metrics)

        texts = [chunk["content"] for chunk in chunks]
        joined = "\n".join(texts)
        # Embedding a whole document is the biggest token spend in the product.
        embedded = track_generation(
            kind="embedding", user_id=source["user_id"], study_kit_id=source["study_kit_id"], source_id=source_id,
            language=detect_cost_language(joined), source_text=joined, request={"chunks": len(texts)},
            describe=lambda v: {"vectors": len(v.get("embeddings") or []), "dimensions": v.get("dimensions")},
            run=lambda ai, on_usage: ai.embed(texts=texts, on_usage=on_usage),
        )
        with_embeddings = [{**chunk, "embedding": embedded["embeddings"][i]} for i, chunk in enumerate(chunks)]

        with transaction() as tx:
            chunks_db.delete_for_source(tx, source_id=source_id)
            chunks_db.insert_batch(tx, source_id=source_id, study_kit_id=source["study_kit_id"], chunks=with_embeddings)

        # The summary of a Khmer page should be Khmer whoever uploaded it.
        _generate_study_materials({"sourceId": source_id, "userId": source["user_id"],
                                   "language": detect_cost_language(joined)})

        sources_db.update_status(source_id, status="ready", stage="ready", progress_percent=100, error_message=None,
                                 metadata={"chunkCount": len(chunks), "stage": "ready", "progressPercent": 100})
        log.info("[ingest] source %s (%s) successfully processed into %d chunks", source_id, source["kind"], len(chunks))
    except Exception as err:
        message = getattr(err, "message", None) or str(err)
        log.error("[ingest] source %s failed: %s", source_id, message)
        sources_db.update_status(source_id, status="failed", error_message=message, stage="failed",
                                 progress_percent=0,
                                 metadata={"stage": "failed", "errorCode": getattr(err, "code", None) or "unknown"})


job_queue.register("source:ingest", lambda payload: process_source(payload["sourceId"]))

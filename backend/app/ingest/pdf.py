"""Page-by-page PDF text extraction (server/src/ingest/pdf.js).

The Node server used pdf-parse (pdf.js); this uses pypdf. Both return text per
page with page numbers intact, which is what citations depend on. Whitespace
and line breaks inside a page can differ slightly between the two libraries —
the chunker normalises sentence boundaries, so retrieval is unaffected.
"""

import io
import logging

from pypdf import PdfReader

from .errors import INGEST_ERROR_CODES, IngestError

logging.getLogger("pypdf").setLevel(logging.ERROR)

FREE_PDF_PAGE_LIMIT = 50


def extract_pdf(source, plan_tier="free"):
    if isinstance(source, (bytes, bytearray)):
        data = bytes(source)
    else:
        with open(source, "rb") as handle:
            data = handle.read()

    # The page count comes from the document structure, so an over-limit PDF
    # is rejected before paying to extract text from every page.
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            reader.decrypt("")
        page_count = len(reader.pages)
    except Exception as err:
        raise IngestError(INGEST_ERROR_CODES["EXTRACT_FAILED"], f"Could not extract text from PDF: {err}") from err

    if plan_tier != "plus" and page_count > FREE_PDF_PAGE_LIMIT:
        raise IngestError(
            INGEST_ERROR_CODES["PAGE_LIMIT_EXCEEDED"],
            f"Free plan allows up to {FREE_PDF_PAGE_LIMIT} pages per PDF (this document has {page_count} pages). "
            "Please upgrade to Plus for larger documents.",
            {"pageCount": page_count, "limit": FREE_PDF_PAGE_LIMIT},
        )

    try:
        pages = [
            {"pageNumber": number, "text": (page.extract_text() or "").strip()}
            for number, page in enumerate(reader.pages, start=1)
        ]
    except Exception as err:
        raise IngestError(INGEST_ERROR_CODES["EXTRACT_FAILED"], f"Could not extract text from PDF: {err}") from err

    # Image-only pages contribute nothing and would just pad the joins.
    full_text = "\n\n".join(page["text"] for page in pages if page["text"]).strip()
    if not full_text:
        raise IngestError(INGEST_ERROR_CODES["EMPTY_CONTENT"], "No readable text could be found in this PDF document.")

    return {"pageCount": page_count or len(pages), "pages": pages, "fullText": full_text}

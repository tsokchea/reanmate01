"""Ingest errors and taxonomy classification (server/src/ingest/errors.js).

Each failure has a distinct user-facing message and a machine-readable code;
the code is stored in kit_sources.metadata.errorCode and read by the client.
"""

INGEST_ERROR_CODES = {
    "NO_CAPTIONS": "no_captions",
    "AGE_RESTRICTED": "age_restricted",
    "REGION_BLOCKED": "region_blocked",
    "RATE_LIMITED": "rate_limited",
    "VIDEO_UNAVAILABLE": "video_unavailable",
    "LIVE_STREAM": "live_stream",
    "DURATION_LIMIT_EXCEEDED": "duration_limit_exceeded",
    "PAGE_LIMIT_EXCEEDED": "page_limit_exceeded",
    "INVALID_URL": "invalid_url",
    "EXTRACT_FAILED": "extract_failed",
    "EMPTY_CONTENT": "empty_content",
}

INGEST_MESSAGES = {
    "no_captions": "This video does not have captions or a transcript available.",
    "age_restricted": "This video is age-restricted and cannot be transcribed.",
    "region_blocked": "This video is not available in the server’s region.",
    "rate_limited": "YouTube is temporarily rate-limiting requests. Please try again in a few minutes.",
    "video_unavailable": "This video is unavailable, private, or has been removed.",
    "live_stream": "Live streams cannot be transcribed until the stream concludes.",
    "duration_limit_exceeded": "Free plan allows videos up to 30 minutes. Please upgrade to Plus for longer videos.",
    "page_limit_exceeded": "Free plan allows up to 50 pages per PDF. Please upgrade to Plus for larger documents.",
    "invalid_url": "Please enter a valid YouTube video URL.",
    "extract_failed": "We could not extract readable text from this material.",
    "empty_content": "No readable text could be found in this document.",
}


class IngestError(Exception):
    def __init__(self, code, custom_message=None, details=None):
        message = custom_message or INGEST_MESSAGES.get(code) or "Ingest processing failed"
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

"""Lets a single request choose its reply language without changing the UI language."""

import re

_KHMER_SCRIPT = re.compile("[ក-៿᧠-᧿]")
_KHMER_REQUEST = re.compile(
    r"(?:\b(?:in|into|using|use|speak|answer|explain|translate|respond|reply|write)\b[\s\S]{0,40}\b(?:khmer|cambodian)\b"
    r"|\b(?:khmer|cambodian)\b[\s\S]{0,40}\b(?:explain|answer|respond|reply|translate|write)\b)",
    re.IGNORECASE,
)


def detect_requested_reply_language(text, fallback="en"):
    value = str(text if text is not None else "")
    if _KHMER_SCRIPT.search(value) or _KHMER_REQUEST.search(value) or "ខ្មែរ" in value:
        return "km"
    return fallback

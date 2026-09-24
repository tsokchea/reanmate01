"""Token-aware text chunking with citation preservation (server/src/ingest/chunker.js).

~500 tokens per chunk with ~60 tokens of overlap; keeps page_number for
documents and start/end seconds for transcripts; contiguous chunk_index.
"""

import math
import re

from ..utils.js import js_round

TARGET_CHUNK_TOKENS = 500
OVERLAP_TOKENS = 60

_KHMER = re.compile(r"[ក-៿᧠-᧿]")
_SENTENCE_BREAK = re.compile(r"(?<=[.!?។៕\n])\s+")


def estimate_tokens(text):
    """Latin ~4 chars/token; Khmer (dense, no word spaces) ~1.6 chars/token."""
    if not text:
        return 0
    value = str(text)
    khmer = len(_KHMER.findall(value))
    other = len(value) - khmer
    return max(1, math.ceil(khmer / 1.6) + math.ceil(other / 4.0))


def _split_sentences(text):
    """Splits on paragraph breaks and Western/Khmer sentence terminators."""
    if not text:
        return []
    return [part.strip() for part in _SENTENCE_BREAK.split(text) if part.strip()]


def _chunk_sentence_list(sentences, initial_overlap=""):
    chunks = []
    parts = [initial_overlap] if initial_overlap else []
    tokens = estimate_tokens(initial_overlap) if initial_overlap else 0

    for sentence in sentences:
        sentence_tokens = estimate_tokens(sentence)
        if tokens + sentence_tokens > TARGET_CHUNK_TOKENS and parts:
            chunks.append({"text": " ".join(parts), "tokens": tokens})

            # Overlap: the last few sentences totalling ~OVERLAP_TOKENS.
            overlap, overlap_tokens = [], 0
            for part in reversed(parts):
                part_tokens = estimate_tokens(part)
                if overlap_tokens + part_tokens <= OVERLAP_TOKENS or not overlap:
                    overlap.insert(0, part)
                    overlap_tokens += part_tokens
                else:
                    break
            parts = [*overlap, sentence]
            tokens = overlap_tokens + sentence_tokens
        else:
            parts.append(sentence)
            tokens += sentence_tokens

    if parts:
        text = " ".join(parts)
        if not chunks or chunks[-1]["text"] != text:
            chunks.append({"text": text, "tokens": tokens})
    return chunks


def chunk_pdf_pages(pages=None):
    result = []
    for page in pages or []:
        if not page.get("text") or not page["text"].strip():
            continue
        sentences = _split_sentences(page["text"])
        if not sentences:
            continue
        for chunk in _chunk_sentence_list(sentences):
            result.append({
                "chunkIndex": len(result),
                "content": chunk["text"],
                "tokenCount": chunk["tokens"],
                "pageNumber": page["pageNumber"],
                "startSeconds": None,
                "endSeconds": None,
                "metadata": {"kind": "pdf", "pageNumber": page["pageNumber"]},
            })
    return result


def chunk_document_sections(sections=None, unit="section", format="document"):
    """Chunks slides, sheets or sections; the part number rides in page_number and metadata."""
    result = []
    for section in sections or []:
        if not section.get("text") or not section["text"].strip():
            continue
        sentences = _split_sentences(section["text"])
        if not sentences:
            continue
        for chunk in _chunk_sentence_list(sentences):
            metadata = {"kind": format, "unit": unit, "pageNumber": section["number"]}
            if section.get("title"):
                metadata["sectionTitle"] = section["title"]
            result.append({
                "chunkIndex": len(result),
                "content": chunk["text"],
                "tokenCount": chunk["tokens"],
                "pageNumber": section["number"],
                "startSeconds": None,
                "endSeconds": None,
                "metadata": metadata,
            })
    return result


def chunk_youtube_transcript(cues=None):
    result = []
    if not cues:
        return result

    def flush(batch):
        if not batch:
            return
        text = " ".join(c["text"] for c in batch)
        start = js_round(batch[0]["startSeconds"])
        end = js_round(batch[-1]["startSeconds"] + (batch[-1].get("durationSeconds") or 0))
        result.append({
            "chunkIndex": len(result),
            "content": text,
            "tokenCount": estimate_tokens(text),
            "pageNumber": None,
            "startSeconds": start,
            "endSeconds": end,
            "metadata": {"kind": "youtube", "startSeconds": start, "endSeconds": end},
        })

    current, tokens = [], 0
    for cue in cues:
        cue_tokens = estimate_tokens(cue["text"])
        if tokens + cue_tokens > TARGET_CHUNK_TOKENS and current:
            flush(current)
            overlap, overlap_tokens = [], 0
            for previous in reversed(current):
                previous_tokens = estimate_tokens(previous["text"])
                if overlap_tokens + previous_tokens <= OVERLAP_TOKENS or not overlap:
                    overlap.insert(0, previous)
                    overlap_tokens += previous_tokens
                else:
                    break
            current = [*overlap, cue]
            tokens = overlap_tokens + cue_tokens
        else:
            current.append(cue)
            tokens += cue_tokens

    flush(current)
    return result


def chunk_text(text, kind="text", page_number=None):
    return [
        {
            "chunkIndex": index,
            "content": chunk["text"],
            "tokenCount": chunk["tokens"],
            "pageNumber": page_number,
            "startSeconds": None,
            "endSeconds": None,
            "metadata": {"kind": kind},
        }
        for index, chunk in enumerate(_chunk_sentence_list(_split_sentences(text)))
    ]

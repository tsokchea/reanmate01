"""YouTube transcript ingest via the InnerTube player (server/src/ingest/youtube.js).

Do NOT go back to scraping the watch page: its caption URLs now return an
empty 200 without a proof-of-origin token, which looks exactly like a video
with no captions. The Android player client is not held to that check.
"""

import json
import re
from urllib.parse import parse_qs, urlsplit

import httpx

from ..utils.js import js_round, parse_float, parse_int
from .errors import INGEST_ERROR_CODES, IngestError

FREE_VIDEO_DURATION_LIMIT_SECONDS = 1800  # 30 minutes

_VIDEO_ID = re.compile(r"^[a-zA-Z0-9_-]{11}$")

INNERTUBE_CLIENT = {"clientName": "ANDROID", "clientVersion": "20.10.38", "androidSdkVersion": 30}
INNERTUBE_USER_AGENT = f"com.google.android.youtube/{INNERTUBE_CLIENT['clientVersion']} (Linux; U; Android 11) gzip"


def extract_video_id(url):
    """Reads the 11-character id from every URL shape the app accepts."""
    if not url or not isinstance(url, str):
        raise IngestError(INGEST_ERROR_CODES["INVALID_URL"])

    trimmed = url.strip()
    if _VIDEO_ID.match(trimmed):
        return trimmed

    try:
        parsed = urlsplit(trimmed if trimmed.startswith("http") else f"https://{trimmed}")
        host = (parsed.hostname or "").replace("www.", "", 1)
        path = parsed.path or "/"
        if host in ("youtube.com", "m.youtube.com"):
            if path == "/watch":
                video_id = (parse_qs(parsed.query).get("v") or [None])[0]
                if video_id and _VIDEO_ID.match(video_id):
                    return video_id
            if path.startswith("/embed/") or path.startswith("/shorts/"):
                parts = path.split("/")
                video_id = parts[2] if len(parts) > 2 else None
                if video_id and _VIDEO_ID.match(video_id):
                    return video_id
        elif host == "youtu.be":
            video_id = path[1:].split("?")[0]
            if video_id and _VIDEO_ID.match(video_id):
                return video_id
    except ValueError:
        pass

    raise IngestError(INGEST_ERROR_CODES["INVALID_URL"])


def _decode_html_entities(text):
    text = str(text).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'")
    return re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1)) & 0xFFFF), text)


def _parse_transcript_xml(xml_text):
    """Legacy ``<text start="seconds" dur="seconds">`` format."""
    cues = []
    pattern = re.compile(r'<text\s+start="([\d.]+)"(?:\s+dur="([\d.]+)")?[^>]*>([\s\S]*?)</text>', re.IGNORECASE)
    for match in pattern.finditer(xml_text):
        text = _decode_html_entities(re.sub(r"<[^>]+>", "", match.group(3))).strip()
        if text:
            cues.append({
                "text": text,
                "startSeconds": parse_float(match.group(1)),
                "durationSeconds": parse_float(match.group(2)) if match.group(2) else 3.0,
            })
    return cues


def _parse_transcript_srv3(xml_text):
    """srv3 (``<timedtext format="3">``): ``<p>`` elements with t/d in MILLISECONDS."""
    cues = []
    for match in re.finditer(r"<p\s+([^>]*)>([\s\S]*?)</p>", xml_text, re.IGNORECASE):
        attrs = match.group(1)
        start = re.search(r'\bt="(-?[\d.]+)"', attrs)
        start_ms = parse_float(start.group(1)) if start else float("nan")
        if start_ms != start_ms:
            continue
        duration = re.search(r'\bd="([\d.]+)"', attrs)
        duration_ms = parse_float(duration.group(1)) if duration else float("nan")
        text = re.sub(r"\s+", " ", _decode_html_entities(re.sub(r"<[^>]+>", "", match.group(2)))).strip()
        if text:
            cues.append({
                "text": text,
                "startSeconds": start_ms / 1000,
                "durationSeconds": 3.0 if duration_ms != duration_ms else duration_ms / 1000,
            })
    return cues


def _parse_transcript_json3(data):
    """json3: events with ``segs``; times in milliseconds."""
    cues = []
    for event in (data or {}).get("events") or []:
        if not event.get("segs"):
            continue
        text = re.sub(r"[\n\r]+", " ", "".join(seg.get("utf8") or "" for seg in event["segs"])).strip()
        if text:
            cues.append({
                "text": text,
                "startSeconds": (event.get("tStartMs") or 0) / 1000,
                "durationSeconds": (event.get("dDurationMs") or 3000) / 1000,
            })
    return cues


def parse_transcript(body):
    """Picks the parser by what actually came back, not by what was requested."""
    trimmed = body.strip()
    if trimmed.startswith("{"):
        try:
            return _parse_transcript_json3(json.loads(trimmed))
        except ValueError:
            return []
    if "<timedtext" in trimmed or "<p " in trimmed:
        return _parse_transcript_srv3(trimmed)
    return _parse_transcript_xml(trimmed)


def _fetch_player_response(video_id):
    try:
        response = httpx.post(
            "https://www.youtube.com/youtubei/v1/player",
            headers={"Content-Type": "application/json", "User-Agent": INNERTUBE_USER_AGENT},
            json={"videoId": video_id, "context": {"client": {**INNERTUBE_CLIENT, "hl": "en", "gl": "US"}}},
            timeout=30,
        )
    except httpx.HTTPError as err:
        raise IngestError(INGEST_ERROR_CODES["EXTRACT_FAILED"], f"Network error contacting YouTube: {err}") from err

    if response.status_code == 429:
        raise IngestError(INGEST_ERROR_CODES["RATE_LIMITED"])
    try:
        player = response.json()
    except ValueError:
        player = None
    if not player or not response.is_success:
        raise IngestError(INGEST_ERROR_CODES["VIDEO_UNAVAILABLE"], "Could not read video details from YouTube.")
    return player


def ingest_youtube(url_or_id, plan_tier="free"):
    video_id = extract_video_id(url_or_id)
    player = _fetch_player_response(video_id)

    playability = (player.get("playabilityStatus") or {}).get("status")
    if playability == "LOGIN_REQUIRED":
        raise IngestError(INGEST_ERROR_CODES["AGE_RESTRICTED"])
    if playability in ("UNPLAYABLE", "ERROR"):
        raise IngestError(INGEST_ERROR_CODES["VIDEO_UNAVAILABLE"])

    details = player.get("videoDetails")
    if not details:
        raise IngestError(INGEST_ERROR_CODES["VIDEO_UNAVAILABLE"])
    if details.get("isLiveContent"):
        raise IngestError(INGEST_ERROR_CODES["LIVE_STREAM"])

    title = details.get("title") or "YouTube Video"
    duration_seconds = parse_int(details.get("lengthSeconds"), 0) or 0
    thumbnails = (details.get("thumbnail") or {}).get("thumbnails") or []
    thumbnail_url = (thumbnails[-1].get("url") if thumbnails else None) or None

    if plan_tier != "plus" and duration_seconds > FREE_VIDEO_DURATION_LIMIT_SECONDS:
        minutes = js_round(duration_seconds / 60)
        raise IngestError(
            INGEST_ERROR_CODES["DURATION_LIMIT_EXCEEDED"],
            f"Free plan allows videos up to 30 minutes (this video is {minutes}m). "
            "Please upgrade to Plus for longer videos.",
            {"durationSeconds": duration_seconds, "limitSeconds": FREE_VIDEO_DURATION_LIMIT_SECONDS},
        )

    tracks = (((player.get("captions") or {}).get("playerCaptionsTracklistRenderer") or {}).get("captionTracks")) or []
    if not tracks:
        raise IngestError(INGEST_ERROR_CODES["NO_CAPTIONS"])

    # Khmer first, then English, then whatever exists.
    track = (next((t for t in tracks if t.get("languageCode") == "km"), None)
             or next((t for t in tracks if (t.get("languageCode") or "").startswith("en")), None)
             or tracks[0])
    if not track or not track.get("baseUrl"):
        raise IngestError(INGEST_ERROR_CODES["NO_CAPTIONS"])

    try:
        # Same client that was issued the URL — these are scoped to the caller.
        transcript = httpx.get(track["baseUrl"], headers={"User-Agent": INNERTUBE_USER_AGENT}, timeout=30)
    except httpx.HTTPError as err:
        raise IngestError(INGEST_ERROR_CODES["NO_CAPTIONS"],
                          f"Could not retrieve transcript from caption track: {err}") from err

    if not transcript.is_success:
        if transcript.status_code == 429:
            raise IngestError(INGEST_ERROR_CODES["RATE_LIMITED"])
        raise IngestError(INGEST_ERROR_CODES["NO_CAPTIONS"])

    body = transcript.text
    # An empty 200 means the track exists but refused to serve without an
    # attestation token — a limit on our side, not a video without captions.
    if not body.strip():
        raise IngestError(
            INGEST_ERROR_CODES["EXTRACT_FAILED"],
            "YouTube listed captions for this video but would not serve them. This is a "
            "limit on our side rather than a problem with the video — please try again later.",
        )

    cues = parse_transcript(body)
    if not cues:
        raise IngestError(INGEST_ERROR_CODES["NO_CAPTIONS"])

    return {
        "videoId": video_id,
        "title": title,
        "durationSeconds": duration_seconds,
        "thumbnailUrl": thumbnail_url,
        "cues": cues,
        "fullText": " ".join(cue["text"] for cue in cues).strip(),
    }

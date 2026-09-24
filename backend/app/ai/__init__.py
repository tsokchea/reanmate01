"""The only entry point to AI for the whole server (server/src/ai/index.js).

Controllers and routes never import a provider module directly — call
get_ai() and use what it returns, so the mock fallback holds everywhere.
"""

import logging
import threading

from ..config import config
from .mock import create_mock_provider
from .types import AI_METHODS, EMBEDDING_DIMENSIONS  # noqa: F401  (re-exported)

log = logging.getLogger("reanmate")

_provider = None
_warned = False
_lock = threading.Lock()


def _warn_once(message):
    global _warned
    if not _warned:
        log.warning("[ai] %s", message)
        _warned = True


def _assert_conforms(candidate):
    missing = [method for method in AI_METHODS if not callable(getattr(candidate, method, None))]
    if missing:
        raise TypeError(f'AI provider "{candidate.name}" is missing: {", ".join(missing)}.')
    return candidate


def _build_provider():
    if not config.OPENAI_API_KEY:
        _warn_once("OPENAI_API_KEY is not set — falling back to the mock provider. "
                   "Responses are canned; the shapes are real.")
        return _assert_conforms(create_mock_provider())
    try:
        from .openai_provider import create_openai_provider

        real = _assert_conforms(create_openai_provider())
        # The endpoint is logged: which host receives study material should never be a surprise.
        endpoint = config.OPENAI_BASE_URL or "api.openai.com (default)"
        log.info("[ai] using OpenAI-compatible endpoint %s (%s, embeddings %s)",
                 endpoint, config.OPENAI_MODEL, config.OPENAI_EMBEDDING_MODEL)
        return real
    except Exception as err:  # a bad key or config should not take the server down
        _warn_once(f"OpenAI provider unavailable ({err}) — using the mock provider")
        return _assert_conforms(create_mock_provider())


def get_ai():
    global _provider
    if _provider is None:
        with _lock:
            if _provider is None:
                _provider = _build_provider()
    return _provider


def is_mock_ai():
    return get_ai().name == "mock"


def reset_ai():
    """Test seam: forces the next get_ai() to rebuild."""
    global _provider, _warned
    _provider = None
    _warned = False

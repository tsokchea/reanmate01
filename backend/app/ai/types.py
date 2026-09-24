"""The AI layer contract (server/src/ai/types.js).

Every provider implements the same methods. Callers get one through
``get_ai()`` in app/ai/__init__.py and never import a provider directly, so
swapping mock for real changes nothing upstream.

Shapes are camelCase dicts because they are the same payloads the Node
providers produced; services map them to snake_case columns when writing rows.

Methods (all keyword-only, each accepting an optional ``on_usage`` callback):

  summarize            -> {title, bodyMd, keyPoints}
  summarizeChapters    -> {title, bodyMd, outline[], chapters[]}   (resumable)
  generateStudyGuide   -> {outline[], modules[]}                   (resumable)
  generateQuiz         -> {title, questions[]}
  generateMockExam     -> {title, questions[]}  with expectedAnswer on each
  gradeWrittenAnswers  -> [{isCorrect, note}]   same order as input
  generateFlashcards   -> [{term, definition, hint, topic}]
  tutorReply           -> iterator of {type: delta|done|error}; exactly one terminal
  summarizeAttempt     -> {takeaways[]}
  embed                -> {embeddings[[1536]], dimensions}
  extractImageText     -> {text, hasText, description}

Token usage is reported through ``on_usage(usage)`` once per underlying API
request — best-effort, and a zero total means "unknown", never "free".
"""

EMBEDDING_DIMENSIONS = 1536
PROVIDER_NAMES = ("mock", "openai")
LANGUAGES = ("km", "en")

AI_METHODS = (
    "summarize",
    "summarize_chapters",
    "generate_study_guide",
    "generate_quiz",
    "generate_mock_exam",
    "grade_written_answers",
    "generate_flashcards",
    "tutor_reply",
    "summarize_attempt",
    "embed",
    "extract_image_text",
)


def empty_usage():
    return {
        "promptTokens": 0,
        "completionTokens": 0,
        "reasoningTokens": 0,
        "cachedPromptTokens": 0,
        "totalTokens": 0,
        "apiCalls": 0,
        "model": None,
    }


class UsageCollector:
    """Accumulates the reports from one logical generation into a single total."""

    def __init__(self):
        self._total = empty_usage()

    def record(self, usage):
        if not usage:
            return
        total = self._total
        total["promptTokens"] += usage.get("promptTokens") or 0
        total["completionTokens"] += usage.get("completionTokens") or 0
        total["reasoningTokens"] += usage.get("reasoningTokens") or 0
        total["cachedPromptTokens"] += usage.get("cachedPromptTokens") or 0
        # Trust a provider's own total when it sends one.
        reported = usage.get("totalTokens")
        total["totalTokens"] += (
            reported if reported is not None
            else (usage.get("promptTokens") or 0) + (usage.get("completionTokens") or 0)
        )
        calls = usage.get("apiCalls")
        total["apiCalls"] += 1 if calls is None else calls
        if total["model"] is None:
            total["model"] = usage.get("model")

    def total(self):
        return dict(self._total)


def create_usage_collector():
    return UsageCollector()


def assert_embedding_width(vector, context="embedding"):
    """Fails at the source rather than at the INSERT into vector(1536)."""
    if not isinstance(vector, list) or len(vector) != EMBEDDING_DIMENSIONS:
        got = len(vector) if isinstance(vector, list) else type(vector).__name__
        raise ValueError(
            f"{context}: expected {EMBEDDING_DIMENSIONS} dimensions to match document_chunks.embedding, got {got}"
        )
    return vector

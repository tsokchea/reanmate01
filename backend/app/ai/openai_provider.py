"""Real OpenAI provider (server/src/ai/openai.js).

Wired but unreachable until OPENAI_API_KEY is set — get_ai() picks the mock
when the key is absent. Structured methods use strict json_schema response
formats; strict mode forbids validation keywords, so the schemas are plain and
anything tighter is enforced in Python after parsing.

Prompts, schemas, retry policy and the optional-parameter fallback are ported
verbatim so the model sees exactly what it saw from the Node server.
"""

import base64
import json
import logging
import math
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import openai

from ..config import config
from ..utils.js import js_round
from .types import EMBEDDING_DIMENSIONS, assert_embedding_width

log = logging.getLogger("reanmate")

MAX_SOURCE_CHARS = 120_000
EMBED_BATCH_SIZE = 96
RETRY_ATTEMPTS = 4
RETRY_BASE_MS = 500

LANGUAGE_NAMES = {"km": "Khmer (ភាសាខ្មែរ)", "en": "English"}

# Khmer measures at ~2.9x English on this tokenizer, so a flat output cap
# sized for English truncates Khmer replies mid-sentence.
LANGUAGE_TOKEN_COST = {"km": 3, "en": 1}

# Reasoning models spend max_completion_tokens on reasoning before writing.
REASONING_HEADROOM_TOKENS = 256

# Optimisations, not requirements; a refused one is dropped and the call retried.
OPTIONAL_PARAMS = ("service_tier", "reasoning_effort", "stream_options")


def _output_budget(max_output_tokens, language):
    return math.ceil(max_output_tokens * LANGUAGE_TOKEN_COST.get(language, LANGUAGE_TOKEN_COST["km"])) + REASONING_HEADROOM_TOKENS


def _status(err):
    return getattr(err, "status_code", None)


def _rejects_param(err, param):
    if _status(err) != 400:
        return False
    message = f"{getattr(err, 'message', '') or ''} {err}".lower()
    return param in message


def _normalize_usage(usage, model):
    if not usage:
        return None
    details = getattr(usage, "completion_tokens_details", None)
    prompt_details = getattr(usage, "prompt_tokens_details", None)
    return {
        "promptTokens": getattr(usage, "prompt_tokens", 0) or 0,
        "completionTokens": getattr(usage, "completion_tokens", 0) or 0,
        "reasoningTokens": (getattr(details, "reasoning_tokens", 0) or 0) if details else 0,
        "cachedPromptTokens": (getattr(prompt_details, "cached_tokens", 0) or 0) if prompt_details else 0,
        "totalTokens": getattr(usage, "total_tokens", 0) or 0,
        "apiCalls": 1,
        "model": model,
    }


def _report(on_usage, usage, model):
    if not callable(on_usage):
        return
    normalized = _normalize_usage(usage, model)
    if not normalized:
        return
    try:
        on_usage(normalized)
    except Exception as err:
        log.warning("[ai] usage reporter threw, ignoring: %s", err)


def _system_prompt(language):
    parts = [
        "You are ReanMate, a study tutor for Cambodian secondary and university students.",
        f"Write every user-facing string in {LANGUAGE_NAMES.get(language, LANGUAGE_NAMES['km'])}.",
        "For Khmer replies, write the explanation in Khmer script and translate ordinary English wording into Khmer. "
        "Keep English only for code, filenames, proper names, or an unavoidable technical label, and put the Khmer "
        "explanation first." if language == "km" else "",
        "Explain plainly, use short sentences, and prefer a concrete example over an abstract rule.",
        "Base every claim on the study material provided. If the material does not answer the",
        "question, say so rather than inventing an answer.",
    ]
    return " ".join(part for part in parts if part)


def _require_fitting_text(text):
    """Never silently truncate — a summary of half a document looks correct and is wrong."""
    value = text or ""
    if len(value) > MAX_SOURCE_CHARS:
        raise ValueError(
            f"Study material is {len(value)} characters, over the {MAX_SOURCE_CHARS} limit for a "
            "single request. Chunk it before calling the AI layer."
        )
    return value or "No study material was provided."


def _is_retryable(err):
    status = _status(err)
    if status == 429:
        return True
    if isinstance(status, int) and 500 <= status < 600:
        return True
    return isinstance(err, openai.APIConnectionError)


def _with_retry(label, fn):
    """Exponential backoff with jitter, honouring Retry-After when the API sends it."""
    attempt = 0
    while True:
        try:
            return fn()
        except Exception as err:
            if not _is_retryable(err) or attempt >= RETRY_ATTEMPTS - 1:
                raise
            retry_after = None
            response = getattr(err, "response", None)
            if response is not None:
                try:
                    retry_after = float(response.headers.get("retry-after"))
                except (TypeError, ValueError):
                    retry_after = None
            delay_ms = retry_after * 1000 if retry_after is not None else RETRY_BASE_MS * 2**attempt + random.random() * 250
            log.warning("[ai] %s failed (%s), retry %d/%d in %dms", label, _status(err) or "network",
                        attempt + 1, RETRY_ATTEMPTS - 1, js_round(delay_ms))
            time.sleep(delay_ms / 1000)
            attempt += 1


# ---------------------------------------------------------------------------
# Strict JSON schemas — the wire contract with the model.
# ---------------------------------------------------------------------------


def _obj(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def _string_array(description):
    return {"type": "array", "items": {"type": "string"}, "description": description}


SUMMARY_SCHEMA = _obj({
    "title": {"type": "string", "description": "Short heading for the summary."},
    "bodyMd": {"type": "string", "description": "Markdown body, headings no deeper than ##."},
    "keyPoints": _string_array("Three to five one-line takeaways."),
})

STUDY_GUIDE_OUTLINE_SCHEMA = _obj({
    "modules": {
        "type": "array",
        "description": "Every concept the document teaches, in the order it introduces them. "
                       "One entry per concept - not per page, and not per heading.",
        "items": _obj({
            "moduleIndex": {"type": "integer", "description": "1-based, contiguous, in document order."},
            "title": {"type": "string", "description":
                      'The concept itself, e.g. "Normalization to 3NF" - never "Module 3" or "Introduction".'},
            "focus": {"type": "string", "description":
                      "One line naming exactly what this module must teach, so modules do not overlap."},
        }),
    },
})

STUDY_GUIDE_MODULE_SCHEMA = _obj({
    "title": {"type": "string", "description": "The concept being taught."},
    "explanationMd": {"type": "string", "description":
                      "EXACTLY 3 to 5 markdown bullets, one line each, with **key terms** bolded. Say how and "
                      "why the concept works, not just what it is. Scannable, not prose - no paragraphs, no "
                      "heading, and no bullet longer than two lines."},
    "applicationMd": {"type": "string", "description":
                      "ONE brief example taken from this document: a worked case, a formula, a fenced code "
                      "block, or a short numbered workflow. A few lines at most. No heading, no second example."},
    "pitfallsMd": {"type": "string", "description":
                   "EXACTLY 3 markdown bullets: two common mistakes students make on THIS concept, then one "
                   'bullet starting "**Exam tip:**" with the single thing worth remembering. No heading.'},
    "recall": {
        "type": "array",
        "description": "One or two questions testing this module. Every question MUST carry its written answer - "
                       "a question with an empty or placeholder answer is invalid.",
        "items": _obj({
            "question": {"type": "string", "description": "A conceptual question, not a definition lookup."},
            "answer": {"type": "string", "description":
                       "The complete answer, written out in 1 to 2 sentences. Never a letter, a cross-reference "
                       'or "see above" - the student reads only this.'},
        }),
    },
})

IMAGE_TEXT_SCHEMA = _obj({
    "text": {"type": "string", "description":
             "Every word visible in the images, in reading order, pages separated by a blank line. "
             "Empty string if there is no legible text."},
    "hasText": {"type": "boolean", "description": "True only if at least some legible text was transcribed."},
    "description": {"type": "string", "description":
                    "One sentence on what the images show, including any diagram or chart."},
})

CHAPTER_OUTLINE_SCHEMA = _obj({
    "chapters": {
        "type": "array",
        "description": "Sequential, non-overlapping chapters covering the whole source from 0.",
        "items": _obj({
            "chapterIndex": {"type": "integer", "description": "1-based, contiguous, in order."},
            "title": {"type": "string"},
            "startSeconds": {"type": "integer"},
            "endSeconds": {"type": "integer"},
        }),
    },
})

CHAPTER_BODY_SCHEMA = _obj({
    "bodyMd": {"type": "string"},
    "keyPoints": _string_array("Up to three takeaways for this chapter alone."),
})

_QUESTION_KINDS = ["multiple_choice", "true_false", "short_answer", "written"]

QUIZ_SCHEMA = _obj({
    "title": {"type": "string"},
    "questions": {
        "type": "array",
        "items": _obj({
            "kind": {"type": "string", "enum": _QUESTION_KINDS},
            "prompt": {"type": "string"},
            "options": _string_array("4 for multiple_choice, 2 for true_false, empty otherwise."),
            "correctIndex": {"type": ["integer", "null"],
                             "description": "0-based index into options for choice questions, else null."},
            "correctText": {"type": ["string", "null"],
                            "description": "Expected answer for short_answer/written, else null."},
            "explanation": {"type": "string", "description":
                            "Why the correct option is right AND why each distractor is wrong, both grounded in "
                            "the document. A student who picked wrongly must learn what they misread."},
            "topic": {"type": "string"},
            "targetedWeakConcept": {"type": ["string", "null"], "description":
                                    "The weak concept this question was written to attack, copied EXACTLY from the "
                                    "list of weak concepts in the instructions. null when the question covers the "
                                    "rest of the document instead."},
        }),
    },
})

MOCK_EXAM_SCHEMA = _obj({
    "title": {"type": "string"},
    "questions": {
        "type": "array",
        "items": _obj({
            "kind": {"type": "string", "enum": _QUESTION_KINDS},
            "prompt": {"type": "string"},
            "options": _string_array("4 for multiple_choice, 2 for true_false, empty otherwise."),
            "correctIndex": {"type": ["integer", "null"],
                             "description": "0-based index into options for choice questions, else null."},
            "correctText": {"type": ["string", "null"],
                            "description": "Expected answer for short_answer/written, else null."},
            "expectedAnswer": {"type": "string", "description":
                               "The correct answer written out in full, one or two sentences, as a student would "
                               "write it from memory. NEVER a letter, an option number, or a cross-reference: this "
                               'is what a typed answer is marked against, and "B" marks nothing.'},
            "difficulty": {"type": "string", "enum": ["easy", "medium", "hard"]},
            "explanation": {"type": "string", "description":
                            "Why the correct answer is right AND why each distractor is wrong, grounded in the "
                            "document."},
            "topic": {"type": "string"},
        }),
    },
})

WRITTEN_GRADES_SCHEMA = _obj({
    "grades": {
        "type": "array",
        "description": "One entry per submitted answer, in the SAME ORDER they were given.",
        "items": _obj({
            "isCorrect": {"type": "boolean", "description":
                          "True when the response conveys the expected answer. Judge MEANING: different "
                          "wording, word order, spelling and a mix of Khmer and English are all fine."},
            "note": {"type": "string", "description":
                     "One short line addressed to the student saying what was right, or what was "
                     "missing. In the requested language."},
        }),
    },
})

FLASHCARDS_SCHEMA = _obj({
    # Strict json_schema requires an object at the root, so the cards are wrapped.
    "cards": {
        "type": "array",
        "items": _obj({
            "term": {"type": "string"},
            "definition": {"type": "string", "description": "One or two recallable sentences."},
            "hint": {"type": ["string", "null"]},
            "topic": {"type": "string"},
        }),
    },
})

ATTEMPT_SCHEMA = _obj({"takeaways": _string_array("Up to five short takeaways addressed to the student.")})

TUTOR_CITATION_HINT = "Answer using only the study material. Name the source you relied on in your answer."


def _wanted(outline, key, only):
    indices = [entry[key] for entry in outline]
    return indices if only is None else [i for i in dict.fromkeys(only) if i in indices]


class OpenAIProvider:
    name = "openai"

    def __init__(self, *, api_key=None, model=None, embedding_model=None, base_url=None):
        api_key = api_key or config.OPENAI_API_KEY
        if not api_key:
            raise ValueError("OpenAIProvider requires OPENAI_API_KEY")
        self.model = model or config.OPENAI_MODEL
        self.embedding_model = embedding_model or config.OPENAI_EMBEDDING_MODEL
        base_url = base_url or config.OPENAI_BASE_URL
        # max_retries=0 — _with_retry owns backoff, so the SDK must not retry too.
        kwargs = {"api_key": api_key, "max_retries": 0}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = openai.OpenAI(**kwargs)
        # Optional parameters this endpoint has already refused, for the life of the process.
        self._unsupported = set()
        self._lock = threading.Lock()

    # --- transport ---------------------------------------------------------

    def _chat_completion(self, label, build):
        while True:
            with self._lock:
                skip = set(self._unsupported)
            params = build(skip)
            try:
                return _with_retry(label, lambda: self.client.chat.completions.create(**params))
            except Exception as err:
                rejected = next((p for p in OPTIONAL_PARAMS if p in params and _rejects_param(err, p)), None)
                if not rejected:
                    raise
                with self._lock:
                    self._unsupported.add(rejected)
                log.warning("[ai] %s: endpoint rejected %s — dropping it for this process and retrying", label, rejected)

    def _structured(self, *, label, schema_name, schema, language, prompt, material, service_tier="default",
                    reasoning_effort=None, on_usage=None):
        def build(skip):
            params = {"model": self.model}
            # OpenAI calls the batch-priced tier "flex" on live requests.
            if service_tier == "batch" and "service_tier" not in skip:
                params["service_tier"] = "flex"
            # 'none' means "do not reason": omit the parameter entirely.
            if reasoning_effort and reasoning_effort != "none" and "reasoning_effort" not in skip:
                params["reasoning_effort"] = reasoning_effort
            params["messages"] = [
                {"role": "system", "content": _system_prompt(language)},
                {"role": "user", "content": f"{prompt}\n\n--- STUDY MATERIAL ---\n{_require_fitting_text(material)}"},
            ]
            params["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            }
            return params

        completion = self._chat_completion(label, build)
        # Reported before validation: those tokens were billed either way.
        _report(on_usage, completion.usage, self.model)

        choice = completion.choices[0] if completion.choices else None
        if choice is not None and choice.finish_reason == "length":
            raise RuntimeError(f"{label}: model hit the output limit before completing the JSON")
        refusal = getattr(choice.message, "refusal", None) if choice else None
        if refusal:
            raise RuntimeError(f"{label}: model refused — {refusal}")
        raw = choice.message.content if choice else None
        if not raw:
            raise RuntimeError(f"{label}: model returned no content")
        try:
            return json.loads(raw)
        except ValueError as err:
            raise RuntimeError(f"{label}: model returned unparseable JSON ({err})") from err

    @staticmethod
    def _parallel(fn, items):
        """Promise.all: run concurrently, keep order, re-raise the first failure."""
        if not items:
            return []
        with ThreadPoolExecutor(max_workers=min(8, len(items))) as pool:
            return list(pool.map(fn, items))

    # --- methods -------------------------------------------------------------

    def summarize(self, *, text=None, title=None, language="km", service_tier="default", on_usage=None, **_):
        about = f' titled "{title}"' if title else ""
        return self._structured(
            label="summarize", schema_name="summary", schema=SUMMARY_SCHEMA, language=language, material=text,
            service_tier=service_tier, on_usage=on_usage,
            prompt=f"Summarise this study material{about} for a student "
                   "seeing it for the first time. Use at most two headings and give 3-5 key points.",
        )

    def summarize_chapters(self, *, text=None, title=None, language="km", duration_seconds=None, chapter_count=12,
                           outline=None, only=None, service_tier="default", on_usage=None, **_):
        material = _require_fitting_text(text)
        about = f' titled "{title}"' if title else ""
        if outline is None:
            timeline = (
                f"The source runs {duration_seconds} seconds; chapters must tile it from 0 with no gaps or overlap."
                if duration_seconds else "Use character offsets scaled to seconds if the source has no timeline."
            )
            outline = self._structured(
                label="summarizeChapters:outline", schema_name="chapter_outline", schema=CHAPTER_OUTLINE_SCHEMA,
                language=language, material=material, service_tier=service_tier, on_usage=on_usage,
                prompt=f"Split this study material{about} into about {chapter_count} sequential chapters. "
                       f"{timeline} Return titles and boundaries only — no bodies.",
            )["chapters"]

        wanted = _wanted(outline, "chapterIndex", only)
        overview = (
            self.summarize(text=material, title=title, language=language, service_tier=service_tier, on_usage=on_usage)
            if len(wanted) == len(outline) or only is None else None
        )

        def body(chapter):
            result = self._structured(
                label=f"summarizeChapters:body[{chapter['chapterIndex']}]", schema_name="chapter_body",
                schema=CHAPTER_BODY_SCHEMA, language=language, material=material, service_tier=service_tier,
                on_usage=on_usage,
                prompt=f"Write the summary for chapter {chapter['chapterIndex']}, \"{chapter['title']}\", "
                       f"covering {chapter['startSeconds']}s to {chapter['endSeconds']}s of the material. "
                       "Cover only that span — other chapters are summarised separately.",
            )
            return {**chapter, "bodyMd": result["bodyMd"], "keyPoints": result["keyPoints"]}

        chapters = self._parallel(body, [c for c in outline if c["chapterIndex"] in wanted])
        return {
            "title": (overview or {}).get("title") or title or "",
            "bodyMd": (overview or {}).get("bodyMd") or "",
            "outline": outline,
            "chapters": chapters,
        }

    def generate_study_guide(self, *, text=None, title=None, language="km", module_count=8, outline=None, only=None,
                             service_tier="default", on_usage=None, **_):
        material = _require_fitting_text(text)
        about = f' titled "{title}"' if title else ""
        if outline is None:
            outline = self._structured(
                label="generateStudyGuide:outline", schema_name="study_guide_outline",
                schema=STUDY_GUIDE_OUTLINE_SCHEMA, language=language, material=material, service_tier=service_tier,
                on_usage=on_usage,
                prompt=" ".join([
                    f"Plan a study guide for this material{about}.",
                    f"Break it into about {module_count} modules, one per distinct concept it teaches,",
                    "in the order the document introduces them. Cover every major concept and do not",
                    "skip technical detail.",
                    "Use only this document: it is the whole syllabus for this guide, and anything it",
                    "does not contain is out of scope even if you know it.",
                    "Return a title and a one-line focus for each. No bodies, and no overview module.",
                ]),
            )["modules"]

        wanted = _wanted(outline, "moduleIndex", only)

        def body(module):
            result = self._structured(
                label=f"generateStudyGuide:module[{module['moduleIndex']}]", schema_name="study_guide_module",
                schema=STUDY_GUIDE_MODULE_SCHEMA, language=language, material=material, service_tier=service_tier,
                on_usage=on_usage,
                prompt=" ".join([
                    f"Teach module {module['moduleIndex']}, \"{module['title']}\", from this material{about}.",
                    f"It must cover: {module.get('focus')}.",
                    "Teach only that - the other modules are written separately, so do not introduce",
                    "their concepts or recap them.",
                    "Write for a student meeting this for the first time, and write to be SKIMMED:",
                    "short bullets, bold key terms, no walls of text. Being brief is not licence to",
                    "drop a technical detail - cut the padding, keep the substance.",
                    "Take the example from this document rather than inventing one.",
                    "Every recall question must carry its own written answer, complete in one or two",
                    "sentences.",
                    "Do not write a summary, an overview or an introduction - start teaching.",
                ]),
            )
            return {
                "moduleIndex": module["moduleIndex"],
                "title": result.get("title") or module["title"],
                "explanationMd": result["explanationMd"],
                "applicationMd": result["applicationMd"],
                "pitfallsMd": result["pitfallsMd"],
                "recall": result["recall"],
            }

        modules = self._parallel(body, [m for m in outline if m["moduleIndex"] in wanted])
        return {"outline": outline, "modules": modules}

    def generate_quiz(self, *, text=None, title=None, language="km", count=10, difficulty="mixed", question_types=None,
                      include_answer_key=True, avoid_questions=None, weak_topics=None, reasoning_effort=None,
                      on_usage=None, **_):
        question_types = question_types or ["multipleChoice"]
        weak_topics = weak_topics or []
        avoid_questions = avoid_questions or []
        # Stated as counts, not percentages — a model asked for "70%" of eight returns five or six.
        targeted = js_round(count * 0.7) if weak_topics else 0
        general = count - targeted
        titled = f'titled "{title}"' if title else ""
        weak_list = ", ".join(f'"{topic}"' for topic in weak_topics)

        parts = [
            f"Write exactly {count} questions about this material at {difficulty} difficulty.",
            f"Allowed question types only: {', '.join(question_types)}.",
            f"{titled}.",
            "Use only this document — not your own knowledge of the subject, and not any other",
            "file it may refer to.",
            "Do not ask questions about the class name, source labels, filenames, or the fact that",
            "a document was supplied. Ask about concepts, definitions, procedures, and examples",
            "stated in the document itself.",
            'For multipleChoice, use kind "multiple_choice" with exactly 4 options and exactly one correctIndex.',
            'For trueFalse, use kind "true_false" with exactly 2 options ("True" and "False") and correctIndex.',
            'For shortAnswer, use kind "short_answer", an empty options array, and correctText.',
            "Use only allowed types and distribute them across the requested count where possible.",
            "Distractors must be plausible to someone who half-understood the material, never filler.",
            "Vary which position holds the correct option instead of writing the true statement",
            "first every time. (The server reshuffles as well, so the four options must read as",
            'a set in any order — never "all of the above", "both A and B", or an option that',
            "refers to another by letter.)",
            "Every question needs a topic and an explanation saying why the right option is right",
            "and why the others are wrong, pointing at what the document actually says.",
            " ".join([
                f"This student has already been tested on this material. Exactly {targeted} of the",
                f"{count} questions must attack these weak concepts, worst first —",
                f"{weak_list} —",
                "and each of those questions must set targetedWeakConcept to the concept it",
                f"attacks, spelled exactly as listed. The other {general} must cover different",
                "parts of the document, with targetedWeakConcept null.",
            ]) if weak_topics else
            "Spread the questions evenly across the core subtopics, and set targetedWeakConcept null on every one.",
            " ".join([
                "The student has already answered the questions listed below. Do not repeat,",
                "rephrase, translate or narrowly re-angle any of them — a question testing the",
                "same fact in different words is a duplicate. Ask about something else in the",
                "document, or test the same concept from a genuinely different direction",
                "(applying it, comparing it, spotting where it breaks).",
                "ALREADY ASKED:\n" + "\n".join(f"- {q}" for q in avoid_questions),
            ]) if avoid_questions else "",
            f'Title the quiz "{title if title is not None else "Generated Quiz"}".',
            "Include correct answers so the teacher can edit the answer key." if include_answer_key else
            "Still include correct answers internally for validation, but the teacher UI may hide them until enabled.",
        ]
        result = self._structured(
            label="generateQuiz", schema_name="quiz", schema=QUIZ_SCHEMA, language=language, material=text,
            reasoning_effort=reasoning_effort, on_usage=on_usage, prompt=" ".join(p for p in parts if p),
        )

        questions = []
        for q in result["questions"]:
            is_choice = q["kind"] in ("multiple_choice", "true_false")
            correct = q.get("correctIndex") if is_choice else q.get("correctText")
            if correct is None:
                raise RuntimeError(f"generateQuiz: question \"{q['prompt']}\" of kind {q['kind']} has no usable answer")
            if is_choice and (correct < 0 or correct >= len(q["options"])):
                raise RuntimeError(f"generateQuiz: correctIndex {correct} is out of range for "
                                   f"{len(q['options'])} options on \"{q['prompt']}\"")
            questions.append({
                "kind": q["kind"],
                "prompt": q["prompt"],
                "options": q["options"],
                "correctAnswer": correct,
                "explanation": q["explanation"],
                "topic": q["topic"],
                # Only trust a label that names a weakness actually asked for.
                "targetedWeakConcept": q.get("targetedWeakConcept") if q.get("targetedWeakConcept") in weak_topics else None,
            })
        return {"title": result["title"], "questions": questions}

    def generate_mock_exam(self, *, text=None, title=None, language="km", count=30, reasoning_effort="medium",
                           service_tier="default", on_usage=None, **_):
        hard = js_round(count * 0.25)
        easy = js_round(count * 0.25)
        medium = count - hard - easy
        source = f' from "{title}"' if title else ""
        prompt = " ".join([
            f"Write exactly {count} exam questions about this material{source}.",
            "This is a mock exam, not a revision quiz. Write questions that test whether the",
            "student can USE the material — apply a rule, compare two ideas, work out what",
            "happens in a case the document did not state outright — rather than whether they",
            "can recall one sentence of it.",
            f"Difficulty must be exactly {easy} easy, {medium} medium and {hard} hard, and",
            "each question must set difficulty to its own level.",
            "Spread the questions across the WHOLE document. Do not cluster them on the first",
            "few pages or on whichever section happens to be the most quotable — a section the",
            "exam never touches is a section the student will not revise.",
            "Use only this document — not your own knowledge of the subject, and not any other",
            "file it may refer to.",
            "Do not ask about the filename, the class name, source labels, or the fact that a",
            "document was supplied. Ask about concepts, definitions, procedures and examples",
            "stated in the document itself.",
            'For multiple choice use kind "multiple_choice" with exactly 4 options and one',
            'correctIndex. For true/false use kind "true_false" with exactly 2 options ("True"',
            'and "False") and correctIndex. For a question better answered in prose use kind',
            '"short_answer" with an empty options array and correctText.',
            "Distractors must be plausible to someone who half-understood the material, never",
            "filler. Vary which position holds the correct option instead of writing the true",
            "statement first every time. (The server reshuffles as well, so the four options",
            'must read as a set in any order — never "all of the above", "both A and B", or an',
            "option that refers to another by letter.)",
            "EVERY question needs expectedAnswer: the correct answer written out in full, one",
            "or two sentences, as a student would write it from memory. This applies to",
            "multiple-choice questions too — the same exam can be sat with the options hidden,",
            "and a typed answer is marked against this text. A letter or an option number there",
            "makes the question ungradeable.",
            "Every question needs a topic and an explanation saying why the right answer is",
            "right and why the others are wrong, pointing at what the document actually says.",
        ])
        result = self._structured(
            label="generateMockExam", schema_name="mock_exam", schema=MOCK_EXAM_SCHEMA, language=language,
            material=text, service_tier=service_tier, reasoning_effort=reasoning_effort, on_usage=on_usage,
            prompt=prompt,
        )

        questions = []
        for q in result["questions"]:
            is_choice = q["kind"] in ("multiple_choice", "true_false")
            correct = q.get("correctIndex") if is_choice else q.get("correctText")
            if correct is None:
                raise RuntimeError(f"generateMockExam: question \"{q['prompt']}\" of kind {q['kind']} has no usable answer")
            if is_choice and (correct < 0 or correct >= len(q["options"])):
                raise RuntimeError(f"generateMockExam: correctIndex {correct} is out of range for "
                                   f"{len(q['options'])} options on \"{q['prompt']}\"")
            expected = q.get("expectedAnswer")
            if not isinstance(expected, str) or not expected.strip():
                raise RuntimeError(f"generateMockExam: question \"{q['prompt']}\" has no expectedAnswer to mark against")
            questions.append({
                "kind": q["kind"], "prompt": q["prompt"], "options": q["options"], "correctAnswer": correct,
                "expectedAnswer": expected.strip(), "difficulty": q["difficulty"], "explanation": q["explanation"],
                "topic": q["topic"],
            })
        return {"title": result["title"], "questions": questions}

    def grade_written_answers(self, *, answers=None, language="km", reasoning_effort="low", on_usage=None, **_):
        answers = answers or []
        if not answers:
            return []
        material = "\n\n".join(
            "\n".join([f"### Answer {i + 1}", f"QUESTION: {a['prompt']}", f"EXPECTED: {a['expectedAnswer']}",
                       f"STUDENT WROTE: {a['response']}"])
            for i, a in enumerate(answers)
        )
        count = len(answers)
        result = self._structured(
            label="gradeWrittenAnswers", schema_name="written_grades", schema=WRITTEN_GRADES_SCHEMA,
            language=language, material=material, reasoning_effort=reasoning_effort, on_usage=on_usage,
            prompt=" ".join([
                f"Mark these {count} exam answers. Return exactly {count} grades,",
                "in the same order as the answers appear.",
                "Mark on MEANING, not on wording. A student who conveys the expected answer in their",
                "own words is correct. Different phrasing, different word order, a different example,",
                "spelling mistakes, and mixing Khmer with English technical terms are all correct.",
                "Khmer has no spaces between words, so do not treat spacing as a mistake.",
                "Mark incorrect only when the response misses, contradicts or fails to reach the",
                "substance of the expected answer. An answer that is right but incomplete on a minor",
                "point is correct — say what was missing in the note.",
                "An empty or irrelevant response is incorrect.",
                "Do not reward length. A short answer that is right is right.",
                "Every note is one short line addressed to the student, in their language.",
            ]),
        )
        grades = result.get("grades") or []
        if len(grades) != count:
            raise RuntimeError(f"gradeWrittenAnswers: expected {count} grades, got {len(grades)}")
        return [{"isCorrect": bool(g.get("isCorrect")),
                 "note": g["note"].strip() if isinstance(g.get("note"), str) else ""} for g in grades]

    def generate_flashcards(self, *, text=None, language="km", count=12, reasoning_effort="none", on_usage=None, **_):
        result = self._structured(
            label="generateFlashcards", schema_name="flashcards", schema=FLASHCARDS_SCHEMA, language=language,
            material=text, reasoning_effort=reasoning_effort, on_usage=on_usage,
            prompt=f"Create {count} flashcards from this material. term is a single concept; "
                   "definition is one or two sentences a student could recall from memory. "
                   "Set hint to null unless a short nudge genuinely helps.",
        )
        return result["cards"]

    def summarize_attempt(self, *, language="km", correct_count=0, total_questions=1, missed_topics=None,
                          quiz_title=None, on_usage=None, **_):
        result = self._structured(
            label="summarizeAttempt", schema_name="attempt_summary", schema=ATTEMPT_SCHEMA, language=language,
            on_usage=on_usage,
            material=json.dumps({"quizTitle": quiz_title, "correctCount": correct_count,
                                 "totalQuestions": total_questions, "missedTopics": missed_topics or []},
                                ensure_ascii=False, separators=(",", ":")),
            prompt="A student just finished a quiz. From this result, write up to 3 short takeaways "
                   "addressed to them, using the missed topics as context. "
                   "Do not calculate or state a mastery percentage; the application computes it.",
        )
        return {"takeaways": result["takeaways"]}

    def tutor_reply(self, *, messages=None, language="km", sources=None, max_output_tokens=400, on_usage=None, **_):
        """Streaming. Retries cover only opening the stream; a mid-stream failure is a terminal error."""
        messages = messages or []
        sources = sources or []
        try:
            grounding = _require_fitting_text("\n\n".join(f"[{s['title']}]\n{s['content']}" for s in sources))

            def build(skip):
                params = {"model": self.model, "stream": True}
                if "stream_options" not in skip:
                    # Without this every tutor turn would log as zero tokens.
                    params["stream_options"] = {"include_usage": True}
                params["max_completion_tokens"] = _output_budget(max_output_tokens, language)
                params["messages"] = [
                    {"role": "system", "content": f"{_system_prompt(language)} {TUTOR_CITATION_HINT}"},
                    {"role": "system", "content": f"--- STUDY MATERIAL ---\n{grounding}"},
                    *({"role": m["role"], "content": m["content"]} for m in messages),
                ]
                return params

            stream = self._chat_completion("tutorReply", build)
        except Exception as err:
            yield {"type": "error", "message": str(err)}
            return

        try:
            for part in stream:
                if getattr(part, "usage", None):
                    _report(on_usage, part.usage, self.model)
                if part.choices:
                    text = getattr(part.choices[0].delta, "content", None)
                    if text:
                        yield {"type": "delta", "text": text}
        except Exception as err:
            yield {"type": "error", "message": f"Stream interrupted: {err}"}
            return

        # Citations come from the retrieved chunks, not from the model.
        yield {
            "type": "done",
            "citations": [{"sourceTitle": s.get("title"), "pageNumber": s.get("pageNumber"),
                           "startSeconds": s.get("startSeconds")} for s in sources],
            "suggestedFollowups": [],
        }

    def extract_image_text(self, *, images=None, language="km", on_usage=None, **_):
        """Transcribes photographed material; never translates, and describes what it cannot transcribe."""
        items = images if isinstance(images, list) else [images]
        items = [image for image in items if image and len(image.get("data") or b"") > 0]
        if not items:
            return {"text": "", "hasText": False, "description": ""}

        intro = ("Read this photograph of study material." if len(items) == 1
                 else f"Read these {len(items)} photographs as consecutive pages of one document.")

        def build(skip):
            params = {"model": self.model}
            if "reasoning_effort" not in skip:
                params["reasoning_effort"] = "low"
            params["messages"] = [
                {"role": "system", "content": " ".join([
                    "You transcribe photographed study material for Cambodian students.",
                    "Transcribe exactly what is written, preserving the original language of",
                    "every word — Khmer notes often contain English technical terms, and those",
                    "stay in English. Do not translate, correct or summarise the page.",
                    "Keep the reading order, and keep headings, numbered lists and equations",
                    "on their own lines.",
                ])},
                {"role": "user", "content": [
                    {"type": "text", "text": " ".join([
                        intro,
                        f"The text is expected to be mostly {LANGUAGE_NAMES.get(language, LANGUAGE_NAMES['km'])},",
                        "but transcribe any other language exactly as it appears.",
                        "If a diagram, chart or figure cannot be transcribed, describe it in the",
                        "description field so it is not lost.",
                    ])},
                    # A data URL rather than a hosted link: a student's uploads are never published.
                    *({"type": "image_url", "image_url": {
                        "url": f"data:{image['mimeType']};base64,{base64.b64encode(image['data']).decode()}",
                        "detail": "high",
                    }} for image in items),
                ]},
            ]
            params["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "image_text", "strict": True, "schema": IMAGE_TEXT_SCHEMA},
            }
            return params

        completion = self._chat_completion("extractImageText", build)
        _report(on_usage, completion.usage, self.model)

        choice = completion.choices[0] if completion.choices else None
        if choice is not None and choice.finish_reason == "length":
            raise RuntimeError("extractImageText: model hit the output limit before completing the JSON")
        refusal = getattr(choice.message, "refusal", None) if choice else None
        if refusal:
            raise RuntimeError(f"extractImageText: model refused — {refusal}")
        raw = choice.message.content if choice else None
        if not raw:
            raise RuntimeError("extractImageText: model returned no content")
        try:
            parsed = json.loads(raw)
        except ValueError as err:
            raise RuntimeError(f"extractImageText: model returned unparseable JSON ({err})") from err

        text = (parsed.get("text") or "").strip()
        return {
            "text": text,
            "hasText": bool(parsed.get("hasText")) and len(text) > 0,
            "description": (parsed.get("description") or "").strip(),
        }

    def embed(self, *, texts=None, on_usage=None, **_):
        items = texts if isinstance(texts, list) else [texts]
        if not items:
            return {"embeddings": [], "dimensions": EMBEDDING_DIMENSIONS}

        embeddings = []
        for start in range(0, len(items), EMBED_BATCH_SIZE):
            batch = items[start:start + EMBED_BATCH_SIZE]
            response = _with_retry(f"embed[{start}]", lambda: self.client.embeddings.create(
                model=self.embedding_model, input=batch, dimensions=EMBEDDING_DIMENSIONS,
            ))
            _report(on_usage, response.usage, self.embedding_model)
            ordered = sorted(response.data, key=lambda item: item.index)
            if len(ordered) != len(batch):
                raise RuntimeError(f"embed: asked for {len(batch)} vectors, got {len(ordered)} from {self.embedding_model}")
            for i, item in enumerate(ordered):
                embeddings.append(assert_embedding_width(list(item.embedding), f"{self.embedding_model}[{start + i}]"))
        return {"embeddings": embeddings, "dimensions": EMBEDDING_DIMENSIONS}


def create_openai_provider(**kwargs):
    return OpenAIProvider(**kwargs)

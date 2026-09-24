"""Summaries, study guides, tutor chat, quizzes, flashcards and practice."""

from flask import Blueprint

from ..controllers import chat_controller as chat
from ..controllers import study_controller as study
from ..middleware.validate import validate_body, validate_params, validate_query
from ..validation import schemas as s
from . import AUTH, add

bp = Blueprint("study", __name__, url_prefix="/api")

SUMMARY_SOURCE = validate_params(s.summary_source_params)
add(bp, "POST", "/sources/<id>/summarize", study.summarize, AUTH, SUMMARY_SOURCE, validate_body(s.summarize_body))
add(bp, "POST", "/sources/<id>/chapters", study.chapters, AUTH, SUMMARY_SOURCE, validate_body(s.chapters_body))
add(bp, "POST", "/sources/<id>/study-guide", study.study_guide, AUTH, SUMMARY_SOURCE,
    validate_body(s.study_guide_body))

# --- tutor chat ---------------------------------------------------------------
CHAT_SESSION = validate_params(s.chat_session_params)
add(bp, "GET", "/chat/history", chat.history, AUTH, validate_query(s.chat_language_query))
add(bp, "POST", "/chat/explain", chat.explain, AUTH, validate_body(s.explain_chat_schema))
add(bp, "GET", "/chat/conversation/<kitId>", chat.conversation, AUTH, validate_params(s.chat_kit_params),
    validate_query(s.chat_language_query))
add(bp, "POST", "/chat", chat.create, AUTH, validate_body(s.create_chat_schema))
add(bp, "POST", "/chat/<sessionId>/retry", chat.retry, AUTH, CHAT_SESSION)
add(bp, "GET", "/chat/<sessionId>/stream", chat.stream, AUTH, CHAT_SESSION)

# --- quiz ---------------------------------------------------------------------
ATTEMPT = validate_params(s.attempt_id_params)
add(bp, "POST", "/sources/<id>/quiz", study.generate_quiz, AUTH, validate_params(s.quiz_source_params),
    validate_body(s.generate_quiz_body))
add(bp, "POST", "/quizzes/<quizId>/attempts", study.start_quiz, AUTH, validate_params(s.quiz_id_params))
add(bp, "GET", "/attempts/<attemptId>", study.attempt, AUTH, ATTEMPT)
add(bp, "PUT", "/attempts/<attemptId>/answers", study.answer_quiz, AUTH, ATTEMPT, validate_body(s.answer_body))
add(bp, "POST", "/attempts/<attemptId>/submit", study.submit_quiz, AUTH, ATTEMPT)

# --- practice -----------------------------------------------------------------
PRACTICE = validate_params(s.practice_session_params)
add(bp, "GET", "/practice/home", study.practice_home, AUTH)
add(bp, "GET", "/practice/progress", study.practice_progress, AUTH)
add(bp, "GET", "/practice/topics", study.practice_topics, AUTH, validate_query(s.practice_topics_query))
add(bp, "POST", "/practice/sessions", study.create_practice, AUTH, validate_body(s.create_practice_body))
add(bp, "GET", "/practice/sessions/<sessionId>", study.get_practice, AUTH, PRACTICE)
add(bp, "PUT", "/practice/sessions/<sessionId>/answers", study.answer_practice, AUTH, PRACTICE,
    validate_body(s.practice_answer_body))
add(bp, "POST", "/practice/sessions/<sessionId>/submit", study.submit_practice, AUTH, PRACTICE,
    validate_body(s.submit_practice_body))

# --- flashcards ---------------------------------------------------------------
add(bp, "POST", "/sources/<id>/flashcards", study.generate_flashcards, AUTH,
    validate_params(s.flashcard_source_params), validate_body(s.generate_flashcards_body))
add(bp, "GET", "/flashcards/due", study.due_flashcards, AUTH, validate_query(s.due_flashcards_query))
add(bp, "POST", "/flashcards/<id>/review", study.review_flashcard, AUTH, validate_params(s.flashcard_params),
    validate_body(s.review_flashcard_body))

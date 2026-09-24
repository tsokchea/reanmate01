"""Summaries, study guides, quizzes, flashcards and practice.

Generation endpoints answer 200 when the cached result is ready and 202 while
it is still being written — the screens poll on 202.
"""

from flask import g

from ..services import flashcards_service, practice_service, quiz_service, study_guide_service, summaries_service
from . import respond


def _generation(result):
    return respond(result, 200 if result["status"] == "ready" else 202)


# --- summaries & study guide --------------------------------------------------


def summarize():
    return _generation(summaries_service.summarize(g.auth["user_id"], g.params["id"], g.body))


def chapters():
    return _generation(summaries_service.chapters(g.auth["user_id"], g.params["id"], g.body))


def study_guide():
    return _generation(study_guide_service.generate(g.auth["user_id"], g.params["id"], g.body))


# --- quiz ---------------------------------------------------------------------


def generate_quiz():
    return _generation(quiz_service.generate(g.auth["user_id"], g.auth["plan"], g.params["id"], g.body))


def start_quiz():
    return respond(quiz_service.start(g.auth["user_id"], g.params["quizId"]), 201)


def attempt():
    return respond(quiz_service.get_attempt(g.auth["user_id"], g.params["attemptId"]))


def answer_quiz():
    return respond(quiz_service.answer(g.auth["user_id"], g.params["attemptId"], g.body))


def submit_quiz():
    return respond(quiz_service.submit(g.auth["user_id"], g.params["attemptId"]))


# --- flashcards ---------------------------------------------------------------


def generate_flashcards():
    return _generation(flashcards_service.generate(g.auth["user_id"], g.auth["plan"], g.params["id"], g.body))


def due_flashcards():
    return respond(flashcards_service.due(g.auth["user_id"], g.query))


def review_flashcard():
    return respond(flashcards_service.review(g.auth["user_id"], g.params["id"], g.body["quality"]))


# --- practice -----------------------------------------------------------------


def practice_topics():
    return respond({"topics": practice_service.topics(g.auth["user_id"], g.query.get("q"), g.query.get("sourceId"))})


def create_practice():
    return respond(practice_service.create(g.auth["user_id"], g.auth["plan"], g.body), 201)


def get_practice():
    return respond(practice_service.get(g.auth["user_id"], g.params["sessionId"]))


def answer_practice():
    return respond(practice_service.answer(g.auth["user_id"], g.params["sessionId"], g.body))


def submit_practice():
    return respond(practice_service.submit(g.auth["user_id"], g.params["sessionId"], g.body))


def practice_home():
    return respond(practice_service.home(g.auth["user_id"]))


def practice_progress():
    return respond(practice_service.progress(g.auth["user_id"]))

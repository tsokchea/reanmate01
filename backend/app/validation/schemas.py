"""Request schemas — one per endpoint, ported 1:1 from server/src/validation/*.schemas.js.

Every endpoint validates its params, query and body against one of these
before its controller runs. Messages that the UI shows under a field
("Enter your name", "Use at least 8 characters", ...) are copied verbatim.
"""

import re

from ..services.onboarding_service import SURVEY_QUESTIONS
from ..utils.schema import (
    MISSING,
    array,
    boolean,
    discriminated_union,
    email,
    enum,
    iso_datetime,
    literal,
    null_value,
    number,
    obj,
    preprocess,
    record,
    strict_obj,
    string,
    union,
    uuid,
)


def _id(message="Not a valid id"):
    return uuid(message)


LANGUAGE = enum(["km", "en"])

# --- auth -------------------------------------------------------------------

MIN_PASSWORD = 8

# An empty string means "left blank", not "invalid": blanking it first makes
# both spellings of absent behave the same (.optional() sits INSIDE preprocess).
_optional_phone = preprocess(
    lambda value: MISSING if isinstance(value, str) and value.strip() == "" else value,
    string().trim()
    .transform(lambda value: re.sub(r"[\s\-().]", "", value))
    .refine(lambda value: bool(re.fullmatch(r"\+?\d{8,15}", value)), "Enter a valid phone number")
    .optional(),
)

_email = string().trim().lower().pipe(email("Enter a valid email address"))

register_schema = obj({
    "fullName": string().trim().min(1, "Enter your name").max(120),
    "email": _email.optional(),
    "phone": _optional_phone,
    "password": string().min(MIN_PASSWORD, f"Use at least {MIN_PASSWORD} characters").max(200),
    "locale": LANGUAGE.optional(),
    "role": enum(["student", "teacher"]),
}).refine(lambda data: bool(data.get("email") or data.get("phone")),
          "Provide an email address or a phone number", ["email"])

login_schema = obj({
    "identifier": string().trim().min(1, "Enter your email or phone number"),
    "password": string().min(1, "Enter your password"),
})

role_schema = obj({"role": enum(["student", "teacher"])})

# strictObject for answers: a misspelled answer key is a 422, not a silent drop.
survey_schema = obj({
    "answers": strict_obj({key: enum(values).optional() for key, values in SURVEY_QUESTIONS.items()}).default({}),
    "skipped": boolean().default(False),
    "complete": boolean().default(False),
})

# --- kits, folders, sources ---------------------------------------------------

KIT_ACCENTS = ["blue", "violet", "amber", "teal"]
KIT_ICONS = ["document", "database", "code", "share"]
KIT_STATUSES = ["in_progress", "completed", "archived"]

kit_id_params = obj({"kitId": _id()})
source_id_params = obj({"kitId": _id(), "sourceId": _id()})
folder_id_params = obj({"folderId": _id()})

kit_list_query = obj({
    "status": enum(KIT_STATUSES).optional(),
    "q": string().trim().min(1).max(200).optional(),
})

create_kit_schema = obj({
    "title": string().trim().min(1, "Give the kit a name").max(200),
    "titleKm": string().trim().max(200).optional(),
    "description": string().trim().max(2000).optional(),
    "subject": string().trim().max(200).optional(),
    "folderId": _id().nullable().optional(),
    "icon": enum(KIT_ICONS).optional(),
    "accent": enum(KIT_ACCENTS).optional(),
})

update_kit_schema = strict_obj({
    "title": string().trim().min(1).max(200).optional(),
    "titleKm": string().trim().max(200).optional(),
    "description": string().trim().max(2000).optional(),
    "subject": string().trim().max(200).optional(),
    "folderId": _id().nullable().optional(),
    "icon": enum(KIT_ICONS).optional(),
    "accent": enum(KIT_ACCENTS).optional(),
    "status": enum(KIT_STATUSES).optional(),
    "progress": number().int().min(0).max(100).optional(),
}).refine(lambda patch: len(patch) > 0, "Send at least one field to update")

create_folder_schema = obj({
    "name": string().trim().min(1, "Give the folder a name").max(200),
    "color": string().trim().max(40).optional(),
    "icon": string().trim().max(40).optional(),
    "sortOrder": number().int().min(0).max(10_000).optional(),
})

update_folder_schema = strict_obj({
    "name": string().trim().min(1).max(200).optional(),
    "color": string().trim().max(40).optional(),
    "icon": string().trim().max(40).optional(),
    "sortOrder": number().int().min(0).max(10_000).optional(),
}).refine(lambda patch: len(patch) > 0, "Send at least one field to update")

create_source_schema = discriminated_union("kind", {
    "youtube": obj({
        "kind": literal("youtube"),
        "url": string().trim().min(1, "Enter a YouTube URL"),
        "title": string().trim().max(200).optional(),
    }),
    "topic": obj({
        "kind": literal("topic"),
        "title": string().trim().min(1, "Enter a topic name").max(200),
    }),
})

# --- summaries / study guide --------------------------------------------------

summary_source_params = obj({"id": uuid("Not a valid source id")})
summarize_body = strict_obj({"language": LANGUAGE.default("km")})
chapters_body = strict_obj({
    "language": LANGUAGE.default("km"),
    "chapterCount": number().int().min(2).max(24).default(12),
})
study_guide_body = strict_obj({
    "language": LANGUAGE.default("km"),
    "moduleCount": number().int().min(2).max(16).default(8),
})

# --- chat -------------------------------------------------------------------

chat_session_params = obj({"sessionId": _id()})
chat_kit_params = obj({"kitId": _id()})
chat_language_query = obj({"language": LANGUAGE.default("km"), "sourceId": _id().optional()})
create_chat_schema = strict_obj({
    "kitId": _id(),
    "sourceId": _id().optional(),
    "content": string().trim().min(1).max(4000),
    "language": LANGUAGE.default("km"),
})
explain_chat_schema = create_chat_schema

# --- quiz -------------------------------------------------------------------

quiz_source_params = obj({"id": _id()})
quiz_id_params = obj({"quizId": _id()})
attempt_id_params = obj({"attemptId": _id()})
generate_quiz_body = strict_obj({
    "language": LANGUAGE.default("km"),
    "difficulty": enum(["easy", "medium", "hard", "mixed"]).default("mixed"),
})
_response = union([number().int().nonnegative(), string().trim().min(1).max(4000)])
answer_body = strict_obj({
    "questionId": _id(),
    "response": _response,
    "timeSpentSeconds": number().int().nonnegative().max(86400).optional(),
})

# --- practice -----------------------------------------------------------------

practice_session_params = obj({"sessionId": _id()})
practice_topics_query = obj({"q": string().trim().max(200).optional(), "sourceId": _id().optional()})
create_practice_body = strict_obj({
    "studyKitId": _id(),
    "sourceId": _id().optional(),
    "mode": enum(["practice", "mock_exam"]).default("practice"),
    "questionCount": number().int().min(1).max(100),
    "answerFormat": enum(["multiple_choice", "written"]),
    "timerSeconds": number().int().min(0).max(7200),
    "topicIds": array(_id()).max(100).default([]),
})
practice_answer_body = strict_obj({
    "position": number().int().min(1),
    "response": _response,
    "timeSpentSeconds": number().int().min(0).max(86400).optional(),
})
submit_practice_body = strict_obj({"durationSeconds": number().int().min(0).max(86400).optional()})

# --- flashcards ---------------------------------------------------------------

flashcard_source_params = obj({"id": _id()})
flashcard_params = obj({"id": _id()})
generate_flashcards_body = strict_obj({
    "language": LANGUAGE.default("km"),
    "regenerate": boolean().default(False),
    "round": number().int().positive().optional(),
})
due_flashcards_query = obj({
    "limit": number(coerce=True).int().min(1).max(100).default(20),
    "kitId": _id().optional(),
    "sourceId": _id().optional(),
})
review_flashcard_body = strict_obj({"quality": number().int().min(0).max(5)})

# --- classes ------------------------------------------------------------------

class_params = obj({"classId": _id()})
class_kit_params = obj({"classId": _id(), "kitId": _id()})
lesson_item_params = obj({"itemId": _id()})
create_class_body = strict_obj({
    "title": string().trim().min(1).max(200),
    "description": string().trim().max(2000).optional(),
    "subject": string().trim().max(200).optional(),
    "weekCount": number().int().min(1).max(52).default(12),
})
join_class_body = strict_obj({"code": string().trim().min(4).max(20).transform(str.upper)})
_lesson_item = strict_obj({
    "title": string().trim().min(1).max(200),
    "kind": enum(["reading", "video", "exercise", "quiz", "file"]).default("reading"),
    "contentMd": string().trim().max(100_000).optional(),
})
create_lesson_body = strict_obj({
    "weekNumber": number().int().min(1).max(52),
    "title": string().trim().min(1).max(200),
    "description": string().trim().max(2000).optional(),
    "kind": enum(["reading", "document", "video", "exercise"]).default("reading"),
    "contentMd": string().trim().max(100_000).optional(),
    "items": array(_lesson_item).min(1).max(50),
})

# --- assignments --------------------------------------------------------------

assignment_params = obj({"assignmentId": _id()})
lesson_assignment_params = obj({"lessonId": _id()})
grade_params = obj({"assignmentId": _id(), "submissionId": _id()})
_instructions = array(string().trim().min(1).max(1000)).max(30).default([])
create_assignment_body = strict_obj({
    "title": string().trim().min(1).max(200),
    "description": string().trim().max(4000).optional(),
    "instructions": _instructions,
    "dueAt": iso_datetime(),
    "type": enum(["file", "quiz"]),
    "quizId": _id().optional(),
    "points": number().nonnegative().max(100000).optional(),
}).refine(lambda v: v.get("type") != "quiz" or v.get("quizId"), "Quiz assignments require a quiz", ["quizId"])
save_submission_body = strict_obj({
    "answers": record(_id(), union([string().max(10000), number(), boolean(), null_value()])),
    "submit": boolean().default(False),
})
grade_submission_body = strict_obj({
    "score": number().nonnegative().max(100000),
    "feedback": string().trim().max(10000).optional(),
})

# --- profile ------------------------------------------------------------------

update_profile_body = strict_obj({
    "fullName": string().trim().min(1).max(120).optional(),
    "locale": LANGUAGE.optional(),
}).refine(lambda value: len(value) > 0, "Send at least one field")

# --- teacher ------------------------------------------------------------------

teacher_class_params = obj({"classId": _id()})
teacher_material_params = obj({"classId": _id(), "materialId": _id()})
teacher_assignment_params = obj({"assignmentId": _id()})
teacher_assignment_update_body = strict_obj({
    "title": string().trim().min(1).max(200),
    "description": string().trim().max(4000).optional(),
    "instructions": _instructions,
    "dueAt": iso_datetime().nullable(),
    "points": number().nonnegative().max(100000),
    "publish": boolean().optional(),
})
update_teacher_class_body = strict_obj({
    "title": string().trim().min(1).max(200).optional(),
    "description": string().trim().max(2000).nullable().optional(),
    "subject": string().trim().max(200).nullable().optional(),
    "status": enum(["active", "archived"]).optional(),
})
teacher_assistant_question_body = strict_obj({
    "classId": _id().optional(),
    "conversationId": _id().optional(),
    "content": string().trim().min(1).max(4000),
    "language": LANGUAGE.default("km"),
})
teacher_quiz_draft_body = strict_obj({
    "classId": _id(),
    "sourceMaterialIds": array(_id()).max(20).default([]),
    "title": string().trim().min(1).max(200).optional(),
    "language": LANGUAGE.default("km"),
    "difficulty": enum(["easy", "medium", "hard"]).default("medium"),
    "questionTypes": array(enum(["multipleChoice", "trueFalse", "shortAnswer"])).min(1).max(3)
    .default(["multipleChoice", "trueFalse"]),
    "count": number().int().min(1).max(30).default(10),
    "includeAnswerKey": boolean().default(True),
})
create_teacher_assignment_body = strict_obj({
    "classId": _id(),
    "title": string().trim().min(1).max(200),
    "description": string().trim().max(4000).optional(),
    "instructions": _instructions,
    "dueAt": iso_datetime().nullable().optional(),
    "points": number().nonnegative().max(100000).optional(),
    "type": enum(["file", "quiz"]).default("file"),
    "quizId": _id().optional(),
    "publish": boolean().default(True),
}).refine(lambda v: v.get("type") != "quiz" or v.get("quizId"), "Quiz assignments require a quiz", ["quizId"])
create_teacher_quiz_body = strict_obj({
    "classId": _id(),
    "title": string().trim().min(1).max(200),
    "language": LANGUAGE.default("km"),
    "count": number().int().min(1).max(30).default(10),
    "dueAt": iso_datetime().nullable().optional(),
    "points": number().nonnegative().max(100000).optional(),
    "publish": boolean().default(True),
    "questions": array(obj({
        "kind": enum(["multiple_choice", "true_false", "short_answer"]),
        "prompt": string().trim().min(1).max(4000),
        "options": array(string().trim().max(1000)).max(4).default([]),
        "correctAnswer": union([number().int().nonnegative(), string().trim()]),
        "explanation": string().max(4000).default(""),
    })).max(30).optional(),
})

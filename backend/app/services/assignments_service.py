"""Assignments and submissions (server/src/services/assignments.service.js)."""

from ..middleware.errors import ApiError
from ..middleware.upload import relative_upload_path, remove_uploaded_file, verify_uploaded_file
from ..models import assignments as assignments_db
from ..utils.serialization import UNDEFINED
from . import usage_service
from .assignment_state_machine import assert_assignment_transition


def _first(*values, default=None):
    """JS ``a ?? b ?? c``."""
    for value in values:
        if value is not None and value is not UNDEFINED:
            return value
    return default


def _submission_api(row):
    return {
        "id": _first(row.get("submission_id"), row.get("id")),
        "status": _first(row.get("submission_status"), row.get("status"), default="not_started"),
        "completed": _first(row.get("completed_questions"), default=0),
        "answers": _first(row.get("answers"), default={}),
        "files": _first(row.get("files"), default=[]),
        "isLate": bool(row.get("is_late")),
        "submittedAt": row.get("submitted_at"),
        "gradedAt": row.get("graded_at"),
        "score": row.get("score"),
        "feedback": row.get("feedback"),
    }


def _assignment_api(row):
    return {
        "id": row["id"], "classId": row["class_id"], "lessonId": row["lesson_id"], "quizId": row["quiz_id"],
        "title": row["title"],
        # class_name only exists on the detail read; on create it was undefined and omitted.
        "className": row.get("class_name", UNDEFINED),
        "overview": row["description"], "instructions": row["instructions"] or [], "dueAt": row["due_at"],
        "points": row["points"], "questionCount": row["question_count"], "type": row["assignment_type"],
        "allowFileUpload": row["allow_file_upload"], "materials": row.get("materials") or [],
    }


def create(teacher_id, lesson_id, data):
    usage_service.check(teacher_id, "assignments", 1)
    row = assignments_db.create(teacher_id=teacher_id, lesson_id=lesson_id, input=data)
    if not row:
        raise ApiError.not_found("That lesson or quiz does not exist")
    usage_service.record(teacher_id, assignments=1)
    return {"assignment": _assignment_api(row)}


def get(user_id, assignment_id):
    row = assignments_db.detail(user_id=user_id, assignment_id=assignment_id)
    if not row:
        raise ApiError.not_found("That assignment does not exist")
    return {"assignment": _assignment_api(row), "submission": _submission_api(row)}


def questions(user_id, assignment_id):
    rows = assignments_db.questions(user_id=user_id, assignment_id=assignment_id)
    return {"questions": [{"id": r["id"], "position": r["position"], "prompt": r["prompt"], "options": r["options"]}
                          for r in rows]}


def save_quiz(user_id, assignment_id, data):
    result = assignments_db.save_quiz(user_id=user_id, assignment_id=assignment_id, answers=data["answers"],
                                      submit=data["submit"])
    if not result:
        raise ApiError.not_found("That quiz assignment does not exist")
    if result.get("invalidAnswers"):
        raise ApiError.bad_request("One or more answers do not belong to this assignment")
    if result.get("incomplete"):
        raise ApiError.conflict("Answer every question before submitting")
    if result.get("terminal"):
        raise ApiError.conflict("That assignment has already been submitted")
    row = result["row"]
    assert_assignment_transition("in_progress" if row["submitted_at"] else "not_started", row["status"])
    return {"submission": _submission_api(row)}


def upload(user_id, assignment_id, file):
    if not file:
        raise ApiError.bad_request("Choose one file to submit")
    verified = verify_uploaded_file(file)
    saved_file = {**file, **verified, "storagePath": relative_upload_path(file["path"])}
    try:
        usage_service.check_upload(user_id, verified["byteSize"])
        result = assignments_db.add_file(user_id=user_id, assignment_id=assignment_id, file=saved_file)
        if not result:
            raise ApiError.not_found("That file assignment does not exist")
        if result.get("terminal"):
            raise ApiError.conflict("That assignment has already been submitted")
        assert_assignment_transition("not_started", result["row"]["status"])
        usage_service.record_upload(user_id, verified["byteSize"])
        stored = result["file"]
        return {
            "submission": _submission_api(result["row"]),
            "file": {"id": stored["id"], "name": stored["original_filename"], "size": int(stored["byte_size"]),
                     "uploadedAt": stored["uploaded_at"]},
        }
    except Exception:
        try:
            remove_uploaded_file(file["path"])
        except OSError:
            pass
        raise


def submissions(teacher_id, assignment_id):
    rows = assignments_db.submissions(teacher_id=teacher_id, assignment_id=assignment_id)
    return {"submissions": [{**_submission_api(row), "studentId": row["user_id"], "studentName": row["student_name"],
                             "fileCount": row["file_count"]} for row in rows]}


def grade(teacher_id, assignment_id, submission_id, data):
    row = assignments_db.grade(teacher_id=teacher_id, assignment_id=assignment_id, submission_id=submission_id,
                               score=data["score"], feedback=data.get("feedback"))
    if not row:
        raise ApiError.conflict("Only a submitted assignment can be graded")
    return {"submission": _submission_api(row)}

"""Classes, lessons, assignments and the teacher workspace."""

from flask import g, send_file

from ..services import assignments_service, classes_service, teacher_assistant_service, teacher_service
from . import respond


def _file(result, inline=False):
    response = send_file(result["path"], mimetype=result.get("mimeType") or "application/octet-stream",
                         conditional=True)
    if inline:
        response.headers["Content-Disposition"] = "inline"
    return response


def _form(key):
    body = g.get("body")
    return body.get(key) if isinstance(body, dict) else None


# --- classes ------------------------------------------------------------------


def list_classes():
    return respond(classes_service.list_classes(g.auth["user_id"]))


def show_class():
    return respond(classes_service.get(g.auth["user_id"], g.params["classId"]))


def remove_class():
    return respond(classes_service.remove(g.auth["user_id"], g.params["classId"]))


def create_class():
    return respond(classes_service.create(g.auth["user_id"], g.body), 201)


def set_cover():
    return respond(classes_service.set_cover(g.auth["user_id"], g.params["classId"], g.get("file")), 201)


def cover():
    return _file(classes_service.cover(g.auth["user_id"], g.params["classId"]))


def join_class():
    return respond(classes_service.join(g.auth["user_id"], g.body["code"]), 201)


def create_lesson():
    return respond(classes_service.create_lesson(g.auth["user_id"], g.params["classId"], g.body), 201)


def share_kit():
    return respond(classes_service.share_kit(g.auth["user_id"], g.params["classId"], g.params["kitId"]))


def complete_item():
    return respond(classes_service.complete_item(g.auth["user_id"], g.params["itemId"]))


# --- assignments --------------------------------------------------------------


def create_assignment():
    return respond(assignments_service.create(g.auth["user_id"], g.params["lessonId"], g.body), 201)


def show_assignment():
    return respond(assignments_service.get(g.auth["user_id"], g.params["assignmentId"]))


def assignment_questions():
    return respond(assignments_service.questions(g.auth["user_id"], g.params["assignmentId"]))


def save_submission():
    return respond(assignments_service.save_quiz(g.auth["user_id"], g.params["assignmentId"], g.body))


def upload_submission():
    return respond(assignments_service.upload(g.auth["user_id"], g.params["assignmentId"], g.get("file")), 201)


def list_submissions():
    return respond(assignments_service.submissions(g.auth["user_id"], g.params["assignmentId"]))


def grade_submission():
    return respond(assignments_service.grade(g.auth["user_id"], g.params["assignmentId"],
                                             g.params["submissionId"], g.body))


# --- teacher ------------------------------------------------------------------


def dashboard():
    return respond(teacher_service.dashboard(g.auth["user_id"]))


def update_class():
    return respond(teacher_service.update_class(g.auth["user_id"], g.params["classId"], g.body))


def students():
    return respond(teacher_service.students(g.auth["user_id"], g.params["classId"]))


def teacher_assignments():
    return respond(teacher_service.assignments(g.auth["user_id"]))


def teacher_assignment():
    return respond(teacher_service.assignment(g.auth["user_id"], g.params["assignmentId"]))


def update_teacher_assignment():
    return respond(teacher_service.update_assignment(g.auth["user_id"], g.params["assignmentId"], g.body))


def delete_teacher_assignment():
    return respond(teacher_service.delete_assignment(g.auth["user_id"], g.params["assignmentId"]))


def create_teacher_assignment():
    return respond(teacher_service.create_assignment(g.auth["user_id"], g.body), 201)


def create_teacher_quiz():
    return respond(teacher_service.create_quiz(g.auth["user_id"], g.body), 201)


def add_assignment_attachment():
    return respond(teacher_service.add_assignment_attachment(g.auth["user_id"], g.params["assignmentId"],
                                                             g.get("file")), 201)


def materials():
    return respond(teacher_service.materials(g.auth["user_id"], g.params["classId"]))


def material_file():
    return _file(teacher_service.material_file(g.auth["user_id"], g.params["classId"], g.params["materialId"]),
                 inline=True)


def add_material():
    return respond(teacher_service.add_material(g.auth["user_id"], g.params["classId"], g.get("file"),
                                                _form("title"), _form("weekNumber")), 201)


def remove_material():
    return respond(teacher_service.remove_material(g.auth["user_id"], g.params["classId"], g.params["materialId"]))


def assistant_ask():
    return respond(teacher_assistant_service.ask(g.auth["user_id"], g.body))


def assistant_history():
    return respond(teacher_assistant_service.history(g.auth["user_id"]))


def clear_assistant_history():
    return respond(teacher_assistant_service.clear_history(g.auth["user_id"]))


def assistant_quiz():
    return respond(teacher_assistant_service.generate_quiz(g.auth["user_id"], g.body))

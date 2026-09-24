"""The teacher workspace. Every route requires a session and the teacher role."""

from flask import Blueprint

from ..controllers import classes_controller as c
from ..middleware.upload import handle_upload
from ..middleware.validate import validate_body, validate_params
from ..validation import schemas as s
from . import AUTH, TEACHER, add

bp = Blueprint("teacher", __name__, url_prefix="/api/teacher")

GUARD = (*AUTH, TEACHER)
ASSIGNMENT = validate_params(s.teacher_assignment_params)
CLASS = validate_params(s.teacher_class_params)
MATERIAL = validate_params(s.teacher_material_params)

add(bp, "GET", "/dashboard", c.dashboard, GUARD)
add(bp, "GET", "/assignments", c.teacher_assignments, GUARD)
add(bp, "GET", "/assignments/<assignmentId>", c.teacher_assignment, GUARD, ASSIGNMENT)
add(bp, "PATCH", "/assignments/<assignmentId>", c.update_teacher_assignment, GUARD, ASSIGNMENT,
    validate_body(s.teacher_assignment_update_body))
add(bp, "DELETE", "/assignments/<assignmentId>", c.delete_teacher_assignment, GUARD, ASSIGNMENT)
add(bp, "POST", "/assignments", c.create_teacher_assignment, GUARD, validate_body(s.create_teacher_assignment_body))
add(bp, "POST", "/quizzes", c.create_teacher_quiz, GUARD, validate_body(s.create_teacher_quiz_body))
add(bp, "POST", "/assignments/<assignmentId>/attachment", c.add_assignment_attachment, GUARD, ASSIGNMENT,
    handle_upload)
add(bp, "POST", "/assistant/ask", c.assistant_ask, GUARD, validate_body(s.teacher_assistant_question_body))
add(bp, "GET", "/assistant/history", c.assistant_history, GUARD)
add(bp, "DELETE", "/assistant/history", c.clear_assistant_history, GUARD)
add(bp, "POST", "/assistant/quiz", c.assistant_quiz, GUARD, validate_body(s.teacher_quiz_draft_body))
add(bp, "GET", "/classes/<classId>/students", c.students, GUARD, CLASS)
add(bp, "GET", "/classes/<classId>/materials", c.materials, GUARD, CLASS)
add(bp, "POST", "/classes/<classId>/materials", c.add_material, GUARD, CLASS, handle_upload)
add(bp, "GET", "/classes/<classId>/materials/<materialId>/file", c.material_file, GUARD, MATERIAL)
add(bp, "DELETE", "/classes/<classId>/materials/<materialId>", c.remove_material, GUARD, MATERIAL)
add(bp, "PATCH", "/classes/<classId>", c.update_class, GUARD, CLASS, validate_body(s.update_teacher_class_body))

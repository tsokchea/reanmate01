"""Classes, lessons and assignments (student and teacher sides)."""

from flask import Blueprint

from ..controllers import classes_controller as c
from ..middleware.upload import handle_upload
from ..middleware.validate import validate_body, validate_params
from ..validation import schemas as s
from . import AUTH, STUDENT, TEACHER, add

bp = Blueprint("classes", __name__, url_prefix="/api")

CLASS = validate_params(s.class_params)
ASSIGNMENT = validate_params(s.assignment_params)

add(bp, "GET", "/classes", c.list_classes, AUTH)
add(bp, "POST", "/classes", c.create_class, AUTH, TEACHER, validate_body(s.create_class_body))
add(bp, "POST", "/classes/join", c.join_class, AUTH, STUDENT, validate_body(s.join_class_body))
add(bp, "POST", "/classes/<classId>/cover", c.set_cover, AUTH, TEACHER, CLASS, handle_upload)
add(bp, "GET", "/classes/<classId>/cover", c.cover, AUTH, CLASS)
add(bp, "GET", "/classes/<classId>", c.show_class, AUTH, CLASS)
add(bp, "DELETE", "/classes/<classId>", c.remove_class, AUTH, TEACHER, CLASS)
add(bp, "POST", "/classes/<classId>/lessons", c.create_lesson, AUTH, TEACHER, CLASS,
    validate_body(s.create_lesson_body))
add(bp, "POST", "/classes/<classId>/kits/<kitId>", c.share_kit, AUTH, TEACHER, validate_params(s.class_kit_params))
add(bp, "POST", "/classes/lesson-items/<itemId>/complete", c.complete_item, AUTH, STUDENT,
    validate_params(s.lesson_item_params))

add(bp, "POST", "/lessons/<lessonId>/assignments", c.create_assignment, AUTH, TEACHER,
    validate_params(s.lesson_assignment_params), validate_body(s.create_assignment_body))
add(bp, "GET", "/assignments/<assignmentId>", c.show_assignment, AUTH, ASSIGNMENT)
add(bp, "GET", "/assignments/<assignmentId>/questions", c.assignment_questions, AUTH, ASSIGNMENT)
add(bp, "PUT", "/assignments/<assignmentId>/submission", c.save_submission, AUTH, STUDENT, ASSIGNMENT,
    validate_body(s.save_submission_body))
add(bp, "POST", "/assignments/<assignmentId>/submission/files", c.upload_submission, AUTH, STUDENT, ASSIGNMENT,
    handle_upload)
add(bp, "GET", "/assignments/<assignmentId>/submissions", c.list_submissions, AUTH, TEACHER, ASSIGNMENT)
add(bp, "PATCH", "/assignments/<assignmentId>/submissions/<submissionId>", c.grade_submission, AUTH, TEACHER,
    validate_params(s.grade_params), validate_body(s.grade_submission_body))

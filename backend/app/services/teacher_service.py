"""The teacher workspace (server/src/services/teacher.service.js)."""

from ..ai import get_ai
from ..middleware.errors import ApiError
from ..middleware.upload import absolute_upload_path, relative_upload_path, remove_uploaded_file, verify_uploaded_file
from ..models import teacher as teacher_db
from ..utils.js import js_trim


def _number(value):
    """Number(value ?? 0) for the int/int8/numeric-string values rows carry."""
    if value is None:
        return 0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return int(number) if number.is_integer() else number


def _js_number(value):
    """Number(value) for a form field: '' -> 0, junk -> NaN."""
    if value is None:
        return 0
    text = str(value).strip()
    if text == "":
        return 0
    try:
        return float(text)
    except ValueError:
        return float("nan")


def dashboard(teacher_id):
    data = teacher_db.dashboard(teacher_id)
    summary = data["summary"]
    return {
        "summary": {
            "activeClasses": _number(summary["active_classes"]),
            "totalStudents": _number(summary["total_students"]),
            "pendingReviews": _number(summary["pending_reviews"]),
            "returnedSubmissions": _number(summary["returned_submissions"]),
        },
        "classes": [{
            "id": row["id"], "title": row["title"], "subject": row["subject"],
            "coverUrl": f"/api/classes/{row['id']}/cover" if row["cover_image_path"] else None,
            "joinCode": row["join_code"], "studentCount": _number(row["student_count"]),
            "lessonCount": _number(row["lesson_count"]), "completedLessons": _number(row["completed_lessons"]),
        } for row in data["classes"]],
        "assignments": [{
            "id": row["id"], "title": row["title"], "classId": row["class_id"], "className": row["class_name"],
            "dueAt": row["due_at"], "submissionCount": _number(row["submission_count"]),
            "pendingCount": _number(row["pending_count"]), "gradedCount": _number(row["graded_count"]),
            "studentCount": _number(row["student_count"]),
        } for row in data["assignments"]],
    }


def update_class(teacher_id, class_id, patch):
    row = teacher_db.update_class(teacher_id=teacher_id, class_id=class_id, patch=patch)
    if not row:
        raise ApiError.not_found("That class does not exist or is not yours")
    return {"class": {
        "id": row["id"], "title": row["title"], "description": row["description"], "subject": row["subject"],
        "joinCode": row["join_code"], "weekCount": row["week_count"], "coverColor": row["cover_color"],
        "status": row["status"],
    }}


def students(teacher_id, class_id):
    return {"students": [{
        "id": row["id"], "name": row["name"], "joinedAt": row["joined_at"],
        "lessonCount": _number(row["lesson_count"]), "completedLessons": _number(row["completed_lessons"]),
        "assignmentCount": _number(row["assignment_count"]),
        "submittedAssignments": _number(row["submitted_assignments"]),
        "gradedAssignments": _number(row["graded_assignments"]), "averageScore": _number(row["average_score"]),
    } for row in teacher_db.students(teacher_id=teacher_id, class_id=class_id)]}


def assignments(teacher_id):
    return {"assignments": [{
        "id": row["id"], "classId": row["class_id"], "className": row["class_name"], "title": row["title"],
        "description": row["description"], "type": row["assignment_type"], "status": row["status"],
        "dueAt": row["due_at"], "points": row["points"], "questionCount": row["question_count"],
        "studentCount": _number(row["student_count"]), "submissionCount": _number(row["submission_count"]),
        "pendingCount": _number(row["pending_count"]), "gradedCount": _number(row["graded_count"]),
    } for row in teacher_db.assignments(teacher_id)]}


def assignment(teacher_id, assignment_id):
    row = teacher_db.assignment(teacher_id=teacher_id, assignment_id=assignment_id)
    if not row:
        raise ApiError.not_found("That assignment does not exist or is not yours")
    return {"assignment": {
        "id": row["id"], "classId": row["class_id"], "quizId": row["quiz_id"], "className": row["class_name"],
        "title": row["title"], "description": row["description"], "instructions": row["instructions"] or [],
        "dueAt": row["due_at"], "points": _number(row["points"]), "questionCount": row["question_count"],
        "type": row["assignment_type"], "allowFileUpload": row["allow_file_upload"], "status": row["status"],
        "materials": row["materials"] or [],
    }}


def update_assignment(teacher_id, assignment_id, data):
    row = teacher_db.update_assignment(teacher_id=teacher_id, assignment_id=assignment_id, input=data)
    if not row:
        raise ApiError.not_found("That assignment does not exist or is not yours")
    return {"assignment": {
        "id": row["id"], "classId": row["class_id"], "title": row["title"], "description": row["description"],
        "instructions": row["instructions"] or [], "dueAt": row["due_at"], "points": _number(row["points"]),
        "type": row["assignment_type"], "status": row["status"],
    }}


def delete_assignment(teacher_id, assignment_id):
    result = teacher_db.delete_assignment(teacher_id=teacher_id, assignment_id=assignment_id)
    if not result:
        raise ApiError.not_found("That assignment does not exist or is not yours")
    for material in result.get("materials") or []:
        if material["storage_path"]:
            try:
                remove_uploaded_file(absolute_upload_path(material["storage_path"]))
            except OSError:
                pass
    return {"deleted": True, "assignmentId": assignment_id}


def create_assignment(teacher_id, data):
    row = teacher_db.create_assignment(teacher_id=teacher_id, input=data)
    if not row:
        raise ApiError.not_found("That class or quiz does not exist, or it is not yours")
    return {"assignment": {
        "id": row["id"], "classId": row["class_id"], "lessonId": row["lesson_id"], "quizId": row["quiz_id"],
        "title": row["title"], "description": row["description"], "instructions": row["instructions"],
        "dueAt": row["due_at"], "points": row["points"], "questionCount": row["question_count"],
        "type": row["assignment_type"], "status": row["status"], "allowFileUpload": row["allow_file_upload"],
    }}


def create_quiz(teacher_id, data):
    context = teacher_db.class_context(teacher_id=teacher_id, class_id=data["classId"])
    if not context:
        raise ApiError.not_found("That class does not exist or is not yours")
    text = "\n\n".join(
        "\n".join(part for part in [row["lesson_title"], row["content_md"], row["item_title"], row["item_content"]]
                  if part)
        for row in context if row["content_md"] or row["item_content"]
    ) or f"Class: {context[0]['class_title']}"
    if data.get("questions"):
        generated = {"title": data["title"], "questions": data["questions"]}
    else:
        generated = get_ai().generate_quiz(text=text, title=data["title"], language=data["language"],
                                           count=data["count"])
    if not (generated or {}).get("questions"):
        raise ApiError.bad_request("The quiz could not be generated")
    result = teacher_db.create_quiz(teacher_id=teacher_id, input=data, quiz=generated)
    if not result:
        raise ApiError.not_found("That class does not exist or is not yours")
    quiz = result["quiz"]
    return {"quiz": {"id": quiz["id"], "title": quiz["title"], "questionCount": quiz["question_count"]},
            "assignment": result["assignment"]}


def add_assignment_attachment(teacher_id, assignment_id, file):
    if not file:
        raise ApiError.bad_request("Choose one attachment file")
    verified = verify_uploaded_file(file)
    saved_file = {**file, **verified, "storagePath": relative_upload_path(file["path"])}
    try:
        row = teacher_db.add_assignment_attachment(teacher_id=teacher_id, assignment_id=assignment_id, file=saved_file)
        if not row:
            raise ApiError.not_found("That assignment does not exist or is not yours")
        return {"material": {
            "id": row["id"], "assignmentId": row["assignment_id"], "title": row["title"],
            "originalFilename": row["original_filename"], "mimeType": row["mime_type"],
            "byteSize": _number(row["byte_size"]),
        }}
    except Exception:
        try:
            remove_uploaded_file(file["path"])
        except OSError:
            pass
        raise


def materials(teacher_id, class_id):
    return {"materials": [{
        "id": row["id"], "title": row["title"], "originalFilename": row["original_filename"],
        "mimeType": row["mime_type"], "byteSize": _number(row["byte_size"]), "lessonId": row["lesson_id"],
        "week": _number(row["week_number"] if row["week_number"] is not None else 1),
        "createdAt": row["created_at"],
    } for row in teacher_db.materials(teacher_id=teacher_id, class_id=class_id)]}


def material_file(teacher_id, class_id, material_id):
    row = teacher_db.material_file(teacher_id=teacher_id, class_id=class_id, material_id=material_id)
    if not row:
        raise ApiError.not_found("That material does not exist or is not yours")
    return {"path": absolute_upload_path(row["storage_path"]), "mimeType": row["mime_type"],
            "originalFilename": row["original_filename"]}


def add_material(teacher_id, class_id, file, title=None, week_number=1):
    if not file:
        raise ApiError.bad_request("Choose one material file")
    verified = verify_uploaded_file(file)
    saved_file = {**file, **verified, "storagePath": relative_upload_path(file["path"])}
    try:
        week = _js_number(week_number)  # Number(weekNumber) || 1: NaN and 0 fall back to week 1
        week = 1 if week != week or week == 0 else (int(week) if float(week).is_integer() else week)
        row = teacher_db.add_material(
            teacher_id=teacher_id, class_id=class_id,
            title=(js_trim(title) if isinstance(title, str) else "") or file["originalname"],
            week_number=week, file=saved_file,
        )
        if not row:
            raise ApiError.not_found("That class does not exist or is not yours")
        return {"material": {
            "id": row["id"], "title": row["title"], "originalFilename": row["original_filename"],
            "mimeType": row["mime_type"], "byteSize": _number(row["byte_size"]), "createdAt": row["created_at"],
            "week": _number(row["week_number"] if row["week_number"] is not None else week_number or 1),
        }}
    except Exception:
        try:
            remove_uploaded_file(file["path"])
        except OSError:
            pass
        raise


def remove_material(teacher_id, class_id, material_id):
    row = teacher_db.remove_material(teacher_id=teacher_id, class_id=class_id, material_id=material_id)
    if not row:
        raise ApiError.not_found("That material does not exist or is not yours")
    remove_uploaded_file(absolute_upload_path(row["storage_path"]))
    return {"deleted": True, "materialId": material_id}

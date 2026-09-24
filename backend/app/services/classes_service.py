"""Classes, lessons and enrollment (server/src/services/classes.service.js)."""

import secrets

from psycopg import errors as pg_errors

from ..middleware.errors import ApiError
from ..middleware.upload import absolute_upload_path, relative_upload_path, remove_uploaded_file, verify_uploaded_file
from ..models import classes as classes_db
from ..utils.serialization import UNDEFINED


def _class_api(row):
    return {
        "id": row["id"], "title": row["title"], "description": row["description"], "subject": row["subject"],
        "coverUrl": f"/api/classes/{row['id']}/cover" if row.get("cover_image_path") else None,
        "teacher": row["teacher_name"], "teacherId": row["teacher_id"], "joinCode": row["join_code"],
        "weeks": row["week_count"], "lessonCount": row["lesson_count"], "lessonsDone": row["lessons_done"],
        "status": row["status"],
    }


def _group_by_week(rows):
    groups = {}
    for row in rows:
        week = row["week_number"]
        groups.setdefault(week, {"week": week, "lessons": []})["lessons"].append({
            "id": row["id"], "title": row["title"], "description": row["description"], "kind": row["kind"],
            "position": row["position"], "status": row["progress_status"], "done": row["completed_items"],
            "total": row["item_count"], "items": row["items"],
        })
    # Object.values of integer-like keys iterates in ascending numeric order.
    return [groups[week] for week in sorted(groups)]


def list_classes(user_id):
    return {"classes": [_class_api(row) for row in classes_db.list_for_user(user_id)]}


def get(user_id, class_id):
    klass = classes_db.detail(user_id, class_id)
    if not klass:
        raise ApiError.not_found("That class does not exist")
    lessons = classes_db.lessons(user_id, class_id)
    materials = classes_db.materials(user_id, class_id)
    quizzes = classes_db.quizzes(user_id, class_id)
    assignments = classes_db.assignments(user_id, class_id)
    return {
        "class": _class_api(klass),
        "weeks": _group_by_week(lessons),
        "materials": [{"id": r["id"], "title": r["title"], "mimeType": r["mime_type"],
                       "byteSize": int(r["byte_size"] or 0), "week": r["week_number"]} for r in materials],
        "quizzes": [{"id": r["id"], "title": r["title"], "questionCount": r["question_count"], "status": r["status"],
                     "week": r["week_number"], "kitId": r["study_kit_id"]} for r in quizzes],
        # quiz_id is not selected by the query, so (as in Express) quizId is omitted.
        "assignments": [{"id": r["id"], "quizId": r.get("quiz_id", UNDEFINED), "title": r["title"], "dueAt": r["due_at"],
                         "status": r["status"], "type": r["assignment_type"], "week": r["week_number"]}
                        for r in assignments],
    }


def remove(teacher_id, class_id):
    row = classes_db.remove(teacher_id, class_id)
    if not row:
        raise ApiError.not_found("That class does not exist or is not yours")
    return {"deleted": True, "classId": row["id"]}


def create(teacher_id, data):
    for attempt in range(5):
        try:
            row = classes_db.create(teacher_id=teacher_id, title=data["title"], description=data.get("description"),
                                    subject=data.get("subject"), weekCount=data["weekCount"],
                                    join_code=secrets.token_hex(4)[:6].upper())
            return {"class": _class_api({**row, "teacher_name": None, "lesson_count": 0, "lessons_done": 0})}
        except pg_errors.UniqueViolation:
            if attempt == 4:
                raise
    raise ApiError.conflict("Could not allocate a class code")


def set_cover(teacher_id, class_id, file):
    if not file:
        raise ApiError.bad_request("Choose a class cover image")
    try:
        verified = verify_uploaded_file(file)
        if verified["kind"] != "image":
            raise ApiError.bad_request("A class cover must be an image")
        row = classes_db.set_cover(teacher_id=teacher_id, class_id=class_id,
                                   storage_path=relative_upload_path(file["path"]), mime_type=file["mimetype"],
                                   byte_size=verified["byteSize"])
        if not row:
            raise ApiError.not_found("That class does not exist")
        return {"coverUrl": f"/api/classes/{class_id}/cover"}
    except Exception:
        try:
            remove_uploaded_file(file["path"])
        except OSError:
            pass
        raise


def cover(user_id, class_id):
    row = classes_db.cover(user_id=user_id, class_id=class_id)
    if not row or not row["cover_image_path"]:
        raise ApiError.not_found("That class has no cover image")
    return {"path": absolute_upload_path(row["cover_image_path"]), "mimeType": row["cover_image_mime_type"]}


def join(user_id, code):
    joined = classes_db.join(user_id=user_id, code=code)
    if not joined:
        raise ApiError.not_found("That class code is not valid")
    return get(user_id, joined["class_id"])


def create_lesson(teacher_id, class_id, data):
    lesson = classes_db.create_lesson(teacher_id=teacher_id, class_id=class_id, lesson=data, items=data["items"])
    if not lesson:
        raise ApiError.not_found("That class does not exist or the week is outside its schedule")
    return {"lesson": {"id": lesson["id"], "classId": class_id, "weekNumber": lesson["week_number"],
                       "position": lesson["position"], "title": lesson["title"], "kind": lesson["kind"],
                       "items": data["items"]}}


def share_kit(teacher_id, class_id, kit_id):
    kit = classes_db.share_kit(teacher_id=teacher_id, class_id=class_id, kit_id=kit_id)
    if not kit:
        raise ApiError.not_found("That class or study kit does not exist")
    return {"kit": {"id": kit["id"], "classId": kit["class_id"]}}


def complete_item(user_id, item_id):
    progress = classes_db.complete_item(user_id=user_id, item_id=item_id)
    if not progress:
        raise ApiError.not_found("That lesson item does not exist")
    return {"progress": {"lessonId": progress["lesson_id"], "status": progress["status"],
                         "startedAt": progress["started_at"], "completedAt": progress["completed_at"]}}

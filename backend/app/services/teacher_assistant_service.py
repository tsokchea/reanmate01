"""The teacher's AI copilot (server/src/services/teacherAssistant.service.js)."""

from concurrent.futures import ThreadPoolExecutor

from ..ai import get_ai
from ..ingest.office import extract_document
from ..ingest.pdf import extract_pdf
from ..middleware.errors import ApiError
from ..middleware.upload import absolute_upload_path
from ..models import teacher as teacher_db
from .ai_usage_service import track_generation
from .quiz_service import balance_answer_positions


def _context_for(rows):
    return "\n\n".join(
        "\n".join(part for part in [row["lesson_title"], row["content_md"], row["item_title"], row["item_content"]]
                  if part)
        for row in rows if row["content_md"] or row["item_content"]
    )


def _require_context(teacher_id, class_id):
    rows = teacher_db.class_context(teacher_id=teacher_id, class_id=class_id)
    if not rows:
        raise ApiError.not_found("That class does not exist or is not yours")
    return {
        "title": rows[0]["class_title"],
        "subject": rows[0]["subject"],
        "text": _context_for(rows)
        or f"Class: {rows[0]['class_title']}\nSubject: {rows[0]['subject'] if rows[0]['subject'] is not None else 'General'}",
    }


def _material_text(material, language, teacher_id=None):
    path = absolute_upload_path(material["storage_path"])
    if material["mime_type"] == "application/pdf":
        return extract_pdf(path)["fullText"]
    if (material["mime_type"] or "").startswith("image/"):
        with open(path, "rb") as handle:
            data = handle.read()
        result = track_generation(
            kind="ocr", user_id=teacher_id, language=language,
            request={"teacherMaterial": material.get("id")},
            describe=lambda v: {"hasText": bool(v.get("hasText"))},
            run=lambda ai, on_usage: ai.extract_image_text(
                images=[{"data": data, "mimeType": material["mime_type"]}], language=language, on_usage=on_usage),
        )
        return result["text"] if result["hasText"] else ""
    return extract_document(path, mime_type=material["mime_type"])["fullText"]


def ask(teacher_id, data):
    context = _require_context(teacher_id, data["classId"]) if data.get("classId") else None
    conversation = teacher_db.assistant_conversation(teacher_id=teacher_id, conversation_id=data.get("conversationId"),
                                                     class_id=data.get("classId"), language=data["language"])
    if not conversation:
        raise ApiError.not_found("That assistant conversation does not exist")
    history = teacher_db.assistant_messages(teacher_id=teacher_id, conversation_id=conversation["id"])
    teacher_db.add_assistant_message(teacher_id=teacher_id, conversation_id=conversation["id"], role="user",
                                     content=data["content"])

    preamble = ("You are a teaching copilot for a teacher. Give practical, accurate help with lesson planning, "
                "assignment design, grading, and student support.")
    if context:
        prompt = (f"{preamble} Use the selected class context only when it answers the question. If it does not, "
                  f"say what information is missing.\n\nClass context:\n{context['text']}\n\nTeacher question:\n"
                  f"{data['content']}")
    else:
        prompt = (f"{preamble} If you do not have enough information, say what is missing.\n\nTeacher question:\n"
                  f"{data['content']}")
    messages = [*({"role": m["role"], "content": m["content"]} for m in history), {"role": "user", "content": prompt}]

    def run(ai, on_usage):
        content, citations = "", []
        for chunk in ai.tutor_reply(messages=messages, language=data["language"],
                                    sources=[{"title": context["title"], "content": context["text"]}] if context else [],
                                    max_output_tokens=500, on_usage=on_usage):
            if chunk["type"] == "delta":
                content += chunk["text"]
            elif chunk["type"] == "done":
                citations = chunk.get("citations") or []
            elif chunk["type"] == "error":
                raise ApiError.bad_request(chunk["message"])
        return {"content": content, "citations": citations}

    result = track_generation(
        kind="tutor", user_id=teacher_id, language=data["language"],
        source_text=context["text"] if context else "",
        request={"teacherAssistant": True, "classId": data.get("classId")},
        describe=lambda v: {"answerChars": len(v["content"])},
        run=run,
    )
    teacher_db.add_assistant_message(teacher_id=teacher_id, conversation_id=conversation["id"], role="assistant",
                                     content=result["content"])
    return {**result, "classId": data.get("classId"), "conversationId": conversation["id"]}


def history(teacher_id):
    return {"conversations": [{
        "id": row["id"], "classId": row["class_id"], "classTitle": row["class_title"], "language": row["language"],
        "title": row["title"], "lastContent": row["last_content"], "lastMessageAt": row["last_message_at"],
    } for row in teacher_db.assistant_history(teacher_id)]}


def clear_history(teacher_id):
    teacher_db.clear_assistant_history(teacher_id)
    return {"cleared": True}


def generate_quiz(teacher_id, data):
    context = _require_context(teacher_id, data["classId"])
    selected = teacher_db.selected_materials(teacher_id=teacher_id, class_id=data["classId"],
                                             material_ids=data["sourceMaterialIds"])
    if len(selected) != len(data["sourceMaterialIds"]):
        raise ApiError.bad_request("One or more source materials do not belong to this class")

    def extract(material):
        return {"title": material["title"], "text": _material_text(material, data["language"], teacher_id)}

    with ThreadPoolExecutor(max_workers=max(1, min(4, len(selected)))) as pool:
        extracted = list(pool.map(extract, selected))

    source_text = (
        "\n\n".join(f"Source: {m['title']}\n{m['text']}" for m in extracted if m["text"].strip())
        if selected else context["text"]
    )
    if not source_text.strip():
        raise ApiError.bad_request("The selected materials contain no readable text")
    ai = get_ai()
    if ai.name == "mock":
        raise ApiError.service_unavailable(
            "AI quiz generation needs an OPENAI_API_KEY. The demo provider cannot create questions from uploaded "
            "course files.")

    quiz = track_generation(
        kind="quiz", user_id=teacher_id, language=data["language"], source_text=source_text,
        request={"teacherAssistant": True, "classId": data["classId"], "count": data["count"],
                 "sourceMaterialIds": data["sourceMaterialIds"]},
        describe=lambda v: {"questionCount": len(v.get("questions") or [])},
        run=lambda ai_, on_usage: ai_.generate_quiz(
            text=source_text, title=data.get("title") or context["title"], language=data["language"],
            count=data["count"], difficulty=data["difficulty"], question_types=data["questionTypes"],
            include_answer_key=data["includeAnswerKey"], on_usage=on_usage),
    )
    return {"draft": {**quiz, "questions": balance_answer_positions(quiz["questions"]), "classId": data["classId"]}}

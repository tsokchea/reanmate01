"""End-to-end API tests: every route, through the real app, database and mock AI.

Tests in this module run in order and share state (users, kits, classes), the
way a real session builds on earlier steps. Each role has its own client, so
each keeps its own cookie jar exactly as separate browsers would.
"""

import io
import json
import re
import time

import pytest

from app.middleware.rate_limit import reset_rate_limits

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
MISSING_ID = "11111111-1111-4111-8111-111111111111"
S = {}  # state shared across the ordered tests


@pytest.fixture(scope="module")
def student(app):
    return app.test_client()


@pytest.fixture(scope="module")
def classmate(app):
    return app.test_client()


@pytest.fixture(scope="module")
def teacher(app):
    return app.test_client()


@pytest.fixture(scope="module")
def anon(app):
    return app.test_client()


def err(response):
    return response.get_json()["error"]


def wait_for(fetch, done, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = fetch()
        if done(result):
            return result
        time.sleep(0.1)
    raise AssertionError(f"timed out; last result: {result}")


def wait_ready(client, kit_id, source_id):
    body = wait_for(lambda: client.get(f"/api/kits/{kit_id}/sources/{source_id}").get_json(),
                    lambda b: b["source"]["status"] in ("ready", "failed"))
    assert body["source"]["status"] == "ready", body["source"]
    return body["source"]


# --- health, routing, envelopes ---------------------------------------------------------

def test_health(anon):
    r = anon.get("/api/health")
    assert r.status_code == 200
    body = r.get_json()
    assert body["status"] == "ok" and body["database"] == "up"
    assert body["migrations"]["version"] == "001_initial_schema.sql"
    assert ISO.match(body["timestamp"])


def test_unknown_routes_match_express(anon):
    assert anon.get("/api/nope").status_code == 401  # passed through an auth-guarded router
    assert err(anon.get("/api/me")) == {"code": "unauthorized", "message": "Sign in to continue"}
    r = anon.get("/not-api?x=1")
    assert r.status_code == 404 and err(r)["message"] == "No route for GET /not-api?x=1"


def test_invalid_json_and_cors(anon):
    r = anon.post("/api/auth/login", data="{bad", content_type="application/json")
    assert r.status_code == 400 and err(r)["code"] == "invalid_json"
    ok = anon.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert ok.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert ok.headers["Access-Control-Allow-Credentials"] == "true"
    assert anon.get("/api/health", headers={"Origin": "https://evil.example"}).status_code == 500


# --- auth & onboarding ----------------------------------------------------------------------

def test_register_validation(anon):
    reset_rate_limits()
    r = anon.post("/api/auth/register", json={"fullName": " ", "password": "x", "role": "student"})
    assert r.status_code == 422
    fields = {d["path"]: d["message"] for d in err(r)["details"]}
    assert fields["fullName"] == "Enter your name"
    assert fields["password"] == "Use at least 8 characters"


def test_register_login_refresh_logout(student, anon):
    r = student.post("/api/auth/register", json={"fullName": "Sok Dara", "email": "Dara@Example.com",
                                                 "password": "password123", "role": "student", "locale": "en"})
    assert r.status_code == 201, r.get_json()
    user = r.get_json()["user"]
    assert "password_hash" not in user and user["email"] == "dara@example.com" and UUID.match(user["id"])
    assert user["email_verified_at"] and user["phone_verified_at"] is None
    cookies = r.headers.getlist("Set-Cookie")
    assert any(c.startswith("rm_at=") and "HttpOnly" in c for c in cookies)
    assert any(c.startswith("rm_rt=") for c in cookies)
    S["student_id"] = user["id"]

    dup = anon.post("/api/auth/register", json={"fullName": "X", "email": "dara@example.com",
                                                "password": "password123", "role": "student"})
    assert dup.status_code == 409 and err(dup)["details"] == {"field": "email"}

    bad = anon.post("/api/auth/login", json={"identifier": "dara@example.com", "password": "wrong-password"})
    assert bad.status_code == 401 and err(bad)["message"] == "Those credentials are not correct"
    assert bad.headers["RateLimit-Limit"] == "30"  # the per-IP limiter runs last and sets the headers

    assert student.post("/api/auth/login", json={"identifier": " DARA@example.com ",
                                                 "password": "password123"}).status_code == 200
    me = student.get("/api/me").get_json()
    assert me["user"]["full_name"] == "Sok Dara"
    assert me["onboarding"] == {"roleChosen": True, "surveyAnswers": {}, "surveySkipped": False, "completedAt": None}
    assert student.get("/api/auth/me").status_code == 200

    refreshed = student.post("/api/auth/refresh")
    assert refreshed.status_code == 200 and refreshed.get_json()["user"]["id"] == S["student_id"]

    assert anon.post("/api/auth/refresh").status_code == 401
    assert anon.post("/api/auth/logout").status_code == 204


def test_logout_revokes_refresh(app):
    client = app.test_client()
    client.post("/api/auth/register", json={"fullName": "Temp", "phone": "012 345 678",
                                            "password": "password123", "role": "student"})
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/me").status_code == 401
    assert client.post("/api/auth/refresh").status_code == 401


def test_onboarding(student):
    r = student.post("/api/onboarding/survey", json={"answers": {"improvFirst": "remember"}})
    assert r.status_code == 422 and err(r)["details"][0]["code"] == "unrecognized_keys"
    r = student.post("/api/onboarding/survey", json={"answers": {"improveFirst": "remember"}})
    assert r.get_json()["survey"]["answers"] == {"improveFirst": "remember"}
    r = student.post("/api/onboarding/survey", json={"answers": {"studyStyle": "mix"}, "complete": True})
    body = r.get_json()
    assert body["survey"]["answers"] == {"improveFirst": "remember", "studyStyle": "mix"}  # merged
    assert ISO.match(body["survey"]["completedAt"]) and body["user"]["onboarding_completed_at"]
    assert student.get("/api/onboarding/survey").get_json()["survey"]["skipped"] is False
    r = student.post("/api/onboarding/role", json={"role": "student"})
    assert r.status_code == 200 and any(c.startswith("rm_at=") for c in r.headers.getlist("Set-Cookie"))


# --- kits, folders, sources ------------------------------------------------------------------

def test_kits_crud_and_cap(student):
    assert student.get("/api/kits/quota").get_json() == {"used": 0, "limit": 3, "planTier": "free"}
    r = student.post("/api/kits", json={"title": "  Databases  "})
    assert r.status_code == 201
    kit = r.get_json()["kit"]
    assert kit["title"] == "Databases" and kit["titleKm"] == "Databases"
    assert (kit["icon"], kit["accent"], kit["cardCount"], kit["fileCount"]) == ("document", "blue", 0, 0)
    S["kit"] = kit["id"]

    assert student.get("/api/kits/not-a-uuid").status_code == 422
    assert student.get(f"/api/kits/{MISSING_ID}").status_code == 404
    shown = student.get(f"/api/kits/{kit['id']}").get_json()
    assert shown["fileCount"] == 0 and shown["kit"]["id"] == kit["id"]

    folder = student.post("/api/folders", json={"name": "Semester 1"}).get_json()["folder"]
    patched = student.patch(f"/api/kits/{kit['id']}", json={"folderId": folder["id"], "progress": 40}).get_json()["kit"]
    assert patched["folderId"] == folder["id"] and patched["progress"] == 40
    assert student.patch(f"/api/kits/{kit['id']}", json={}).status_code == 422
    assert student.get("/api/folders").get_json()["folders"][0]["kitCount"] == 1
    assert student.patch(f"/api/folders/{folder['id']}", json={"color": "navy"}).get_json()["folder"]["color"] == "navy"
    assert student.get(f"/api/folders/{folder['id']}").status_code == 200
    assert student.delete(f"/api/folders/{folder['id']}").get_json() == {"deleted": True}
    assert student.get(f"/api/kits/{kit['id']}").get_json()["kit"]["folderId"] is None  # unfiled, not deleted

    for title in ("Chemistry", "ប្រវត្តិសាស្ត្រ"):
        assert student.post("/api/kits", json={"title": title}).status_code == 201
    capped = student.post("/api/kits", json={"title": "One too many"})
    assert capped.status_code == 403 and err(capped)["code"] == "quota_exceeded"

    assert [k["title"] for k in student.get("/api/kits?q=datbases").get_json()["kits"]] == ["Databases"]  # trigram
    assert len(student.get("/api/kits?q=ប្រវត្តិ").get_json()["kits"]) == 1  # Khmer substring
    assert len(student.get("/api/kits?status=completed").get_json()["kits"]) == 0


def test_topic_source_ingest(student):
    r = student.post(f"/api/kits/{S['kit']}/sources", json={"kind": "topic", "title": "Relational databases"})
    assert r.status_code == 202
    source = r.get_json()["source"]
    assert source["kind"] == "topic" and source["stage"] == "reading" and source["progressPercent"] == 10
    ready = wait_ready(student, S["kit"], source["id"])
    assert ready["progressPercent"] == 100 and ready["extractedText"] == "Relational databases"
    S["topic_source"] = source["id"]


def test_upload_source_ingest(student):
    text = ("Primary keys uniquely identify rows. Foreign keys point at other tables. "
            "Normalization removes duplicated data. ") * 20
    r = student.post(f"/api/kits/{S['kit']}/files",
                     data={"file": (io.BytesIO(text.encode()), "notes.txt", "text/plain")},
                     content_type="multipart/form-data")
    assert r.status_code == 202, r.get_json()
    source = r.get_json()["source"]
    assert source["originalFilename"] == "notes.txt" and source["byteSize"] == len(text) and source["kind"] == "document"
    ready = wait_ready(student, S["kit"], source["id"])
    assert ready["pageCount"] == 1
    S["source"] = source["id"]
    assert len(student.get(f"/api/kits/{S['kit']}/sources").get_json()["sources"]) == 2


def test_upload_rejections(student):
    r = student.post(f"/api/kits/{S['kit']}/sources",
                     data={"file": (io.BytesIO(b"x"), "essay.doc", "application/msword")},
                     content_type="multipart/form-data")
    assert r.status_code == 415 and err(r)["details"]["convertTo"] == ".docx"
    r = student.post(f"/api/kits/{S['kit']}/sources",
                     data={"file": (io.BytesIO(b"MZ fake"), "a.pdf", "application/pdf")},
                     content_type="multipart/form-data")
    assert r.status_code == 415 and err(r)["message"] == "That file is not the type its name and Content-Type claim"
    r = student.post(f"/api/kits/{S['kit']}/sources",
                     data={"other": (io.BytesIO(b"hi"), "a.txt", "text/plain")},
                     content_type="multipart/form-data")
    assert r.status_code == 400
    assert student.post(f"/api/kits/{S['kit']}/sources", json={"kind": "pdf"}).status_code == 422


# --- study materials --------------------------------------------------------------------------

def test_summaries_and_study_guide(student):
    r = student.post(f"/api/sources/{S['source']}/summarize", json={"language": "en"})
    assert r.status_code == 200, r.get_json()  # prewarmed during ingest
    body = r.get_json()
    assert body["status"] == "ready" and body["summary"]["title"].startswith("[MOCK]")
    assert body["cache"]["method"] == "summarize" and len(body["cache"]["paramsHash"]) == 64

    km = student.post(f"/api/sources/{S['source']}/summarize", json={})  # default km: generated on demand
    assert km.status_code in (200, 202)
    done = wait_for(lambda: student.post(f"/api/sources/{S['source']}/summarize", json={}),
                    lambda resp: resp.status_code == 200)
    assert done.get_json()["summary"]["language"] == "km"

    chapters = student.post(f"/api/sources/{S['source']}/chapters", json={"language": "en"})
    assert chapters.status_code == 403 and err(chapters)["code"] == "feature_unavailable"

    guide = student.post(f"/api/sources/{S['source']}/study-guide", json={"language": "en"})
    assert guide.status_code == 200 and len(guide.get_json()["modules"]) == 8
    assert guide.get_json()["modules"][0]["recall"][0]["answer"]


def test_quiz_flow(student):
    r = student.post(f"/api/sources/{S['source']}/quiz", json={"language": "en"})
    assert r.status_code == 200, r.get_json()
    quiz = r.get_json()["quiz"]
    assert quiz["questionCount"] == 10
    start = student.post(f"/api/quizzes/{quiz['id']}/attempts")
    assert start.status_code == 201
    attempt, questions = start.get_json()["attempt"], start.get_json()["questions"]
    assert all(q["correctAnswer"] is None and q["explanation"] is None for q in questions)  # nothing revealed yet

    first = questions[0]
    answered = student.put(f"/api/attempts/{attempt['id']}/answers",
                           json={"questionId": first["id"], "response": 0, "timeSpentSeconds": 4}).get_json()["answer"]
    assert isinstance(answered["isCorrect"], bool) and isinstance(answered["correctAnswer"], int)
    assert student.get(f"/api/attempts/{attempt['id']}").get_json()["questions"][0]["response"] == 0

    submitted = student.post(f"/api/attempts/{attempt['id']}/submit").get_json()["attempt"]
    assert submitted["status"] == "submitted" and submitted["takeaways"] and ISO.match(submitted["submittedAt"])
    again = student.put(f"/api/attempts/{attempt['id']}/answers", json={"questionId": first["id"], "response": 1})
    assert again.status_code == 409

    # One quiz finished: the next request is a new round, generated on demand.
    nxt = student.post(f"/api/sources/{S['source']}/quiz", json={"language": "en"})
    assert nxt.status_code in (200, 202) and nxt.get_json()["cache"]["params"]["round"] == 1


def test_flashcards(student):
    r = student.post(f"/api/sources/{S['source']}/flashcards", json={"language": "en"})
    assert r.status_code == 200
    cards = r.get_json()["cards"]
    assert len(cards) == 20 and cards[0]["easeFactor"] == 2.5 and ISO.match(cards[0]["dueAt"])
    due = student.get(f"/api/flashcards/due?limit=5&sourceId={S['source']}").get_json()["cards"]
    assert len(due) == 5
    review = student.post(f"/api/flashcards/{cards[0]['id']}/review", json={"quality": 5}).get_json()
    assert review["review"]["easeFactor"] == 2.6 and review["review"]["intervalDays"] == 1
    assert student.post(f"/api/flashcards/{MISSING_ID}/review", json={"quality": 5}).status_code == 404
    assert student.get("/api/flashcards/due?limit=abc").status_code == 422


def test_tutor_chat_and_sse(student):
    r = student.post("/api/chat", json={"kitId": S["kit"], "sourceId": S["source"], "content": "What is a primary key?",
                                        "language": "en"})
    assert r.status_code == 201, r.get_json()
    body = r.get_json()
    assert body["assistantMessage"]["status"] == "queued" and body["quota"] == {"used": 0, "limit": 20, "remaining": 20}

    stream = student.get(f"/api/chat/{body['sessionId']}/stream")
    assert stream.status_code == 200 and stream.headers["Content-Type"] == "text/event-stream; charset=utf-8"
    frames = [dict(line.split(": ", 1) for line in block.split("\n"))
              for block in stream.get_data(as_text=True).strip().split("\n\n")]
    assert frames[0]["event"] == "delta" and frames[0]["id"] == "1"
    done = frames[-1]
    assert done["event"] == "done" and done["id"] == "terminal"
    data = json.loads(done["data"])
    assert data["citations"][0]["sourceTitle"] == "notes.txt" and data["quota"]["used"] == 1

    # Reconnecting after completion replays just the terminal frame.
    replay = student.get(f"/api/chat/{body['sessionId']}/stream", headers={"Last-Event-ID": "3"})
    assert "event: done" in replay.get_data(as_text=True)

    convo = student.get(f"/api/chat/conversation/{S['kit']}?language=en&sourceId={S['source']}").get_json()
    assert [m["role"] for m in convo["messages"]] == ["user", "assistant"]
    assert convo["messages"][1]["status"] == "complete" and convo["conversation"]["sourceTitle"] == "notes.txt"
    assert student.get("/api/chat/history?language=en").get_json()["conversations"][0]["preview"] == "What is a primary key?"

    # A second message reuses the same (kit, source, language) thread.
    student.post("/api/chat", json={"kitId": S["kit"], "sourceId": S["source"], "content": "And a foreign key?",
                                    "language": "en"})
    assert len(student.get("/api/chat/history?language=en").get_json()["conversations"]) == 1
    # A kit-wide thread (no source) is its own thread, and is unique too.
    for _ in range(2):
        student.post("/api/chat", json={"kitId": S["kit"], "content": "Kit-wide?", "language": "en"})
    assert len(student.get("/api/chat/history?language=en").get_json()["conversations"]) == 2

    assert student.post(f"/api/chat/{body['sessionId']}/retry").status_code == 409
    explained = student.post("/api/chat/explain", json={"kitId": S["kit"], "content": "Explain in Khmer please"})
    assert explained.get_json()["language"] == "km" and explained.get_json()["content"]


def test_practice_and_mock_exam(student):
    topics = student.get(f"/api/practice/topics?sourceId={S['source']}").get_json()["topics"]
    assert topics and {"id", "kitId", "title", "mastery", "effectiveMastery", "recommended", "needsPractice"} <= set(topics[0])

    r = student.post("/api/practice/sessions", json={"studyKitId": S["kit"], "sourceId": S["source"], "questionCount": 3,
                                                     "answerFormat": "multiple_choice", "timerSeconds": 0})
    assert r.status_code == 201, r.get_json()
    session = r.get_json()["session"]
    assert r.get_json()["quota"] == {"used": 1, "limit": 3, "remaining": 2}
    got = student.get(f"/api/practice/sessions/{session['id']}").get_json()
    assert all(q["correctAnswer"] is None for q in got["questions"])  # hidden while sitting
    ans = student.put(f"/api/practice/sessions/{session['id']}/answers", json={"position": 1, "response": 0})
    assert ans.status_code == 200 and ans.get_json()["answer"]["position"] == 1
    assert student.get("/api/practice/home").get_json()["continue"]["sessionId"] == session["id"]
    result = student.post(f"/api/practice/sessions/{session['id']}/submit", json={"durationSeconds": 30}).get_json()["result"]
    assert result["status"] == "completed" and result["total"] == 3
    revealed = student.get(f"/api/practice/sessions/{session['id']}").get_json()["questions"]
    assert revealed[0]["correctAnswer"] is not None

    exam = student.post("/api/practice/sessions", json={"studyKitId": S["kit"], "sourceId": S["source"], "mode": "mock_exam",
                                                        "questionCount": 2, "answerFormat": "written", "timerSeconds": 600})
    assert exam.status_code == 201
    exam_id = exam.get_json()["session"]["id"]
    assert ISO.match(exam.get_json()["session"]["expiresAt"])
    student.put(f"/api/practice/sessions/{exam_id}/answers", json={"position": 1, "response": "It is a written answer"})
    graded = student.post(f"/api/practice/sessions/{exam_id}/submit", json={}).get_json()["result"]
    assert graded["answered"] == 1
    note = student.get(f"/api/practice/sessions/{exam_id}").get_json()["questions"][0]["graderNote"]
    assert note.startswith("[MOCK]")  # graded by the (mock) AI at submit

    progress = student.get("/api/practice/progress").get_json()
    assert progress["hasActivity"] and ISO.match(progress["accuracyOverTime"][0]["date"])
    assert progress["activityStreak"] >= 0

    third = student.post("/api/practice/sessions", json={"studyKitId": S["kit"], "questionCount": 1,
                                                         "answerFormat": "multiple_choice", "timerSeconds": 0})
    assert third.status_code == 201
    capped = student.post("/api/practice/sessions", json={"studyKitId": S["kit"], "questionCount": 1,
                                                          "answerFormat": "multiple_choice", "timerSeconds": 0})
    assert capped.status_code == 429 and err(capped)["code"] == "quota_exceeded"


def test_profile_and_limits(student):
    profile = student.get("/api/profile").get_json()["profile"]
    assert profile["summary"]["kits"] == 3 and profile["planTier"] == "free"
    assert student.patch("/api/profile", json={"locale": "km"}).get_json()["profile"]["locale"] == "km"
    assert student.patch("/api/profile", json={}).status_code == 422
    limits = student.get("/api/me/limits").get_json()
    assert limits["limits"]["tutor_messages_per_month"]["used"] == 1  # charged when a reply finishes streaming
    assert limits["features"] == {"chapter_summaries": False, "mock_exams": False}
    assert limits["plans"]["plus"]["limits"]["max_kits"] is None


# --- classes, assignments, teacher --------------------------------------------------------------

def test_teacher_classes_lessons(teacher, student, classmate):
    reset_rate_limits()
    t = teacher.post("/api/auth/register", json={"fullName": "Teacher Sokha", "email": "sokha@school.edu",
                                                 "password": "password123", "role": "teacher"})
    assert t.status_code == 201
    classmate.post("/api/auth/register", json={"fullName": "Classmate", "email": "mate@example.com",
                                               "password": "password123", "role": "student"})

    denied = student.post("/api/classes", json={"title": "Nope"})
    assert denied.status_code == 403 and err(denied)["message"] == "Your account cannot do that"
    assert student.get("/api/teacher/dashboard").status_code == 403

    klass = teacher.post("/api/classes", json={"title": "Grade 12 IT", "subject": "IT"}).get_json()["class"]
    assert len(klass["joinCode"]) == 6 and klass["weeks"] == 12 and klass["coverUrl"] is None
    S["class"], S["code"] = klass["id"], klass["joinCode"]

    lesson = teacher.post(f"/api/classes/{S['class']}/lessons", json={
        "weekNumber": 1, "title": "Keys", "contentMd": "Primary keys identify rows.",
        "items": [{"title": "Read"}, {"title": "Practice", "kind": "exercise"}]}).get_json()["lesson"]
    S["lesson"] = lesson["id"]
    assert teacher.post(f"/api/classes/{S['class']}/lessons", json={
        "weekNumber": 40, "title": "Too late", "items": [{"title": "x"}]}).status_code == 404

    joined = student.post("/api/classes/join", json={"code": S["code"].lower()})
    assert joined.status_code == 201
    detail = joined.get_json()
    item_ids = [i["id"] for i in detail["weeks"][0]["lessons"][0]["items"]]
    assert detail["weeks"][0]["week"] == 1 and len(item_ids) == 2
    classmate.post("/api/classes/join", json={"code": S["code"]})

    progress = student.post(f"/api/classes/lesson-items/{item_ids[0]}/complete").get_json()["progress"]
    assert progress["status"] == "in_progress"
    progress = student.post(f"/api/classes/lesson-items/{item_ids[1]}/complete").get_json()["progress"]
    assert progress["status"] == "completed" and ISO.match(progress["completedAt"])
    assert student.get("/api/classes").get_json()["classes"][0]["lessonsDone"] == 1

    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    cover = teacher.post(f"/api/classes/{S['class']}/cover", data={"file": (io.BytesIO(png), "c.png", "image/png")},
                         content_type="multipart/form-data")
    assert cover.status_code == 201
    image = student.get(cover.get_json()["coverUrl"])
    assert image.status_code == 200 and image.mimetype == "image/png" and image.data == png
    image.close()

    shared = teacher.post("/api/kits", json={"title": "Teacher kit"}).get_json()["kit"]
    assert teacher.post(f"/api/classes/{S['class']}/kits/{shared['id']}").get_json()["kit"]["classId"] == S["class"]

    updated = teacher.patch(f"/api/teacher/classes/{S['class']}", json={"description": None, "status": "active"})
    assert updated.get_json()["class"]["description"] is None


def test_file_assignment_submission_grading(teacher, student):
    created = teacher.post(f"/api/lessons/{S['lesson']}/assignments", json={
        "title": "Essay", "dueAt": "2099-01-01T00:00:00Z", "type": "file", "points": 10, "instructions": ["Write"]})
    assert created.status_code == 201, created.get_json()
    assignment = created.get_json()["assignment"]
    assert assignment["points"] == "10.00" and assignment["dueAt"] == "2099-01-01T00:00:00.000Z"
    assert "className" not in assignment  # absent on create, as the Express API omitted it
    S["file_assignment"] = assignment["id"]

    upload = student.post(f"/api/assignments/{assignment['id']}/submission/files",
                          data={"file": (io.BytesIO(b"%PDF-1.4 essay"), "essay.pdf", "application/pdf")},
                          content_type="multipart/form-data")
    assert upload.status_code == 201, upload.get_json()
    assert upload.get_json()["submission"]["status"] == "submitted" and upload.get_json()["file"]["size"] == 14

    detail = student.get(f"/api/assignments/{assignment['id']}").get_json()
    assert detail["assignment"]["className"] == "Grade 12 IT" and detail["submission"]["files"][0]["name"] == "essay.pdf"
    assert detail["submission"]["isLate"] is False

    subs = teacher.get(f"/api/assignments/{assignment['id']}/submissions").get_json()["submissions"]
    assert subs[0]["studentName"] == "Sok Dara" and subs[0]["fileCount"] == 1
    graded = teacher.patch(f"/api/assignments/{assignment['id']}/submissions/{subs[0]['id']}",
                           json={"score": 9.5, "feedback": "Good"}).get_json()["submission"]
    assert graded["status"] == "graded" and graded["score"] == "9.50"
    assert teacher.patch(f"/api/assignments/{assignment['id']}/submissions/{subs[0]['id']}",
                         json={"score": 1}).status_code == 409


def test_quiz_assignment(teacher, student):
    r = teacher.post("/api/teacher/quizzes", json={"classId": S["class"], "title": "Keys quiz", "language": "en",
                                                   "points": 5, "questions": [
        {"kind": "multiple_choice", "prompt": "PK?", "options": ["unique", "b", "c", "d"], "correctAnswer": 0},
        {"kind": "true_false", "prompt": "Two PKs?", "options": ["True", "False"], "correctAnswer": 1}]})
    assert r.status_code == 201, r.get_json()
    assignment_id = r.get_json()["assignment"]["id"]
    questions = student.get(f"/api/assignments/{assignment_id}/questions").get_json()["questions"]
    assert len(questions) == 2
    partial = student.put(f"/api/assignments/{assignment_id}/submission", json={"answers": {questions[0]["id"]: 0}})
    assert partial.get_json()["submission"]["status"] == "in_progress"
    incomplete = student.put(f"/api/assignments/{assignment_id}/submission", json={"answers": {}, "submit": True})
    assert incomplete.status_code == 409
    bad = student.put(f"/api/assignments/{assignment_id}/submission", json={"answers": {MISSING_ID: 1}})
    assert bad.status_code == 400
    done = student.put(f"/api/assignments/{assignment_id}/submission",
                       json={"answers": {questions[1]["id"]: 1}, "submit": True}).get_json()["submission"]
    assert done["status"] == "submitted" and done["completed"] == 2

    detail = teacher.get(f"/api/teacher/assignments/{assignment_id}").get_json()["assignment"]
    assert detail["type"] == "quiz" and detail["points"] == 5 and detail["materials"] == []
    assert teacher.get("/api/teacher/assignments").get_json()["assignments"]


def test_teacher_workspace(teacher, student):
    dash = teacher.get("/api/teacher/dashboard").get_json()
    assert dash["summary"]["activeClasses"] == 1 and dash["summary"]["totalStudents"] == 2
    assert dash["summary"]["returnedSubmissions"] == 1 and dash["classes"][0]["coverUrl"]

    students = teacher.get(f"/api/teacher/classes/{S['class']}/students").get_json()["students"]
    dara = next(s for s in students if s["name"] == "Sok Dara")
    assert dara["completedLessons"] == 1 and dara["averageScore"] == 9.5

    material = teacher.post(f"/api/teacher/classes/{S['class']}/materials",
                            data={"file": (io.BytesIO(b"Week 2 reading"), "reading.txt", "text/plain"),
                                  "title": "Reading", "weekNumber": "2"}, content_type="multipart/form-data")
    assert material.status_code == 201
    m = material.get_json()["material"]
    assert m["week"] == 2 and m["byteSize"] == 14
    listed = teacher.get(f"/api/teacher/classes/{S['class']}/materials").get_json()["materials"]
    assert listed[0]["title"] == "Reading"
    served = teacher.get(f"/api/teacher/classes/{S['class']}/materials/{m['id']}/file")
    assert served.data == b"Week 2 reading" and served.headers["Content-Disposition"] == "inline"
    served.close()  # release the file handle before it is deleted below (Windows)
    assert student.get(f"/api/classes/{S['class']}").get_json()["materials"][0]["week"] == 2

    attach = teacher.post(f"/api/teacher/assignments/{S['file_assignment']}/attachment",
                          data={"file": (io.BytesIO(b"%PDF-1.4 rubric"), "rubric.pdf", "application/pdf")},
                          content_type="multipart/form-data")
    assert attach.status_code == 201
    patched = teacher.patch(f"/api/teacher/assignments/{S['file_assignment']}", json={
        "title": "Essay v2", "dueAt": None, "points": 20, "publish": True}).get_json()["assignment"]
    assert patched["title"] == "Essay v2" and patched["points"] == 20 and patched["dueAt"] is None

    draft = teacher.post("/api/teacher/assignments", json={"classId": S["class"], "title": "Draft", "publish": False})
    assert draft.status_code == 201 and draft.get_json()["assignment"]["status"] == "draft"
    assert student.get(f"/api/assignments/{draft.get_json()['assignment']['id']}").status_code == 404

    asked = teacher.post("/api/teacher/assistant/ask", json={"classId": S["class"], "content": "Plan week 2",
                                                             "language": "en"}).get_json()
    assert asked["content"] and asked["conversationId"]
    follow = teacher.post("/api/teacher/assistant/ask", json={"conversationId": asked["conversationId"],
                                                              "content": "More", "language": "en"})
    assert follow.status_code == 200
    history = teacher.get("/api/teacher/assistant/history").get_json()["conversations"]
    assert history[0]["lastContent"]
    quiz_draft = teacher.post("/api/teacher/assistant/quiz", json={"classId": S["class"]})
    assert quiz_draft.status_code == 503 and err(quiz_draft)["code"] == "service_unavailable"  # mock AI
    assert teacher.delete("/api/teacher/assistant/history").get_json() == {"cleared": True}

    assert teacher.delete(f"/api/teacher/classes/{S['class']}/materials/{m['id']}").get_json()["deleted"] is True
    assert teacher.delete(f"/api/teacher/assignments/{S['file_assignment']}").get_json()["deleted"] is True
    created = teacher.post("/api/teacher/quizzes", json={"classId": S["class"], "title": "AI quiz", "count": 3})
    assert created.status_code == 201 and created.get_json()["quiz"]["questionCount"] == 3


# --- deletion ------------------------------------------------------------------------------------

def test_delete_kit_and_account(student, anon):
    removed = student.delete(f"/api/kits/{S['kit']}").get_json()
    assert removed == {"deleted": True, "filesRemoved": 1, "filesOrphaned": 0}
    assert student.get(f"/api/kits/{S['kit']}/sources").status_code == 404
    gone = student.delete("/api/account")
    assert gone.get_json() == {"deleted": True}
    assert anon.post("/api/auth/login", json={"identifier": "dara@example.com",
                                              "password": "password123"}).status_code == 401

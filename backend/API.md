# ReanMate API reference

Base path: `/api`. JSON in, JSON out, unless noted (uploads are
`multipart/form-data` with the file in a field named `file`; two endpoints
serve files; one streams Server-Sent Events).

Every path, method, status code and response shape here is identical to the
former Express API.

## Conventions

### Authentication

Sessions are two **httpOnly cookies**, set by register/login/refresh:

| Cookie | Contents | Lifetime |
| --- | --- | --- |
| `rm_at` | HS256 JWT: `sub` (user id), `role`, `plan`, `pv`, `ev` | 15 minutes |
| `rm_rt` | Opaque refresh token (only its SHA-256 is stored) | 30 days, rotated on every refresh |

Browsers must send credentials (`withCredentials: true` / `credentials: 'include'`).
When an access token expires, call `POST /auth/refresh` and retry.

**Auth** column below: `none`, `user` (any signed-in account), `teacher`,
`student`, or a permission such as `users.view` (admin console — see the last
section). Every authenticated request re-reads the account's status, role and
must-change-password flag, so disabling an account or changing its role takes
effect on its next request.

### Errors

All errors share one envelope; `code` is stable and maps to client copy:

```json
{ "error": { "code": "not_found", "message": "That study kit does not exist", "details": {} } }
```

| Status | `code` | When |
| --- | --- | --- |
| 400 | `bad_request`, `invalid_json` | Business-rule rejection; malformed JSON body |
| 401 | `unauthorized`, `account_disabled` | No/expired session ("Sign in to continue", "That session has expired"); the account was disabled or deleted |
| 403 | `forbidden`, `quota_exceeded`, `feature_unavailable` | Wrong role; plan cap reached; plan lacks the feature (`details.requiredPlan`) |
| 403 | `password_change_required` | The account holds a temporary password; only `GET /auth/me` and `POST /auth/password` work |
| 403 | `DAILY_AI_LIMIT_REACHED`, `MONTHLY_AI_LIMIT_REACHED`, `DAILY_/MONTHLY_UPLOAD_…`, `…_ASSIGNMENT_…`, `…_FLASHCARD_…`, `…_TUTOR_…`, `…_STORAGE_LIMIT_REACHED` | Per-account usage limit (`details`: `metric`, `period`, `limit`, `used`, `requested`, `resetsAt`) |
| 403 | `signups_disabled` | Registration is paused in system settings |
| 403 | `admin_access_required`, `permission_denied` (`details.required`), `permission_escalation`, `super_admin_required`, `super_admin_protected`, `target_outranks_actor`, `cannot_modify_self`, `system_role_locked`, `admin_account` | Admin console authorization — see the last section |
| 404 | `not_found` | Missing, or not yours (never 403 for someone else's resource) |
| 409 | `conflict` | State conflict (duplicate email → `details.field`, not ready, already submitted) |
| 413 | `payload_too_large`, `file_too_large` | Body over 1 MB; upload over 25 MB (`details.limit`) |
| 415 | `unsupported_file_type` | Upload type refused (`details.convertTo` for legacy formats) |
| 422 | `validation_failed` | Request failed validation — see below |
| 429 | `too_many_requests`, `quota_exceeded` | Login/register rate limit (`Retry-After`); monthly/weekly usage cap (`details.used`, `details.limit`) |
| 500 | `internal_error` | Unexpected; `details` holds the message outside production |
| 503 | `service_unavailable`, (health: body below) | Feature needs a real AI key |

Validation errors list each problem with a dotted `path`:

```json
{ "error": { "code": "validation_failed", "message": "Request validation failed",
  "details": [ { "path": "password", "code": "too_small", "message": "Use at least 8 characters" } ] } }
```

An unknown path answers `404 {"error":{"code":"not_found","message":"No route for GET /api/..."}}`
— after a `401` if the request has no session.

### Common types

- **ids** are UUIDs; timestamps are ISO-8601 UTC strings (`2026-09-24T03:15:00.123Z`).
- **language** is `"km"` or `"en"` (default `"km"`).
- **Generation endpoints** answer `200` when the result is ready and `202` while it is
  still being generated; poll the same endpoint until `status` is `"ready"` or `"failed"`.

---

## Health

### `GET /health` — none
`200` when the database is reachable, else `503`.
```json
{ "status": "ok", "database": "up", "migrations": { "version": "001_initial_schema.sql", "applied_at": "…" },
  "env": "development", "uptimeSeconds": 12, "timestamp": "…" }
```

## Auth

### `POST /auth/register` — none (10/hour per IP)
```json
{ "fullName": "Sok Dara", "email": "dara@example.com", "phone": "012 345 678",
  "password": "at least 8 chars", "role": "student", "locale": "km" }
```
`email` or `phone` required (both optional individually). `201 { "user": User }` + session cookies.
Errors: `422` (field messages), `409` email/phone taken (`details.field`), `429`.

`User` is the account row without the password hash:
`id, full_name, email, phone, avatar_url, role, locale, plan_tier, plan_status, trial_started_at,
trial_ends_at, plan_period_end, phone_verified_at, email_verified_at, onboarding_completed_at,
status, last_seen_at, created_at, updated_at`.

### `POST /auth/login` — none (5/15 min per identifier, 30/15 min per IP)
`{ "identifier": "email or phone", "password": "…" }` → `200 { "user": User }` + cookies.
Errors: `401` "Those credentials are not correct", `422`, `429`.

### `POST /auth/refresh` — refresh cookie
Rotates the refresh token. `200 { "user": User }` + new cookies. `401` (cookies cleared) if expired/revoked.

### `POST /auth/logout` — none
Revokes the refresh token and clears cookies. `204`.

### `POST /auth/password` — user (10/15 min per account)
`{ "currentPassword", "newPassword" }` → `200 { "user": User }`. Clears a
temporary password, signs out every other session and issues a fresh one.
A wrong current password is a `422` on `currentPassword`.

### `GET /auth/me`, `GET /me` — user
```json
{ "user": User, "onboarding": { "roleChosen": true, "surveyAnswers": {}, "surveySkipped": false, "completedAt": null } }
```

## Onboarding

### `POST /onboarding/role` — user
`{ "role": "student" | "teacher" }` → `200 { "user": User }` and a refreshed access cookie.

### `POST /onboarding/survey` — user
```json
{ "answers": { "improveFirst": "exam_prep", "studyStyle": "mix", "studyFrequency": "every_day" },
  "skipped": false, "complete": false }
```
Answers merge across calls; unknown answer keys → `422`. `complete` or `skipped` finishes onboarding.
`200 { "survey": { "answers", "skipped", "completedAt" }, "user"? }` (`user` when finished).

### `GET /onboarding/survey` — user
`200 { "survey": { "answers": {}, "skipped": false, "completedAt": null } }`

## Profile & plan

| Method & path | Auth | Request | Response |
| --- | --- | --- | --- |
| `GET /profile` | user | — | `{ "profile": { id, fullName, email, phone, avatarUrl, role, locale, planTier, planStatus, summary: { kits, streak, mastery }, activityDays } }` |
| `PATCH /profile` | user | `{ "fullName"?, "locale"? }` (at least one) | same as GET |
| `DELETE /profile`, `DELETE /account` | user | — | `{ "deleted": true }`, cookies cleared, uploads removed |
| `GET /me/limits` | user | — | `{ planTier, periodStart, limits: { max_kits, tutor_messages_per_month, practice_sessions_per_week: { limit, used, remaining } }, features: { chapter_summaries, mock_exams }, plans: { free, plus } }` |

## Study kits

`Kit`: `id, title, titleKm, description, subject, icon, accent, status, progress, cardCount,
fileCount, sourceKind, folderId, lastStudiedAt, createdAt, updatedAt`.

| Method & path | Auth | Request | Response / errors |
| --- | --- | --- | --- |
| `GET /kits?status=&q=` | user | `status`: `in_progress`/`completed`/`archived`; `q`: search (trigram, Khmer-safe) | `{ "kits": [Kit] }` |
| `POST /kits` | user | `{ title, description?, subject?, folderId?, icon?, accent? }` | `201 { "kit": Kit }`; `403 quota_exceeded` past the plan cap (free: 3) |
| `GET /kits/quota` | user | — | `{ used, limit, planTier }` |
| `GET /kits/{kitId}` | user | — | `{ "kit": Kit, "fileCount": n }`; `404` |
| `PATCH /kits/{kitId}` | user | any of `title, description, subject, folderId (nullable), icon, accent, status, progress` | `{ "kit": Kit }`; `422` if empty |
| `DELETE /kits/{kitId}` | user | — | `{ deleted, filesRemoved, filesOrphaned }` |

### Sources (`/files` is an alias of `/sources` on every route)

`Source`: `id, kitId, name, kind (pdf|image|document|youtube|topic), originalFilename, mimeType,
byteSize, pageCount, durationSeconds, sourceUrl, thumbnailUrl, status (pending|processing|ready|failed),
stage (reading|extracting|embedding|generating|ready|failed), progressPercent, errorMessage, createdAt`
(+ `extractedText` on the single-source read).

| Method & path | Auth | Request | Response / errors |
| --- | --- | --- | --- |
| `GET /kits/{kitId}/sources` | user | — | `{ "sources": [Source] }` |
| `POST /kits/{kitId}/sources` | user | multipart `file` (PDF, JPEG/PNG/WEBP, DOCX/XLSX/PPTX, TXT/MD/CSV ≤ 25 MB) **or** JSON `{ "kind": "youtube", "url", "title"? }` / `{ "kind": "topic", "title" }` | `202 { "source": Source }` — processing continues in the background; poll the source. `415`, `413`, `400`, `404`, `422` |
| `GET /kits/{kitId}/sources/{sourceId}` | user | — | `{ "source": Source }` |
| `DELETE /kits/{kitId}/sources/{sourceId}` | user | — | `{ "deleted": true }` |

Ingest failures land on the source (`status: "failed"`, `errorMessage`, `metadata.errorCode`
such as `page_limit_exceeded` — free plan: 50 pages/slides/sheets, 30-minute videos).

## Folders

| Method & path | Auth | Request | Response |
| --- | --- | --- | --- |
| `GET /folders` | user | — | `{ "folders": [{ id, name, color, icon, sortOrder, kitCount, createdAt, updatedAt }] }` |
| `POST /folders` | user | `{ name, color?, icon?, sortOrder? }` | `201 { "folder": Folder }` |
| `GET /folders/{folderId}` | user | — | `{ "folder": Folder }` |
| `PATCH /folders/{folderId}` | user | any of the create fields | `{ "folder": Folder }` |
| `DELETE /folders/{folderId}` | user | — | `{ "deleted": true }` (kits are unfiled, not deleted) |

## Study materials (generation endpoints: 200 ready / 202 generating)

All take a source the user owns or can see through an active class enrollment; a source
that is not `ready` → `409`.

| Method & path | Request | Response |
| --- | --- | --- |
| `POST /sources/{id}/summarize` | `{ language? }` | `{ cache, source, status, summary: { title, bodyMd, keyPoints, language } \| null, chapters: [] }` |
| `POST /sources/{id}/chapters` | `{ language?, chapterCount? (2–24, default 12) }` | same shape, `chapters: [{ index, title, bodyMd, keyPoints, startSeconds, endSeconds, status, updatedAt }]`; `403 feature_unavailable` on the free plan |
| `POST /sources/{id}/study-guide` | `{ language?, moduleCount? (2–16, default 8) }` | `{ status, source, modules: [{ index, title, explanationMd, applicationMd, pitfallsMd, recall: [{ question, answer }], status, updatedAt }] }` |
| `POST /sources/{id}/quiz` | `{ language?, difficulty? (easy\|medium\|hard\|mixed) }` | `{ cache, status, quiz: { id, title, language, difficulty, questionCount } \| null }` — a new round after each finished quiz |
| `POST /sources/{id}/flashcards` | `{ language?, regenerate?, round? }` | `{ cache, status, cards: [Card], error? }` |

## Quiz attempts

| Method & path | Auth | Request | Response / errors |
| --- | --- | --- | --- |
| `POST /quizzes/{quizId}/attempts` | user | — | `201 { attempt, questions }` |
| `GET /attempts/{attemptId}` | user | — | `{ attempt, questions }` |
| `PUT /attempts/{attemptId}/answers` | user | `{ questionId, response (option index or text), timeSpentSeconds? }` | `{ "answer": { questionId, response, isCorrect, correctAnswer, explanation } }`; `409` once submitted |
| `POST /attempts/{attemptId}/submit` | user | — | `{ "attempt": Attempt }` with `mastery` and AI `takeaways` |

`Attempt`: `id, quizId, status, total, correct, mastery, takeaways, startedAt, submittedAt`.
`Question`: `id, position, kind, prompt, options, explanation, topic, response, isCorrect,
correctAnswer, targetedWeakConcept` — `explanation`/`correctAnswer` stay `null` until answered.

## Flashcards

`Card`: `id, kitId, sourceId, term, definition, hint, language, position, easeFactor,
intervalDays, repetitions, lapses, dueAt, lastReviewedAt`.

| Method & path | Auth | Request | Response |
| --- | --- | --- | --- |
| `GET /flashcards/due?limit=&kitId=&sourceId=` | user | `limit` 1–100 (default 20) | `{ "cards": [Card] }` |
| `POST /flashcards/{id}/review` | user | `{ quality: 0–5 }` (SM-2) | `{ nextDueAt, review: { flashcardId, quality, easeFactor, intervalDays, repetitions, lapses, dueAt, lastReviewedAt } }`; `404` |

## AI tutor chat

| Method & path | Auth | Request | Response / errors |
| --- | --- | --- | --- |
| `POST /chat` | user | `{ kitId, sourceId?, content, language? }` | `201 { sessionId, userMessage, assistantMessage (status "queued"), quota: { used, limit, remaining } }`; `429 quota_exceeded` (free: 20/month) |
| `GET /chat/{sessionId}/stream` | user | header `Last-Event-ID`? | **SSE** (below); `404` |
| `POST /chat/{sessionId}/retry` | user | — | `201 { sessionId, assistantMessage }`; `409` unless the message failed |
| `GET /chat/conversation/{kitId}?language=&sourceId=` | user | — | `{ conversation: { id, kitId, sourceId, sourceTitle, language, kitTitle, lastMessageAt } \| null, messages: [{ id, role, content, citations, status, createdAt }], quota }` |
| `GET /chat/history?language=` | user | — | `{ "conversations": [{ id, kitId, sourceId, language, kitTitle, sourceTitle, preview, lastMessageAt }] }` |
| `POST /chat/explain` | user | `{ kitId, sourceId?, content, language? }` | `{ content, citations, language }` (non-streaming) |

The stream (`Content-Type: text/event-stream; charset=utf-8`) sends frames

```
id: 1
event: delta
data: {"text":"A primary key"}

id: terminal
event: done
data: {"messageId":"…","citations":[{"sourceTitle":"Week 1.pdf","pageNumber":3,"startSeconds":null}],"suggestedFollowups":[],"quota":{"used":1,"limit":20,"remaining":19}}
```

then closes. Failures end with `event: error` and `{ code, message, retryable }`
(`generation_failed`, `stream_interrupted`, `stream_unavailable`). Reconnect with
`Last-Event-ID` to receive only the missed frames. Idle `: ping` comments keep the connection alive.
One tutor reply is charged when it completes.

## Practice & mock exams

| Method & path | Auth | Request | Response / errors |
| --- | --- | --- | --- |
| `GET /practice/topics?q=&sourceId=` | user | — | `{ "topics": [{ id, kitId, title, mastery, effectiveMastery, recommended, needsPractice }] }` |
| `POST /practice/sessions` | user | `{ studyKitId, sourceId?, mode? (practice\|mock_exam), questionCount 1–100, answerFormat (multiple_choice\|written), timerSeconds 0–7200, topicIds? }` | `201 { session: Session, quota }`; `429` weekly cap (free: 3); `409` not enough questions |
| `GET /practice/sessions/{sessionId}` | user | — | `{ session, questions: [{ id, position, prompt, options, response, answeredAt, isCorrect, graderNote, explanation, correctAnswer }] }` — answer key hidden until completed |
| `PUT /practice/sessions/{sessionId}/answers` | user | `{ position, response, timeSpentSeconds? }` | `{ "answer": { position, response, answeredAt } }`; `409` if closed/expired |
| `POST /practice/sessions/{sessionId}/submit` | user | `{ durationSeconds? }` | `{ "result": Session + { total, toReview } }` — written answers are graded by AI first |
| `GET /practice/home` | user | — | `{ "continue": { sessionId, kitId, title, answered, total } \| null }` |
| `GET /practice/progress` | user | — | `{ hasActivity, accuracyOverTime: [{ date, correct, total, accuracy }], topics: [{ id, name, mastery, attempts }], activityStreak }` |

`Session`: `id, kitId, sourceId, mode, questionCount, answerFormat, timerSeconds, expiresAt,
status, answered, correct, mastery, weakTopics, durationSeconds, startedAt, completedAt`.

## Classes (students and teachers)

`Class`: `id, title, description, subject, coverUrl, teacher, teacherId, joinCode, weeks,
lessonCount, lessonsDone, status`.

| Method & path | Auth | Request | Response / errors |
| --- | --- | --- | --- |
| `GET /classes` | user | — | `{ "classes": [Class] }` (taught or enrolled) |
| `POST /classes` | teacher | `{ title, description?, subject?, weekCount? (1–52, default 12) }` | `201 { "class": Class }` |
| `POST /classes/join` | student | `{ code }` (case-insensitive) | `201` class detail (below); `404` bad code |
| `GET /classes/{classId}` | user | — | `{ class, weeks: [{ week, lessons: [{ id, title, description, kind, position, status, done, total, items }] }], materials: [{ id, title, mimeType, byteSize, week }], quizzes: [{ id, title, questionCount, status, week, kitId }], assignments: [{ id, title, dueAt, status, type, week }] }` |
| `DELETE /classes/{classId}` | teacher | — | `{ deleted, classId }` |
| `POST /classes/{classId}/cover` | teacher | multipart image | `201 { coverUrl }` |
| `GET /classes/{classId}/cover` | user | — | the image file |
| `POST /classes/{classId}/lessons` | teacher | `{ weekNumber, title, description?, kind?, contentMd?, items: [{ title, kind?, contentMd? }] }` | `201 { "lesson": { id, classId, weekNumber, position, title, kind, items } }`; `404` week beyond the class |
| `POST /classes/{classId}/kits/{kitId}` | teacher | — | `{ "kit": { id, classId } }` (shares one of your kits into the class) |
| `POST /classes/lesson-items/{itemId}/complete` | student | — | `{ "progress": { lessonId, status, startedAt, completedAt } }` |

## Assignments

| Method & path | Auth | Request | Response / errors |
| --- | --- | --- | --- |
| `POST /lessons/{lessonId}/assignments` | teacher | `{ title, description?, instructions?, dueAt, type (file\|quiz), quizId? (required for quiz), points? }` | `201 { "assignment": Assignment }` |
| `GET /assignments/{assignmentId}` | user | — | `{ assignment, submission: { id, status, completed, answers, files, isLate, submittedAt, gradedAt, score, feedback } }` (drafts are hidden) |
| `GET /assignments/{assignmentId}/questions` | user | — | `{ "questions": [{ id, position, prompt, options }] }` |
| `PUT /assignments/{assignmentId}/submission` | student | `{ answers: { questionId: value }, submit? }` | `{ submission }`; `400` foreign question; `409` incomplete on submit / already submitted |
| `POST /assignments/{assignmentId}/submission/files` | student | multipart `file` | `201 { submission, file: { id, name, size, uploadedAt } }` |
| `GET /assignments/{assignmentId}/submissions` | teacher | — | `{ "submissions": [submission + { studentId, studentName, fileCount }] }` |
| `PATCH /assignments/{assignmentId}/submissions/{submissionId}` | teacher | `{ score, feedback? }` | `{ submission }`; `409` unless submitted/late |

`Assignment`: `id, classId, lessonId, quizId, title, className, overview, instructions, dueAt,
points ("10.00"), questionCount, type, allowFileUpload, materials`.

## Teacher workspace (all routes: teacher)

| Method & path | Request | Response |
| --- | --- | --- |
| `GET /teacher/dashboard` | — | `{ summary: { activeClasses, totalStudents, pendingReviews, returnedSubmissions }, classes: [...], assignments: [...] }` |
| `PATCH /teacher/classes/{classId}` | `{ title?, description? (nullable), subject? (nullable), status? (active\|archived) }` | `{ "class": { id, title, description, subject, joinCode, weekCount, coverColor, status } }` |
| `GET /teacher/classes/{classId}/students` | — | `{ "students": [{ id, name, joinedAt, lessonCount, completedLessons, assignmentCount, submittedAssignments, gradedAssignments, averageScore }] }` |
| `GET /teacher/classes/{classId}/materials` | — | `{ "materials": [{ id, title, originalFilename, mimeType, byteSize, lessonId, week, createdAt }] }` |
| `POST /teacher/classes/{classId}/materials` | multipart `file`, `title?`, `weekNumber?` | `201 { "material": … }` |
| `GET /teacher/classes/{classId}/materials/{materialId}/file` | — | the file, `Content-Disposition: inline` |
| `DELETE /teacher/classes/{classId}/materials/{materialId}` | — | `{ deleted, materialId }` |
| `GET /teacher/assignments` | — | `{ "assignments": [...] }` with submission counts |
| `POST /teacher/assignments` | `{ classId, title, description?, instructions?, dueAt?, points?, type?, quizId?, publish? (default true) }` | `201 { assignment }` |
| `GET /teacher/assignments/{assignmentId}` | — | `{ assignment }` incl. `status`, `materials` |
| `PATCH /teacher/assignments/{assignmentId}` | `{ title, description?, instructions?, dueAt (nullable), points, publish? }` | `{ assignment }` |
| `DELETE /teacher/assignments/{assignmentId}` | — | `{ deleted, assignmentId }` (its quiz and files too) |
| `POST /teacher/assignments/{assignmentId}/attachment` | multipart `file` | `201 { "material": … }` |
| `POST /teacher/quizzes` | `{ classId, title, language?, count?, dueAt?, points?, publish?, questions? }` (AI-generated when `questions` omitted) | `201 { quiz: { id, title, questionCount }, assignment: { id, status } }` |
| `POST /teacher/assistant/ask` | `{ classId?, conversationId?, content, language? }` | `{ content, citations, classId, conversationId }` |
| `GET /teacher/assistant/history` | — | `{ "conversations": [{ id, classId, classTitle, language, title, lastContent, lastMessageAt }] }` |
| `DELETE /teacher/assistant/history` | — | `{ "cleared": true }` |
| `POST /teacher/assistant/quiz` | `{ classId, sourceMaterialIds?, title?, language?, difficulty?, questionTypes?, count?, includeAnswerKey? }` | `{ "draft": { title, questions, classId } }`; `503` without an OpenAI key |

## Admin console (`/api/admin`)

Every route needs a session **and** an admin account (`role` `admin` or
`super_admin`); students and teachers get `403 admin_access_required` on any
path under `/api/admin`, including unknown ones. The permission column is
checked on the server against the account's role and grants, loaded from the
database on every request. Where one route serves several kinds of account,
the service then applies the exact rule for the account it touches:

| Action on… | student | teacher | admin / super admin |
| --- | --- | --- | --- |
| view | `users.view` or `students.view` | `users.view` or `teachers.view` | `admins.view` |
| edit, reset password | `users.edit` | `users.edit` or `teachers.manage` | `admins.edit` |
| disable / enable | `users.disable` | `users.disable` or `teachers.manage` | `admins.disable` |
| delete | `users.delete` | `users.delete` | `admins.delete` |

On top of that, for every change: nobody acts on their own account
(`cannot_modify_self`), only a super admin touches a super admin
(`super_admin_protected`) or creates / promotes one (`super_admin_required`),
an admin never acts on an admin holding permissions it lacks
(`target_outranks_actor`), and nobody grants a permission — through a role or
an account — that they do not hold (`permission_escalation`). An account of a
kind the admin cannot view answers `404`, not `403`. The last active super
admin can never be disabled, demoted or deleted (`409`, `details.code:
"last_super_admin"`).

Rate limits: 240 reads and 60 writes per minute per admin; 20 password resets
per 15 minutes.

| Method & path | Permission | Request | Response |
| --- | --- | --- | --- |
| `GET /admin/me` | any admin | — | `{ user: Account, permissions: [key], isSuperAdmin }` |
| `GET /admin/dashboard` | any admin (sections filtered) | — | `{ overview?, activity?, aiUsage?, content?, generatedAt }` |
| `GET /admin/dashboard/series` | `analytics.view` or `usage.view` | `?range=today\|7d\|30d\|90d` | `{ range, granularity: hour\|day, points: [{ bucket, aiTokens, uploads, assignments, flashcards, activeUsers }] }` |
| `GET /admin/users` | any `*.view` for accounts | `?tab=all\|students\|teachers\|admins\|disabled&q&sort=created\|name\|lastLogin\|aiUsage&page&pageSize` | `{ users: [Account], page, pageSize, total }` |
| `POST /admin/users` | `users.create` | `{ fullName, email?, phone?, role: student\|teacher, temporaryPassword?, locale? }` | `201 { user, temporaryPassword? }` (generated when omitted; shown once) |
| `GET /admin/users/{userId}` | view rule | — | `{ user, usage?, limits?, activity?, audit? }` (sections by permission) |
| `PATCH /admin/users/{userId}` | edit rule | `{ fullName?, email?, phone?, role? }` | `{ user }` |
| `POST /admin/users/{userId}/disable`, `/enable` | disable rule | — | `{ user }`; disabling revokes every session |
| `DELETE /admin/users/{userId}` | delete rule | — | `{ deleted, id }` (soft delete: email freed, name cleared, history kept) |
| `POST /admin/users/{userId}/reset-password` | edit rule | — | `{ temporaryPassword, mustChangePassword: true }` |
| `GET /admin/admins` | `admins.view` | `?q&page&pageSize` | `{ admins: [Account + permissions, extraPermissions, limits?], … }` |
| `POST /admin/admins` | `admins.create` | `{ fullName, email, roleId, temporaryPassword?, status?, permissions?: [key], limits?: Limits }` | `201 { admin, temporaryPassword? }` |
| `GET /admin/admins/{userId}` | `admins.view` | — | as `GET /admin/users/{userId}` |
| `PATCH /admin/admins/{userId}` | `admins.edit` | `{ fullName?, email?, roleId?, permissions? }` | `{ admin }` |
| `DELETE /admin/admins/{userId}` | `admins.delete` | — | `{ deleted, id }` |
| `GET /admin/roles` | `roles.view`, `roles.manage`, `admins.create` or `admins.edit` | — | `{ roles: [{ id, key, name, description, kind, isSystemRole, editable, userCount, permissions, limits? }] }` |
| `POST /admin/roles` | `roles.manage` | `{ name, key?, description?, permissions }` | `201 { role }` |
| `PATCH /admin/roles/{roleId}` | `roles.manage` | `{ name?, description?, permissions? }` | `{ role }`; student, teacher and super admin roles are locked |
| `DELETE /admin/roles/{roleId}` | `roles.manage` | — | `{ deleted, id }`; `409` while any account holds it |
| `GET /admin/permissions` | as `GET /admin/roles` | — | `{ permissions: [{ category, permissions: [{ key, description }] }] }` |
| `GET /admin/usage` | `usage.view` | `?q&kind&page&pageSize` | `{ accounts: [{ …, today, month, limits }], … }` |
| `GET /admin/usage/{userId}` | `usage.view` | — | `{ today: Usage, month: Usage, daily: [Usage + date] (30 days), limits? }` |
| `POST /admin/usage/{userId}/reset` | `usage.manage` | — | today's counters set to zero |
| `GET /admin/limits/defaults` | `limits.view` | — | `{ roles: [{ id, key, name, kind, limits: Limits }] }` |
| `PATCH /admin/limits/defaults/{roleId}` | `limits.manage` | `Limits` (null = no limit) | `{ role: { id, key, limits } }` |
| `GET /admin/limits/{userId}` | `limits.view` | — | `{ defaults, overrides, effective, source, usage }` |
| `PATCH /admin/limits/{userId}` | `limits.manage` | `Limits` (null = inherit the role default) | same as GET |
| `GET /admin/audit-logs` | `audit.view` | `?from&to&actor&actorId&action&target&targetId&page&pageSize` | `{ logs: [{ id, actor, actorId, action, target, targetId, resource, resourceId, metadata, ipAddress, userAgent, createdAt }], actions, … }` |
| `GET /admin/settings` | `settings.view` or `settings.manage` | — | `{ settings: { usageLimitsEnabled, signupsEnabled } }` |
| `PATCH /admin/settings` | `settings.manage` | `{ usageLimitsEnabled?, signupsEnabled? }` | as GET |
| `GET /admin/content/sources` | `content.view` | `?q&kind&page&pageSize` | `{ items: [...], … }` |
| `DELETE /admin/content/sources/{sourceId}` | `content.manage` | — | `{ deleted, id }` |
| `GET /admin/content/classes` | `content.view` | `?q&page&pageSize` | `{ items, … }` |
| `GET /admin/content/assignments` | `assignments.view` | `?q&page&pageSize` | `{ items, … }` |
| `DELETE /admin/content/assignments/{assignmentId}` | `assignments.manage` | — | `{ deleted, id }` |
| `GET /admin/content/flashcards` | `flashcards.view` | `?q&page&pageSize` | `{ items, … }` |
| `DELETE /admin/content/flashcards/{setId}` | `flashcards.manage` | — | `{ deleted, id }` |

`Limits` is any of `dailyAiTokens`, `monthlyAiTokens`, `dailyPdfUploads`,
`monthlyPdfUploads`, `dailyAssignments`, `monthlyAssignments`,
`dailyFlashcards`, `monthlyFlashcards`, `dailyTutorMessages`,
`monthlyTutorMessages`, `dailyFileStorageBytes`, `monthlyFileStorageBytes`
(non-negative integers or `null`). Bodies that change access or limits are
strict: an unknown key is a `422`.

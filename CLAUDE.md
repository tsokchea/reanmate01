# ReanMate

Bilingual (Khmer/English) study app. Students upload documents — PDF, Word, Excel,
PowerPoint, plain text — photograph their notes, or paste a YouTube link, and get
summaries, quizzes, flashcards, and an AI tutor. Teachers create classes, lessons,
and assignments.

## Build state

**The build is complete.** Every flow — kits, ingest, summaries, tutor chat, quiz,
practice, flashcards, classes, assignments, plan limits — has a migration, a service,
a route, and a wired React page. 39 of 41 screens are built; the two skipped are the
phone-OTP and email-code screens, which need a provider that does not exist yet.

**The API is Python/Flask on SQLite.** It replaced the original Node/Express +
PostgreSQL server (still in git history) route for route: same paths, status codes,
JSON shapes, cookies and error envelope, so the client did not change.
`backend/README.md` has the architecture and the Express → Flask mapping;
`backend/API.md` documents every endpoint.

Prototype mode is retired. `client/src/mock/` is kept for backend-free design review
behind a single `VITE_DEMO` flag, default off. The shipped default is the live API.

**RBAC and the admin console are built** (`/admin` in the client, `/api/admin`
in the API, migration 002). Roles and permissions, per-account usage limits
with role defaults, usage tracking and an append-only audit log — see the
"Admin console" section of `backend/README.md`. Permissions, limits and
account status are always read from the database; the JWT's `role` claim is
never trusted for authorization. The first super admin comes from
`python -m scripts.create_super_admin`.

**The mock AI and notify providers remain in place** — see the two sections below.
They are not placeholders to be removed; they are the automatic fallback whenever a
real key is absent, and every feature was built and tested against them.

What is left before real users:

1. **OpenAI key** — the token logging is built and only the key is missing. Every
   provider method takes an `on_usage` callback (`backend/app/ai/types.py`), services
   wrap their calls in `track_generation` (`backend/app/services/ai_usage_service.py`),
   and each call lands in `ai_generations` with prompt / completion / reasoning /
   cached token counts, the language, and the source character count. Set
   `OPENAI_API_KEY` and real numbers start accruing with no code change.
   Then read `ai_token_ratios` for the Khmer-versus-English cost multiplier —
   it excludes mock rows, so it stays empty until a real key is in use.
   A week of real data beats every cost estimate.

   Measured on gpt-5.6-luna + text-embedding-3-small, same paragraph in both
   languages: Khmer costs **7.2x** the tokens in embeddings and **2.9x** in chat.
   The models do not share a tokenizer, so there is no single Khmer multiplier —
   re-measure after any change of model or endpoint. Ingest is the bulk-volume
   operation, so the embedding figure is what drives total spend.

   Before pointing `OPENAI_BASE_URL` at a new endpoint, check that it supports
   strict json_schema output, streamed usage and 1536-wide embeddings. Embedding
   width is the expensive one — `document_chunks.embedding` holds exactly 1536
   float32 values, so a mismatch means a migration and a full re-embed.

   `gpt-5.6-luna` reasons, and reasoning tokens are spent out of
   `max_completion_tokens` before any visible text is written. The tutor's
   output cap therefore covers thinking, the answer, and Khmer's ~3x token
   cost all at once — `_output_budget()` in `backend/app/ai/openai_provider.py`
   scales for both. A flat cap truncated Khmer replies mid-sentence while leaving
   English intact. Raising a cap is close to free: only generated tokens are billed.
2. **SMS/email provider** — wire `backend/app/notify`, add a `require_verified`
   step to `authenticated` in `backend/app/middleware/auth.py`, build the two
   skipped screens in `docs/screens/01-auth-onboarding/`.
3. **Storage** — uploads and the SQLite file are on local disk. Put both on a
   persistent volume (or move uploads to S3 or equivalent) before hosting.
4. **Scale-out** — rate limits, tutor stream buffers and the job queue are
   in-process, and SQLite allows one writer. Run one API process (threads, not
   workers) until those move into a shared store / client-server database.
5. **Deploy** — client to Vercel; `vercel.json` rewrites `/api` to the API host,
   so update it when the Flask API is deployed.

## Architecture

Monorepo, two apps, no shared build tooling.

- `client/` — React 19 + Vite + React Router + Tailwind. Talks to the API over HTTP only.
- `backend/` — Python + Flask REST API. Owns all database and AI access.
- `docs/` — PRD, schema docs, and UI screenshots.

The client NEVER touches the database or the AI provider directly. Everything goes
through `backend/` endpoints under `/api`.

## Stack

- React 19, Vite, React Router v7, Tailwind CSS, axios
- Python 3.11+, Flask 3 (Blueprints), Flask-CORS, SQLite via the stdlib `sqlite3` (raw SQL, no ORM)
- JWT (PyJWT, HS256) in httpOnly cookies, bcrypt for passwords, a zod-compatible
  validator (`backend/app/utils/schema.py`) for requests
- Local disk for uploads in dev
- stdlib `zipfile` for OOXML (.docx/.xlsx/.pptx are ZIP+XML containers), `pypdf` for PDF
- OpenAI API (not configured yet — see AI layer)

## Hard rules

- **Client: JavaScript only.** No `.ts` or `.tsx`, no type annotations. **npm only** —
  never pnpm, yarn, or bun; lockfiles are `package-lock.json`. **ESM everywhere** in
  the client.
- **Backend: Python only**, dependencies in `backend/requirements.txt`.
- Backend structure: `routes/` → `controllers/` → `services/` → `models/`.
  Routes only wire things up (path, guard/validation steps, controller).
  Business logic lives in services. SQL lives in models.
- No SQL string interpolation. Parameterized queries only (`$1`, `$2`).
- Admin routes guard with `require_permission(...)` (`backend/app/middleware/permissions.py`);
  per-account rules (no self-modification, no granting what you lack, super
  admins untouchable by admins) live in `backend/app/services/rbac_service.py`.
  Hiding a React link is never the security check.
- New AI calls go through `track_generation` so they are metered and stopped
  by the account's AI allowance.
- Every endpoint validates its params, query and body before doing anything else,
  and keeps the `{ error: { code, message, details } }` envelope — the client maps
  `code` to copy and renders 422 `details` per field.
- Every user-facing string in the client comes from `client/src/i18n` (km + en).
  No hardcoded text, ever.
- Write the SQL migration before building the endpoint that uses it.

## Database

SQLite (3.44+), one file at `DATABASE_URL` (default `backend/instance/reanmate.db`).
Raw parameterized SQL, no ORM. Connection handling, type converters and the SQL
functions below live in `backend/app/extensions.py`.

- UUID primary keys (TEXT, v4 generated in SQL). Timestamps are ISO-8601 UTC text
  in one fixed format (`YYYY-MM-DDTHH:MM:SS.sssZ`) so text order is time order —
  always store them through the adapter / `normalize_timestamp`, never ad hoc.
- JSON columns (declared `JSONTEXT`) for survey answers, quiz options and AI payloads.
- Declared types drive conversion on read (`TIMESTAMPTZ`, `JSONTEXT`, `BOOLEAN`,
  `DECIMAL2`, `DATE`); a computed column opts in with `AS "name [JSONTEXT]"`.
  Keep API output types stable: booleans, ISO timestamps, `"10.00"` numeric strings.
- Embeddings are 1536 float32 values in a BLOB on `document_chunks`; retrieval is
  `vec_cosine_distance()` over one kit (or one material).
- **Khmer text: NEVER use word tokenising for search.** Khmer has no word spaces.
  Use the registered `similarity()` (trigram) and `ilike()`, or vector search.
- Every foreign key gets an index. `PRAGMA foreign_keys` is on for every connection.
- Transactions are `BEGIN IMMEDIATE`, which serialises writers — that is what
  guards check-then-insert sequences (kit cap, quotas); there are no row locks.
- No Redis. OTP codes live in the database with an `expires_at` column.

### Migrations are never stubbed

**Never edit, comment out, or skip a statement to make a migration apply.** If a
prerequisite is missing, STOP and report it. Do not swap a real type for a stand-in,
drop an index the environment cannot build, or record a version in
`schema_migrations` that does not match what actually ran.

A partial apply recorded as complete is worse than a failed migration: the ledger
says the schema is current while it is not, and every later migration builds on a
database nobody has actually verified. The runner checksums each file for this
reason and refuses a migration whose contents changed after it was applied.

If a migration cannot run in the current environment, fix the environment.

## AI layer

The OpenAI API key is NOT set up yet. The mock provider serves every AI feature.

- All AI calls go through `get_ai()` in `backend/app/ai/__init__.py`. Never call the
  API from a controller or route directly.
- If `OPENAI_API_KEY` is missing, fall back to the mock provider automatically and
  log one warning at boot.
- Build and test every AI feature against the mock. Do not block UI work on the real API.
- Mock responses must return realistic shapes in both `km` and `en`.

### Provider details
- SDK: `openai` Python package.
- Chat/generation model read from `OPENAI_MODEL`, so it can change.
- Embeddings: `text-embedding-3-small`, 1536 dimensions — matches the
  `document_chunks.embedding` width exactly. Do not change the model without a migration.
- Structured output: `response_format: { type: "json_schema", strict: true }`
  for summaries, quizzes, and flashcards. Do not prompt for JSON and parse loosely.
- Streaming: `stream=True`, relayed to the client over SSE from Flask.
- The provider interface in `backend/app/ai/types.py` stays provider-agnostic. Adding
  an Anthropic provider later must require no changes outside `backend/app/ai/`.

## Ingest and file formats

All extraction lives in `backend/app/ingest/`, one module per family, each
returning numbered parts so a citation can point at something the student can
find.

- `pdf.py` — pages.
- `office.py` — Word, Excel, PowerPoint and plain text. All three Office
  formats are ZIP+XML (OOXML), so they share one reader rather than three libraries.
- `youtube.py` — transcript cues, via the InnerTube player. Do NOT go back to
  scraping the watch page: it still lists caption tracks, but their URLs now
  return an empty 200 without a proof-of-origin token, so the failure looks
  exactly like a video with no captions.
- Photographs go through the AI layer's `extract_image_text` (vision OCR), not
  through a module here.

Rules that are easy to break quietly:

- **Number parts by their real position**, never by how many survived
  extraction. A picture-only slide yields no text and is dropped; numbering by
  the surviving count shifts every slide after it, and a citation reading
  "slide 5" opens slide 6.
- **Order comes from the relationship list**, not from file names.
  `slide12.xml` is a name, not a position — reordering a deck rewrites the
  relationships and leaves the names alone. Same for workbook sheets.
- **Units are per format.** "Page 4" of a spreadsheet means nothing, so each
  extractor names its own (`slide`, `sheet`, `section`) and it rides in chunk
  metadata. Word genuinely has no pages, so it is divided into sections.
- **Reject unreadable formats at upload**, with the conversion step. A `.doc`
  is not a renamed `.docx`; `LEGACY_FORMAT_ADVICE` in
  `backend/app/middleware/upload.py` names the Save As for each one.
- Magic bytes cannot tell OOXML formats apart — all three are ZIPs. The real
  format is read from the package contents (`detect_ooxml_format`), so a
  mislabelled file is read correctly instead of refused.

## OTP and email delivery

No SMS or email provider is configured yet. The mock notifier serves every code.

- Delivery goes through `backend/app/notify` with the same mock-fallback pattern.
- In dev, the mock provider prints the code to the console and returns success.
  Never stub this in a way that can't be tested end to end.

## Design

Reference screenshots are in `docs/screens/`, grouped by flow — read
`docs/screens/INDEX.md` for the map. Match layout, spacing, and color from the
screenshots. Navy primary, owl mascot. Do not invent a visual style.

## Workflow

New work is change to a built flow: write the migration first, keep logic in
services, wire the existing screen rather than rebuilding it. Commit after each
working step.

From `backend/`: `python -m scripts.migrate` after pulling, `python run.py` to
serve, `python -m pytest` before committing (the end-to-end suite covers every route).

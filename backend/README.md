# ReanMate API — Flask

The REST API behind the ReanMate client: auth, study kits, document ingest,
AI study materials (summaries, study guides, quizzes, flashcards, mock exams),
the AI tutor, practice, classes and assignments. It owns all database and AI
access; the React client talks to it over HTTP only, under `/api`.

This is a port of the former Node/Express server (`server/`, removed — see git
history). Every route, status code, JSON shape, cookie and error envelope is
the same, so the client needed no functional changes. Endpoint reference:
[API.md](API.md).

## Stack

| Concern | Choice |
| --- | --- |
| Web framework | Flask 3 with Blueprints, Flask-CORS |
| Database | SQLite (Python's built-in `sqlite3`, SQLite 3.44+), raw parameterized SQL — no ORM |
| Auth | HS256 JWT access token + opaque refresh token, both httpOnly cookies; bcrypt passwords |
| Validation | `app/utils/schema.py`, a small zod-compatible validator (same 422 `details` the client renders) |
| AI | OpenAI (`openai` SDK), falling back to a built-in mock when `OPENAI_API_KEY` is unset |
| Ingest | `pypdf` (PDF), stdlib `zipfile` + regex (Word/Excel/PowerPoint), `httpx` (YouTube) |
| Background work | In-process job queue (`JOB_WORKERS` threads) |

## Run it

Python 3.11+ is required (3.13 tested).

```bash
cd backend
python -m venv venv

# Windows
venv\Scripts\activate
# Linux / macOS
source venv/bin/activate

pip install -r requirements.txt
cp .env.example .env          # then edit JWT_SECRET etc.
python -m scripts.migrate     # creates instance/reanmate.db and the schema
python run.py                 # http://localhost:4000
```

In another terminal, start the client (it proxies `/api` to port 4000):

```bash
npm install --prefix client
npm run dev --prefix client   # http://localhost:5173
```

Tests (unit + end-to-end over every route, on a throwaway database):

```bash
python -m pytest
```

Other commands, from `backend/`:

| Command | What it does |
| --- | --- |
| `python -m scripts.migrate` | Applies new files in `migrations/` once each; refuses a migration edited after it was applied |
| `python -m scripts.recompute_lesson_progress` | Rebuilds the lesson progress roll-up from item progress |

### Production

```bash
gunicorn --worker-class gthread --workers 1 --threads 16 --bind 0.0.0.0:$PORT wsgi:app
```

Use **one worker process**: rate-limit counters, tutor stream buffers and the
job queue live in process memory (as they did in the single Node process).
Set `NODE_ENV=production` (secure cookies, no error details in 500s) and put
`DATABASE_URL` and `UPLOAD_DIR` on a persistent disk — on a host with an
ephemeral filesystem every deploy would otherwise start empty.

## Configuration

All settings come from the environment (`backend/.env`, loaded by
python-dotenv). Names are unchanged from the Node server. See `.env.example`.

| Variable | Default | Notes |
| --- | --- | --- |
| `NODE_ENV` | `development` | `production` enables secure cookies and hides 500 details |
| `PORT` | `4000` | The client's dev proxy targets 4000 |
| `DATABASE_URL` | `sqlite:///instance/reanmate.db` | Relative paths resolve against `backend/` |
| `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated, exact origins (cookies forbid `*`) |
| `JWT_SECRET` | dev placeholder | **Change in production** |
| `ACCESS_TOKEN_TTL` | `15m` | |
| `REFRESH_TOKEN_TTL_DAYS` | `30` | |
| `UPLOAD_DIR` | `uploads` | Relative to `backend/` |
| `MAX_UPLOAD_BYTES` | `26214400` | 25 MB |
| `JSON_BODY_LIMIT` | `1mb` | |
| `OPENAI_API_KEY` | unset | Unset → mock AI provider |
| `OPENAI_BASE_URL`, `OPENAI_MODEL`, `OPENAI_EMBEDDING_MODEL` | | |
| `AI_MAX_CONCURRENCY` | `8` | AI requests one generation may run at once |
| `JOB_WORKERS` | `4` | Background jobs that run side by side |
| `OPENAI_USE_FLEX` | `false` | `true` → cheaper, ~2x slower "flex" tier for background generations |
| `SMS_PROVIDER`, `EMAIL_PROVIDER` | unset | Unset → mock notifier |

## Layout

```
backend/
├── app/
│   ├── __init__.py        create_app(): CORS, proxy fix, body parsing, blueprints
│   ├── config.py          environment → Config
│   ├── extensions.py      SQLite connections, transactions, type converters, SQL functions
│   ├── routes/            Blueprints: path + guard/validation steps + controller
│   ├── controllers/       HTTP in/out: read validated input, call a service, pick the status
│   ├── services/          business logic
│   ├── models/            SQL, one module per table group
│   ├── middleware/        auth guards, validation steps, uploads, rate limits, error handlers
│   ├── validation/        request schemas
│   ├── ai/                provider interface, mock provider, OpenAI provider
│   ├── ingest/            PDF / Office / YouTube extraction and chunking
│   ├── jobs/              background job queue
│   ├── notify/            SMS/email (mock)
│   └── utils/             JSON serialization, zod-compatible schema, JS-semantics helpers
├── migrations/            001_initial_schema.sql (SQLite)
├── scripts/               migrate.py, recompute_lesson_progress.py
├── tests/                 pytest: unit + end-to-end API
├── requirements.txt
├── .env.example
├── run.py                 development server
└── wsgi.py                production entry point
```

Request flow: `routes/` → `middleware` steps (auth → role → params → body/upload,
in the order Express ran them) → `controllers/` → `services/` → `models/`.

## How the Node server maps here

| Express (`server/src/…`) | Flask (`backend/app/…`) |
| --- | --- |
| `app.js`, `index.js` | `__init__.py` (`create_app`), `run.py`, `wsgi.py` |
| `config/env.js` | `config.py` |
| `db/pool.js`, `db/migrate.js` | `extensions.py`, `scripts/migrate.py` |
| `db/*.db.js` | `models/*.py` |
| `routes/*.routes.js` | `routes/{auth,kits,study,classes,teacher}.py` |
| `controllers/*.controller.js` | `controllers/*_controller.py` |
| `services/*.service.js` | `services/*_service.py` |
| `middleware/requireAuth.js`, `guards.js` | `middleware/auth.py` |
| `middleware/validate.js` + zod | `middleware/validate.py` + `utils/schema.py` |
| `validation/*.schemas.js` | `validation/schemas.py` |
| `middleware/upload.js` (multer) | `middleware/upload.py` |
| `middleware/rateLimit.js` | `middleware/rate_limit.py` |
| `middleware/errors.js` | `middleware/errors.py` |
| `ai/*`, `ingest/*`, `jobs/queue.js`, `notify/*` | `ai/*`, `ingest/*`, `jobs/queue.py`, `notify/` |
| `migrations/001…025_*.sql` (PostgreSQL) | `migrations/001_initial_schema.sql` (SQLite) |
| `test/*.test.js` | `tests/test_*.py` |

## Database notes (SQLite)

The schema is the final state of the 25 PostgreSQL migrations, consolidated.
Where PostgreSQL features had no SQLite equivalent:

- **pgvector** → embeddings are 1536 float32 values in a BLOB; nearest-neighbour
  search is an exact scan scored by a registered `vec_cosine_distance()`,
  scoped to one kit (or one material). Fine at study-kit scale; there is no ANN index.
- **pg_trgm** → a registered `similarity()` implementing trigram similarity, and
  `ilike()` for Unicode case-insensitive `ILIKE`. Khmer search behaves as before.
- **uuid-ossp** → UUIDv4 defaults generated in SQL.
- **`FOR UPDATE` / advisory locks** → every transaction is `BEGIN IMMEDIATE`,
  which serialises writers (the kit cap, quota counters, attempt submission).
- **timestamptz** → ISO-8601 UTC text in one fixed format, so comparison is time order.
- **`NULLS NOT DISTINCT`** (one kit-wide tutor thread) → a unique index over `COALESCE(source_id, '')`.

Column types are converted on read (by declared type) so the JSON is what the
client always received: booleans as `true/false`, timestamps as
`2026-09-24T03:15:00.123Z`, `numeric` columns (points, scores) as `"10.00"` strings.

SQLite allows one writer at a time. WAL mode keeps reads concurrent, which suits
a single-instance deployment; to run several API instances, move to a
client-server database.

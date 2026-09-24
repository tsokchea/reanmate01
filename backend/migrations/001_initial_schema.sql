-- ============================================================================
-- ReanMate — 001_initial_schema (SQLite 3.44+)
--
-- The final state of PostgreSQL migrations 001–025 (server/migrations),
-- consolidated into one SQLite schema: same tables, columns, constraints,
-- unique keys and seed rows.
--
-- How PostgreSQL features map here:
--   uuid DEFAULT uuid_generate_v4()   TEXT with a random-v4 DEFAULT expression
--   timestamptz DEFAULT now()         TIMESTAMPTZ holding ISO-8601 UTC text,
--                                     'YYYY-MM-DDTHH:MM:SS.sssZ' — one fixed
--                                     format, so text comparison is time order
--   jsonb                             JSONTEXT (JSON text; the app parses it)
--   boolean                           BOOLEAN (0/1)
--   numeric(p, 2)                     DECIMAL2 (read back as a 2-decimal string,
--                                     as node-postgres returned numerics)
--   vector(1536)                      BLOB of 1536 little-endian float32; cosine
--                                     distance is an app-registered SQL function
--   pg_trgm similarity / ILIKE        app-registered similarity() and ilike()
--   BEFORE UPDATE set_updated_at()    AFTER UPDATE triggers
--   UNIQUE ... NULLS NOT DISTINCT     a unique index over COALESCE(col, '')
--
-- The declared type names (TIMESTAMPTZ, JSONTEXT, BOOLEAN, DECIMAL2, DATE)
-- are what app/extensions.py keys its column converters on — keep them.
--
-- Khmer note: there is no full-text search here, on purpose. Khmer has no word
-- spaces; search is trigram similarity or vector search over document_chunks.
-- ============================================================================

-- ============================================================================
-- IDENTITY, AUTH, PLAN
-- ============================================================================

CREATE TABLE users (
  id                      TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  phone                   TEXT UNIQUE,
  email                   TEXT UNIQUE,
  password_hash           TEXT NOT NULL,
  full_name               TEXT,
  avatar_url              TEXT,
  role                    TEXT CHECK (role IN ('student', 'teacher')),
  locale                  TEXT NOT NULL DEFAULT 'km' CHECK (locale IN ('km', 'en')),
  plan_tier               TEXT NOT NULL DEFAULT 'free' CHECK (plan_tier IN ('free', 'plus')),
  plan_status             TEXT NOT NULL DEFAULT 'active'
                            CHECK (plan_status IN ('active', 'trialing', 'past_due', 'canceled')),
  trial_started_at        TIMESTAMPTZ,
  trial_ends_at           TIMESTAMPTZ,
  plan_period_end         TIMESTAMPTZ,
  phone_verified_at       TIMESTAMPTZ,
  email_verified_at       TIMESTAMPTZ,
  onboarding_completed_at TIMESTAMPTZ,
  status                  TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'deleted')),
  last_seen_at            TIMESTAMPTZ,
  created_at              TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at              TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  -- An account is reachable by phone, email, or both — never neither.
  CONSTRAINT users_needs_identifier CHECK (phone IS NOT NULL OR email IS NOT NULL)
);

CREATE INDEX users_role_idx      ON users (role);
CREATE INDEX users_plan_tier_idx ON users (plan_tier);

-- Phone + email one-time codes. Expiry lives here; no Redis.
CREATE TABLE verification_codes (
  id            TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  user_id       TEXT REFERENCES users (id) ON DELETE CASCADE,
  channel       TEXT NOT NULL CHECK (channel IN ('sms', 'email')),
  destination   TEXT NOT NULL,
  code_hash     TEXT NOT NULL,
  purpose       TEXT NOT NULL CHECK (purpose IN ('phone_verify', 'email_verify', 'login', 'password_reset')),
  expires_at    TIMESTAMPTZ NOT NULL,
  consumed_at   TIMESTAMPTZ,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  max_attempts  INTEGER NOT NULL DEFAULT 5,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX verification_codes_user_id_idx ON verification_codes (user_id);
CREATE INDEX verification_codes_lookup_idx  ON verification_codes (destination, purpose, expires_at DESC);
CREATE INDEX verification_codes_expires_idx ON verification_codes (expires_at);

-- Refresh-token store so httpOnly cookie sessions can be revoked.
CREATE TABLE auth_sessions (
  id         TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  user_id    TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  token_hash TEXT NOT NULL UNIQUE,
  user_agent TEXT,
  ip_address TEXT,
  expires_at TIMESTAMPTZ NOT NULL,
  revoked_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX auth_sessions_user_id_idx ON auth_sessions (user_id);
CREATE INDEX auth_sessions_expires_idx ON auth_sessions (expires_at);

CREATE TABLE onboarding_responses (
  id             TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  user_id        TEXT NOT NULL UNIQUE REFERENCES users (id) ON DELETE CASCADE,
  survey_version INTEGER NOT NULL DEFAULT 1,
  answers        JSONTEXT NOT NULL DEFAULT '{}',
  skipped        BOOLEAN NOT NULL DEFAULT 0,
  completed_at   TIMESTAMPTZ,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE plan_events (
  id           TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  user_id      TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  from_tier    TEXT CHECK (from_tier IN ('free', 'plus')),
  to_tier      TEXT NOT NULL CHECK (to_tier IN ('free', 'plus')),
  reason       TEXT NOT NULL CHECK (reason IN ('signup', 'trial_start', 'trial_end', 'upgrade', 'downgrade', 'cancel')),
  effective_at TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX plan_events_user_id_idx ON plan_events (user_id, effective_at DESC);

CREATE TABLE plan_limits (
  plan_tier   TEXT NOT NULL CHECK (plan_tier IN ('free', 'plus')),
  limit_key   TEXT NOT NULL CHECK (limit_key IN ('max_kits', 'tutor_messages_per_month', 'practice_sessions_per_week')),
  limit_value INTEGER CHECK (limit_value IS NULL OR limit_value >= 0),
  PRIMARY KEY (plan_tier, limit_key)
);

CREATE TABLE plan_features (
  plan_tier   TEXT NOT NULL CHECK (plan_tier IN ('free', 'plus')),
  feature_key TEXT NOT NULL CHECK (feature_key IN ('chapter_summaries', 'mock_exams')),
  enabled     BOOLEAN NOT NULL,
  PRIMARY KEY (plan_tier, feature_key)
);

CREATE TABLE usage_counters (
  user_id      TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  counter_key  TEXT NOT NULL,
  period_start DATE NOT NULL,
  quantity     INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  PRIMARY KEY (user_id, counter_key, period_start)
);

CREATE INDEX usage_counters_period_idx ON usage_counters (period_start, counter_key);

-- NULL means no cap.
INSERT INTO plan_limits (plan_tier, limit_key, limit_value) VALUES
  ('free', 'max_kits', 3),
  ('plus', 'max_kits', NULL),
  ('free', 'tutor_messages_per_month', 20),
  ('plus', 'tutor_messages_per_month', 300),
  ('free', 'practice_sessions_per_week', 3),
  ('plus', 'practice_sessions_per_week', NULL);

INSERT INTO plan_features (plan_tier, feature_key, enabled) VALUES
  ('free', 'chapter_summaries', 0),
  ('plus', 'chapter_summaries', 1),
  ('free', 'mock_exams', 0),
  ('plus', 'mock_exams', 1);

-- ============================================================================
-- CLASSES (declared early: kits, topics, quizzes and sessions reference them)
-- ============================================================================

CREATE TABLE classes (
  id                    TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  teacher_id            TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  title                 TEXT NOT NULL,
  description           TEXT,
  subject               TEXT,
  join_code             TEXT NOT NULL UNIQUE,
  week_count            INTEGER NOT NULL DEFAULT 12,
  cover_color           TEXT,
  cover_image_path      TEXT,
  cover_image_mime_type TEXT,
  cover_image_byte_size INTEGER,
  status                TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('draft', 'active', 'archived')),
  created_at            TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX classes_teacher_id_idx ON classes (teacher_id);
CREATE INDEX classes_status_idx     ON classes (status);

CREATE TABLE class_enrollments (
  id        TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  class_id  TEXT NOT NULL REFERENCES classes (id) ON DELETE CASCADE,
  user_id   TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  role      TEXT NOT NULL DEFAULT 'student' CHECK (role IN ('student', 'assistant')),
  status    TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'removed')),
  joined_at TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  UNIQUE (class_id, user_id)
);

CREATE INDEX class_enrollments_class_id_idx ON class_enrollments (class_id);
CREATE INDEX class_enrollments_user_id_idx  ON class_enrollments (user_id, status);

CREATE TABLE lessons (
  id          TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  class_id    TEXT NOT NULL REFERENCES classes (id) ON DELETE CASCADE,
  week_number INTEGER NOT NULL CHECK (week_number >= 1),
  position    INTEGER NOT NULL DEFAULT 0,
  title       TEXT NOT NULL,
  description TEXT,
  kind        TEXT NOT NULL DEFAULT 'reading' CHECK (kind IN ('reading', 'document', 'video', 'exercise')),
  content_md  TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX lessons_class_id_idx ON lessons (class_id, week_number, position);

CREATE TABLE lesson_items (
  id         TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  lesson_id  TEXT NOT NULL REFERENCES lessons (id) ON DELETE CASCADE,
  position   INTEGER NOT NULL,
  title      TEXT NOT NULL,
  kind       TEXT NOT NULL DEFAULT 'reading' CHECK (kind IN ('reading', 'video', 'exercise', 'quiz', 'file')),
  content_md TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  UNIQUE (lesson_id, position)
);

CREATE INDEX lesson_items_lesson_id_idx ON lesson_items (lesson_id);

CREATE TABLE lesson_item_progress (
  id             TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  lesson_item_id TEXT NOT NULL REFERENCES lesson_items (id) ON DELETE CASCADE,
  user_id        TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  completed_at   TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  UNIQUE (lesson_item_id, user_id)
);

CREATE INDEX lesson_item_progress_lesson_item_id_idx ON lesson_item_progress (lesson_item_id);
CREATE INDEX lesson_item_progress_user_id_idx        ON lesson_item_progress (user_id);

CREATE TABLE lesson_progress (
  id           TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  lesson_id    TEXT NOT NULL REFERENCES lessons (id) ON DELETE CASCADE,
  user_id      TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  status       TEXT NOT NULL DEFAULT 'not_started' CHECK (status IN ('not_started', 'in_progress', 'completed')),
  started_at   TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  UNIQUE (lesson_id, user_id)
);

CREATE INDEX lesson_progress_lesson_id_idx ON lesson_progress (lesson_id);
CREATE INDEX lesson_progress_user_id_idx   ON lesson_progress (user_id, status);

CREATE TABLE class_materials (
  id                TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  class_id          TEXT NOT NULL REFERENCES classes (id) ON DELETE CASCADE,
  lesson_id         TEXT REFERENCES lessons (id) ON DELETE SET NULL,
  uploaded_by       TEXT REFERENCES users (id) ON DELETE SET NULL,
  title             TEXT NOT NULL,
  original_filename TEXT,
  storage_path      TEXT,
  mime_type         TEXT,
  byte_size         INTEGER,
  week_number       INTEGER NOT NULL DEFAULT 1 CHECK (week_number BETWEEN 1 AND 52),
  created_at        TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX class_materials_class_id_idx    ON class_materials (class_id);
CREATE INDEX class_materials_lesson_id_idx   ON class_materials (lesson_id);
CREATE INDEX class_materials_uploaded_by_idx ON class_materials (uploaded_by);
CREATE INDEX class_materials_week_idx        ON class_materials (class_id, week_number, created_at);

-- ============================================================================
-- STUDY KITS, SOURCES, EMBEDDINGS, SUMMARIES
-- ============================================================================

CREATE TABLE study_folders (
  id         TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  user_id    TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  name       TEXT NOT NULL,
  color      TEXT,
  icon       TEXT,
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX study_folders_user_id_idx ON study_folders (user_id);

CREATE TABLE study_kits (
  id               TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  user_id          TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  folder_id        TEXT REFERENCES study_folders (id) ON DELETE SET NULL,
  class_id         TEXT REFERENCES classes (id) ON DELETE SET NULL,
  title            TEXT NOT NULL,
  description      TEXT,
  subject          TEXT,
  icon             TEXT,
  accent_color     TEXT,
  status           TEXT NOT NULL DEFAULT 'in_progress' CHECK (status IN ('in_progress', 'completed', 'archived')),
  progress_percent INTEGER NOT NULL DEFAULT 0 CHECK (progress_percent BETWEEN 0 AND 100),
  last_studied_at  TIMESTAMPTZ,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX study_kits_user_id_idx   ON study_kits (user_id);
CREATE INDEX study_kits_folder_id_idx ON study_kits (folder_id);
CREATE INDEX study_kits_class_id_idx  ON study_kits (class_id);
CREATE INDEX study_kits_status_idx    ON study_kits (user_id, status);

CREATE TABLE kit_sources (
  id                TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  study_kit_id      TEXT NOT NULL REFERENCES study_kits (id) ON DELETE CASCADE,
  user_id           TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  kind              TEXT NOT NULL CHECK (kind IN ('pdf', 'image', 'youtube', 'link', 'topic', 'text', 'document')),
  title             TEXT NOT NULL,
  original_filename TEXT,
  storage_path      TEXT,
  mime_type         TEXT,
  byte_size         INTEGER,
  page_count        INTEGER,
  source_url        TEXT,
  youtube_video_id  TEXT,
  duration_seconds  INTEGER,
  thumbnail_url     TEXT,
  extracted_text    TEXT,
  status            TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'ready', 'failed')),
  error_message     TEXT,
  processed_at      TIMESTAMPTZ,
  metadata          JSONTEXT NOT NULL DEFAULT '{}',
  created_at        TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX kit_sources_study_kit_id_idx ON kit_sources (study_kit_id);
CREATE INDEX kit_sources_user_id_idx      ON kit_sources (user_id);
CREATE INDEX kit_sources_status_idx       ON kit_sources (status) WHERE status IN ('pending', 'processing');

-- Retrieval corpus for the AI tutor; embedding is 1536 float32 values.
CREATE TABLE document_chunks (
  id            TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  source_id     TEXT NOT NULL REFERENCES kit_sources (id) ON DELETE CASCADE,
  study_kit_id  TEXT NOT NULL REFERENCES study_kits (id) ON DELETE CASCADE,
  chunk_index   INTEGER NOT NULL,
  content       TEXT NOT NULL,
  token_count   INTEGER,
  page_number   INTEGER,
  start_seconds INTEGER,
  end_seconds   INTEGER,
  embedding     BLOB CHECK (embedding IS NULL OR length(embedding) = 6144),
  metadata      JSONTEXT NOT NULL DEFAULT '{}',
  created_at    TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  UNIQUE (source_id, chunk_index)
);

CREATE INDEX document_chunks_source_id_idx    ON document_chunks (source_id);
CREATE INDEX document_chunks_study_kit_id_idx ON document_chunks (study_kit_id);

-- One cache row per (source, method, params, provider) for every generated artifact.
CREATE TABLE ai_generation_cache (
  id            TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  source_id     TEXT NOT NULL REFERENCES kit_sources (id) ON DELETE CASCADE,
  method        TEXT NOT NULL CHECK (method IN ('summarize', 'summarizeChapters', 'generateQuiz',
                                                'generateFlashcards', 'generateStudyGuide', 'generateMockExam')),
  params        JSONTEXT NOT NULL DEFAULT '{}',
  params_hash   TEXT NOT NULL CHECK (length(params_hash) = 64),
  provider      TEXT NOT NULL DEFAULT 'mock' CHECK (provider IN ('mock', 'openai')),
  outline       JSONTEXT,
  status        TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'generating', 'ready', 'failed')),
  error_message TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  UNIQUE (source_id, method, params_hash, provider)
);

CREATE INDEX ai_generation_cache_source_id_idx ON ai_generation_cache (source_id);

CREATE TABLE summaries (
  id                  TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  study_kit_id        TEXT NOT NULL REFERENCES study_kits (id) ON DELETE CASCADE,
  source_id           TEXT REFERENCES kit_sources (id) ON DELETE CASCADE,
  generation_cache_id TEXT REFERENCES ai_generation_cache (id) ON DELETE CASCADE,
  scope               TEXT NOT NULL DEFAULT 'kit' CHECK (scope IN ('kit', 'source', 'chapter')),
  chapter_index       INTEGER,
  title               TEXT NOT NULL,
  body_md             TEXT,
  key_points          JSONTEXT NOT NULL DEFAULT '[]',
  language            TEXT NOT NULL DEFAULT 'km' CHECK (language IN ('km', 'en')),
  start_seconds       INTEGER,
  end_seconds         INTEGER,
  status              TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'generating', 'ready', 'failed')),
  model               TEXT,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  CONSTRAINT summaries_chapter_needs_index CHECK (scope <> 'chapter' OR chapter_index IS NOT NULL)
);

CREATE INDEX summaries_study_kit_id_idx ON summaries (study_kit_id);
CREATE INDEX summaries_source_id_idx    ON summaries (source_id);
CREATE INDEX summaries_chapter_idx      ON summaries (source_id, chapter_index);
CREATE UNIQUE INDEX summaries_cache_scope_chapter_uidx
  ON summaries (generation_cache_id, scope, COALESCE(chapter_index, 0))
  WHERE generation_cache_id IS NOT NULL;

CREATE TABLE study_guide_modules (
  id                  TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  study_kit_id        TEXT NOT NULL REFERENCES study_kits (id) ON DELETE CASCADE,
  source_id           TEXT NOT NULL REFERENCES kit_sources (id) ON DELETE CASCADE,
  generation_cache_id TEXT REFERENCES ai_generation_cache (id) ON DELETE CASCADE,
  position            INTEGER NOT NULL CHECK (position >= 1),
  title               TEXT NOT NULL,
  explanation_md      TEXT,
  application_md      TEXT,
  pitfalls_md         TEXT,
  recall              JSONTEXT NOT NULL DEFAULT '[]',
  language            TEXT NOT NULL DEFAULT 'km' CHECK (language IN ('km', 'en')),
  status              TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'generating', 'ready', 'failed')),
  model               TEXT,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  UNIQUE (generation_cache_id, position)
);

CREATE INDEX study_guide_modules_study_kit_id_idx ON study_guide_modules (study_kit_id);
CREATE INDEX study_guide_modules_source_id_idx    ON study_guide_modules (source_id);
CREATE INDEX study_guide_modules_cache_id_idx     ON study_guide_modules (generation_cache_id);

-- ============================================================================
-- TOPICS + MASTERY
-- ============================================================================

CREATE TABLE topics (
  id           TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  study_kit_id TEXT REFERENCES study_kits (id) ON DELETE CASCADE,
  class_id     TEXT REFERENCES classes (id) ON DELETE CASCADE,
  name         TEXT NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX topics_study_kit_id_idx ON topics (study_kit_id);
CREATE INDEX topics_class_id_idx     ON topics (class_id);
CREATE UNIQUE INDEX topics_kit_name_uidx ON topics (study_kit_id, name) WHERE study_kit_id IS NOT NULL;

CREATE TABLE user_topic_mastery (
  id                TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  user_id           TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  topic_id          TEXT NOT NULL REFERENCES topics (id) ON DELETE CASCADE,
  attempts          INTEGER NOT NULL DEFAULT 0,
  correct_count     INTEGER NOT NULL DEFAULT 0,
  mastery_percent   INTEGER NOT NULL DEFAULT 0 CHECK (mastery_percent BETWEEN 0 AND 100),
  last_practiced_at TIMESTAMPTZ,
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  UNIQUE (user_id, topic_id)
);

CREATE INDEX user_topic_mastery_user_id_idx  ON user_topic_mastery (user_id);
CREATE INDEX user_topic_mastery_topic_id_idx ON user_topic_mastery (topic_id);
CREATE INDEX user_topic_mastery_weak_idx     ON user_topic_mastery (user_id, mastery_percent);

-- ============================================================================
-- QUIZZES
-- ============================================================================

-- A quiz hangs off a study kit (student-generated) or a class (teacher-authored).
CREATE TABLE quizzes (
  id                  TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  study_kit_id        TEXT REFERENCES study_kits (id) ON DELETE CASCADE,
  class_id            TEXT REFERENCES classes (id) ON DELETE CASCADE,
  lesson_id           TEXT REFERENCES lessons (id) ON DELETE CASCADE,
  source_id           TEXT REFERENCES kit_sources (id) ON DELETE SET NULL,
  created_by          TEXT REFERENCES users (id) ON DELETE SET NULL,
  generation_cache_id TEXT REFERENCES ai_generation_cache (id) ON DELETE CASCADE,
  title               TEXT NOT NULL,
  description         TEXT,
  language            TEXT NOT NULL DEFAULT 'km' CHECK (language IN ('km', 'en')),
  difficulty          TEXT CHECK (difficulty IN ('easy', 'medium', 'hard', 'mixed')),
  question_count      INTEGER NOT NULL DEFAULT 0,
  generated_by_ai     BOOLEAN NOT NULL DEFAULT 0,
  status              TEXT NOT NULL DEFAULT 'ready' CHECK (status IN ('pending', 'generating', 'ready', 'failed')),
  created_at          TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  CONSTRAINT quizzes_needs_owner CHECK (study_kit_id IS NOT NULL OR class_id IS NOT NULL)
);

CREATE INDEX quizzes_study_kit_id_idx ON quizzes (study_kit_id);
CREATE INDEX quizzes_class_id_idx     ON quizzes (class_id);
CREATE INDEX quizzes_lesson_id_idx    ON quizzes (lesson_id);
CREATE INDEX quizzes_source_id_idx    ON quizzes (source_id);
CREATE INDEX quizzes_created_by_idx   ON quizzes (created_by);
CREATE UNIQUE INDEX quizzes_generation_cache_uidx ON quizzes (generation_cache_id) WHERE generation_cache_id IS NOT NULL;

CREATE TABLE quiz_questions (
  id                    TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  quiz_id               TEXT NOT NULL REFERENCES quizzes (id) ON DELETE CASCADE,
  topic_id              TEXT REFERENCES topics (id) ON DELETE SET NULL,
  position              INTEGER NOT NULL,
  kind                  TEXT NOT NULL DEFAULT 'multiple_choice'
                          CHECK (kind IN ('multiple_choice', 'true_false', 'short_answer', 'written')),
  prompt                TEXT NOT NULL,
  options               JSONTEXT NOT NULL DEFAULT '[]',
  correct_answer        JSONTEXT,
  explanation           TEXT,
  points                INTEGER NOT NULL DEFAULT 1,
  topic_label           TEXT,
  targeted_weak_concept TEXT,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  UNIQUE (quiz_id, position)
);

CREATE INDEX quiz_questions_quiz_id_idx  ON quiz_questions (quiz_id);
CREATE INDEX quiz_questions_topic_id_idx ON quiz_questions (topic_id);
CREATE INDEX quiz_questions_targeted_weak_concept_idx ON quiz_questions (quiz_id) WHERE targeted_weak_concept IS NOT NULL;

CREATE TABLE quiz_attempts (
  id               TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  quiz_id          TEXT NOT NULL REFERENCES quizzes (id) ON DELETE CASCADE,
  user_id          TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  status           TEXT NOT NULL DEFAULT 'in_progress' CHECK (status IN ('in_progress', 'submitted', 'abandoned')),
  total_questions  INTEGER NOT NULL DEFAULT 0,
  correct_count    INTEGER NOT NULL DEFAULT 0,
  mastery_percent  INTEGER CHECK (mastery_percent BETWEEN 0 AND 100),
  takeaways        JSONTEXT NOT NULL DEFAULT '[]',
  duration_seconds INTEGER,
  started_at       TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  submitted_at     TIMESTAMPTZ
);

CREATE INDEX quiz_attempts_quiz_id_idx ON quiz_attempts (quiz_id);
CREATE INDEX quiz_attempts_user_id_idx ON quiz_attempts (user_id, started_at DESC);

CREATE TABLE quiz_attempt_answers (
  id                 TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  attempt_id         TEXT NOT NULL REFERENCES quiz_attempts (id) ON DELETE CASCADE,
  question_id        TEXT NOT NULL REFERENCES quiz_questions (id) ON DELETE CASCADE,
  response           JSONTEXT,
  is_correct         BOOLEAN,
  time_spent_seconds INTEGER,
  answered_at        TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  UNIQUE (attempt_id, question_id)
);

CREATE INDEX quiz_attempt_answers_attempt_id_idx  ON quiz_attempt_answers (attempt_id);
CREATE INDEX quiz_attempt_answers_question_id_idx ON quiz_attempt_answers (question_id);

-- ============================================================================
-- FLASHCARDS + SPACED REPETITION
-- ============================================================================

-- Shared generated content; per-user SM-2 state lives in flashcard_reviews.
CREATE TABLE flashcards (
  id                  TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  study_kit_id        TEXT NOT NULL REFERENCES study_kits (id) ON DELETE CASCADE,
  user_id             TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  source_id           TEXT REFERENCES kit_sources (id) ON DELETE SET NULL,
  topic_id            TEXT REFERENCES topics (id) ON DELETE SET NULL,
  generation_cache_id TEXT REFERENCES ai_generation_cache (id) ON DELETE CASCADE,
  term                TEXT NOT NULL,
  definition          TEXT NOT NULL,
  hint                TEXT,
  language            TEXT NOT NULL DEFAULT 'km' CHECK (language IN ('km', 'en')),
  position            INTEGER NOT NULL DEFAULT 0,
  generated_by_ai     BOOLEAN NOT NULL DEFAULT 0,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX flashcards_study_kit_id_idx ON flashcards (study_kit_id);
CREATE INDEX flashcards_user_id_idx      ON flashcards (user_id);
CREATE INDEX flashcards_source_id_idx    ON flashcards (source_id);
CREATE INDEX flashcards_topic_id_idx     ON flashcards (topic_id);
CREATE UNIQUE INDEX flashcards_generation_position_uidx
  ON flashcards (generation_cache_id, position) WHERE generation_cache_id IS NOT NULL;

-- The pre-SM-2 append-only log (PostgreSQL migration 007 kept it under this name).
CREATE TABLE flashcard_review_history (
  id                TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  flashcard_id      TEXT NOT NULL REFERENCES flashcards (id) ON DELETE CASCADE,
  user_id           TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  rating            TEXT NOT NULL CHECK (rating IN ('again', 'hard', 'good', 'easy')),
  previous_interval INTEGER,
  new_interval      INTEGER,
  ease_after        DECIMAL2,
  reviewed_at       TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX flashcard_review_history_flashcard_id_idx ON flashcard_review_history (flashcard_id);
CREATE INDEX flashcard_review_history_user_id_idx      ON flashcard_review_history (user_id, reviewed_at DESC);

CREATE TABLE flashcard_reviews (
  id               TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  user_id          TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  flashcard_id     TEXT NOT NULL REFERENCES flashcards (id) ON DELETE CASCADE,
  quality          INTEGER CHECK (quality BETWEEN 0 AND 5),
  ease_factor      DECIMAL2 NOT NULL DEFAULT 2.50 CHECK (ease_factor >= 1.30),
  interval_days    INTEGER NOT NULL DEFAULT 0 CHECK (interval_days >= 0),
  repetitions      INTEGER NOT NULL DEFAULT 0 CHECK (repetitions >= 0),
  lapses           INTEGER NOT NULL DEFAULT 0 CHECK (lapses >= 0),
  due_at           TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  last_reviewed_at TIMESTAMPTZ,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  UNIQUE (user_id, flashcard_id)
);

CREATE INDEX flashcard_reviews_due_idx ON flashcard_reviews (user_id, due_at);

-- ============================================================================
-- PRACTICE + MOCK EXAMS
-- ============================================================================

CREATE TABLE practice_sessions (
  id               TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  user_id          TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  study_kit_id     TEXT REFERENCES study_kits (id) ON DELETE CASCADE,
  class_id         TEXT REFERENCES classes (id) ON DELETE SET NULL,
  source_id        TEXT REFERENCES kit_sources (id) ON DELETE SET NULL,
  mode             TEXT NOT NULL DEFAULT 'practice' CHECK (mode IN ('practice', 'mock_exam')),
  question_count   INTEGER NOT NULL,
  answer_format    TEXT NOT NULL DEFAULT 'multiple_choice' CHECK (answer_format IN ('multiple_choice', 'written')),
  timer_seconds    INTEGER NOT NULL DEFAULT 0,
  expires_at       TIMESTAMPTZ,
  status           TEXT NOT NULL DEFAULT 'in_progress' CHECK (status IN ('in_progress', 'completed', 'abandoned')),
  answered_count   INTEGER NOT NULL DEFAULT 0,
  correct_count    INTEGER NOT NULL DEFAULT 0,
  mastery_percent  INTEGER CHECK (mastery_percent BETWEEN 0 AND 100),
  weak_topics      JSONTEXT NOT NULL DEFAULT '[]',
  duration_seconds INTEGER,
  started_at       TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  completed_at     TIMESTAMPTZ
);

CREATE INDEX practice_sessions_user_id_idx      ON practice_sessions (user_id, started_at DESC);
CREATE INDEX practice_sessions_study_kit_id_idx ON practice_sessions (study_kit_id);
CREATE INDEX practice_sessions_class_id_idx     ON practice_sessions (class_id);
CREATE INDEX practice_sessions_source_id_idx    ON practice_sessions (source_id);
CREATE INDEX practice_sessions_expires_at_idx   ON practice_sessions (expires_at)
  WHERE status = 'in_progress' AND expires_at IS NOT NULL;

CREATE TABLE practice_session_questions (
  id               TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  session_id       TEXT NOT NULL REFERENCES practice_sessions (id) ON DELETE CASCADE,
  question_id      TEXT REFERENCES quiz_questions (id) ON DELETE SET NULL,
  topic_id         TEXT REFERENCES topics (id) ON DELETE SET NULL,
  position         INTEGER NOT NULL,
  prompt           TEXT NOT NULL,
  options          JSONTEXT NOT NULL DEFAULT '[]',
  correct_answer   JSONTEXT NOT NULL,
  expected_answer  TEXT,
  explanation      TEXT NOT NULL,
  weight_at_select REAL NOT NULL DEFAULT 0,
  UNIQUE (session_id, position),
  UNIQUE (session_id, question_id)
);

CREATE INDEX practice_session_questions_session_idx ON practice_session_questions (session_id, position);
CREATE INDEX practice_session_questions_topic_idx   ON practice_session_questions (topic_id);

CREATE TABLE practice_answers (
  id                 TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  session_id         TEXT NOT NULL REFERENCES practice_sessions (id) ON DELETE CASCADE,
  question_id        TEXT REFERENCES quiz_questions (id) ON DELETE SET NULL,
  topic_id           TEXT REFERENCES topics (id) ON DELETE SET NULL,
  position           INTEGER NOT NULL,
  prompt_snapshot    TEXT,
  response           JSONTEXT,
  is_correct         BOOLEAN,
  grader_note        TEXT,
  time_spent_seconds INTEGER,
  answered_at        TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  UNIQUE (session_id, position)
);

CREATE INDEX practice_answers_session_id_idx  ON practice_answers (session_id);
CREATE INDEX practice_answers_question_id_idx ON practice_answers (question_id);
CREATE INDEX practice_answers_topic_id_idx    ON practice_answers (topic_id);

CREATE TABLE mock_exam_banks (
  id                  TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  study_kit_id        TEXT NOT NULL REFERENCES study_kits (id) ON DELETE CASCADE,
  source_id           TEXT NOT NULL REFERENCES kit_sources (id) ON DELETE CASCADE,
  generation_cache_id TEXT REFERENCES ai_generation_cache (id) ON DELETE CASCADE,
  title               TEXT NOT NULL,
  language            TEXT NOT NULL DEFAULT 'km' CHECK (language IN ('km', 'en')),
  question_count      INTEGER NOT NULL DEFAULT 0,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE UNIQUE INDEX mock_exam_banks_cache_uidx ON mock_exam_banks (generation_cache_id) WHERE generation_cache_id IS NOT NULL;
CREATE INDEX mock_exam_banks_study_kit_id_idx ON mock_exam_banks (study_kit_id);
CREATE INDEX mock_exam_banks_source_id_idx    ON mock_exam_banks (source_id);

CREATE TABLE mock_exam_questions (
  id              TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  bank_id         TEXT NOT NULL REFERENCES mock_exam_banks (id) ON DELETE CASCADE,
  topic_id        TEXT REFERENCES topics (id) ON DELETE SET NULL,
  position        INTEGER NOT NULL CHECK (position >= 1),
  kind            TEXT NOT NULL DEFAULT 'multiple_choice'
                    CHECK (kind IN ('multiple_choice', 'true_false', 'short_answer', 'written')),
  prompt          TEXT NOT NULL,
  options         JSONTEXT NOT NULL DEFAULT '[]',
  correct_answer  JSONTEXT NOT NULL,
  expected_answer TEXT NOT NULL CHECK (length(trim(expected_answer)) > 0),
  difficulty      TEXT NOT NULL DEFAULT 'medium' CHECK (difficulty IN ('easy', 'medium', 'hard')),
  explanation     TEXT NOT NULL,
  topic_label     TEXT,
  UNIQUE (bank_id, position)
);

CREATE INDEX mock_exam_questions_bank_idx  ON mock_exam_questions (bank_id, position);
CREATE INDEX mock_exam_questions_topic_idx ON mock_exam_questions (topic_id);

-- ============================================================================
-- ASSIGNMENTS
-- ============================================================================

CREATE TABLE assignments (
  id                TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  class_id          TEXT NOT NULL REFERENCES classes (id) ON DELETE CASCADE,
  lesson_id         TEXT REFERENCES lessons (id) ON DELETE SET NULL,
  quiz_id           TEXT REFERENCES quizzes (id) ON DELETE SET NULL,
  created_by        TEXT REFERENCES users (id) ON DELETE SET NULL,
  title             TEXT NOT NULL,
  description       TEXT,
  instructions      JSONTEXT NOT NULL DEFAULT '[]',
  due_at            TIMESTAMPTZ,
  points            DECIMAL2,
  question_count    INTEGER NOT NULL DEFAULT 0,
  allow_file_upload BOOLEAN NOT NULL DEFAULT 1,
  assignment_type   TEXT NOT NULL DEFAULT 'file' CHECK (assignment_type IN ('file', 'quiz')),
  status            TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published', 'closed')),
  published_at      TIMESTAMPTZ,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX assignments_class_id_idx   ON assignments (class_id, due_at);
CREATE INDEX assignments_lesson_id_idx  ON assignments (lesson_id);
CREATE INDEX assignments_quiz_id_idx    ON assignments (quiz_id);
CREATE INDEX assignments_created_by_idx ON assignments (created_by);

CREATE TABLE assignment_materials (
  id                TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  assignment_id     TEXT NOT NULL REFERENCES assignments (id) ON DELETE CASCADE,
  title             TEXT NOT NULL,
  original_filename TEXT,
  storage_path      TEXT,
  mime_type         TEXT,
  byte_size         INTEGER,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX assignment_materials_assignment_id_idx ON assignment_materials (assignment_id);

CREATE TABLE assignment_submissions (
  id                  TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  assignment_id       TEXT NOT NULL REFERENCES assignments (id) ON DELETE CASCADE,
  user_id             TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  status              TEXT NOT NULL DEFAULT 'not_started'
                        CHECK (status IN ('not_started', 'in_progress', 'submitted', 'graded', 'late')),
  answers             JSONTEXT NOT NULL DEFAULT '{}',
  completed_questions INTEGER NOT NULL DEFAULT 0,
  is_late             BOOLEAN NOT NULL DEFAULT 0,
  score               DECIMAL2,
  feedback            TEXT,
  graded_by           TEXT REFERENCES users (id) ON DELETE SET NULL,
  graded_at           TIMESTAMPTZ,
  submitted_at        TIMESTAMPTZ,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  UNIQUE (assignment_id, user_id)
);

CREATE INDEX assignment_submissions_assignment_id_idx ON assignment_submissions (assignment_id, status);
CREATE INDEX assignment_submissions_user_id_idx       ON assignment_submissions (user_id);
CREATE INDEX assignment_submissions_graded_by_idx     ON assignment_submissions (graded_by);

CREATE TABLE submission_files (
  id                TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  submission_id     TEXT NOT NULL REFERENCES assignment_submissions (id) ON DELETE CASCADE,
  original_filename TEXT NOT NULL,
  storage_path      TEXT NOT NULL,
  mime_type         TEXT,
  byte_size         INTEGER,
  uploaded_at       TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX submission_files_submission_id_idx ON submission_files (submission_id);

-- ============================================================================
-- AI TUTOR CHAT + TEACHER ASSISTANT
-- ============================================================================

CREATE TABLE chat_conversations (
  id              TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  user_id         TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  study_kit_id    TEXT REFERENCES study_kits (id) ON DELETE CASCADE,
  source_id       TEXT REFERENCES kit_sources (id) ON DELETE CASCADE,
  assignment_id   TEXT REFERENCES assignments (id) ON DELETE CASCADE,
  title           TEXT,
  language        TEXT NOT NULL DEFAULT 'km' CHECK (language IN ('km', 'en')),
  last_message_at TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX chat_conversations_user_id_idx       ON chat_conversations (user_id, last_message_at DESC);
CREATE INDEX chat_conversations_study_kit_id_idx  ON chat_conversations (study_kit_id);
CREATE INDEX chat_conversations_assignment_id_idx ON chat_conversations (assignment_id);
CREATE INDEX chat_conversations_source_id_idx     ON chat_conversations (source_id);
-- One thread per (student, kit, material, language); a NULL source is the
-- kit-wide thread and must be unique too (PostgreSQL: NULLS NOT DISTINCT).
CREATE UNIQUE INDEX chat_conversations_user_kit_source_language_uidx
  ON chat_conversations (user_id, study_kit_id, COALESCE(source_id, ''), language)
  WHERE study_kit_id IS NOT NULL;

CREATE TABLE chat_messages (
  id                  TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  conversation_id     TEXT NOT NULL REFERENCES chat_conversations (id) ON DELETE CASCADE,
  reply_to_message_id TEXT REFERENCES chat_messages (id) ON DELETE SET NULL,
  role                TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
  content             TEXT NOT NULL DEFAULT '',
  citations           JSONTEXT NOT NULL DEFAULT '[]',
  status              TEXT NOT NULL DEFAULT 'complete' CHECK (status IN ('queued', 'streaming', 'complete', 'failed')),
  model               TEXT,
  token_count         INTEGER,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX chat_messages_conversation_id_idx ON chat_messages (conversation_id, created_at);
CREATE INDEX chat_messages_reply_to_idx        ON chat_messages (reply_to_message_id);

CREATE TABLE teacher_assistant_conversations (
  id              TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  teacher_id      TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  class_id        TEXT REFERENCES classes (id) ON DELETE CASCADE,
  language        TEXT NOT NULL CHECK (language IN ('km', 'en')),
  title           TEXT,
  last_message_at TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX teacher_assistant_conversations_teacher_idx
  ON teacher_assistant_conversations (teacher_id, last_message_at DESC);

CREATE TABLE teacher_assistant_messages (
  id              TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  conversation_id TEXT NOT NULL REFERENCES teacher_assistant_conversations (id) ON DELETE CASCADE,
  role            TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  content         TEXT NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX teacher_assistant_messages_conversation_idx ON teacher_assistant_messages (conversation_id, created_at);

-- ============================================================================
-- AI AUDIT + COST LEDGER
-- ============================================================================

CREATE TABLE ai_generations (
  id                   TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  user_id              TEXT REFERENCES users (id) ON DELETE SET NULL,
  study_kit_id         TEXT REFERENCES study_kits (id) ON DELETE SET NULL,
  source_id            TEXT REFERENCES kit_sources (id) ON DELETE SET NULL,
  kind                 TEXT NOT NULL CHECK (kind IN ('summary', 'quiz', 'flashcards', 'tutor', 'takeaways',
                                                     'embedding', 'ocr', 'mock_exam')),
  provider             TEXT NOT NULL CHECK (provider IN ('openai', 'anthropic', 'mock')),
  model                TEXT,
  request              JSONTEXT NOT NULL DEFAULT '{}',
  response             JSONTEXT NOT NULL DEFAULT '{}',
  status               TEXT NOT NULL DEFAULT 'ok' CHECK (status IN ('ok', 'failed')),
  error_message        TEXT,
  latency_ms           INTEGER,
  prompt_tokens        INTEGER CHECK (prompt_tokens IS NULL OR prompt_tokens >= 0),
  completion_tokens    INTEGER CHECK (completion_tokens IS NULL OR completion_tokens >= 0),
  reasoning_tokens     INTEGER CHECK (reasoning_tokens IS NULL OR reasoning_tokens >= 0),
  cached_prompt_tokens INTEGER CHECK (cached_prompt_tokens IS NULL OR cached_prompt_tokens >= 0),
  total_tokens         INTEGER CHECK (total_tokens IS NULL OR total_tokens >= 0),
  language             TEXT CHECK (language IS NULL OR language IN ('km', 'en')),
  source_chars         INTEGER CHECK (source_chars IS NULL OR source_chars >= 0),
  api_calls            INTEGER NOT NULL DEFAULT 1 CHECK (api_calls >= 1),
  created_at           TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX ai_generations_user_id_idx      ON ai_generations (user_id, created_at DESC);
CREATE INDEX ai_generations_study_kit_id_idx ON ai_generations (study_kit_id);
CREATE INDEX ai_generations_source_id_idx    ON ai_generations (source_id);
CREATE INDEX ai_generations_language_kind_idx ON ai_generations (language, kind, created_at DESC)
  WHERE language IS NOT NULL;

-- The Khmer-versus-English cost comparison. Mock rows are excluded.
CREATE VIEW ai_token_ratios AS
SELECT language,
       kind,
       model,
       count(*)                                                     AS generations,
       sum(api_calls)                                               AS api_calls,
       sum(prompt_tokens)                                           AS prompt_tokens,
       sum(completion_tokens)                                       AS completion_tokens,
       sum(source_chars)                                            AS source_chars,
       round(avg(prompt_tokens), 1)                                 AS avg_prompt_tokens,
       round(CAST(sum(prompt_tokens) AS REAL) / NULLIF(sum(source_chars), 0), 4) AS prompt_tokens_per_char
  FROM ai_generations
 WHERE status = 'ok'
   AND provider <> 'mock'
   AND language IS NOT NULL
 GROUP BY language, kind, model;

-- ============================================================================
-- updated_at maintenance (PostgreSQL: BEFORE UPDATE set_updated_at()).
-- Recursive triggers are off, so the inner UPDATE does not re-fire these.
-- ============================================================================

CREATE TRIGGER users_set_updated_at AFTER UPDATE ON users FOR EACH ROW WHEN NEW.updated_at IS OLD.updated_at
BEGIN UPDATE users SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;

CREATE TRIGGER onboarding_responses_set_updated_at AFTER UPDATE ON onboarding_responses FOR EACH ROW WHEN NEW.updated_at IS OLD.updated_at
BEGIN UPDATE onboarding_responses SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;

CREATE TRIGGER usage_counters_set_updated_at AFTER UPDATE ON usage_counters FOR EACH ROW WHEN NEW.updated_at IS OLD.updated_at
BEGIN UPDATE usage_counters SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
       WHERE user_id = NEW.user_id AND counter_key = NEW.counter_key AND period_start = NEW.period_start; END;

CREATE TRIGGER classes_set_updated_at AFTER UPDATE ON classes FOR EACH ROW WHEN NEW.updated_at IS OLD.updated_at
BEGIN UPDATE classes SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;

CREATE TRIGGER lessons_set_updated_at AFTER UPDATE ON lessons FOR EACH ROW WHEN NEW.updated_at IS OLD.updated_at
BEGIN UPDATE lessons SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;

CREATE TRIGGER lesson_progress_set_updated_at AFTER UPDATE ON lesson_progress FOR EACH ROW WHEN NEW.updated_at IS OLD.updated_at
BEGIN UPDATE lesson_progress SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;

CREATE TRIGGER study_folders_set_updated_at AFTER UPDATE ON study_folders FOR EACH ROW WHEN NEW.updated_at IS OLD.updated_at
BEGIN UPDATE study_folders SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;

CREATE TRIGGER study_kits_set_updated_at AFTER UPDATE ON study_kits FOR EACH ROW WHEN NEW.updated_at IS OLD.updated_at
BEGIN UPDATE study_kits SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;

CREATE TRIGGER kit_sources_set_updated_at AFTER UPDATE ON kit_sources FOR EACH ROW WHEN NEW.updated_at IS OLD.updated_at
BEGIN UPDATE kit_sources SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;

CREATE TRIGGER ai_generation_cache_set_updated_at AFTER UPDATE ON ai_generation_cache FOR EACH ROW WHEN NEW.updated_at IS OLD.updated_at
BEGIN UPDATE ai_generation_cache SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;

CREATE TRIGGER summaries_set_updated_at AFTER UPDATE ON summaries FOR EACH ROW WHEN NEW.updated_at IS OLD.updated_at
BEGIN UPDATE summaries SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;

CREATE TRIGGER study_guide_modules_set_updated_at AFTER UPDATE ON study_guide_modules FOR EACH ROW WHEN NEW.updated_at IS OLD.updated_at
BEGIN UPDATE study_guide_modules SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;

CREATE TRIGGER user_topic_mastery_set_updated_at AFTER UPDATE ON user_topic_mastery FOR EACH ROW WHEN NEW.updated_at IS OLD.updated_at
BEGIN UPDATE user_topic_mastery SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;

CREATE TRIGGER quizzes_set_updated_at AFTER UPDATE ON quizzes FOR EACH ROW WHEN NEW.updated_at IS OLD.updated_at
BEGIN UPDATE quizzes SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;

CREATE TRIGGER flashcards_set_updated_at AFTER UPDATE ON flashcards FOR EACH ROW WHEN NEW.updated_at IS OLD.updated_at
BEGIN UPDATE flashcards SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;

CREATE TRIGGER flashcard_reviews_set_updated_at AFTER UPDATE ON flashcard_reviews FOR EACH ROW WHEN NEW.updated_at IS OLD.updated_at
BEGIN UPDATE flashcard_reviews SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;

CREATE TRIGGER mock_exam_banks_set_updated_at AFTER UPDATE ON mock_exam_banks FOR EACH ROW WHEN NEW.updated_at IS OLD.updated_at
BEGIN UPDATE mock_exam_banks SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;

CREATE TRIGGER chat_conversations_set_updated_at AFTER UPDATE ON chat_conversations FOR EACH ROW WHEN NEW.updated_at IS OLD.updated_at
BEGIN UPDATE chat_conversations SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;

CREATE TRIGGER assignments_set_updated_at AFTER UPDATE ON assignments FOR EACH ROW WHEN NEW.updated_at IS OLD.updated_at
BEGIN UPDATE assignments SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;

CREATE TRIGGER assignment_submissions_set_updated_at AFTER UPDATE ON assignment_submissions FOR EACH ROW WHEN NEW.updated_at IS OLD.updated_at
BEGIN UPDATE assignment_submissions SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;

-- ============================================================================
-- ReanMate — 001_init
-- PostgreSQL 16. Raw SQL, no ORM. UUID PKs, timestamptz everywhere.
--
-- Khmer note: this schema deliberately contains NO to_tsvector / tsquery.
-- Khmer has no word spaces and Postgres ships no Khmer dictionary, so the
-- default tokenizer collapses a whole sentence into one lexeme and search
-- silently returns nothing. All text search here is pg_trgm similarity
-- (see the gin_trgm_ops indexes) or vector search over document_chunks.
-- ============================================================================


-- ---------------------------------------------------------------------------
-- Extensions
-- ---------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------------------
-- Shared helpers
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- IDENTITY, AUTH, PLAN
-- Serves docs/screens/01-auth-onboarding/ and 10-profile/
-- ============================================================================

CREATE TABLE users (
  id                    uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  phone                 text UNIQUE NOT NULL,
  email                 text UNIQUE,
  password_hash         text NOT NULL,
  full_name             text,
  avatar_url            text,

  -- chosen on docs/screens/01-auth-onboarding/04-role-selection; null until picked
  role                  text CHECK (role IN ('student', 'teacher')),
  locale                text NOT NULL DEFAULT 'km' CHECK (locale IN ('km', 'en')),

  -- plan state is denormalised here because every gate check reads it
  plan_tier             text NOT NULL DEFAULT 'free' CHECK (plan_tier IN ('free', 'plus')),
  plan_status           text NOT NULL DEFAULT 'active'
                          CHECK (plan_status IN ('active', 'trialing', 'past_due', 'canceled')),
  trial_started_at      timestamptz,
  trial_ends_at         timestamptz,
  plan_period_end       timestamptz,

  phone_verified_at     timestamptz,
  email_verified_at     timestamptz,
  onboarding_completed_at timestamptz,

  status                text NOT NULL DEFAULT 'active'
                          CHECK (status IN ('active', 'suspended', 'deleted')),
  last_seen_at          timestamptz,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX users_role_idx        ON users (role);
CREATE INDEX users_plan_tier_idx   ON users (plan_tier);
CREATE INDEX users_full_name_trgm  ON users USING gin (full_name gin_trgm_ops);

CREATE TRIGGER users_set_updated_at
  BEFORE UPDATE ON users FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Phone + email one-time codes. No Redis: expiry lives here and a cleanup job
-- deletes consumed/expired rows (see cleanup_expired_verification_codes below).
CREATE TABLE verification_codes (
  id            uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id       uuid REFERENCES users (id) ON DELETE CASCADE,
  channel       text NOT NULL CHECK (channel IN ('sms', 'email')),
  destination   text NOT NULL,                 -- phone number or email address
  code_hash     text NOT NULL,                 -- bcrypt; never store the raw code
  purpose       text NOT NULL
                  CHECK (purpose IN ('phone_verify', 'email_verify', 'login', 'password_reset')),
  expires_at    timestamptz NOT NULL,
  consumed_at   timestamptz,
  attempt_count integer NOT NULL DEFAULT 0,
  max_attempts  integer NOT NULL DEFAULT 5,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX verification_codes_user_id_idx ON verification_codes (user_id);
CREATE INDEX verification_codes_lookup_idx  ON verification_codes (destination, purpose, expires_at DESC);
CREATE INDEX verification_codes_expires_idx ON verification_codes (expires_at);

-- Refresh-token store so httpOnly cookie sessions can actually be revoked.
CREATE TABLE auth_sessions (
  id            uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id       uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  token_hash    text NOT NULL UNIQUE,
  user_agent    text,
  ip_address    inet,
  expires_at    timestamptz NOT NULL,
  revoked_at    timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX auth_sessions_user_id_idx ON auth_sessions (user_id);
CREATE INDEX auth_sessions_expires_idx ON auth_sessions (expires_at);

-- 3-step survey from docs/screens/01-auth-onboarding/05..07. Shape is expected
-- to churn, so answers stay JSONB and survey_version records which shape it is.
CREATE TABLE onboarding_responses (
  id             uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id        uuid NOT NULL UNIQUE REFERENCES users (id) ON DELETE CASCADE,
  survey_version integer NOT NULL DEFAULT 1,
  answers        jsonb NOT NULL DEFAULT '{}'::jsonb,
  skipped        boolean NOT NULL DEFAULT false,
  completed_at   timestamptz,
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX onboarding_responses_user_id_idx ON onboarding_responses (user_id);
CREATE INDEX onboarding_responses_answers_gin ON onboarding_responses USING gin (answers);

CREATE TRIGGER onboarding_responses_set_updated_at
  BEFORE UPDATE ON onboarding_responses FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Audit trail behind the Free/Plus card in 01-auth-onboarding/08.
CREATE TABLE plan_events (
  id           uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id      uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  from_tier    text CHECK (from_tier IN ('free', 'plus')),
  to_tier      text NOT NULL CHECK (to_tier IN ('free', 'plus')),
  reason       text NOT NULL
                 CHECK (reason IN ('signup', 'trial_start', 'trial_end', 'upgrade', 'downgrade', 'cancel')),
  effective_at timestamptz NOT NULL DEFAULT now(),
  created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX plan_events_user_id_idx ON plan_events (user_id, effective_at DESC);

-- ============================================================================
-- STUDY KITS, SOURCES, EMBEDDINGS, SUMMARIES
-- Serves docs/screens/03-study-kits/ and 04-study-mode-summaries/
-- ============================================================================

CREATE TABLE study_folders (
  id         uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id    uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  name       text NOT NULL,
  color      text,
  icon       text,
  sort_order integer NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX study_folders_user_id_idx ON study_folders (user_id);
CREATE INDEX study_folders_name_trgm   ON study_folders USING gin (name gin_trgm_ops);

CREATE TRIGGER study_folders_set_updated_at
  BEFORE UPDATE ON study_folders FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- The cards on docs/screens/03-study-kits/01-kits-tab: title, accent, progress,
-- and an All / In progress / Completed filter driven by status.
CREATE TABLE study_kits (
  id               uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id          uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  folder_id        uuid REFERENCES study_folders (id) ON DELETE SET NULL,
  class_id         uuid,                         -- FK added after classes exists
  title            text NOT NULL,
  description      text,
  subject          text,
  icon             text,
  accent_color     text,
  status           text NOT NULL DEFAULT 'in_progress'
                     CHECK (status IN ('in_progress', 'completed', 'archived')),
  progress_percent smallint NOT NULL DEFAULT 0
                     CHECK (progress_percent BETWEEN 0 AND 100),
  last_studied_at  timestamptz,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX study_kits_user_id_idx   ON study_kits (user_id);
CREATE INDEX study_kits_folder_id_idx ON study_kits (folder_id);
CREATE INDEX study_kits_class_id_idx  ON study_kits (class_id);
CREATE INDEX study_kits_status_idx    ON study_kits (user_id, status);
-- "Search your kits" -- trigram, never to_tsvector (Khmer titles)
CREATE INDEX study_kits_title_trgm    ON study_kits USING gin (title gin_trgm_ops);

CREATE TRIGGER study_kits_set_updated_at
  BEFORE UPDATE ON study_kits FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Everything a kit was built from: uploaded PDFs/photos, YouTube links, or a
-- bare topic the student typed. status drives the processing screens in
-- docs/screens/03-study-kits/06-youtube-processing.
CREATE TABLE kit_sources (
  id                uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  study_kit_id      uuid NOT NULL REFERENCES study_kits (id) ON DELETE CASCADE,
  user_id           uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  kind              text NOT NULL
                      CHECK (kind IN ('pdf', 'image', 'youtube', 'link', 'topic', 'text')),
  title             text NOT NULL,

  -- file uploads (multer + local disk in dev)
  original_filename text,
  storage_path      text,
  mime_type         text,
  byte_size         bigint,
  page_count        integer,

  -- youtube / link
  source_url        text,
  youtube_video_id  text,
  duration_seconds  integer,
  thumbnail_url     text,

  extracted_text    text,
  status            text NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending', 'processing', 'ready', 'failed')),
  error_message     text,
  processed_at      timestamptz,
  metadata          jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX kit_sources_study_kit_id_idx ON kit_sources (study_kit_id);
CREATE INDEX kit_sources_user_id_idx      ON kit_sources (user_id);
CREATE INDEX kit_sources_status_idx       ON kit_sources (status)
  WHERE status IN ('pending', 'processing');
CREATE INDEX kit_sources_title_trgm       ON kit_sources USING gin (title gin_trgm_ops);
CREATE INDEX kit_sources_metadata_gin     ON kit_sources USING gin (metadata);

CREATE TRIGGER kit_sources_set_updated_at
  BEFORE UPDATE ON kit_sources FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Retrieval corpus for the AI tutor. page_number for PDFs, start/end seconds
-- for YouTube transcripts, so a citation can point back at the exact spot.
CREATE TABLE document_chunks (
  id            uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  source_id     uuid NOT NULL REFERENCES kit_sources (id) ON DELETE CASCADE,
  study_kit_id  uuid NOT NULL REFERENCES study_kits (id) ON DELETE CASCADE,
  chunk_index   integer NOT NULL,
  content       text NOT NULL,
  token_count   integer,
  page_number   integer,
  start_seconds integer,
  end_seconds   integer,
  embedding     vector(1536),
  metadata      jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (source_id, chunk_index)
);

CREATE INDEX document_chunks_source_id_idx    ON document_chunks (source_id);
CREATE INDEX document_chunks_study_kit_id_idx ON document_chunks (study_kit_id);
CREATE INDEX document_chunks_metadata_gin     ON document_chunks USING gin (metadata);
-- Khmer-safe lexical fallback alongside vector search
CREATE INDEX document_chunks_content_trgm     ON document_chunks USING gin (content gin_trgm_ops);
CREATE INDEX document_chunks_embedding_hnsw   ON document_chunks
  USING hnsw (embedding vector_cosine_ops);

-- docs/screens/04-study-mode-summaries/02-five-hour-summary shows a long source
-- broken into numbered chapters, each with its own generation status, so one
-- table covers the kit overview, a per-source summary, and a chapter.
CREATE TABLE summaries (
  id            uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  study_kit_id  uuid NOT NULL REFERENCES study_kits (id) ON DELETE CASCADE,
  source_id     uuid REFERENCES kit_sources (id) ON DELETE CASCADE,
  scope         text NOT NULL DEFAULT 'kit' CHECK (scope IN ('kit', 'source', 'chapter')),
  chapter_index integer,
  title         text NOT NULL,
  body_md       text,
  key_points    jsonb NOT NULL DEFAULT '[]'::jsonb,
  language      text NOT NULL DEFAULT 'km' CHECK (language IN ('km', 'en')),
  start_seconds integer,
  end_seconds   integer,
  status        text NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending', 'generating', 'ready', 'failed')),
  model         text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT summaries_chapter_needs_index
    CHECK (scope <> 'chapter' OR chapter_index IS NOT NULL)
);

CREATE INDEX summaries_study_kit_id_idx ON summaries (study_kit_id);
CREATE INDEX summaries_source_id_idx    ON summaries (source_id);
CREATE INDEX summaries_chapter_idx      ON summaries (source_id, chapter_index);
CREATE INDEX summaries_key_points_gin   ON summaries USING gin (key_points);

CREATE TRIGGER summaries_set_updated_at
  BEFORE UPDATE ON summaries FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================================================================
-- TOPICS + MASTERY
-- Feeds "What to review" (07-practice/04) and Plus weak-topic detection.
-- ============================================================================

CREATE TABLE topics (
  id           uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  study_kit_id uuid REFERENCES study_kits (id) ON DELETE CASCADE,
  class_id     uuid,                             -- FK added after classes exists
  name         text NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX topics_study_kit_id_idx ON topics (study_kit_id);
CREATE INDEX topics_class_id_idx     ON topics (class_id);
CREATE INDEX topics_name_trgm        ON topics USING gin (name gin_trgm_ops);

CREATE TABLE user_topic_mastery (
  id                uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id           uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  topic_id          uuid NOT NULL REFERENCES topics (id) ON DELETE CASCADE,
  attempts          integer NOT NULL DEFAULT 0,
  correct_count     integer NOT NULL DEFAULT 0,
  mastery_percent   smallint NOT NULL DEFAULT 0
                      CHECK (mastery_percent BETWEEN 0 AND 100),
  last_practiced_at timestamptz,
  updated_at        timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, topic_id)
);

CREATE INDEX user_topic_mastery_user_id_idx  ON user_topic_mastery (user_id);
CREATE INDEX user_topic_mastery_topic_id_idx ON user_topic_mastery (topic_id);
CREATE INDEX user_topic_mastery_weak_idx     ON user_topic_mastery (user_id, mastery_percent);

CREATE TRIGGER user_topic_mastery_set_updated_at
  BEFORE UPDATE ON user_topic_mastery FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================================================================
-- QUIZZES
-- Serves docs/screens/06-quiz/ and the Quizzes tab in 09-classes-assignments/03
-- ============================================================================

-- A quiz hangs off a study kit (student-generated) or a class/lesson
-- (teacher-authored); exactly one owner is required.
CREATE TABLE quizzes (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  study_kit_id    uuid REFERENCES study_kits (id) ON DELETE CASCADE,
  class_id        uuid,                           -- FK added after classes exists
  lesson_id       uuid,                           -- FK added after lessons exists
  source_id       uuid REFERENCES kit_sources (id) ON DELETE SET NULL,
  created_by      uuid REFERENCES users (id) ON DELETE SET NULL,
  title           text NOT NULL,
  description     text,
  language        text NOT NULL DEFAULT 'km' CHECK (language IN ('km', 'en')),
  difficulty      text CHECK (difficulty IN ('easy', 'medium', 'hard', 'mixed')),
  question_count  integer NOT NULL DEFAULT 0,
  generated_by_ai boolean NOT NULL DEFAULT false,
  status          text NOT NULL DEFAULT 'ready'
                    CHECK (status IN ('pending', 'generating', 'ready', 'failed')),
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT quizzes_needs_owner
    CHECK (study_kit_id IS NOT NULL OR class_id IS NOT NULL)
);

CREATE INDEX quizzes_study_kit_id_idx ON quizzes (study_kit_id);
CREATE INDEX quizzes_class_id_idx     ON quizzes (class_id);
CREATE INDEX quizzes_lesson_id_idx    ON quizzes (lesson_id);
CREATE INDEX quizzes_source_id_idx    ON quizzes (source_id);
CREATE INDEX quizzes_created_by_idx   ON quizzes (created_by);
CREATE INDEX quizzes_title_trgm       ON quizzes USING gin (title gin_trgm_ops);

CREATE TRIGGER quizzes_set_updated_at
  BEFORE UPDATE ON quizzes FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- options and correct_answer are JSONB so one table holds multiple choice,
-- true/false and written answers without a column per shape.
CREATE TABLE quiz_questions (
  id             uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  quiz_id        uuid NOT NULL REFERENCES quizzes (id) ON DELETE CASCADE,
  topic_id       uuid REFERENCES topics (id) ON DELETE SET NULL,
  position       integer NOT NULL,
  kind           text NOT NULL DEFAULT 'multiple_choice'
                   CHECK (kind IN ('multiple_choice', 'true_false', 'short_answer', 'written')),
  prompt         text NOT NULL,
  options        jsonb NOT NULL DEFAULT '[]'::jsonb,
  correct_answer jsonb,
  explanation    text,
  points         smallint NOT NULL DEFAULT 1,
  created_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (quiz_id, position)
);

CREATE INDEX quiz_questions_quiz_id_idx  ON quiz_questions (quiz_id);
CREATE INDEX quiz_questions_topic_id_idx ON quiz_questions (topic_id);
CREATE INDEX quiz_questions_options_gin  ON quiz_questions USING gin (options);

-- takeaways is the AI "Your takeaways" list on 06-quiz/03-quiz-completed-results
CREATE TABLE quiz_attempts (
  id               uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  quiz_id          uuid NOT NULL REFERENCES quizzes (id) ON DELETE CASCADE,
  user_id          uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  status           text NOT NULL DEFAULT 'in_progress'
                     CHECK (status IN ('in_progress', 'submitted', 'abandoned')),
  total_questions  integer NOT NULL DEFAULT 0,
  correct_count    integer NOT NULL DEFAULT 0,
  mastery_percent  smallint CHECK (mastery_percent BETWEEN 0 AND 100),
  takeaways        jsonb NOT NULL DEFAULT '[]'::jsonb,
  duration_seconds integer,
  started_at       timestamptz NOT NULL DEFAULT now(),
  submitted_at     timestamptz
);

CREATE INDEX quiz_attempts_quiz_id_idx ON quiz_attempts (quiz_id);
CREATE INDEX quiz_attempts_user_id_idx ON quiz_attempts (user_id, started_at DESC);
CREATE INDEX quiz_attempts_takeaways_gin ON quiz_attempts USING gin (takeaways);

CREATE TABLE quiz_attempt_answers (
  id                 uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  attempt_id         uuid NOT NULL REFERENCES quiz_attempts (id) ON DELETE CASCADE,
  question_id        uuid NOT NULL REFERENCES quiz_questions (id) ON DELETE CASCADE,
  response           jsonb,
  is_correct         boolean,
  time_spent_seconds integer,
  answered_at        timestamptz NOT NULL DEFAULT now(),
  UNIQUE (attempt_id, question_id)
);

CREATE INDEX quiz_attempt_answers_attempt_id_idx  ON quiz_attempt_answers (attempt_id);
CREATE INDEX quiz_attempt_answers_question_id_idx ON quiz_attempt_answers (question_id);
CREATE INDEX quiz_attempt_answers_response_gin    ON quiz_attempt_answers USING gin (response);

-- ============================================================================
-- FLASHCARDS + SPACED REPETITION
-- Serves docs/screens/08-flashcards/
-- ============================================================================

-- Kits are personal, so SM-2 scheduling state lives on the card itself.
CREATE TABLE flashcards (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  study_kit_id    uuid NOT NULL REFERENCES study_kits (id) ON DELETE CASCADE,
  user_id         uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  source_id       uuid REFERENCES kit_sources (id) ON DELETE SET NULL,
  topic_id        uuid REFERENCES topics (id) ON DELETE SET NULL,
  term            text NOT NULL,
  definition      text NOT NULL,
  hint            text,
  language        text NOT NULL DEFAULT 'km' CHECK (language IN ('km', 'en')),
  position        integer NOT NULL DEFAULT 0,
  generated_by_ai boolean NOT NULL DEFAULT false,

  -- SM-2 scheduling
  state            text NOT NULL DEFAULT 'new'
                     CHECK (state IN ('new', 'learning', 'review', 'relearning')),
  due_at           timestamptz NOT NULL DEFAULT now(),
  interval_days    integer NOT NULL DEFAULT 0,
  ease_factor      numeric(4, 2) NOT NULL DEFAULT 2.50 CHECK (ease_factor >= 1.30),
  repetition_count integer NOT NULL DEFAULT 0,
  lapse_count      integer NOT NULL DEFAULT 0,
  last_reviewed_at timestamptz,

  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX flashcards_study_kit_id_idx ON flashcards (study_kit_id);
CREATE INDEX flashcards_user_id_idx      ON flashcards (user_id);
CREATE INDEX flashcards_source_id_idx    ON flashcards (source_id);
CREATE INDEX flashcards_topic_id_idx     ON flashcards (topic_id);
-- the "cards due now" query
CREATE INDEX flashcards_due_idx          ON flashcards (user_id, due_at);
CREATE INDEX flashcards_term_trgm        ON flashcards USING gin (term gin_trgm_ops);

CREATE TRIGGER flashcards_set_updated_at
  BEFORE UPDATE ON flashcards FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Append-only review log; lets scheduling be recomputed or tuned later.
CREATE TABLE flashcard_reviews (
  id                uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  flashcard_id      uuid NOT NULL REFERENCES flashcards (id) ON DELETE CASCADE,
  user_id           uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  rating            text NOT NULL CHECK (rating IN ('again', 'hard', 'good', 'easy')),
  previous_interval integer,
  new_interval      integer,
  ease_after        numeric(4, 2),
  reviewed_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX flashcard_reviews_flashcard_id_idx ON flashcard_reviews (flashcard_id);
CREATE INDEX flashcard_reviews_user_id_idx      ON flashcard_reviews (user_id, reviewed_at DESC);

-- ============================================================================
-- PRACTICE
-- Serves docs/screens/07-practice/ (setup, batch session, results, mock exam)
-- ============================================================================

CREATE TABLE practice_sessions (
  id               uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id          uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  study_kit_id     uuid REFERENCES study_kits (id) ON DELETE CASCADE,
  class_id         uuid,                          -- FK added after classes exists
  mode             text NOT NULL DEFAULT 'practice'
                     CHECK (mode IN ('practice', 'mock_exam')),

  -- the three controls on 07-practice/01-practice-setup
  question_count   integer NOT NULL,
  answer_format    text NOT NULL DEFAULT 'multiple_choice'
                     CHECK (answer_format IN ('multiple_choice', 'written')),
  timer_seconds    integer NOT NULL DEFAULT 0,    -- 0 = no timer

  status           text NOT NULL DEFAULT 'in_progress'
                     CHECK (status IN ('in_progress', 'completed', 'abandoned')),
  answered_count   integer NOT NULL DEFAULT 0,
  correct_count    integer NOT NULL DEFAULT 0,
  mastery_percent  smallint CHECK (mastery_percent BETWEEN 0 AND 100),
  weak_topics      jsonb NOT NULL DEFAULT '[]'::jsonb,
  duration_seconds integer,
  started_at       timestamptz NOT NULL DEFAULT now(),
  completed_at     timestamptz
);

CREATE INDEX practice_sessions_user_id_idx     ON practice_sessions (user_id, started_at DESC);
CREATE INDEX practice_sessions_study_kit_id_idx ON practice_sessions (study_kit_id);
CREATE INDEX practice_sessions_class_id_idx    ON practice_sessions (class_id);
CREATE INDEX practice_sessions_weak_topics_gin ON practice_sessions USING gin (weak_topics);

CREATE TABLE practice_answers (
  id                 uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  session_id         uuid NOT NULL REFERENCES practice_sessions (id) ON DELETE CASCADE,
  question_id        uuid REFERENCES quiz_questions (id) ON DELETE SET NULL,
  topic_id           uuid REFERENCES topics (id) ON DELETE SET NULL,
  position           integer NOT NULL,
  prompt_snapshot    text,                        -- survives question deletion
  response           jsonb,
  is_correct         boolean,
  time_spent_seconds integer,
  answered_at        timestamptz NOT NULL DEFAULT now(),
  UNIQUE (session_id, position)
);

CREATE INDEX practice_answers_session_id_idx  ON practice_answers (session_id);
CREATE INDEX practice_answers_question_id_idx ON practice_answers (question_id);
CREATE INDEX practice_answers_topic_id_idx    ON practice_answers (topic_id);
CREATE INDEX practice_answers_response_gin    ON practice_answers USING gin (response);

-- ============================================================================
-- AI TUTOR CHAT
-- Serves docs/screens/05-ai-tutor-chat/
-- ============================================================================

CREATE TABLE chat_conversations (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id         uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  study_kit_id    uuid REFERENCES study_kits (id) ON DELETE CASCADE,
  assignment_id   uuid,                           -- FK added after assignments exists
  title           text,
  language        text NOT NULL DEFAULT 'km' CHECK (language IN ('km', 'en')),
  last_message_at timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX chat_conversations_user_id_idx       ON chat_conversations (user_id, last_message_at DESC);
CREATE INDEX chat_conversations_study_kit_id_idx  ON chat_conversations (study_kit_id);
CREATE INDEX chat_conversations_assignment_id_idx ON chat_conversations (assignment_id);

CREATE TRIGGER chat_conversations_set_updated_at
  BEFORE UPDATE ON chat_conversations FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- citations holds the "Source: Database Week 1.pdf" chips, as an array of
-- {source_id, title, page_number|start_seconds, chunk_id}.
CREATE TABLE chat_messages (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  conversation_id uuid NOT NULL REFERENCES chat_conversations (id) ON DELETE CASCADE,
  role            text NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
  content         text NOT NULL DEFAULT '',
  citations       jsonb NOT NULL DEFAULT '[]'::jsonb,
  status          text NOT NULL DEFAULT 'complete'
                    CHECK (status IN ('streaming', 'complete', 'failed')),
  model           text,
  token_count     integer,
  created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX chat_messages_conversation_id_idx ON chat_messages (conversation_id, created_at);
CREATE INDEX chat_messages_citations_gin       ON chat_messages USING gin (citations);

-- ============================================================================
-- CLASSES, LESSONS, ASSIGNMENTS
-- Serves docs/screens/09-classes-assignments/
-- ============================================================================

CREATE TABLE classes (
  id          uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  teacher_id  uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  title       text NOT NULL,
  description text,
  subject     text,
  join_code   text NOT NULL UNIQUE,
  week_count  smallint NOT NULL DEFAULT 12,
  cover_color text,
  status      text NOT NULL DEFAULT 'active'
                CHECK (status IN ('draft', 'active', 'archived')),
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX classes_teacher_id_idx ON classes (teacher_id);
CREATE INDEX classes_status_idx     ON classes (status);
CREATE INDEX classes_title_trgm     ON classes USING gin (title gin_trgm_ops);

CREATE TRIGGER classes_set_updated_at
  BEFORE UPDATE ON classes FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Deferred FKs from earlier sections, now that classes exists.
ALTER TABLE study_kits
  ADD CONSTRAINT study_kits_class_id_fkey
  FOREIGN KEY (class_id) REFERENCES classes (id) ON DELETE SET NULL;
ALTER TABLE topics
  ADD CONSTRAINT topics_class_id_fkey
  FOREIGN KEY (class_id) REFERENCES classes (id) ON DELETE CASCADE;
ALTER TABLE quizzes
  ADD CONSTRAINT quizzes_class_id_fkey
  FOREIGN KEY (class_id) REFERENCES classes (id) ON DELETE CASCADE;
ALTER TABLE practice_sessions
  ADD CONSTRAINT practice_sessions_class_id_fkey
  FOREIGN KEY (class_id) REFERENCES classes (id) ON DELETE SET NULL;

CREATE TABLE class_enrollments (
  id        uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  class_id  uuid NOT NULL REFERENCES classes (id) ON DELETE CASCADE,
  user_id   uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  role      text NOT NULL DEFAULT 'student'
              CHECK (role IN ('student', 'assistant')),
  status    text NOT NULL DEFAULT 'active'
              CHECK (status IN ('active', 'removed')),
  joined_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (class_id, user_id)
);

CREATE INDEX class_enrollments_class_id_idx ON class_enrollments (class_id);
CREATE INDEX class_enrollments_user_id_idx  ON class_enrollments (user_id, status);

-- "Lessons by week" accordion on 09-classes-assignments/02
CREATE TABLE lessons (
  id          uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  class_id    uuid NOT NULL REFERENCES classes (id) ON DELETE CASCADE,
  week_number smallint NOT NULL CHECK (week_number >= 1),
  position    integer NOT NULL DEFAULT 0,
  title       text NOT NULL,
  description text,
  kind        text NOT NULL DEFAULT 'reading'
                CHECK (kind IN ('reading', 'document', 'video', 'exercise')),
  content_md  text,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX lessons_class_id_idx ON lessons (class_id, week_number, position);
CREATE INDEX lessons_title_trgm   ON lessons USING gin (title gin_trgm_ops);

CREATE TRIGGER lessons_set_updated_at
  BEFORE UPDATE ON lessons FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE quizzes
  ADD CONSTRAINT quizzes_lesson_id_fkey
  FOREIGN KEY (lesson_id) REFERENCES lessons (id) ON DELETE CASCADE;

-- A lesson row on 09-classes-assignments/02 reads "1 of 3 completed", so a
-- lesson is made of ordered items and progress is tracked per item.
CREATE TABLE lesson_items (
  id         uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  lesson_id  uuid NOT NULL REFERENCES lessons (id) ON DELETE CASCADE,
  position   integer NOT NULL,
  title      text NOT NULL,
  kind       text NOT NULL DEFAULT 'reading'
               CHECK (kind IN ('reading', 'video', 'exercise', 'quiz', 'file')),
  content_md text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (lesson_id, position)
);

CREATE INDEX lesson_items_lesson_id_idx ON lesson_items (lesson_id);

CREATE TABLE lesson_item_progress (
  id             uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  lesson_item_id uuid NOT NULL REFERENCES lesson_items (id) ON DELETE CASCADE,
  user_id        uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  completed_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (lesson_item_id, user_id)
);

CREATE INDEX lesson_item_progress_lesson_item_id_idx ON lesson_item_progress (lesson_item_id);
CREATE INDEX lesson_item_progress_user_id_idx        ON lesson_item_progress (user_id);

-- Lesson-level rollup so "6 of 12 lessons completed" is one cheap count.
CREATE TABLE lesson_progress (
  id           uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  lesson_id    uuid NOT NULL REFERENCES lessons (id) ON DELETE CASCADE,
  user_id      uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  status       text NOT NULL DEFAULT 'not_started'
                 CHECK (status IN ('not_started', 'in_progress', 'completed')),
  started_at   timestamptz,
  completed_at timestamptz,
  updated_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (lesson_id, user_id)
);

CREATE INDEX lesson_progress_lesson_id_idx ON lesson_progress (lesson_id);
CREATE INDEX lesson_progress_user_id_idx   ON lesson_progress (user_id, status);

CREATE TRIGGER lesson_progress_set_updated_at
  BEFORE UPDATE ON lesson_progress FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- The Materials tab on 09-classes-assignments/02
CREATE TABLE class_materials (
  id                uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  class_id          uuid NOT NULL REFERENCES classes (id) ON DELETE CASCADE,
  lesson_id         uuid REFERENCES lessons (id) ON DELETE SET NULL,
  uploaded_by       uuid REFERENCES users (id) ON DELETE SET NULL,
  title             text NOT NULL,
  original_filename text,
  storage_path      text,
  mime_type         text,
  byte_size         bigint,
  created_at        timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX class_materials_class_id_idx    ON class_materials (class_id);
CREATE INDEX class_materials_lesson_id_idx   ON class_materials (lesson_id);
CREATE INDEX class_materials_uploaded_by_idx ON class_materials (uploaded_by);
CREATE INDEX class_materials_title_trgm      ON class_materials USING gin (title gin_trgm_ops);

-- instructions is the numbered list on 09-classes-assignments/04-assignment-detail
CREATE TABLE assignments (
  id                uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  class_id          uuid NOT NULL REFERENCES classes (id) ON DELETE CASCADE,
  lesson_id         uuid REFERENCES lessons (id) ON DELETE SET NULL,
  quiz_id           uuid REFERENCES quizzes (id) ON DELETE SET NULL,
  created_by        uuid REFERENCES users (id) ON DELETE SET NULL,
  title             text NOT NULL,
  description       text,
  instructions      jsonb NOT NULL DEFAULT '[]'::jsonb,
  due_at            timestamptz,
  points            numeric(6, 2),
  question_count    integer NOT NULL DEFAULT 0,
  allow_file_upload boolean NOT NULL DEFAULT true,
  status            text NOT NULL DEFAULT 'draft'
                      CHECK (status IN ('draft', 'published', 'closed')),
  published_at      timestamptz,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX assignments_class_id_idx     ON assignments (class_id, due_at);
CREATE INDEX assignments_lesson_id_idx    ON assignments (lesson_id);
CREATE INDEX assignments_quiz_id_idx      ON assignments (quiz_id);
CREATE INDEX assignments_created_by_idx   ON assignments (created_by);
CREATE INDEX assignments_instructions_gin ON assignments USING gin (instructions);
CREATE INDEX assignments_title_trgm       ON assignments USING gin (title gin_trgm_ops);

CREATE TRIGGER assignments_set_updated_at
  BEFORE UPDATE ON assignments FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE chat_conversations
  ADD CONSTRAINT chat_conversations_assignment_id_fkey
  FOREIGN KEY (assignment_id) REFERENCES assignments (id) ON DELETE CASCADE;

-- The "Attached materials" PDFs on 09-classes-assignments/04
CREATE TABLE assignment_materials (
  id                uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  assignment_id     uuid NOT NULL REFERENCES assignments (id) ON DELETE CASCADE,
  title             text NOT NULL,
  original_filename text,
  storage_path      text,
  mime_type         text,
  byte_size         bigint,
  created_at        timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX assignment_materials_assignment_id_idx ON assignment_materials (assignment_id);

CREATE TABLE assignment_submissions (
  id                  uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  assignment_id       uuid NOT NULL REFERENCES assignments (id) ON DELETE CASCADE,
  user_id             uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  status              text NOT NULL DEFAULT 'not_started'
                        CHECK (status IN ('not_started', 'in_progress', 'submitted', 'graded')),
  answers             jsonb NOT NULL DEFAULT '{}'::jsonb,
  completed_questions integer NOT NULL DEFAULT 0,
  is_late             boolean NOT NULL DEFAULT false,
  score               numeric(6, 2),
  feedback            text,
  graded_by           uuid REFERENCES users (id) ON DELETE SET NULL,
  graded_at           timestamptz,
  submitted_at        timestamptz,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  UNIQUE (assignment_id, user_id)
);

CREATE INDEX assignment_submissions_assignment_id_idx ON assignment_submissions (assignment_id, status);
CREATE INDEX assignment_submissions_user_id_idx       ON assignment_submissions (user_id);
CREATE INDEX assignment_submissions_graded_by_idx     ON assignment_submissions (graded_by);
CREATE INDEX assignment_submissions_answers_gin       ON assignment_submissions USING gin (answers);

CREATE TRIGGER assignment_submissions_set_updated_at
  BEFORE UPDATE ON assignment_submissions FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Upload sheet on 09-classes-assignments/05-assignment-detail-upload-file
CREATE TABLE submission_files (
  id                uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  submission_id     uuid NOT NULL REFERENCES assignment_submissions (id) ON DELETE CASCADE,
  original_filename text NOT NULL,
  storage_path      text NOT NULL,
  mime_type         text,
  byte_size         bigint,
  uploaded_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX submission_files_submission_id_idx ON submission_files (submission_id);

-- ============================================================================
-- AI AUDIT
-- Every call through server/src/ai/index.js lands here, mock or real.
-- ============================================================================

CREATE TABLE ai_generations (
  id           uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id      uuid REFERENCES users (id) ON DELETE SET NULL,
  study_kit_id uuid REFERENCES study_kits (id) ON DELETE SET NULL,
  source_id    uuid REFERENCES kit_sources (id) ON DELETE SET NULL,
  kind         text NOT NULL
                 CHECK (kind IN ('summary', 'quiz', 'flashcards', 'tutor', 'takeaways', 'embedding')),
  provider     text NOT NULL CHECK (provider IN ('anthropic', 'mock')),
  model        text,
  request      jsonb NOT NULL DEFAULT '{}'::jsonb,
  response     jsonb NOT NULL DEFAULT '{}'::jsonb,
  status       text NOT NULL DEFAULT 'ok' CHECK (status IN ('ok', 'failed')),
  error_message text,
  latency_ms   integer,
  created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ai_generations_user_id_idx      ON ai_generations (user_id, created_at DESC);
CREATE INDEX ai_generations_study_kit_id_idx ON ai_generations (study_kit_id);
CREATE INDEX ai_generations_source_id_idx    ON ai_generations (source_id);
CREATE INDEX ai_generations_request_gin      ON ai_generations USING gin (request);
CREATE INDEX ai_generations_response_gin     ON ai_generations USING gin (response);

-- ============================================================================
-- Cleanup job (no Redis; OTP expiry is swept in Postgres)
-- ============================================================================

CREATE OR REPLACE FUNCTION cleanup_expired_verification_codes()
RETURNS integer AS $$
DECLARE
  deleted_count integer;
BEGIN
  DELETE FROM verification_codes
  WHERE expires_at < now() - interval '1 day'
     OR (consumed_at IS NOT NULL AND consumed_at < now() - interval '1 day');
  GET DIAGNOSTICS deleted_count = ROW_COUNT;

  DELETE FROM auth_sessions
  WHERE expires_at < now() - interval '30 days';

  RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;


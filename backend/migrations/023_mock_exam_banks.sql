-- A mock exam gets its own generated questions.
--
-- Until now "mock exam" was a label on a practice session and nothing else:
-- `practice_sessions.mode` was written and never read, and the questions were
-- reshuffled out of `quiz_questions` — whatever the quiz feature had generated
-- for that source at ingest. Two consequences, both visible to a student:
--
--   * The bank was one quiz, 10 questions on the free plan. Choosing 20 on the
--     setup screen failed with "Not enough generated questions for those
--     settings", which reads like a bug because it is one.
--   * Exam questions and revision questions were the same questions. Sitting a
--     mock exam asked what the student had already been drilled on.
--
-- `mock_exam_questions` is deliberately NOT more rows in `quiz_questions`.
-- practiceDb.candidateQuestions draws practice from that table, so exam
-- questions living there would leak straight into revision — the separation is
-- structural rather than a WHERE clause somebody has to remember.
--
-- Shape follows `study_guide_modules` and `quizzes`: rows hang off
-- `ai_generation_cache`, so a bank is cached per (source, params, provider) and
-- regenerates when any of those change.

-- generateMockExam joins the methods that may be cached. Same widening as 005
-- (quizzes), 007 (flashcards) and 015 (study guides), and its own file for the
-- same reason 015 gives: the runner checksums applied migrations, so an earlier
-- file cannot be edited to add this.
ALTER TABLE ai_generation_cache DROP CONSTRAINT ai_generation_cache_method_check;
ALTER TABLE ai_generation_cache ADD CONSTRAINT ai_generation_cache_method_check
  CHECK (method IN ('summarize', 'summarizeChapters', 'generateQuiz',
                    'generateFlashcards', 'generateStudyGuide', 'generateMockExam'));

CREATE TABLE mock_exam_banks (
  id                  uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  study_kit_id        uuid NOT NULL REFERENCES study_kits (id) ON DELETE CASCADE,

  -- One document, one bank. The generator is handed this source's text and
  -- nothing else, so "examine this material only" is a property of the data
  -- rather than of the prompt.
  source_id           uuid NOT NULL REFERENCES kit_sources (id) ON DELETE CASCADE,
  generation_cache_id uuid REFERENCES ai_generation_cache (id) ON DELETE CASCADE,

  title               text NOT NULL,
  language            text NOT NULL DEFAULT 'km' CHECK (language IN ('km', 'en')),
  question_count      integer NOT NULL DEFAULT 0,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now()
);

-- One bank per cache row, so a regeneration updates in place instead of
-- stacking a second bank behind the first.
CREATE UNIQUE INDEX mock_exam_banks_cache_uidx
  ON mock_exam_banks (generation_cache_id)
  WHERE generation_cache_id IS NOT NULL;

CREATE TRIGGER mock_exam_banks_set_updated_at
  BEFORE UPDATE ON mock_exam_banks FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX mock_exam_banks_study_kit_id_idx ON mock_exam_banks (study_kit_id);
CREATE INDEX mock_exam_banks_source_id_idx    ON mock_exam_banks (source_id);

CREATE TABLE mock_exam_questions (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  bank_id         uuid NOT NULL REFERENCES mock_exam_banks (id) ON DELETE CASCADE,
  topic_id        uuid REFERENCES topics (id) ON DELETE SET NULL,

  position        integer NOT NULL CHECK (position >= 1),
  kind            text NOT NULL DEFAULT 'multiple_choice'
                    CHECK (kind IN ('multiple_choice', 'true_false', 'short_answer', 'written')),
  prompt          text NOT NULL,
  options         jsonb NOT NULL DEFAULT '[]'::jsonb,
  correct_answer  jsonb NOT NULL,

  -- The correct answer written out in full, one or two sentences — never a
  -- letter. This is what makes the answer-format toggle real: the same question
  -- can be sat with its options shown, or with them hidden and a typed answer
  -- marked against this text. Marking free prose against one option's wording
  -- is why a correct answer phrased differently has been scored wrong.
  expected_answer text NOT NULL CHECK (length(trim(expected_answer)) > 0),

  difficulty      text NOT NULL DEFAULT 'medium'
                    CHECK (difficulty IN ('easy', 'medium', 'hard')),
  explanation     text NOT NULL,
  topic_label     text,

  UNIQUE (bank_id, position)
);

CREATE INDEX mock_exam_questions_bank_idx  ON mock_exam_questions (bank_id, position);
CREATE INDEX mock_exam_questions_topic_idx ON mock_exam_questions (topic_id);

-- A session question drawn from a bank has no mastery weight: the exam covers
-- the document rather than targeting what the student is weakest at, so there
-- is no figure to record. NOT NULL without a default meant every insert had to
-- invent one.
ALTER TABLE practice_session_questions
  ALTER COLUMN weight_at_select SET DEFAULT 0;

-- `question_id` is already nullable and already ON DELETE SET NULL, so an exam
-- question that points at no `quiz_questions` row needs nothing further. The
-- UNIQUE (session_id, question_id) on that table tolerates repeated NULLs —
-- Postgres treats NULLs as distinct — so a whole exam of them is fine.

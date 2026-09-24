ALTER TABLE ai_generation_cache DROP CONSTRAINT ai_generation_cache_method_check;
ALTER TABLE ai_generation_cache ADD CONSTRAINT ai_generation_cache_method_check
  CHECK (method IN ('summarize', 'summarizeChapters', 'generateQuiz'));

ALTER TABLE quizzes
  ADD COLUMN generation_cache_id uuid REFERENCES ai_generation_cache (id) ON DELETE CASCADE;

CREATE UNIQUE INDEX quizzes_generation_cache_uidx
  ON quizzes (generation_cache_id) WHERE generation_cache_id IS NOT NULL;

ALTER TABLE quiz_questions ADD COLUMN topic_label text;

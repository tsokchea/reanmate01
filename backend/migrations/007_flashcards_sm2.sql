ALTER TABLE ai_generation_cache DROP CONSTRAINT ai_generation_cache_method_check;
ALTER TABLE ai_generation_cache ADD CONSTRAINT ai_generation_cache_method_check
  CHECK (method IN ('summarize', 'summarizeChapters', 'generateQuiz', 'generateFlashcards'));

-- Generated card content is shared at source/cache level. Scheduling belongs
-- exclusively to the reviewing user in flashcard_reviews.
DROP INDEX IF EXISTS flashcards_due_idx;
ALTER TABLE flashcards
  DROP COLUMN state,
  DROP COLUMN due_at,
  DROP COLUMN interval_days,
  DROP COLUMN ease_factor,
  DROP COLUMN repetition_count,
  DROP COLUMN lapse_count,
  DROP COLUMN last_reviewed_at,
  ADD COLUMN generation_cache_id uuid REFERENCES ai_generation_cache (id) ON DELETE CASCADE;

CREATE UNIQUE INDEX flashcards_generation_position_uidx
  ON flashcards (generation_cache_id, position) WHERE generation_cache_id IS NOT NULL;

-- Preserve any legacy append-only records, then replace the table with the
-- per-user current scheduling state required for shared kits.
ALTER TABLE flashcard_reviews RENAME TO flashcard_review_history;
ALTER TABLE flashcard_review_history RENAME CONSTRAINT flashcard_reviews_pkey TO flashcard_review_history_pkey;
ALTER INDEX flashcard_reviews_flashcard_id_idx RENAME TO flashcard_review_history_flashcard_id_idx;
ALTER INDEX flashcard_reviews_user_id_idx RENAME TO flashcard_review_history_user_id_idx;

CREATE TABLE flashcard_reviews (
  id               uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id          uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  flashcard_id     uuid NOT NULL REFERENCES flashcards (id) ON DELETE CASCADE,
  quality          integer CHECK (quality BETWEEN 0 AND 5),
  ease_factor      numeric(4, 2) NOT NULL DEFAULT 2.50 CHECK (ease_factor >= 1.30),
  interval_days    integer NOT NULL DEFAULT 0 CHECK (interval_days >= 0),
  repetitions      integer NOT NULL DEFAULT 0 CHECK (repetitions >= 0),
  lapses           integer NOT NULL DEFAULT 0 CHECK (lapses >= 0),
  due_at           timestamptz NOT NULL DEFAULT now(),
  last_reviewed_at timestamptz,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, flashcard_id)
);

CREATE INDEX flashcard_reviews_due_idx ON flashcard_reviews (user_id, due_at);
CREATE TRIGGER flashcard_reviews_set_updated_at
  BEFORE UPDATE ON flashcard_reviews FOR EACH ROW EXECUTE FUNCTION set_updated_at();

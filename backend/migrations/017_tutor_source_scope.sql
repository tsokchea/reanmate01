-- Point the tutor at one file.
--
-- The tutor has been kit-wide: a question was answered from whichever chunk in
-- the whole kit matched best, so asking about one PDF could be answered out of
-- an unrelated one sitting next to it — with that other file's name on the
-- citation chip, which reads as a bug and is one.
--
-- A conversation now belongs to a material. `source_id` NULL still means the
-- whole kit, which is what every existing conversation is and what the picker
-- offers as "all materials".
--
-- ON DELETE CASCADE, matching summaries, quizzes and flashcards: a thread whose
-- file is gone cannot retrieve anything and every citation in it dangles, so
-- keeping it would leave the student a conversation that can no longer answer.

ALTER TABLE chat_conversations
  ADD COLUMN source_id uuid REFERENCES kit_sources (id) ON DELETE CASCADE;

CREATE INDEX chat_conversations_source_id_idx ON chat_conversations (source_id);

-- One thread per file, so switching between materials and back returns to the
-- conversation you were having about each.
--
-- NULLS NOT DISTINCT is the point of this index: without it Postgres treats
-- every NULL `source_id` as unique, so the kit-wide conversation would be
-- created again on every message instead of being reused. It needs PG15+; the
-- project is on 16.
DROP INDEX chat_conversations_user_kit_language_uidx;

CREATE UNIQUE INDEX chat_conversations_user_kit_source_language_uidx
  ON chat_conversations (user_id, study_kit_id, source_id, language)
  NULLS NOT DISTINCT
  WHERE study_kit_id IS NOT NULL;

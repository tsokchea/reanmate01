-- Scope a practice session to one uploaded file.
--
-- Studying a kit now starts from a single material: picking cost-analyst1.pdf
-- out of a kit opens the study options for that file alone, and a mock exam
-- taken from there must draw only on questions generated from that file.
-- Quizzes already carry `source_id`, so the questions can be filtered; what was
-- missing was somewhere to record which file a session was about, without which
-- the session could not say afterwards what it had covered.
--
-- Nullable on purpose: a session started from the Practice tab is still about
-- the whole kit, and every session that already exists is one of those.
-- ON DELETE SET NULL matches quizzes and flashcards — deleting a file must not
-- take a completed session's score with it.

ALTER TABLE practice_sessions
  ADD COLUMN source_id uuid REFERENCES kit_sources (id) ON DELETE SET NULL;

CREATE INDEX practice_sessions_source_id_idx ON practice_sessions (source_id);

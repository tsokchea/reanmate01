ALTER TABLE practice_sessions
  ADD COLUMN expires_at timestamptz;

CREATE INDEX practice_sessions_expires_at_idx
  ON practice_sessions (expires_at)
  WHERE status = 'in_progress' AND expires_at IS NOT NULL;

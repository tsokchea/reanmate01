ALTER TABLE assignments
  ADD COLUMN assignment_type text NOT NULL DEFAULT 'file'
    CHECK (assignment_type IN ('file', 'quiz'));

UPDATE assignments SET assignment_type = 'quiz' WHERE quiz_id IS NOT NULL;

ALTER TABLE assignment_submissions DROP CONSTRAINT assignment_submissions_status_check;
ALTER TABLE assignment_submissions ADD CONSTRAINT assignment_submissions_status_check
  CHECK (status IN ('not_started', 'in_progress', 'submitted', 'graded', 'late'));


ALTER TABLE class_materials
  ADD COLUMN week_number integer NOT NULL DEFAULT 1
  CHECK (week_number BETWEEN 1 AND 52);

CREATE INDEX class_materials_week_idx
  ON class_materials (class_id, week_number, created_at);

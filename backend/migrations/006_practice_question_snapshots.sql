CREATE UNIQUE INDEX topics_kit_name_uidx
  ON topics (study_kit_id, name) WHERE study_kit_id IS NOT NULL;

INSERT INTO topics (study_kit_id, name)
SELECT DISTINCT q.study_kit_id, qq.topic_label
  FROM quiz_questions qq JOIN quizzes q ON q.id = qq.quiz_id
 WHERE q.study_kit_id IS NOT NULL AND NULLIF(trim(qq.topic_label), '') IS NOT NULL
ON CONFLICT (study_kit_id, name) WHERE study_kit_id IS NOT NULL DO NOTHING;

UPDATE quiz_questions qq
   SET topic_id = t.id
  FROM quizzes q, topics t
 WHERE q.id = qq.quiz_id AND t.study_kit_id = q.study_kit_id
   AND t.name = qq.topic_label AND qq.topic_id IS NULL;

CREATE TABLE practice_session_questions (
  id                uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  session_id        uuid NOT NULL REFERENCES practice_sessions (id) ON DELETE CASCADE,
  question_id       uuid REFERENCES quiz_questions (id) ON DELETE SET NULL,
  topic_id          uuid REFERENCES topics (id) ON DELETE SET NULL,
  position          integer NOT NULL,
  prompt            text NOT NULL,
  options           jsonb NOT NULL DEFAULT '[]'::jsonb,
  correct_answer    jsonb NOT NULL,
  explanation       text NOT NULL,
  weight_at_select  numeric(8, 4) NOT NULL,
  UNIQUE (session_id, position),
  UNIQUE (session_id, question_id)
);

CREATE INDEX practice_session_questions_session_idx ON practice_session_questions (session_id, position);
CREATE INDEX practice_session_questions_topic_idx ON practice_session_questions (topic_id);

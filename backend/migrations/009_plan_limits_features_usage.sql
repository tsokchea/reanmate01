CREATE TABLE plan_limits (
  plan_tier text NOT NULL CHECK (plan_tier IN ('free', 'plus')),
  limit_key text NOT NULL CHECK (limit_key IN (
    'max_kits', 'tutor_messages_per_month', 'practice_sessions_per_week'
  )),
  limit_value integer CHECK (limit_value IS NULL OR limit_value >= 0),
  PRIMARY KEY (plan_tier, limit_key)
);

CREATE TABLE plan_features (
  plan_tier text NOT NULL CHECK (plan_tier IN ('free', 'plus')),
  feature_key text NOT NULL CHECK (feature_key IN ('chapter_summaries', 'mock_exams')),
  enabled boolean NOT NULL,
  PRIMARY KEY (plan_tier, feature_key)
);

CREATE TABLE usage_counters (
  user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  counter_key text NOT NULL,
  period_start date NOT NULL,
  quantity integer NOT NULL DEFAULT 0 CHECK (quantity >= 0),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, counter_key, period_start)
);

CREATE INDEX usage_counters_period_idx ON usage_counters (period_start, counter_key);
CREATE TRIGGER usage_counters_set_updated_at
  BEFORE UPDATE ON usage_counters FOR EACH ROW EXECUTE FUNCTION set_updated_at();

INSERT INTO plan_limits (plan_tier, limit_key, limit_value) VALUES
  ('free', 'max_kits', 3),
  ('plus', 'max_kits', NULL),
  ('free', 'tutor_messages_per_month', 20),
  ('plus', 'tutor_messages_per_month', 300),
  ('free', 'practice_sessions_per_week', 3),
  ('plus', 'practice_sessions_per_week', NULL);

INSERT INTO plan_features (plan_tier, feature_key, enabled) VALUES
  ('free', 'chapter_summaries', false),
  ('plus', 'chapter_summaries', true),
  ('free', 'mock_exams', false),
  ('plus', 'mock_exams', true);

INSERT INTO usage_counters (user_id, counter_key, period_start, quantity)
SELECT c.user_id, 'tutor_messages_per_month',
       (date_trunc('month', now() AT TIME ZONE 'UTC'))::date,
       count(*)::int
  FROM chat_messages m JOIN chat_conversations c ON c.id = m.conversation_id
 WHERE m.role = 'assistant' AND m.status = 'complete'
   AND m.created_at >= date_trunc('month', now() AT TIME ZONE 'UTC')
 GROUP BY c.user_id;


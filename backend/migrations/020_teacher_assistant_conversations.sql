CREATE TABLE teacher_assistant_conversations (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  teacher_id      uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  class_id        uuid REFERENCES classes (id) ON DELETE CASCADE,
  language       text NOT NULL CHECK (language IN ('km', 'en')),
  title           text,
  last_message_at timestamptz NOT NULL DEFAULT now(),
  created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX teacher_assistant_conversations_teacher_idx
  ON teacher_assistant_conversations (teacher_id, last_message_at DESC);

CREATE TABLE teacher_assistant_messages (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  conversation_id uuid NOT NULL REFERENCES teacher_assistant_conversations (id) ON DELETE CASCADE,
  role            text NOT NULL CHECK (role IN ('user', 'assistant')),
  content         text NOT NULL,
  created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX teacher_assistant_messages_conversation_idx
  ON teacher_assistant_messages (conversation_id, created_at);

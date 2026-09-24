-- One conversation per user/kit/language keeps reloads on the same history.
CREATE UNIQUE INDEX chat_conversations_user_kit_language_uidx
  ON chat_conversations (user_id, study_kit_id, language)
  WHERE study_kit_id IS NOT NULL;

ALTER TABLE chat_messages
  ADD COLUMN reply_to_message_id uuid REFERENCES chat_messages (id) ON DELETE SET NULL;

CREATE INDEX chat_messages_reply_to_idx ON chat_messages (reply_to_message_id);

ALTER TABLE chat_messages DROP CONSTRAINT chat_messages_status_check;
ALTER TABLE chat_messages ADD CONSTRAINT chat_messages_status_check
  CHECK (status IN ('queued', 'streaming', 'complete', 'failed'));

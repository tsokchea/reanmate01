-- Photo materials are about to start costing tokens.
--
-- Until now an uploaded photo was stored as a single placeholder chunk
-- ("[Image: notes.jpg]") — the upload succeeded, the source went ready, and
-- every summary, quiz and flashcard was then generated from that one string.
-- Reading the text off the image needs a vision call, and that call has to be
-- logged like every other one or the photo path becomes the one kind of AI
-- spend that never appears in ai_generations.
--
-- The kind CHECK dates from 001_init.sql, when the only generations were the
-- ones that write study materials, so adding a row with kind 'ocr' would fail
-- the constraint. It is listed alongside 'embedding' rather than the content
-- kinds on purpose: both are ingest-time work that produces no user-visible
-- text of its own, and the cost reports read more honestly when the two
-- mechanical steps sit together.
--
-- This also puts photos into ai_token_ratios, which is the point. Khmer
-- handwriting is exactly the material where the Khmer-versus-English token
-- multiplier is least predictable, and image tokens are priced differently
-- from text tokens again — so it needs measuring, not estimating.

ALTER TABLE ai_generations DROP CONSTRAINT ai_generations_kind_check;
ALTER TABLE ai_generations ADD CONSTRAINT ai_generations_kind_check
  CHECK (kind IN ('summary', 'quiz', 'flashcards', 'tutor', 'takeaways', 'embedding', 'ocr'));

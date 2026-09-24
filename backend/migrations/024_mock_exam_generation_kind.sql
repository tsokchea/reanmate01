-- Let a mock exam generation be logged.
--
-- `ai_generations.kind` names what an AI call was FOR, and is constrained to a
-- known list — last rewritten in 011 to admit 'ocr'. Every service wraps its
-- call in `trackGeneration`, which inserts a row here, so a kind the CHECK does
-- not know fails the INSERT and takes the whole generation down with it.
--
-- Separate from 023 because 023 has already been committed. The runner
-- checksums each file and refuses one whose contents changed after it was
-- applied; editing 023 in place would either be rejected on a database that has
-- run it, or — worse — accepted on one that has not, leaving two databases with
-- the same recorded version and different schemas.
--
-- Worth having its own kind rather than borrowing 'quiz': exam generation is a
-- 30-question bank with an expected answer written out per question, so its
-- token cost per call is several times a quiz's. Folded together, the Khmer
-- multiplier read off `ai_token_ratios` would average two workloads that are
-- not comparable, and the number is meant to drive real cost decisions.

ALTER TABLE ai_generations DROP CONSTRAINT ai_generations_kind_check;
ALTER TABLE ai_generations ADD CONSTRAINT ai_generations_kind_check
  CHECK (kind IN ('summary', 'quiz', 'flashcards', 'tutor', 'takeaways',
                  'embedding', 'ocr', 'mock_exam'));

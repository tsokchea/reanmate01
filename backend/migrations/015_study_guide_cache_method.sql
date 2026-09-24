-- Let a study guide be cached.
--
-- `ai_generation_cache.method` names the provider method whose output the row
-- holds, and is constrained to a known list — last rewritten in 007 to admit
-- flashcards. `generateStudyGuide` has to join it or every guide fails at the
-- INSERT, before the model is ever called.
--
-- Separate from 014 because 014 has already been applied: the runner checksums
-- each file and refuses one whose contents changed afterwards, which is the
-- behaviour that keeps the ledger honest.

ALTER TABLE ai_generation_cache DROP CONSTRAINT ai_generation_cache_method_check;
ALTER TABLE ai_generation_cache ADD CONSTRAINT ai_generation_cache_method_check
  CHECK (method IN ('summarize', 'summarizeChapters', 'generateQuiz',
                    'generateFlashcards', 'generateStudyGuide'));

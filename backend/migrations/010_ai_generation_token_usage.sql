-- ai_generations has existed since 001_init.sql but nothing ever wrote to it:
-- no service inserts a row, so the table is empty and the cost question
-- CLAUDE.md raises ("measure Khmer token ratios against English") has no data
-- behind it. Two things blocked that.
--
-- First, the provider CHECK predates the move to OpenAI and allows only
-- 'anthropic' and 'mock', so logging a real call would fail the constraint.
-- 'anthropic' stays listed: types.js keeps the interface provider-agnostic so a
-- second provider needs no changes outside server/src/ai/, and this constraint
-- should not be what breaks that.
--
-- Second, there were no token columns at all. The four below mirror the OpenAI
-- usage block exactly (prompt/completion/reasoning, plus the cached prompt
-- tokens that are billed at a discount) so a row is a faithful record of what
-- was charged rather than a derived guess.

ALTER TABLE ai_generations DROP CONSTRAINT ai_generations_provider_check;
ALTER TABLE ai_generations ADD CONSTRAINT ai_generations_provider_check
  CHECK (provider IN ('openai', 'anthropic', 'mock'));

ALTER TABLE ai_generations
  ADD COLUMN prompt_tokens        integer CHECK (prompt_tokens IS NULL OR prompt_tokens >= 0),
  ADD COLUMN completion_tokens    integer CHECK (completion_tokens IS NULL OR completion_tokens >= 0),
  -- Null on models that do not reason (gpt-4o-mini), set on the o-series.
  ADD COLUMN reasoning_tokens     integer CHECK (reasoning_tokens IS NULL OR reasoning_tokens >= 0),
  -- usage.prompt_tokens_details.cached_tokens — a subset of prompt_tokens.
  ADD COLUMN cached_prompt_tokens integer CHECK (cached_prompt_tokens IS NULL OR cached_prompt_tokens >= 0),
  ADD COLUMN total_tokens         integer CHECK (total_tokens IS NULL OR total_tokens >= 0),
  -- The ratio measurement is meaningless without knowing which script was sent
  -- and how much of it: Khmer is dense in characters and, on a byte-pair
  -- tokenizer with no Khmer vocabulary, expensive in tokens per character.
  ADD COLUMN language             text CHECK (language IS NULL OR language IN ('km', 'en')),
  ADD COLUMN source_chars         integer CHECK (source_chars IS NULL OR source_chars >= 0),
  -- One logical generation can span several API calls — summarizeChapters
  -- fans out one call per chapter — so tokens are summed and this records how
  -- many calls that sum covers.
  ADD COLUMN api_calls            integer NOT NULL DEFAULT 1 CHECK (api_calls >= 1);

-- The measurement query groups by language and kind over a time window.
CREATE INDEX ai_generations_language_kind_idx
  ON ai_generations (language, kind, created_at DESC)
  WHERE language IS NOT NULL;

-- Answers the CLAUDE.md question directly: tokens per source character, by
-- language. Compare the km and en rows — the quotient is the Khmer cost
-- multiplier. Mock rows are excluded because their token counts are synthetic
-- and would otherwise pollute the average.
CREATE VIEW ai_token_ratios AS
SELECT
  language,
  kind,
  model,
  count(*)                                        AS generations,
  sum(api_calls)                                  AS api_calls,
  sum(prompt_tokens)                              AS prompt_tokens,
  sum(completion_tokens)                          AS completion_tokens,
  sum(source_chars)                               AS source_chars,
  round(avg(prompt_tokens)::numeric, 1)           AS avg_prompt_tokens,
  -- NULLIF keeps a zero-character row from dividing by zero.
  round(sum(prompt_tokens)::numeric
        / NULLIF(sum(source_chars), 0), 4)        AS prompt_tokens_per_char
FROM ai_generations
WHERE status = 'ok'
  AND provider <> 'mock'
  AND language IS NOT NULL
GROUP BY language, kind, model;

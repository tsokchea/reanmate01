-- Source-level AI artefacts are shared cache entries. params_hash is SHA-256
-- of canonical JSON params; user_id is intentionally absent from the key.
CREATE TABLE ai_generation_cache (
  id           uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  source_id    uuid NOT NULL REFERENCES kit_sources (id) ON DELETE CASCADE,
  method       text NOT NULL CHECK (method IN ('summarize', 'summarizeChapters')),
  params       jsonb NOT NULL DEFAULT '{}'::jsonb,
  params_hash  text NOT NULL CHECK (length(params_hash) = 64),
  outline      jsonb,
  status       text NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending', 'generating', 'ready', 'failed')),
  error_message text,
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (source_id, method, params_hash)
);

CREATE INDEX ai_generation_cache_source_id_idx ON ai_generation_cache (source_id);
CREATE INDEX ai_generation_cache_params_gin ON ai_generation_cache USING gin (params);

CREATE TRIGGER ai_generation_cache_set_updated_at
  BEFORE UPDATE ON ai_generation_cache FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE summaries
  ADD COLUMN generation_cache_id uuid REFERENCES ai_generation_cache (id) ON DELETE CASCADE;

CREATE UNIQUE INDEX summaries_cache_scope_chapter_uidx
  ON summaries (generation_cache_id, scope, COALESCE(chapter_index, 0))
  WHERE generation_cache_id IS NOT NULL;

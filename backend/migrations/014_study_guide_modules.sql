-- The study guide, as teaching modules rather than a summary.
--
-- A summary is passive: it tells a student what the document said. A module
-- teaches one concept out of it — scaffolded explanation, worked application,
-- the pitfalls around it, and a recall question to check the student actually
-- has it. That is four bodies of markdown plus a set of question/answer pairs
-- per concept, which is why this is its own table and not more columns on
-- `summaries`.
--
-- Shape follows `summaries`: rows hang off `ai_generation_cache` so a run is
-- resumable. The guide is outlined once (module titles land in the cache's
-- `outline`), one row per module is inserted as 'pending', and each body is
-- claimed and written independently — a failure on module 6 leaves 1-5 readable
-- and only 6 is retried.
--
-- `position` is the module's place in the guide, numbered by the order concepts
-- appear in the document, and is what the screen orders by. It is NOT a count
-- of what generated successfully: a module whose body failed keeps its position
-- and shows as failed, so the numbering a student sees never shifts under them.

CREATE TABLE study_guide_modules (
  id                  uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  study_kit_id        uuid NOT NULL REFERENCES study_kits (id) ON DELETE CASCADE,

  -- One document, one guide. The generator is given this source's text and
  -- nothing else, and every module is a child of that one source — there is no
  -- column here that could pull in a sibling file from the same kit.
  source_id           uuid NOT NULL REFERENCES kit_sources (id) ON DELETE CASCADE,
  generation_cache_id uuid REFERENCES ai_generation_cache (id) ON DELETE CASCADE,

  position            integer NOT NULL CHECK (position >= 1),
  title               text NOT NULL,

  -- The four sections. Null until the body is generated; the row exists from
  -- the outline onward so the screen can show the module list while it fills.
  explanation_md      text,
  application_md      text,
  pitfalls_md         text,

  -- [{ "question": "...", "answer": "..." }] — one or two per module. JSONB so
  -- the pair stays together; splitting it into a second table would buy nothing
  -- since nothing ever queries a single question on its own.
  recall              jsonb NOT NULL DEFAULT '[]'::jsonb,

  language            text NOT NULL DEFAULT 'km' CHECK (language IN ('km', 'en')),
  status              text NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'generating', 'ready', 'failed')),
  model               text,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),

  UNIQUE (generation_cache_id, position)
);

-- Every foreign key gets an index (CLAUDE.md, Database).
CREATE INDEX study_guide_modules_study_kit_id_idx  ON study_guide_modules (study_kit_id);
CREATE INDEX study_guide_modules_source_id_idx     ON study_guide_modules (source_id);
CREATE INDEX study_guide_modules_cache_id_idx      ON study_guide_modules (generation_cache_id);
CREATE INDEX study_guide_modules_recall_idx        ON study_guide_modules USING gin (recall);

CREATE TRIGGER study_guide_modules_set_updated_at
  BEFORE UPDATE ON study_guide_modules
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

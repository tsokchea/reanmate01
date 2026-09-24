"""SQL for ``study_guide_modules``. The cache row itself belongs to models.summaries."""

from ..extensions import query, query_one, transaction
from ..utils.serialization import dumps


def save_outline(*, cache_id, source, outline, language):
    """One 'pending' row per module; DO NOTHING so a resumed run never resets a written module."""
    with transaction() as tx:
        tx.query("UPDATE ai_generation_cache SET outline = $2 WHERE id = $1", [cache_id, dumps(outline)])
        for module in outline:
            tx.query(
                """INSERT INTO study_guide_modules
                     (study_kit_id, source_id, generation_cache_id, position, title, language, status)
                   VALUES ($1, $2, $3, $4, $5, $6, 'pending')
                   ON CONFLICT (generation_cache_id, position) DO NOTHING""",
                [source["study_kit_id"], source["id"], cache_id, module.get("moduleIndex"), module.get("title"),
                 language],
            )


def list_modules(cache_id):
    return query(
        """SELECT id, position, title, explanation_md, application_md, pitfalls_md,
                  recall, language, status, updated_at
             FROM study_guide_modules
            WHERE generation_cache_id = $1
            ORDER BY position""",
        [cache_id],
    ).rows


def claim_module(cache_id, position):
    return query_one(
        """UPDATE study_guide_modules SET status = 'generating'
            WHERE generation_cache_id = $1 AND position = $2 AND status IN ('pending', 'failed')
            RETURNING id""",
        [cache_id, position],
    )


def save_module(*, cache_id, module, model):
    query(
        """UPDATE study_guide_modules
              SET title = $3, explanation_md = $4, application_md = $5, pitfalls_md = $6,
                  recall = $7, status = 'ready', model = $8
            WHERE generation_cache_id = $1 AND position = $2""",
        [cache_id, module["moduleIndex"], module["title"], module["explanationMd"], module["applicationMd"],
         module["pitfallsMd"], dumps(module.get("recall") or []), model],
    )


def fail_module(cache_id, position):
    query(
        "UPDATE study_guide_modules SET status = 'failed' WHERE generation_cache_id = $1 AND position = $2",
        [cache_id, position],
    )


def finish(cache_id):
    """Ready only when every module is; one failed module leaves the guide 'failed' for a retry."""
    query(
        """UPDATE ai_generation_cache c
              SET status = CASE
                WHEN NOT EXISTS (
                  SELECT 1 FROM study_guide_modules m
                   WHERE m.generation_cache_id = c.id AND m.status <> 'ready') THEN 'ready'
                WHEN EXISTS (
                  SELECT 1 FROM study_guide_modules m
                   WHERE m.generation_cache_id = c.id AND m.status = 'failed') THEN 'failed'
                ELSE 'generating' END
            WHERE c.id = $1""",
        [cache_id],
    )

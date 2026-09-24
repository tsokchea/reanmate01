"""SQL for ``ai_generation_cache`` and ``summaries``.

The cache row is shared by every generated artifact (summaries, chapters,
study guides, quizzes, flashcards, exam banks); this module owns it.
"""

from ..extensions import query, query_one, transaction
from ..utils.serialization import dumps

CACHE_SELECT = """
  SELECT c.id, c.source_id, c.method, c.params, c.params_hash, c.provider,
         c.outline, c.status, c.error_message, c.created_at, c.updated_at
    FROM ai_generation_cache c"""


def get_or_create_cache(key):
    """``provider`` completes the key — a mock row and a real row are different rows."""
    return query_one(
        """INSERT INTO ai_generation_cache (source_id, method, params, params_hash, provider)
           VALUES ($1, $2, $3, $4, $5)
           ON CONFLICT (source_id, method, params_hash, provider) DO UPDATE
             SET params = ai_generation_cache.params
           RETURNING *""",
        [key["sourceId"], key["method"], dumps(key["params"]), key["paramsHash"], key["provider"]],
    )


def find_cache(cache_id):
    return query_one(f"{CACHE_SELECT} WHERE c.id = $1", [cache_id])


def claim_cache(cache_id):
    return query_one(
        """UPDATE ai_generation_cache
              SET status = 'generating', error_message = NULL
            WHERE id = $1 AND status <> 'ready'
            RETURNING *""",
        [cache_id],
    )


def save_summary(*, cache_id, source, result, model):
    with transaction() as tx:
        tx.query(
            """INSERT INTO summaries
                 (study_kit_id, source_id, generation_cache_id, scope, title, body_md,
                  key_points, language, status, model)
               VALUES ($1, $2, $3, 'source', $4, $5, $6, $7, 'ready', $8)
               ON CONFLICT (generation_cache_id, scope, COALESCE(chapter_index, 0))
                 WHERE generation_cache_id IS NOT NULL
               DO UPDATE SET title = excluded.title, body_md = excluded.body_md,
                             key_points = excluded.key_points, status = 'ready', model = excluded.model""",
            [source["study_kit_id"], source["id"], cache_id, result["title"], result["bodyMd"],
             dumps(result["keyPoints"]), result["language"], model],
        )
        tx.query("UPDATE ai_generation_cache SET status = 'ready', error_message = NULL WHERE id = $1", [cache_id])


def save_outline(*, cache_id, source, outline, language):
    with transaction() as tx:
        tx.query("UPDATE ai_generation_cache SET outline = $2 WHERE id = $1", [cache_id, dumps(outline)])
        for chapter in outline:
            tx.query(
                """INSERT INTO summaries
                     (study_kit_id, source_id, generation_cache_id, scope, chapter_index,
                      title, language, start_seconds, end_seconds, status)
                   VALUES ($1, $2, $3, 'chapter', $4, $5, $6, $7, $8, 'pending')
                   ON CONFLICT (generation_cache_id, scope, COALESCE(chapter_index, 0))
                     WHERE generation_cache_id IS NOT NULL DO NOTHING""",
                [source["study_kit_id"], source["id"], cache_id, chapter.get("chapterIndex"), chapter.get("title"),
                 language, chapter.get("startSeconds"), chapter.get("endSeconds")],
            )


def list_chapters(cache_id):
    return query(
        """SELECT id, chapter_index, title, body_md, key_points, language,
                  start_seconds, end_seconds, status, updated_at
             FROM summaries
            WHERE generation_cache_id = $1 AND scope = 'chapter'
            ORDER BY chapter_index""",
        [cache_id],
    ).rows


def get_summary(cache_id):
    return query_one(
        """SELECT id, title, body_md, key_points, language, status, updated_at
             FROM summaries WHERE generation_cache_id = $1 AND scope = 'source'""",
        [cache_id],
    )


def claim_chapter(cache_id, chapter_index):
    return query_one(
        """UPDATE summaries SET status = 'generating'
            WHERE generation_cache_id = $1 AND scope = 'chapter' AND chapter_index = $2
              AND status IN ('pending', 'failed')
            RETURNING id""",
        [cache_id, chapter_index],
    )


def save_chapter(*, cache_id, chapter, model):
    query(
        """UPDATE summaries SET body_md = $3, key_points = $4, status = 'ready', model = $5
            WHERE generation_cache_id = $1 AND scope = 'chapter' AND chapter_index = $2""",
        [cache_id, chapter["chapterIndex"], chapter["bodyMd"], dumps(chapter["keyPoints"]), model],
    )


def fail_chapter(cache_id, chapter_index):
    query(
        """UPDATE summaries SET status = 'failed'
            WHERE generation_cache_id = $1 AND scope = 'chapter' AND chapter_index = $2""",
        [cache_id, chapter_index],
    )


def finish_chapters(cache_id):
    query(
        """UPDATE ai_generation_cache AS c
              SET status = CASE
                WHEN NOT EXISTS (SELECT 1 FROM summaries s WHERE s.generation_cache_id = c.id AND s.status <> 'ready')
                  THEN 'ready'
                WHEN EXISTS (SELECT 1 FROM summaries s WHERE s.generation_cache_id = c.id AND s.status = 'failed')
                  THEN 'failed'
                ELSE 'generating' END
            WHERE c.id = $1""",
        [cache_id],
    )


def fail_cache(cache_id, message):
    query(
        "UPDATE ai_generation_cache SET status = 'failed', error_message = $2 WHERE id = $1",
        [cache_id, str(message)[:2000]],
    )

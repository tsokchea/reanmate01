"""SQL for ``document_chunks`` — the retrieval corpus.

Embeddings are 1536 float32 values in a BLOB. Nearest-neighbour search is an
exact scan scored by vec_cosine_distance() (pgvector's ``<=>``), limited to one
kit — or one material — so it only ever touches that kit's chunks.
"""

from ..extensions import query, vector_blob
from ..utils.serialization import dumps


def insert_batch(tx, *, source_id, study_kit_id, chunks):
    inserted = []
    for chunk in chunks or []:
        inserted.append(tx.query_one(
            """INSERT INTO document_chunks (
                 source_id, study_kit_id, chunk_index, content, token_count,
                 page_number, start_seconds, end_seconds, embedding, metadata
               )
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
               RETURNING id, chunk_index""",
            [
                source_id, study_kit_id, chunk["chunkIndex"], chunk["content"], chunk.get("tokenCount"),
                chunk.get("pageNumber"), chunk.get("startSeconds"), chunk.get("endSeconds"),
                vector_blob(chunk.get("embedding")), dumps(chunk.get("metadata") or {}),
            ],
        ))
    return inserted


def list_for_source(source_id):
    return query(
        """SELECT id, source_id, study_kit_id, chunk_index, content,
                  token_count, page_number, start_seconds, end_seconds, metadata, created_at
             FROM document_chunks
            WHERE source_id = $1
            ORDER BY chunk_index ASC""",
        [source_id],
    ).rows


def count_for_source(source_id):
    rows = query("SELECT count(*) AS count FROM document_chunks WHERE source_id = $1", [source_id]).rows
    return rows[0]["count"] if rows else 0


def cosine_search_for_kit(*, kit_id, embedding, limit=3, source_id=None):
    """Nearest chunks to a question, optionally narrowed to one material."""
    return query(
        """SELECT c.id, c.source_id, c.content, c.page_number,
                  c.start_seconds, c.end_seconds, s.title,
                  vec_cosine_distance(c.embedding, $2) AS distance
             FROM document_chunks c
             JOIN kit_sources s ON s.id = c.source_id
            WHERE c.study_kit_id = $1 AND c.embedding IS NOT NULL
              AND ($4 IS NULL OR c.source_id = $4)
            ORDER BY distance
            LIMIT $3""",
        [kit_id, vector_blob(embedding), limit, source_id],
    ).rows


def delete_for_source(tx, *, source_id):
    sql = "DELETE FROM document_chunks WHERE source_id = $1"
    if tx:
        tx.query(sql, [source_id])
    else:
        query(sql, [source_id])

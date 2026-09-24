"""SQL for flashcards and per-user SM-2 reviews."""

from ..extensions import query, query_one, transaction
from .quiz import upsert_topic

CARD_SELECT = """
  SELECT f.id, f.study_kit_id, f.source_id, f.term, f.definition, f.hint,
         f.language, f.position, f.generated_by_ai,
         CAST(COALESCE(r.ease_factor, 2.50) AS REAL) AS ease_factor,
         CAST(COALESCE(r.interval_days, 0) AS INTEGER) AS interval_days,
         CAST(COALESCE(r.repetitions, 0) AS INTEGER) AS repetitions,
         CAST(COALESCE(r.lapses, 0) AS INTEGER) AS lapses,
         COALESCE(r.due_at, f.created_at) AS "due_at [TIMESTAMPTZ]",
         r.last_reviewed_at"""

# The owner, or a student actively enrolled in the class the kit is shared to.
_ACCESS = """(k.user_id = $1 OR EXISTS (
    SELECT 1 FROM class_enrollments ce
     WHERE ce.class_id = k.class_id AND ce.user_id = $1 AND ce.status = 'active'
  ))"""


def save_generated(*, cache_id, source, cards, language):
    with transaction() as tx:
        for position, card in enumerate(cards):
            topic_id = upsert_topic(tx, source["study_kit_id"], card["topic"])["id"] if card.get("topic") else None
            tx.query(
                """INSERT INTO flashcards
                     (study_kit_id, user_id, source_id, topic_id, generation_cache_id,
                      term, definition, hint, language, position, generated_by_ai)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 1)
                   ON CONFLICT (generation_cache_id, position) WHERE generation_cache_id IS NOT NULL
                   DO NOTHING""",
                [source["study_kit_id"], source["user_id"], source["id"], topic_id, cache_id,
                 card["term"], card["definition"], card.get("hint"), language, position],
            )
        tx.query("UPDATE ai_generation_cache SET status = 'ready', error_message = NULL WHERE id = $1", [cache_id])


def by_cache(cache_id, user_id):
    return query(
        f"""{CARD_SELECT}
             FROM flashcards f
             LEFT JOIN flashcard_reviews r ON r.flashcard_id = f.id AND r.user_id = $2
            WHERE f.generation_cache_id = $1 ORDER BY f.position""",
        [cache_id, user_id],
    ).rows


def due(*, user_id, limit, kit_id=None, source_id=None):
    return query(
        f"""{CARD_SELECT}
             FROM flashcards f
             JOIN study_kits k ON k.id = f.study_kit_id
             LEFT JOIN flashcard_reviews r ON r.flashcard_id = f.id AND r.user_id = $1
            WHERE {_ACCESS}
              AND ($3 IS NULL OR f.study_kit_id = $3)
              AND ($4 IS NULL OR f.source_id = $4)
              AND COALESCE(r.due_at, f.created_at) <= now()
            ORDER BY COALESCE(r.due_at, f.created_at), f.position
            LIMIT $2""",
        [user_id, limit, kit_id, source_id],
    ).rows


def review(*, user_id, flashcard_id, quality, reviewed_at, calculate):
    with transaction() as tx:
        card = tx.query_one(
            """SELECT f.id FROM flashcards f JOIN study_kits k ON k.id = f.study_kit_id
                WHERE f.id = $2 AND (k.user_id = $1 OR EXISTS (
                  SELECT 1 FROM class_enrollments ce
                   WHERE ce.class_id = k.class_id AND ce.user_id = $1 AND ce.status = 'active'
                ))""",
            [user_id, flashcard_id],
        )
        if not card:
            return None

        current = tx.query_one(
            """SELECT CAST(ease_factor AS REAL) AS ease_factor, interval_days, repetitions, lapses
                 FROM flashcard_reviews WHERE user_id = $1 AND flashcard_id = $2""",
            [user_id, flashcard_id],
        )
        state = current and {
            "easeFactor": current["ease_factor"],
            "intervalDays": current["interval_days"],
            "repetitions": current["repetitions"],
            "lapses": current["lapses"],
        }
        nxt = calculate(state, quality, reviewed_at)

        return tx.query_one(
            """INSERT INTO flashcard_reviews
                 (user_id, flashcard_id, quality, ease_factor, interval_days,
                  repetitions, lapses, due_at, last_reviewed_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
               ON CONFLICT (user_id, flashcard_id) DO UPDATE SET
                 quality = excluded.quality, ease_factor = excluded.ease_factor,
                 interval_days = excluded.interval_days, repetitions = excluded.repetitions,
                 lapses = excluded.lapses, due_at = excluded.due_at,
                 last_reviewed_at = excluded.last_reviewed_at
               RETURNING *""",
            [user_id, flashcard_id, quality, nxt["easeFactor"], nxt["intervalDays"], nxt["repetitions"],
             nxt["lapses"], nxt["dueAt"], nxt["lastReviewedAt"]],
        )


def find_cache_cards(cache_id):
    return query_one("SELECT count(*) AS count FROM flashcards WHERE generation_cache_id = $1", [cache_id])

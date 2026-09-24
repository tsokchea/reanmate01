"""SQL for ``ai_generations`` — the per-call cost ledger.

One row per logical generation. Written for cost analysis, never read on a
user's critical path.
"""

from ..extensions import query
from ..utils.serialization import dumps


def insert(*, user_id=None, study_kit_id=None, source_id=None, kind, provider, model=None, request=None,
           response=None, status="ok", error_message=None, latency_ms=None, usage=None, language=None,
           source_chars=None):
    usage = usage or {}
    return query(
        """INSERT INTO ai_generations (
             user_id, study_kit_id, source_id, kind, provider, model,
             request, response, status, error_message, latency_ms,
             prompt_tokens, completion_tokens, reasoning_tokens,
             cached_prompt_tokens, total_tokens, language, source_chars, api_calls
           )
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
                   $12, $13, $14, $15, $16, $17, $18, $19)
           RETURNING id, created_at""",
        [
            user_id, study_kit_id, source_id, kind, provider, model,
            dumps(request or {}), dumps(response or {}), status, error_message, latency_ms,
            usage.get("promptTokens"), usage.get("completionTokens"), usage.get("reasoningTokens"),
            usage.get("cachedPromptTokens"), usage.get("totalTokens"), language, source_chars,
            # The column is NOT NULL: a generation that reported no usage still
            # made at least one request, so floor at 1 rather than writing 0.
            max(1, usage.get("apiCalls") or 1),
        ],
    ).rows[0]


def token_ratios(since_days=7):
    """The Khmer-versus-English comparison over a window."""
    return query(
        """SELECT language, kind, model,
                  count(*)                                AS generations,
                  sum(api_calls)                          AS api_calls,
                  sum(prompt_tokens)                      AS prompt_tokens,
                  sum(completion_tokens)                  AS completion_tokens,
                  sum(source_chars)                       AS source_chars,
                  round(avg(prompt_tokens)::numeric, 1)   AS avg_prompt_tokens,
                  round(sum(prompt_tokens)::numeric
                        / NULLIF(sum(source_chars), 0), 4) AS prompt_tokens_per_char
             FROM ai_generations
            WHERE status = 'ok'
              AND provider <> 'mock'
              AND language IS NOT NULL
              AND created_at >= now() - make_interval(days => $1)
            GROUP BY language, kind, model
            ORDER BY kind, language""",
        [since_days],
    ).rows

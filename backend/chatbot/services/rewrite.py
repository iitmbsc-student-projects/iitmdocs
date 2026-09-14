"""Query rewrite — port of worker.js rewriteQueryWithSource.

Sanitize -> reject if injection emptied it -> synonym fast-path -> LLM rewrite
(gpt-4o-mini). Returns {"query": str|None, "source": "rejected"|"original"|"synonym"|"llm"}.

Both the synonym list and the knowledge-base summary in the LLM prompt belong to the
programme being asked about, so `program_id` is threaded through from the pipeline.
"""
from __future__ import annotations

import re
import time

from programs import DEFAULT_PROGRAM_ID

from ..business import find_synonym_match, remove_stop_words, sanitize_query
from ..prompts import build_rewrite_system_prompt
from .llm import chat_completion_async, token_usage
from .logs import log_duration

_LANG_TAG_RE = re.compile(r"\[LANG:\w+\]", re.IGNORECASE)


async def rewrite_query_with_source_async(client, query, program_id=DEFAULT_PROGRAM_ID):
    """Rewrite one query for one programme without blocking the ASGI event loop.

    Example: a configured ES synonym for ``"qualifier fee"`` returns the original
    query plus that expansion with ``source="synonym"`` when program_id is "es".
    """
    original_query = query
    query = sanitize_query(query)
    if not query and original_query and str(original_query).strip():
        return {"query": None, "source": "rejected", "tokens": None}
    if not query:
        return {"query": "", "source": "original", "tokens": None}
    synonym_start_time = time.monotonic()
    synonym_match = find_synonym_match(query, program_id)
    if synonym_match:
        log_duration(
            "query_rewrite_synonym",
            int((time.monotonic() - synonym_start_time) * 1000),
        )
        return {"query": f"{query} {synonym_match}", "source": "synonym", "tokens": None}
    try:
        response = await chat_completion_async(
            client,
            [
                {"role": "system", "content": build_rewrite_system_prompt(program_id)},
                {"role": "user", "content": remove_stop_words(query)},
            ],
            model="gpt-4o-mini",
            temperature=0,
            max_tokens=100,
            timeout=60,
            operation="query_rewrite_chat_api",
        )
        if not response.is_success:
            return {"query": query, "source": "original", "tokens": None}
        result = response.json()
        try:
            content = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            content = None
        rewritten = content.strip() if isinstance(content, str) and content.strip() else query
        language = _LANG_TAG_RE.search(rewritten)
        tag = language.group(0) if language else "[LANG:english]"
        return {
            "query": f"{query} {_LANG_TAG_RE.sub('', rewritten).strip()} {tag}",
            "source": "llm",
            "tokens": token_usage(result),
        }
    except Exception:
        return {"query": query, "source": "original", "tokens": None}

"""Server-Sent Events record builders — exact byte-compatible port of worker.js.

The frontend consumes an OpenAI-style `data: {json}\n\n` stream terminated by
`data: [DONE]\n\n`. Streaming is simulated: the whole answer is one content delta.
"""
from __future__ import annotations

import json
import re

DONE = "data: [DONE]\n\n"
DEFAULT_REPO_URL = "https://github.com/RishavT/iitmdocs"


def _dumps(obj) -> str:
    # Compact separators + non-ASCII kept literal, matching JS JSON.stringify output.
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def sse_document_records(documents, repo_url: str = DEFAULT_REPO_URL) -> str:
    """Concatenated `document` tool-call records, one per Weaviate hit (streamed first)."""
    parts = []
    for doc in documents:
        filename = doc["filename"]
        # Documents live in src/<program_id>/, so link with the stored path. The
        # fallback covers objects embedded before the per-programme folders existed.
        filepath = doc.get("filepath") or f"src/{filename}"
        arguments = _dumps(
            {
                "relevance": doc.get("relevance"),
                "name": re.sub(r"\.md$", "", filename),
                "link": f"{repo_url}/blob/main/{filepath}",
            }
        )
        record = {
            "role": "assistant",
            "choices": [
                {"delta": {"tool_calls": [{"function": {"name": "document", "arguments": arguments}}]}}
            ],
        }
        parts.append(f"data: {_dumps(record)}\n\n")
    return "".join(parts)


def sse_content(text: str, rejected: bool = False) -> str:
    """A single content delta + [DONE]. `rejected` marks non-answers (skip history)."""
    data = {"choices": [{"delta": {"content": text}}]}
    if rejected:
        data["rejected"] = True
    return f"data: {_dumps(data)}\n\n" + DONE


def sse_error(message: str) -> str:
    """Error record — emitted WITHOUT a trailing [DONE], exactly like the Worker."""
    data = {"error": {"message": message, "type": "server_error"}}
    return f"data: {_dumps(data)}\n\n"

"""Weaviate hybrid document search — port of worker.js searchWeaviate.

Supports both DEPLOYMENT_MODE=local (Weaviate does text2vec-ollama vectorization,
query text passed to hybrid) and =gce (compute an Ollama embedding first, pass the
vector to hybrid). GraphQL string built identically to the Worker (same escaping).

Results are restricted to one programme's documents. Unlike FAQs there is no shared
"common" pool here - src/ has a folder per programme and nothing outside them.
"""
from __future__ import annotations


from .. import appconfig
from .embeddings import get_ollama_embedding_async
from .logs import measure_duration


def _sanitize_graphql(query: str) -> str:
    return (
        query.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", " ")
        .replace("\r", " ")
        .replace("\t", " ")
    )

async def search_weaviate_async(client, query, limit, program_id):
    """Search one programme's documents in Weaviate; return ``items`` plus ``error``.

    Example: search_weaviate_async(client, "fees", 2, "es") only ever returns
    documents that were embedded from src/es/.
    """
    mode = appconfig.deployment_mode()
    if mode not in ("local", "gce"):
        return {"items": [], "error": f"weaviate_config_error:unsupported_DEPLOYMENT_MODE_{mode}"}
    url = appconfig.local_weaviate_url() if mode == "local" else appconfig.gce_weaviate_url()
    if not url:
        return {"items": [], "error": "weaviate_config_error:missing_GCE_WEAVIATE_URL"}
    sanitized_query = _sanitize_graphql(query)
    # program_id is whitelist-validated in the view, so it needs no escaping here.
    program_filter = f'where: {{path:["program_id"] operator:Equal valueText:"{program_id}"}} '
    if mode == "gce":
        ollama_url = appconfig.gce_ollama_url()
        if not ollama_url:
            return {"items": [], "error": "weaviate_config_error:missing_GCE_OLLAMA_URL"}
        try:
            values = await get_ollama_embedding_async(
                client,
                query,
                ollama_url,
                appconfig.ollama_model(),
            )
        except Exception as exc:  # noqa: BLE001
            return {"items": [], "error": f"weaviate_embedding_error:{exc}"}
        vector = "[" + ",".join(str(value) for value in values) + "]"
        graphql = (
            "{ Get { Document("
            f'hybrid: {{ query: "{sanitized_query}" vector: {vector} alpha: 0.5 }} '
            f"{program_filter}"
            f"limit: {limit}) "
            "{ program_id filename filepath content file_size _additional { score } } } }"
        )
    else:
        graphql = (
            "{ Get { Document("
            f'hybrid: {{ query: "{sanitized_query}" alpha: 0.5 }} '
            f"{program_filter}"
            f"limit: {limit}) "
            "{ program_id filename filepath content file_size _additional { score } } } }"
        )
    try:
        with measure_duration("weaviate_graphql_search"):
            response = await client.post(
                f"{url}/v1/graphql",
                json={"query": graphql},
                headers={"Content-Type": "application/json"},
                timeout=60,
            )
        if not response.is_success:
            return {"items": [], "error": f"weaviate_api_error:{response.status_code}"}
        try:
            data = response.json()
        except Exception as exc:  # noqa: BLE001
            return {"items": [], "error": f"weaviate_response_malformed:{exc}"}
        if not isinstance(data, dict):
            return {"items": [], "error": "weaviate_response_malformed:not_an_object"}
        documents = (((data.get("data") or {}).get("Get") or {}).get("Document")) or []
        graphql_error = None
        if "errors" in data:
            errors = data["errors"]
            if not isinstance(errors, list):
                graphql_error = "weaviate_response_malformed:errors_not_array"
            elif errors:
                messages = []
                for error in errors:
                    if isinstance(error, dict):
                        messages.append(error.get("message") or str(error))
                    else:
                        messages.append(str(error))
                graphql_error = "weaviate_graphql_error:" + ", ".join(messages)

        items = [
            {**doc, "relevance": (doc.get("_additional") or {}).get("score") or 0}
            for doc in documents
        ]
        return {"items": items, "error": graphql_error}
    except Exception as exc:  # noqa: BLE001
        return {"items": [], "error": f"weaviate_fetch_error:{exc}"}

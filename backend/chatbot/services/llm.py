"""Chat-completions primitive (OpenAI-compatible) shared by rewrite/answer/fact-check."""
from __future__ import annotations

import httpx

from .. import appconfig
from .logs import measure_duration


RESPONSE_HEADERS = (
    "x-request-id", "openai-processing-ms",
    "x-ratelimit-limit-requests", "x-ratelimit-limit-tokens",
    "x-ratelimit-remaining-requests", "x-ratelimit-remaining-tokens",
    "x-ratelimit-reset-requests", "x-ratelimit-reset-tokens",
)


def token_usage(payload):
    """Return normalized input/output counts from one chat response.

    Called after rewrite, answer, and fact-check responses are decoded. Providers
    that omit ``usage`` return ``None`` so callers can distinguish unavailable
    accounting from a reported zero-token value.

    Example: ``{"usage": {"prompt_tokens": 4}}`` returns
    ``{"input": 4, "output": 0}``.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("usage"), dict):
        return None
    usage = payload["usage"]
    return {
        "input": usage.get("prompt_tokens") or 0,
        "output": usage.get("completion_tokens") or 0,
    }


async def chat_completion_async(client, messages, *, model, temperature, max_tokens=None, response_format=None, reasoning_effort=None, timeout=60, operation="chat_api"):
    """Send one non-streaming chat request without blocking the event loop.

    The caller owns the long-lived ``httpx.AsyncClient``. This helper keeps the
    payload identical to ``chat_completion`` while allowing an ASGI request to
    serve other users during the network wait.
    """
    endpoint = appconfig.chat_endpoint()
    api_key = appconfig.chat_api_key()
    body = {"model": model, "messages": messages, "temperature": temperature, "stream": False}
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    if response_format is not None:
        body["response_format"] = response_format
    if reasoning_effort is not None:
        body["reasoning_effort"] = reasoning_effort
    request_timeout = httpx.Timeout(
        connect=timeout, pool=timeout, write=timeout, read=timeout,
    )
    with measure_duration(operation) as diagnostic:
        try:
            response = await client.post(
                endpoint,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                json=body,
                timeout=request_timeout,
            )
        except Exception as error:
            categories = {
                httpx.ConnectTimeout: "connect_timeout",
                httpx.PoolTimeout: "pool_timeout",
                httpx.WriteTimeout: "write_timeout",
                httpx.ReadTimeout: "read_timeout",
            }
            diagnostic["exception_category"] = categories.get(type(error), "other")
            raise
        # A strict allowlist avoids capturing credentials or response bodies.
        if isinstance(response, httpx.Response):
            diagnostic["outcome"] = "success" if response.is_success else "http_error"
            diagnostic["http_status"] = response.status_code
            diagnostic["response_headers"] = {
                name: response.headers[name][:256]
                for name in RESPONSE_HEADERS if name in response.headers
            }
        return response

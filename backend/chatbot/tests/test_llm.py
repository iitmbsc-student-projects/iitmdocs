"""Transport diagnostics use synthetic HTTPX responses; no external requests."""
import asyncio
from unittest import mock

import httpx
from django.test import SimpleTestCase

from chatbot.services import llm, logs


class TransportDiagnosticsTests(SimpleTestCase):
    async def test_reasoning_effort_is_sent_only_when_requested(self):
        """FAQ review can request Luna's medium reasoning without changing chat calls."""
        client = mock.AsyncMock()

        await llm.chat_completion_async(
            client,
            [],
            model="gpt-5.6-luna",
            temperature=0,
            reasoning_effort="medium",
        )

        self.assertEqual(client.post.call_args.kwargs["json"]["reasoning_effort"], "medium")

    async def test_explicit_timeouts_preserve_normal_and_answer_limits(self):
        for seconds in (60, 120):
            client = mock.AsyncMock()
            await llm.chat_completion_async(client, [], model="test", temperature=0, timeout=seconds)
            timeout = client.post.call_args.kwargs["timeout"]
            self.assertIsInstance(timeout, httpx.Timeout)
            self.assertEqual(timeout.as_dict(), dict(connect=seconds, pool=seconds, write=seconds, read=seconds))

    @mock.patch.dict("os.environ", {"ENABLE_DURATION_LOGS": "true"})
    @mock.patch("chatbot.services.logs.structured_log")
    async def test_real_local_http_response_metadata(self, emit):
        """Exercise real HTTPX parsing against a loopback-only fake provider."""
        async def respond(reader, writer):
            await reader.readuntil(b"\r\n\r\n")
            writer.write(
                b"HTTP/1.1 429 Too Many Requests\r\nContent-Length: 2\r\n"
                b"x-request-id: local-test\r\nopenai-processing-ms: 4\r\n"
                b"Connection: close\r\n\r\n{}"
            )
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(respond, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        async with server, httpx.AsyncClient(trust_env=False) as client:
            with mock.patch("chatbot.services.llm.appconfig.chat_endpoint", return_value=f"http://127.0.0.1:{port}"):
                response = await self.call_chat(client)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(emit.call_args.kwargs["outcome"], "http_error")

    async def call_chat(self, client):
        return await llm.chat_completion_async(
            client, [], model="test", temperature=0, operation="answer_chat_api"
        )

    @mock.patch.dict("os.environ", {"ENABLE_DURATION_LOGS": "true"})
    @mock.patch("chatbot.services.logs.structured_log")
    async def test_response_metadata_and_correlation(self, emit):
        response = httpx.Response(200, headers={
            "x-request-id": "synthetic-id", "openai-processing-ms": "12",
            "x-ratelimit-remaining-requests": "99", "authorization": "private",
        })
        client = mock.AsyncMock()
        client.post.return_value = response
        with logs.duration_context("conversation-test"):
            self.assertIs(await self.call_chat(client), response)
        event = emit.call_args.kwargs
        self.assertEqual(event["conversation_id"], "conversation-test")
        self.assertEqual(event["outcome"], "success")
        self.assertEqual(event["http_status"], 200)
        self.assertEqual(event["response_headers"]["x-request-id"], "synthetic-id")
        self.assertNotIn("authorization", event["response_headers"])
        self.assertEqual(emit.call_count, 1)

    @mock.patch.dict("os.environ", {"ENABLE_DURATION_LOGS": "true"})
    @mock.patch("chatbot.services.logs.structured_log")
    async def test_timeouts_preserve_exception_and_emit_once(self, emit):
        for error_class, category in (
            (httpx.ConnectTimeout, "connect_timeout"),
            (httpx.PoolTimeout, "pool_timeout"),
            (httpx.WriteTimeout, "write_timeout"),
            (httpx.ReadTimeout, "read_timeout"),
        ):
            emit.reset_mock()
            error = error_class("private error text")
            client = mock.AsyncMock()
            client.post.side_effect = error
            with self.assertRaises(error_class) as caught:
                await self.call_chat(client)
            self.assertIs(caught.exception, error)
            self.assertEqual(emit.call_count, 1)
            self.assertEqual(emit.call_args.kwargs["exception_category"], category)
            self.assertNotIn("response_headers", emit.call_args.kwargs)
            self.assertNotIn("private error text", str(emit.call_args))

    @mock.patch.dict("os.environ", {"ENABLE_DURATION_LOGS": "true"})
    @mock.patch("chatbot.services.logs.structured_log")
    async def test_cancellation_is_preserved(self, emit):
        client = mock.AsyncMock()
        client.post.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.call_chat(client)
        self.assertEqual(emit.call_args.kwargs["outcome"], "cancelled")

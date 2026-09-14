"""ASGI boundary tests using only local static files and mocked cleanup."""
import json
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, mock

from asgiref.testing import ApplicationCommunicator
from asgiref.sync import iscoroutinefunction

from config.asgi import application, django_application


async def request_asgi(path, method="GET", headers=None, body=b""):
    """Return status, headers, and body from one synthetic ASGI request."""
    communicator = ApplicationCommunicator(
        application,
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": headers or [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        },
    )
    await communicator.send_input(
        {"type": "http.request", "body": body, "more_body": False}
    )
    start = await communicator.receive_output(timeout=1)
    body = b""
    while True:
        event = await communicator.receive_output(timeout=1)
        body += event.get("body", b"")
        if not event.get("more_body", False):
            break
    await communicator.wait(timeout=1)
    response_headers = {name.lower(): value for name, value in start["headers"]}
    return start["status"], response_headers, body


class AsgiBoundaryTests(IsolatedAsyncioTestCase):
    def test_django_middleware_chain_stays_async(self):
        """A sync-only middleware would adapt this chain back onto a thread."""
        self.assertTrue(iscoroutinefunction(django_application._middleware_chain))

    async def test_root_static_page_keeps_cors_and_security_headers(self):
        """Removing WhiteNoise must not turn the browser entrypoint into a 404."""
        status, headers, body = await request_asgi(
            "/",
            headers=[(b"origin", b"https://example.test")],
        )

        expected_start = Path("../static/index.html").read_bytes()[:80]
        self.assertEqual(status, 200)
        self.assertTrue(body.startswith(expected_start))
        self.assertEqual(headers[b"access-control-allow-origin"], b"*")
        self.assertEqual(headers[b"x-content-type-options"], b"nosniff")

    async def test_async_data_routes_keep_contract_through_asgi(self):
        """The real router and middleware must preserve both async API shapes."""
        async def answer_events():
            yield 'data: {"documents":[{"filename":"fees.md"}]}\n\n'
            yield 'data: {"choices":[{"delta":{"content":"answer"}}]}\n\n'

        faq_row = {
            "id": 7,
            "question": "What are the fees?",
            "answer": "Rs 32000",
            "cosine_similarity": 1.0,
        }
        with (
            mock.patch("chatbot.views.get_async_http_client", return_value=object()),
            mock.patch("chatbot.views.get_openai_http_client", return_value=mock.sentinel.openai_client, create=True),
            mock.patch(
                "chatbot.views.pipeline.answer_events_async",
                return_value=answer_events(),
            ),
            mock.patch(
                "chatbot.views.faq.get_faq_async",
                new_callable=mock.AsyncMock,
                return_value=faq_row,
            ),
        ):
            answer_status, answer_headers, answer_body = await request_asgi(
                "/answer",
                method="POST",
                headers=[(b"content-type", b"application/json")],
                body=json.dumps({"q": "fees"}).encode(),
            )
            search_status, _search_headers, _search_body = await request_asgi(
                "/search",
                method="POST",
                headers=[(b"content-type", b"application/json")],
                body=json.dumps({"q": "fees", "k": 5}).encode(),
            )
            faq_status, _faq_headers, faq_body = await request_asgi("/faq/7")

        self.assertEqual(answer_status, 200)
        self.assertEqual(answer_headers[b"content-type"], b"text/event-stream")
        self.assertEqual(
            answer_body,
            b'data: {"documents":[{"filename":"fees.md"}]}\n\n'
            b'data: {"choices":[{"delta":{"content":"answer"}}]}\n\n',
        )
        # /search was removed: the static layer now rejects it like any other POST.
        self.assertEqual(search_status, 405)
        self.assertEqual(faq_status, 200)
        self.assertEqual(json.loads(faq_body), faq_row)

    @mock.patch("config.asgi.close_async_faq_engine", new_callable=mock.AsyncMock, create=True)
    @mock.patch("config.asgi.close_async_http_client", new_callable=mock.AsyncMock, create=True)
    async def test_lifespan_shutdown_closes_shared_clients(self, close_http, close_database):
        """Process-wide connection pools must close cleanly at server shutdown."""
        communicator = ApplicationCommunicator(
            application,
            {"type": "lifespan", "asgi": {"version": "3.0"}, "state": {}},
        )
        await communicator.send_input({"type": "lifespan.startup"})
        self.assertEqual(
            await communicator.receive_output(timeout=1),
            {"type": "lifespan.startup.complete"},
        )
        await communicator.send_input({"type": "lifespan.shutdown"})
        self.assertEqual(
            await communicator.receive_output(timeout=1),
            {"type": "lifespan.shutdown.complete"},
        )
        await communicator.wait(timeout=1)
        close_http.assert_awaited_once_with()
        close_database.assert_awaited_once_with()

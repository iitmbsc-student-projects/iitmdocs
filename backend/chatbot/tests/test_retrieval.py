"""Retrieval result-envelope tests with synthetic service responses.

Flow: configure one local or GCE request, call the service helper, and assert
that usable items and concise failure causes reach the answer pipeline without
contacting real Weaviate, Ollama, or Postgres services.
"""
import asyncio
from types import SimpleNamespace
from unittest import mock

import httpx
from django.test import SimpleTestCase

from chatbot.services import embeddings, faq, pipeline, weaviate


class _Response:
    def __init__(self, *, ok=True, status=200, text="{}", payload=None):
        self.is_success = ok
        self.status_code = status
        self.text = text
        self._payload = payload or {}

    def json(self):
        return self._payload


class _AsyncClient:
    def __init__(self, response):
        self.response = response

    async def post(self, *_args, **_kwargs):
        return self.response


class _MalformedResponse(_Response):
    def json(self):
        raise ValueError("not JSON")


class SearchContextIssueTests(SimpleTestCase):
    def test_errors_take_priority_over_empty_causes(self):
        reasons = pipeline.search_context_issues(
            {"items": [], "error": "weaviate_api_error:503"},
            {"items": [], "error": None},
        )
        self.assertEqual(reasons, ["weaviate_api_error:503", "pg_faqs_empty"])

    def test_reports_both_empty_sources(self):
        reasons = pipeline.search_context_issues(
            {"items": [], "error": None},
            {"items": [], "error": None},
        )
        self.assertEqual(reasons, ["weaviate_documents_empty", "pg_faqs_empty"])

    def test_reports_only_the_empty_source_when_documents_exist(self):
        reasons = pipeline.search_context_issues(
            {"items": [{"filename": "fees.md"}], "error": None},
            {"items": [], "error": None},
        )
        self.assertEqual(reasons, ["pg_faqs_empty"])

    def test_no_issues_when_both_sources_have_context(self):
        reasons = pipeline.search_context_issues(
            {"items": [{"filename": "fees.md"}], "error": None},
            {"items": [{"id": 2}], "error": None},
        )
        self.assertEqual(reasons, [])


class FaqResultTests(SimpleTestCase):
    @mock.patch("chatbot.services.faq.search_async", new_callable=mock.AsyncMock)
    async def test_returns_successful_search_results(self, search):
        items = [{"id": 1, "question": "What are the fees?"}]
        search.return_value = items

        self.assertEqual(
            await faq.search_result_async(object(), "fees", 5, "ds"),
            {"items": items, "error": None},
        )

    @mock.patch("chatbot.services.faq.search_async", new_callable=mock.AsyncMock)
    async def test_preserves_embedding_failure(self, search):
        search.side_effect = faq.FaqEmbeddingError("failed")
        self.assertEqual(
            await faq.search_result_async(object(), "fees", 5, "ds"),
            {"items": [], "error": "pg_faq_embedding_error"},
        )

    @mock.patch("chatbot.services.faq.search_async", new_callable=mock.AsyncMock)
    async def test_preserves_database_failure(self, search):
        search.side_effect = faq.FaqDatabaseError("failed")

        self.assertEqual(
            await faq.search_result_async(object(), "fees", 5, "ds"),
            {"items": [], "error": "pg_faq_database_error"},
        )

    @mock.patch("chatbot.services.faq.search_async", new_callable=mock.AsyncMock)
    async def test_reports_unexpected_search_failure(self, search):
        search.side_effect = RuntimeError("unexpected")

        self.assertEqual(
            await faq.search_result_async(object(), "fees", 5, "ds"),
            {"items": [], "error": "pg_faq_search_error"},
        )

    async def test_async_search_returns_rows_and_closes_its_session(self):
        """A missing context-manager exit would leak one DB session per search."""
        session_closed = False

        class Result:
            def all(self):
                row = SimpleNamespace(id=7, program_id="ds", question="What are the fees?", answer="Rs 32000")
                return [(row, 0.91)]

        class Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                nonlocal session_closed
                session_closed = True

            async def execute(self, _statement):
                return Result()

        with (
            mock.patch(
                "chatbot.services.faq.request_embedding_async",
                new=mock.AsyncMock(return_value=[0.1] * 1024),
            ),
            mock.patch("chatbot.services.faq._get_async_session_factory", return_value=Session),
        ):
            results = await faq.search_async(object(), "fees", 5, "ds")

        self.assertEqual(
            results,
            [
                {
                    "id": 7,
                    "program_id": "ds",
                    "question": "What are the fees?",
                    "answer": "Rs 32000",
                    "cosine_similarity": 0.91,
                }
            ],
        )
        self.assertTrue(session_closed)

    async def test_async_search_preserves_embedding_and_database_error_categories(self):
        """The two upstream failures must keep their different HTTP mappings."""
        with mock.patch(
            "chatbot.services.faq.request_embedding_async",
            new=mock.AsyncMock(side_effect=RuntimeError("ollama unavailable")),
        ):
            with self.assertRaises(faq.FaqEmbeddingError):
                await faq.search_async(object(), "fees", 5, "ds")

        class BrokenSession:
            async def __aenter__(self):
                raise RuntimeError("postgres unavailable")

            async def __aexit__(self, *_args):
                return None

        with (
            mock.patch(
                "chatbot.services.faq.request_embedding_async",
                new=mock.AsyncMock(return_value=[0.1] * 1024),
            ),
            mock.patch("chatbot.services.faq._get_async_session_factory", return_value=BrokenSession),
        ):
            with self.assertRaises(faq.FaqDatabaseError):
                await faq.search_async(object(), "fees", 5, "ds")


class EmbeddingValidationTests(SimpleTestCase):
    async def test_async_embedding_accepts_a_real_httpx_response(self):
        """Using Requests' `.ok` attribute would fail with the real HTTPX client."""
        def respond(request):
            return httpx.Response(200, json={"embedding": [1, 2.5]}, request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            result = await embeddings.get_ollama_embedding_async(
                client,
                "fees",
                "http://ollama",
            )

        self.assertEqual(result, [1.0, 2.5])

    def test_async_embedding_returns_numeric_values(self):
        """The async endpoint must keep the same validated embedding contract."""
        class Response:
            is_success = True
            status_code = 200

            def json(self):
                return {"embedding": [1, "2.5"]}

        class Client:
            async def post(self, *args, **kwargs):
                return Response()

        result = asyncio.run(embeddings.get_ollama_embedding_async(Client(), "fees", "http://ollama"))

        self.assertEqual(result, [1.0, 2.5])

    async def test_rejects_empty_embedding(self):
        with self.assertRaisesRegex(RuntimeError, "non-empty array"):
            await embeddings.get_ollama_embedding_async(
                _AsyncClient(_Response(payload={"embedding": []})),
                "fees",
                "http://ollama",
            )

    async def test_rejects_non_array_embedding(self):
        with self.assertRaisesRegex(RuntimeError, "non-empty array"):
            await embeddings.get_ollama_embedding_async(
                _AsyncClient(_Response(payload={"embedding": "not an array"})),
                "fees",
                "http://ollama",
            )

    async def test_rejects_non_finite_embedding(self):
        with self.assertRaisesRegex(RuntimeError, "non-finite"):
            await embeddings.get_ollama_embedding_async(
                _AsyncClient(_Response(payload={"embedding": [1, float("nan")]})),
                "fees",
                "http://ollama",
            )


class WeaviateResultTests(SimpleTestCase):
    @mock.patch("chatbot.services.weaviate.appconfig.local_weaviate_url", return_value="http://weaviate")
    @mock.patch("chatbot.services.weaviate.appconfig.deployment_mode", return_value="local")
    async def test_local_graphql_has_balanced_braces(self, _mode, _url):
        """The compact async query must remain valid GraphQL."""
        class Client:
            async def post(self, *_args, **kwargs):
                self.query = kwargs["json"]["query"]
                return _Response(payload={"data": {"Get": {"Document": []}}})

        client = Client()
        await weaviate.search_weaviate_async(client, "fees", 2, "ds")

        self.assertEqual(client.query.count("{"), client.query.count("}"))

    @mock.patch(
        "chatbot.services.weaviate.get_ollama_embedding_async",
        new_callable=mock.AsyncMock,
        return_value=[0.1, 0.2],
    )
    @mock.patch("chatbot.services.weaviate.appconfig.gce_ollama_url", return_value="http://ollama")
    @mock.patch("chatbot.services.weaviate.appconfig.gce_weaviate_url", return_value="http://weaviate")
    @mock.patch("chatbot.services.weaviate.appconfig.deployment_mode", return_value="gce")
    async def test_gce_graphql_has_balanced_braces(
        self,
        _mode,
        _weaviate_url,
        _ollama_url,
        _embedding,
    ):
        """Adding a supplied vector must not unbalance the GraphQL query."""
        class Client:
            async def post(self, *_args, **kwargs):
                self.query = kwargs["json"]["query"]
                return _Response(payload={"data": {"Get": {"Document": []}}})

        client = Client()
        await weaviate.search_weaviate_async(client, "fees", 2, "ds")

        self.assertEqual(client.query.count("{"), client.query.count("}"))

    @mock.patch("chatbot.services.weaviate.appconfig.local_weaviate_url", return_value="http://weaviate")
    @mock.patch("chatbot.services.weaviate.appconfig.deployment_mode", return_value="local")
    async def test_async_search_preserves_documents_and_graphql_error(self, _mode, _url):
        """Partial GraphQL data must remain usable while its failure is logged."""
        class Client:
            async def post(self, *_args, **_kwargs):
                return _Response(
                    payload={
                        "data": {
                            "Get": {
                                "Document": [
                                    {"filename": "fees.md", "_additional": {"score": "0.8"}}
                                ]
                            }
                        },
                        "errors": [{"message": "optional field failed"}],
                    }
                )

        result = await weaviate.search_weaviate_async(Client(), "fees", 2, "ds")

        self.assertEqual(result["items"][0]["filename"], "fees.md")
        self.assertEqual(result["error"], "weaviate_graphql_error:optional field failed")

    @mock.patch("chatbot.services.weaviate.appconfig.local_weaviate_url", return_value="http://weaviate")
    @mock.patch("chatbot.services.weaviate.appconfig.deployment_mode", return_value="local")
    async def test_reports_malformed_graphql_errors_field(self, _mode, _url):
        self.assertEqual(
            await weaviate.search_weaviate_async(
                _AsyncClient(_Response(payload={"errors": "upstream unavailable"})),
                "fees",
                2,
                "ds",
            ),
            {"items": [], "error": "weaviate_response_malformed:errors_not_array"},
        )

    @mock.patch("chatbot.services.weaviate.appconfig.local_weaviate_url", return_value="http://weaviate")
    @mock.patch("chatbot.services.weaviate.appconfig.deployment_mode", return_value="local")
    async def test_reports_http_and_malformed_responses(self, _mode, _url):
        self.assertEqual(
            await weaviate.search_weaviate_async(
                _AsyncClient(_Response(ok=False, status=503)),
                "fees",
                2,
                "ds",
            ),
            {"items": [], "error": "weaviate_api_error:503"},
        )

        result = await weaviate.search_weaviate_async(
            _AsyncClient(_MalformedResponse()),
            "fees",
            2,
            "ds",
        )
        self.assertEqual(result["items"], [])
        self.assertTrue(result["error"].startswith("weaviate_response_malformed:"))

    @mock.patch("chatbot.services.weaviate.appconfig.deployment_mode", return_value="invalid")
    async def test_reports_unsupported_mode_without_fetching(self, _mode):
        result = await weaviate.search_weaviate_async(object(), "fees", 2, "ds")
        self.assertEqual(result["items"], [])
        self.assertEqual(result["error"], "weaviate_config_error:unsupported_DEPLOYMENT_MODE_invalid")

    @mock.patch("chatbot.services.weaviate.appconfig.gce_weaviate_url", return_value=None)
    @mock.patch("chatbot.services.weaviate.appconfig.deployment_mode", return_value="gce")
    async def test_reports_missing_gce_weaviate_url(self, _mode, _url):
        self.assertEqual(
            await weaviate.search_weaviate_async(object(), "fees", 2, "ds"),
            {"items": [], "error": "weaviate_config_error:missing_GCE_WEAVIATE_URL"},
        )

    @mock.patch("chatbot.services.weaviate.appconfig.gce_ollama_url", return_value=None)
    @mock.patch("chatbot.services.weaviate.appconfig.gce_weaviate_url", return_value="http://weaviate")
    @mock.patch("chatbot.services.weaviate.appconfig.deployment_mode", return_value="gce")
    async def test_reports_missing_gce_ollama_url(self, _mode, _weaviate_url, _ollama_url):
        self.assertEqual(
            await weaviate.search_weaviate_async(object(), "fees", 2, "ds"),
            {"items": [], "error": "weaviate_config_error:missing_GCE_OLLAMA_URL"},
        )

    @mock.patch("chatbot.services.weaviate.get_ollama_embedding_async", new_callable=mock.AsyncMock)
    @mock.patch("chatbot.services.weaviate.appconfig.gce_ollama_url", return_value="http://ollama")
    @mock.patch("chatbot.services.weaviate.appconfig.gce_weaviate_url", return_value="http://weaviate")
    @mock.patch("chatbot.services.weaviate.appconfig.deployment_mode", return_value="gce")
    async def test_reports_gce_embedding_failure(
        self,
        _mode,
        _weaviate_url,
        _ollama_url,
        get_embedding,
    ):
        get_embedding.side_effect = RuntimeError("Ollama unavailable")

        self.assertEqual(
            await weaviate.search_weaviate_async(object(), "fees", 2, "ds"),
            {"items": [], "error": "weaviate_embedding_error:Ollama unavailable"},
        )


class _CapturingClient:
    """Records the GraphQL query a search sends, and returns an empty result."""

    graphql = ""

    async def post(self, *_args, **kwargs):
        self.graphql = kwargs["json"]["query"]
        return _Response(payload={"data": {"Get": {"Document": []}}})


class ProgramScopingTests(SimpleTestCase):
    """Prove one programme cannot see another programme's FAQs or documents."""

    def test_faq_search_sql_covers_only_the_program_and_common(self):
        from sqlalchemy import select

        from programs import faq_program_scope
        from pg.faq_api.orm import Faq

        statement = select(Faq).where(Faq.program_id.in_(faq_program_scope("es")))
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        self.assertIn("'es'", sql)
        self.assertIn("'common'", sql)
        self.assertNotIn("'ds'", sql)

    async def test_faq_lookup_returns_none_for_another_programs_row(self):
        """An id belonging to `ds` must read as missing when asked for as `es`."""

        class Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def execute(self, _statement):
                return SimpleNamespace(scalar_one_or_none=lambda: None)

        with mock.patch("chatbot.services.faq._get_async_session_factory", return_value=Session):
            self.assertIsNone(await faq.get_faq_async(7, "es"))

    @mock.patch("chatbot.services.weaviate.appconfig.local_weaviate_url", return_value="http://weaviate")
    @mock.patch("chatbot.services.weaviate.appconfig.deployment_mode", return_value="local")
    async def test_local_graphql_filters_on_program_id(self, _mode, _url):
        client = _CapturingClient()
        await weaviate.search_weaviate_async(client, "fees", 2, "es")
        self.assertIn('path:["program_id"]', client.graphql)
        self.assertIn('valueText:"es"', client.graphql)

    @mock.patch("chatbot.services.weaviate.appconfig.ollama_model", return_value="bge-m3")
    @mock.patch("chatbot.services.weaviate.appconfig.gce_ollama_url", return_value="http://ollama")
    @mock.patch("chatbot.services.weaviate.appconfig.gce_weaviate_url", return_value="http://weaviate")
    @mock.patch("chatbot.services.weaviate.appconfig.deployment_mode", return_value="gce")
    async def test_gce_graphql_filters_on_program_id(self, _mode, _url, _ollama, _model):
        client = _CapturingClient()
        with mock.patch(
            "chatbot.services.weaviate.get_ollama_embedding_async",
            new=mock.AsyncMock(return_value=[0.1, 0.2]),
        ):
            await weaviate.search_weaviate_async(client, "fees", 2, "mg")
        self.assertIn('path:["program_id"]', client.graphql)
        self.assertIn('valueText:"mg"', client.graphql)

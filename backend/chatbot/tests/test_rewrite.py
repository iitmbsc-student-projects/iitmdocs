"""Query-rewrite metadata tests with a synthetic chat response.

Flow: submit a query, mock the OpenAI-compatible response, and verify that the
rewritten query and provider token usage are returned to the request pipeline.
"""
from unittest import mock
import asyncio

from django.test import SimpleTestCase

from chatbot.services import rewrite
from chatbot.services import llm


class _Response:
    is_success = True

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class RewriteMetadataTests(SimpleTestCase):
    @mock.patch("chatbot.services.rewrite.chat_completion_async")
    async def test_llm_rewrite_returns_usage(self, completion):
        completion.return_value = _Response(
            {
                "choices": [{"message": {"content": "fees payment [LANG:english]"}}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 2},
            }
        )

        result = await rewrite.rewrite_query_with_source_async(
            object(), "Could tuition be explained", "ds"
        )

        self.assertEqual(result["source"], "llm")
        self.assertEqual(result["tokens"], {"input": 7, "output": 2})

    @mock.patch("chatbot.services.rewrite.chat_completion_async")
    async def test_synonym_rewrite_has_no_provider_usage(self, completion):
        result = await rewrite.rewrite_query_with_source_async(
            object(), "What is the grading policy?", "ds"
        )

        self.assertEqual(result["source"], "synonym")
        self.assertIsNone(result["tokens"])
        completion.assert_not_called()

    @mock.patch("chatbot.services.rewrite.chat_completion_async")
    async def test_ds_synonym_is_a_miss_for_es_and_uses_es_prompt(self, completion):
        """The same question takes the LLM path for ES, with the ES topic list."""
        completion.return_value = _Response(
            {
                "choices": [{"message": {"content": "grading [LANG:english]"}}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 2},
            }
        )

        result = await rewrite.rewrite_query_with_source_async(
            object(), "What is the grading policy?", "es"
        )

        self.assertEqual(result["source"], "llm")
        system_prompt = completion.call_args.args[1][0]["content"]
        self.assertIn("Electronic Systems", system_prompt)
        self.assertNotIn("International Students Information", system_prompt)

    @mock.patch("chatbot.services.rewrite.chat_completion_async")
    async def test_malformed_success_keeps_llm_source_and_usage(self, completion):
        """A 200 reply without choices still represents a completed LLM rewrite."""
        completion.return_value = _Response(
            {
                "choices": [],
                "usage": {"prompt_tokens": 7, "completion_tokens": 0},
            }
        )

        result = await rewrite.rewrite_query_with_source_async(
            object(),
            "Could tuition be explained",
            "ds",
        )

        self.assertEqual(result["source"], "llm")
        self.assertEqual(result["tokens"], {"input": 7, "output": 0})
        self.assertTrue(result["query"].endswith("[LANG:english]"))


class AsyncChatCompletionTests(SimpleTestCase):
    def test_async_chat_completion_sends_the_current_openai_payload(self):
        """A wrong async payload would break every chat call after the migration."""
        response = object()

        class Client:
            async def post(self, endpoint, **kwargs):
                self.endpoint = endpoint
                self.kwargs = kwargs
                return response

        client = Client()
        result = asyncio.run(
            llm.chat_completion_async(
                client,
                [{"role": "user", "content": "fees"}],
                model="gpt-4o-mini",
                temperature=0,
                max_tokens=100,
                timeout=60,
            )
        )

        self.assertIs(result, response)
        self.assertEqual(client.kwargs["json"]["stream"], False)
        self.assertEqual(client.kwargs["json"]["max_tokens"], 100)
        self.assertEqual(client.kwargs["timeout"].as_dict(), dict(connect=60, pool=60, write=60, read=60))

    def test_async_rewrite_returns_llm_query_and_usage(self):
        """The async path must preserve the query format consumed by retrieval."""
        class Response:
            is_success = True

            def json(self):
                return {
                    "choices": [{"message": {"content": "fees payment [LANG:english]"}}],
                    "usage": {"prompt_tokens": 7, "completion_tokens": 2},
                }

        class Client:
            async def post(self, *args, **kwargs):
                return Response()

        result = asyncio.run(rewrite.rewrite_query_with_source_async(Client(), "Could tuition be explained"))

        self.assertEqual(result["source"], "llm")
        self.assertEqual(result["tokens"], {"input": 7, "output": 2})
        self.assertTrue(result["query"].endswith("[LANG:english]"))

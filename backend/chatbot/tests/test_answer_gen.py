"""generate_answer / check_response tests (chat_completion mocked)."""
import json
from unittest import mock

from django.test import SimpleTestCase

from chatbot.services import answer as answer_mod


class _FakeResp:
    def __init__(self, ok=True, payload=None, status=200):
        self.is_success = ok
        self._payload = payload or {}
        self.status_code = status
        self.reason = "OK"

    def json(self):
        return self._payload


def _chat(content):
    return {"choices": [{"message": {"content": content}}]}


def _chat_with_usage(content, input_tokens, output_tokens):
    return {
        **_chat(content),
        "usage": {"prompt_tokens": input_tokens, "completion_tokens": output_tokens},
    }


class GenerateAnswerTests(SimpleTestCase):
    @mock.patch("chatbot.services.answer.chat_completion_async", create=True)
    async def test_async_valid_answer_preserves_answer_and_fact_check_contract(self, completion):
        """Using the sync chat primitive here would block the ASGI request path."""
        completion.side_effect = [
            _FakeResp(payload=_chat_with_usage("The fee is 32000", 10, 3)),
            _FakeResp(payload=_chat_with_usage('{"approved":"YES","incorrect":[]}', 8, 2)),
        ]

        result = await answer_mod.generate_answer_async(
            object(),
            "q",
            [{"filename": "f.md", "content": "c", "relevance": 0.9}],
            [],
            [],
            "english",
        )

        self.assertEqual(result["final_answer"], "The fee is 32000")
        self.assertTrue(result["fact_check_passed"])
        self.assertEqual(result["tokens"]["answer_generation_input"], 10)
        self.assertEqual(result["tokens"]["fact_check_input"], 8)

    @mock.patch("chatbot.services.answer.chat_completion_async")
    async def test_valid_answer_passes(self, m_chat):
        m_chat.side_effect = [
            _FakeResp(payload=_chat_with_usage("The fee is 32000", 10, 3)),
            _FakeResp(payload=_chat_with_usage('{"approved":"YES","incorrect":[]}', 8, 2)),
        ]
        result = await answer_mod.generate_answer_async(
            object(),
            "q", [{"filename": "f.md", "content": "c", "relevance": 0.9}], [], [], "english"
        )
        self.assertEqual(result["final_answer"], "The fee is 32000")
        self.assertFalse(result["rejected"])
        self.assertTrue(result["fact_check_passed"])
        self.assertIsNone(result["rejection_reason"])
        self.assertEqual(result["original_answer"], "The fee is 32000")
        self.assertEqual(
            result["tokens"],
            {
                "answer_generation_input": 10,
                "answer_generation_output": 3,
                "fact_check_input": 8,
                "fact_check_output": 2,
            },
        )
        self.assertEqual(
            result["fact_checks"],
            [
                {
                    "scope": "answer",
                    "history_used": False,
                    "approved": True,
                    "incorrect": [],
                    "outcome": "json",
                }
            ],
        )

    @mock.patch("chatbot.services.answer.chat_completion_async")
    async def test_failed_factcheck_falls_back_with_suggestions(self, m_chat):
        m_chat.side_effect = [
            _FakeResp(payload=_chat("A hallucinated answer")),
            _FakeResp(payload=_chat('{"approved":"NO","incorrect":["made up"]}')),
        ]
        result = await answer_mod.generate_answer_async(
            object(),
            "q", [], [{"id": 1, "question": "Q1", "answer": "A1", "cosine_similarity": 0.5}], [], "english"
        )
        self.assertIn("don't have the information", result["final_answer"])
        self.assertIn("[FAQID:1]", result["final_answer"])
        self.assertTrue(result["rejected"])
        self.assertFalse(result["fact_check_passed"])
        self.assertEqual(result["rejection_reason"], "fact_check_failed")
        self.assertEqual(result["fact_checks"][0]["incorrect"], ["made up"])

    @mock.patch("chatbot.services.answer.chat_completion_async")
    async def test_chat_api_error_raises(self, m_chat):
        m_chat.return_value = _FakeResp(ok=False, status=500)
        with self.assertRaises(RuntimeError):
            await answer_mod.generate_answer_async(object(), "q", [], [], [], "english")

    @mock.patch("chatbot.services.answer.chat_completion_async")
    async def test_factcheck_retry_tokens_are_added(self, m_chat):
        m_chat.side_effect = [
            _FakeResp(payload=_chat_with_usage("Answer", 10, 2)),
            _FakeResp(payload=_chat_with_usage('{"approved":"NO","incorrect":["x"]}', 4, 1)),
            _FakeResp(payload=_chat_with_usage('{"approved":"YES","incorrect":[]}', 3, 1)),
        ]

        result = await answer_mod.generate_answer_async(
            object(),
            "q",
            [{"filename": "f.md", "content": "c", "relevance": 0.9}],
            [],
            [{"role": "user", "content": "Earlier question"}],
            "english",
        )

        self.assertEqual(result["tokens"]["fact_check_input"], 7)
        self.assertEqual(result["tokens"]["fact_check_output"], 2)
        self.assertEqual(
            [(item["history_used"], item["approved"]) for item in result["fact_checks"]],
            [(True, False), (False, True)],
        )


class RelevanceCoercionTests(SimpleTestCase):
    """Regression: Weaviate returns _additional.score as a STRING; the relevance
    filter must coerce it (worker.js relied on JS string->number coercion)."""

    def test_relevance_helper(self):
        self.assertEqual(answer_mod._relevance({"relevance": "0.64"}), 0.64)
        self.assertEqual(answer_mod._relevance({"relevance": "1"}), 1.0)
        self.assertEqual(answer_mod._relevance({"relevance": 0}), 0.0)
        self.assertEqual(answer_mod._relevance({"relevance": None}), 0.0)
        self.assertEqual(answer_mod._relevance({}), 0.0)

    @mock.patch("chatbot.services.answer.chat_completion_async")
    async def test_string_relevance_filters_without_error(self, m_chat):
        m_chat.side_effect = [
            _FakeResp(payload=_chat("answer")),
            _FakeResp(payload=_chat('{"approved":"YES","incorrect":[]}')),
        ]
        docs = [
            {"filename": "high.md", "content": "HIGHDOC", "relevance": "1"},
            {"filename": "low.md", "content": "LOWDOC", "relevance": "0.01"},
        ]
        result = await answer_mod.generate_answer_async(
            object(), "q", docs, [], [], "english"
        )  # must not raise TypeError
        self.assertEqual(result["final_answer"], "answer")
        context_msg = m_chat.call_args_list[0].args[1][1]["content"]
        self.assertIn("HIGHDOC", context_msg)  # "1" > 0.05 -> kept
        self.assertNotIn("LOWDOC", context_msg)  # "0.01" < 0.05 -> dropped


class CheckResponseTests(SimpleTestCase):
    @mock.patch("chatbot.services.answer.chat_completion_async")
    async def test_approved_yes(self, m_chat):
        m_chat.return_value = _FakeResp(payload=_chat('{"approved":"YES","incorrect":[]}'))
        result = await answer_mod.check_response_async(object(), "resp", "ctx", [])
        self.assertTrue(result["approved"])

    @mock.patch("chatbot.services.answer.chat_completion_async")
    async def test_rejected_no(self, m_chat):
        m_chat.return_value = _FakeResp(payload=_chat('{"approved":"NO","incorrect":["x"]}'))
        result = await answer_mod.check_response_async(object(), "resp", "ctx", [])
        self.assertFalse(result["approved"])
        self.assertEqual(result["incorrect"], ["x"])
        self.assertEqual(result["outcome"], "json")

    @mock.patch("chatbot.services.answer.chat_completion_async")
    async def test_incorrect_reasons_are_bounded_for_logs(self, m_chat):
        reasons = ["  " + (str(index) * 600) for index in range(1, 8)]
        m_chat.return_value = _FakeResp(
            payload=_chat('{"approved":"NO","incorrect":' + json.dumps(reasons) + "}")
        )

        result = await answer_mod.check_response_async(object(), "resp", "ctx", [])

        self.assertEqual(len(result["incorrect"]), 5)
        self.assertTrue(all(len(reason) == 500 for reason in result["incorrect"]))

    @mock.patch("chatbot.services.answer.chat_completion_async")
    async def test_fails_open_on_api_error(self, m_chat):
        m_chat.return_value = _FakeResp(ok=False, status=500)
        result = await answer_mod.check_response_async(object(), "resp", "ctx", [])
        self.assertTrue(result["approved"])
        self.assertEqual(result["outcome"], "http_fail_open")

    @mock.patch("chatbot.services.answer.chat_completion_async")
    async def test_fails_open_on_exception(self, m_chat):
        m_chat.side_effect = RuntimeError("network")
        result = await answer_mod.check_response_async(object(), "resp", "ctx", [])
        self.assertTrue(result["approved"])
        self.assertEqual(result["outcome"], "exception_fail_open")

    @mock.patch("chatbot.services.answer.chat_completion_async")
    async def test_malformed_json_strict_yes_fallback(self, m_chat):
        m_chat.return_value = _FakeResp(payload=_chat("YES"))
        result = await answer_mod.check_response_async(object(), "resp", "ctx", [])
        self.assertTrue(result["approved"])
        self.assertEqual(result["outcome"], "strict_text")

    @mock.patch("chatbot.services.answer.chat_completion_async")
    async def test_returns_factcheck_tokens(self, m_chat):
        m_chat.return_value = _FakeResp(
            payload=_chat_with_usage('{"approved":"YES","incorrect":[]}', 6, 1)
        )
        result = await answer_mod.check_response_async(object(), "resp", "ctx", [])
        self.assertEqual(result["tokens"], {"input": 6, "output": 1})


class ProgramContactsTests(SimpleTestCase):
    """A rejected answer must name the asking programme's support contacts."""

    @mock.patch("chatbot.services.answer.chat_completion_async")
    async def test_fact_check_failure_uses_the_programs_contacts(self, m_chat):
        m_chat.side_effect = [
            _FakeResp(payload=_chat("A hallucinated answer")),
            _FakeResp(payload=_chat('{"approved":"NO","incorrect":["made up"]}')),
            _FakeResp(payload=_chat('{"approved":"NO","incorrect":["made up"]}')),
        ]
        result = await answer_mod.generate_answer_async(
            object(),
            "q",
            [{"filename": "f.md", "content": "c", "relevance": 0.9}],
            [],
            [],
            "english",
            "es",
        )

        self.assertFalse(result["fact_check_passed"])
        self.assertIn("support-es@study.iitm.ac.in", result["final_answer"])
        self.assertNotIn("us at support@study.iitm.ac.in", result["final_answer"])

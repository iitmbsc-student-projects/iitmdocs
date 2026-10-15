"""Tests for the answer-only pre-save fact-checker risk review."""
import json
from unittest import mock

from django.test import SimpleTestCase

from faq_admin import safety


class _FakeResponse:
    """Small OpenAI-compatible response used without a network request."""

    def __init__(self, payload, ok=True):
        self.is_success = ok
        self._payload = payload

    def json(self):
        return self._payload


def _completion(content):
    return {"choices": [{"message": {"content": content}}]}


class AnswerSafetyReviewTests(SimpleTestCase):
    @mock.patch("faq_admin.safety.get_openai_http_client")
    @mock.patch("faq_admin.safety.chat_completion_async")
    async def test_safe_answer_returns_no_without_a_suggestion(self, completion, get_client):
        completion.return_value = _FakeResponse(_completion(json.dumps({
            "likely_to_be_rejected_by_fact_checker": "no",
            "exact_line_from_fact_checker_prompt_because_of_which_rejection_is_possible": "NA",
            "suggested_answer_likely_to_pass_fact_checker": "NA",
        })))

        result = await safety.check_answer_safety("The fee details are available on the programme website.")

        self.assertEqual(result["likely_to_be_rejected_by_fact_checker"], "no")
        self.assertEqual(result["suggested_answer_likely_to_pass_fact_checker"], "NA")
        sent_messages = completion.call_args.args[1]
        self.assertIn("FACT-CHECKER PROMPT START", sent_messages[0]["content"])
        self.assertNotIn("FAQ question", sent_messages[1]["content"])
        self.assertIn("The fee details", sent_messages[1]["content"])
        get_client.assert_called_once()

    @mock.patch("faq_admin.safety.get_openai_http_client")
    @mock.patch("faq_admin.safety.chat_completion_async")
    async def test_rejected_answer_returns_the_prompt_rule_and_suggestion(self, completion, get_client):
        rule = "- Any dating advice"
        completion.return_value = _FakeResponse(_completion(json.dumps({
            "likely_to_be_rejected_by_fact_checker": "yes",
            "exact_line_from_fact_checker_prompt_because_of_which_rejection_is_possible": rule,
            "suggested_answer_likely_to_pass_fact_checker": "Please contact support@study.iitm.ac.in for programme-related help.",
        })))

        result = await safety.check_answer_safety("You should date your classmate.")

        self.assertEqual(result["likely_to_be_rejected_by_fact_checker"], "yes")
        self.assertEqual(result["exact_line_from_fact_checker_prompt_because_of_which_rejection_is_possible"], rule)
        self.assertIn("support@study.iitm.ac.in", result["suggested_answer_likely_to_pass_fact_checker"])
        get_client.assert_called_once()

    @mock.patch("faq_admin.safety.get_openai_http_client")
    @mock.patch("faq_admin.safety.chat_completion_async")
    async def test_invalid_model_output_blocks_the_save_flow(self, completion, get_client):
        completion.return_value = _FakeResponse(_completion("not JSON"))

        with self.assertRaises(safety.FaqAnswerSafetyError):
            await safety.check_answer_safety("A proposed FAQ answer")

        get_client.assert_called_once()

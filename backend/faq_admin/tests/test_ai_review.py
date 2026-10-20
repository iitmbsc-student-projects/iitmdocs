import json
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from faq_admin.ai_review import FaqReviewError, _validate_review, review_unanswered_question


def _run_sync_inline(function, **_options):
    """Replace Asgiref's worker-thread bridge in this no-database unit test."""
    async def runner(*args):
        return function(*args)

    return runner


class FaqReviewValidationTests(SimpleTestCase):
    def test_should_be_added_requires_a_clean_question_that_preserves_the_problem(self):
        """A valid add recommendation returns all evidence needed by the admin."""
        result = _validate_review(
            {
                "ai_suggestion": "should_be_added",
                "reason": "The supplied FAQs do not cover exam-city changes.",
                "matching_faq_ids": [],
                "suggested_clean_question": "Can I change my selected exam city?",
            },
            available_faq_ids={41, 87},
        )

        self.assertEqual(result["suggested_clean_question"], "Can I change my selected exam city?")
        self.assertEqual(result["matching_faq_ids"], [])

    def test_existing_answer_rejects_an_id_outside_the_programme_scope(self):
        """The model cannot cite an FAQ it was not allowed to inspect."""
        with self.assertRaisesRegex(FaqReviewError, "invalid data"):
            _validate_review(
                {
                    "ai_suggestion": "answer_already_present",
                    "reason": "FAQ 99 answers it.",
                    "matching_faq_ids": [99],
                    "suggested_clean_question": "NA",
                },
                available_faq_ids={41, 87},
            )

    def test_rejects_extra_model_fields(self):
        """The strict contract prevents unreviewed model data reaching storage."""
        with self.assertRaisesRegex(FaqReviewError, "invalid data"):
            _validate_review(
                {
                    "ai_suggestion": "should_not_be_added",
                    "reason": "This is outside the chatbot scope.",
                    "matching_faq_ids": [],
                    "suggested_clean_question": "NA",
                    "unexpected": "not allowed",
                },
                available_faq_ids=set(),
            )


class FaqReviewServiceTests(SimpleTestCase):
    @mock.patch("faq_admin.ai_review.chat_completion_async")
    @mock.patch("faq_admin.ai_review.get_openai_http_client")
    @mock.patch("faq_admin.ai_review._load_faq_rows")
    @mock.patch("faq_admin.ai_review._load_unanswered_question")
    @mock.patch("faq_admin.ai_review._save_review_result")
    @mock.patch("faq_admin.ai_review.sync_to_async", side_effect=_run_sync_inline)
    async def test_failed_model_response_does_not_save_any_result(
        self, run_sync, save_result, load_question, load_faq_rows, get_client, chat_completion
    ):
        """A provider failure leaves the review row untouched so the admin can retry."""
        load_question.return_value = SimpleNamespace(
            id=7,
            program_id="ds",
            original_question="Can I change my exam city?",
            accepted_or_rejected_by_admin="accepted",
            ai_suggestion=None,
        )
        load_faq_rows.return_value = []
        chat_completion.return_value = mock.Mock(is_success=False)

        with self.assertRaisesRegex(FaqReviewError, "failed"):
            await review_unanswered_question(7)

        save_result.assert_not_called()

    @mock.patch("faq_admin.ai_review.chat_completion_async")
    @mock.patch("faq_admin.ai_review._load_unanswered_question")
    @mock.patch("faq_admin.ai_review.sync_to_async", side_effect=_run_sync_inline)
    async def test_saved_review_returns_without_calling_the_model(
        self, run_sync, load_question, chat_completion
    ):
        """One saved result is stable; pressing the button again never reruns AI."""
        load_question.return_value = SimpleNamespace(
            id=7,
            program_id="ds",
            original_question="Can I change my exam city?",
            accepted_or_rejected_by_admin="accepted",
            ai_suggestion="should_not_be_added",
            ai_reason="Outside scope.",
            matching_faq_ids=None,
            suggested_clean_question="NA",
            rewritten_question=None,
            rejection_reason=None,
            original_answer=None,
            asked_at=None,
            fact_check_passed=False,
            fact_check_rejection_reason=None,
        )

        result = await review_unanswered_question(7)

        self.assertEqual(result["ai_suggestion"], "should_not_be_added")
        chat_completion.assert_not_called()
    @mock.patch("faq_admin.ai_review.chat_completion_async")
    @mock.patch("faq_admin.ai_review.get_openai_http_client")
    @mock.patch("faq_admin.ai_review._load_faq_rows")
    @mock.patch("faq_admin.ai_review._load_unanswered_question")
    @mock.patch("faq_admin.ai_review._save_review_result")
    @mock.patch("faq_admin.ai_review.sync_to_async", side_effect=_run_sync_inline)
    async def test_review_sends_only_programme_and_shared_faq_rows_and_saves_once(
        self, run_sync, save_result, load_question, load_faq_rows, get_client, chat_completion
    ):
        """An AE review receives AE/common evidence and saves the validated result."""
        row = SimpleNamespace(
            id=7,
            program_id="ae",
            original_question="Can I change my selected exam city?",
            accepted_or_rejected_by_admin="accepted",
            ai_suggestion=None,
            ai_reason=None,
            matching_faq_ids=None,
            suggested_clean_question=None,
        )
        load_question.return_value = row
        load_faq_rows.return_value = [
            SimpleNamespace(id=41, program_id="ae", question="How do I choose my city?", answer="Choose it in the portal."),
            SimpleNamespace(id=87, program_id="common", question="When are exams?", answer="See the calendar."),
        ]
        response = mock.Mock(is_success=True)
        response.json.return_value = {
            "choices": [{"message": {"content": json.dumps({
                "ai_suggestion": "should_be_added",
                "reason": "The available FAQs do not explain city changes.",
                "matching_faq_ids": [],
                "suggested_clean_question": "Can I change my selected exam city?",
            })}}]
        }
        chat_completion.return_value = response
        save_result.return_value = {
            "ai_suggestion": "should_be_added",
            "ai_reason": "The available FAQs do not explain city changes.",
            "matching_faq_ids": [],
            "suggested_clean_question": "Can I change my selected exam city?",
        }

        result = await review_unanswered_question(7)

        self.assertEqual(result["ai_suggestion"], "should_be_added")
        self.assertEqual(result["ai_reason"], "The available FAQs do not explain city changes.")
        messages = chat_completion.call_args.args[1]
        self.assertIn("PROGRAMME: ae", messages[1]["content"])
        self.assertIn("FAQ ID: 41", messages[1]["content"])
        self.assertIn("FAQ ID: 87", messages[1]["content"])
        self.assertNotIn("original_answer", messages[1]["content"])
        self.assertEqual(chat_completion.call_args.kwargs["model"], "gpt-5.6-luna")
        self.assertEqual(chat_completion.call_args.kwargs["reasoning_effort"], "medium")
        self.assertEqual(chat_completion.call_args.kwargs["max_completion_tokens"], 1200)
        self.assertNotIn("max_tokens", chat_completion.call_args.kwargs)
        self.assertNotIn("temperature", chat_completion.call_args.kwargs)
        self.assertEqual(save_result.call_args.args[0], 7)


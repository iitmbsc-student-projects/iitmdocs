from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from faq_admin.services import (
    FaqAdminValidationError,
    build_answers_for_safety_check,
    build_faq_update_data,
    build_new_faq_rows,
    get_faq_answer,
    normalize_question,
)


class NewFaqRowTests(SimpleTestCase):
    def test_normalize_question_ignores_case_and_extra_spaces(self):
        self.assertEqual(normalize_question("  Fee   Payment? "), "fee payment?")
    def test_different_answers_create_one_row_for_each_programme(self):
        rows = build_new_faq_rows(
            {
                "question_category": "diff_answers",
                "question": "What are the fees?",
                "answers": {"ds": "DS", "ae": "AE", "es": "ES", "mg": "MG"},
            }
        )

        self.assertEqual(
            rows,
            [
                {"program_id": "ds", "question": "What are the fees?", "answer": "DS", "question_category": "diff_answers"},
                {"program_id": "es", "question": "What are the fees?", "answer": "ES", "question_category": "diff_answers"},
                {"program_id": "mg", "question": "What are the fees?", "answer": "MG", "question_category": "diff_answers"},
                {"program_id": "ae", "question": "What are the fees?", "answer": "AE", "question_category": "diff_answers"},
            ],
        )

    def test_common_faq_creates_one_shared_row(self):
        rows = build_new_faq_rows(
            {"question_category": "common", "question": "When do applications open?", "answer": "See the website."}
        )

        self.assertEqual(rows, [{"program_id": "common", "question": "When do applications open?", "answer": "See the website.", "question_category": "common"}])

    def test_new_different_answer_safety_check_includes_each_answer_that_will_be_saved(self):
        answers = build_answers_for_safety_check(
            {
                "action": "add",
                "question_category": "diff_answers",
                "question": "What are the fees?",
                "answers": {"ds": "DS", "ae": "AE", "es": "ES", "mg": "MG"},
            }
        )

        self.assertEqual(
            answers,
            [
                {"program_id": "ds", "answer": "DS"},
                {"program_id": "es", "answer": "ES"},
                {"program_id": "mg", "answer": "MG"},
                {"program_id": "ae", "answer": "AE"},
            ],
        )


class ExistingFaqUpdateTests(SimpleTestCase):
    def test_different_answer_update_can_change_one_programme_only(self):
        update = build_faq_update_data(
            {
                "question": "When are fees due?",
                "answer_program_id": "ae",
                "answers": {"ae": "Pay before the AE deadline."},
            },
            "diff_answers",
            "ds",
        )

        self.assertEqual(
            update,
            {
                "question": "When are fees due?",
                "answers": {"ae": "Pay before the AE deadline."},
            },
        )

    def test_different_answer_update_for_all_requires_all_four_answers(self):
        with self.assertRaisesMessage(FaqAdminValidationError, "All four answers are required"):
            build_faq_update_data(
                {
                    "question": "When are fees due?",
                    "answer_program_id": "all",
                    "answers": {"ds": "DS answer"},
                },
                "diff_answers",
                "ds",
            )

    @mock.patch("pg.faq_api.orm.session_scope")
    @mock.patch("pg.faq_api.orm.create_session_factory")
    @mock.patch("pg.faq_api.orm.create_pg_engine")
    def test_safety_check_rejects_an_incomplete_different_answer_group(self, create_pg_engine, create_session_factory, session_scope):
        session = session_scope.return_value.__enter__.return_value
        session.get.return_value = SimpleNamespace(
            id=8,
            question="When are fees due?",
            program_id="ds",
            question_category="diff_answers",
        )
        session.execute.return_value.scalars.return_value.all.return_value = [
            SimpleNamespace(program_id="ds"),
        ]

        with self.assertRaisesMessage(FaqAdminValidationError, "incomplete"):
            build_answers_for_safety_check(
                {
                    "action": "update",
                    "selected_faq_id": 8,
                    "question": "When are fees due?",
                    "answer_program_id": "ds",
                    "answers": {"ds": "Pay before the deadline."},
                }
            )


class SelectedFaqDetailsTests(SimpleTestCase):
    @mock.patch("pg.faq_api.orm.session_scope")
    @mock.patch("pg.faq_api.orm.create_session_factory")
    @mock.patch("pg.faq_api.orm.create_pg_engine")
    def test_selected_faq_details_include_the_stored_question(self, create_pg_engine, create_session_factory, session_scope):
        """The edit screen needs the stored question, not the admin's search text."""
        session = session_scope.return_value.__enter__.return_value
        session.get.return_value = SimpleNamespace(
            id=8,
            question="How do I pay fees?",
            answer="Pay before the deadline.",
            program_id="ae",
            question_category="program_specific",
        )

        details = get_faq_answer(8)

        self.assertEqual(details["question"], "How do I pay fees?")

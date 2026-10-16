from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from faq_admin.services import (
    FaqAdminValidationError,
    build_answers_for_safety_check,
    build_faq_update_data,
    build_new_faq_rows,
    delete_faq_from_management,
    get_faq_answer,
    list_all_faqs,
    normalize_question,
    update_faq_from_management,
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


class AllFaqManagementTests(SimpleTestCase):
    @mock.patch("pg.faq_api.orm.session_scope")
    @mock.patch("pg.faq_api.orm.create_session_factory")
    @mock.patch("pg.faq_api.orm.create_pg_engine")
    def test_all_faq_rows_include_every_database_column(self, create_pg_engine, create_session_factory, session_scope):
        session = session_scope.return_value.__enter__.return_value
        session.execute.return_value.scalars.return_value.all.return_value = [
            SimpleNamespace(
                id=8,
                program_id="ae",
                question="How do I pay fees?",
                answer="Pay before the deadline.",
                question_category="program_specific",
                embedding=[0.1, 0.2],
            )
        ]

        rows = list_all_faqs()

        self.assertEqual(rows, [{
            "id": 8,
            "program_id": "ae",
            "question": "How do I pay fees?",
            "answer": "Pay before the deadline.",
            "question_category": "program_specific",
            "embedding": [0.1, 0.2],
        }])

    @mock.patch("faq_admin.services._question_embedding", return_value=[0.3, 0.4])
    @mock.patch("pg.faq_api.orm.session_scope")
    @mock.patch("pg.faq_api.orm.create_session_factory")
    @mock.patch("pg.faq_api.orm.create_pg_engine")
    def test_management_update_changes_a_different_answer_group_question_and_one_answer(self, create_pg_engine, create_session_factory, session_scope, question_embedding):
        session = session_scope.return_value.__enter__.return_value
        selected = SimpleNamespace(
            id=8, program_id="ae", question="Old question?", answer="Old AE answer",
            question_category="diff_answers", embedding=[0.1],
        )
        ds_row = SimpleNamespace(id=7, program_id="ds", question="Old question?", answer="DS answer", embedding=[0.1])
        session.get.return_value = selected
        session.execute.return_value.scalars.return_value.all.return_value = [selected, ds_row]

        updated = update_faq_from_management(8, "New question?", "New AE answer")

        self.assertEqual(updated["updated_ids"], [8, 7])
        self.assertEqual(selected.answer, "New AE answer")
        self.assertEqual(ds_row.answer, "DS answer")
        self.assertEqual(selected.question, "New question?")
        self.assertEqual(ds_row.question, "New question?")
        question_embedding.assert_called_once_with("New question?")

    @mock.patch("pg.faq_api.orm.session_scope")
    @mock.patch("pg.faq_api.orm.create_session_factory")
    @mock.patch("pg.faq_api.orm.create_pg_engine")
    def test_management_delete_removes_all_rows_in_a_different_answer_group(self, create_pg_engine, create_session_factory, session_scope):
        session = session_scope.return_value.__enter__.return_value
        selected = SimpleNamespace(id=8, program_id="ae", question="What are the fees?", question_category="diff_answers")
        ds_row = SimpleNamespace(id=7, program_id="ds", question="What are the fees?", question_category="diff_answers")
        session.get.return_value = selected
        session.execute.return_value.scalars.return_value.all.return_value = [selected, ds_row]

        deleted = delete_faq_from_management(8)

        self.assertEqual(deleted, {"deleted_ids": [8, 7], "question_category": "diff_answers"})
        self.assertEqual(session.delete.call_args_list, [mock.call(selected), mock.call(ds_row)])

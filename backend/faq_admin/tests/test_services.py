from django.test import SimpleTestCase

from faq_admin.services import build_new_faq_rows


class NewFaqRowTests(SimpleTestCase):
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

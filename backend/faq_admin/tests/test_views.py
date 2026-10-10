from django.test import Client, SimpleTestCase
from unittest import mock


class FaqAdminPageTests(SimpleTestCase):
    def test_page_opens_at_the_internal_url(self):
        response = self.client.get("/faq-admin")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "FAQ Admin")
        self.assertContains(response, "Check similar FAQs")
        self.assertContains(response, "Update selected FAQ")
        self.assertContains(response, 'id="program-id"')
        self.assertContains(response, 'id="answer-program-field"')
        self.assertContains(response, 'id="answer-entry" hidden')
        self.assertContains(response, "/faq-admin.js")

    @mock.patch("faq_admin.views.find_similar_faqs")
    def test_similarity_endpoint_returns_matching_faqs(self, find_similar_faqs):
        find_similar_faqs.return_value = [{"id": 8, "question": "How do I pay fees?", "program_id": "ds", "question_category": "program_specific", "similarity": 0.82}]

        response = self.client.post("/faq-admin/check-similar", data='{"question": "fee payment procedure", "program_id": "ds"}', content_type="application/json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["matches"][0]["id"], 8)
        find_similar_faqs.assert_called_once_with("fee payment procedure", "ds")

    @mock.patch("faq_admin.views.add_new_faq")
    def test_add_endpoint_returns_saved_row_ids(self, add_new_faq):
        add_new_faq.return_value = [31]

        response = self.client.post("/faq-admin/add", data='{"question_category":"program_specific","program_id":"ds","question":"New FAQ?","answer":"New answer"}', content_type="application/json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"saved_ids": [31]})

    @mock.patch("faq_admin.views.update_existing_faq")
    def test_update_endpoint_returns_the_rows_changed(self, update_existing_faq):
        update_existing_faq.return_value = {
            "updated_ids": [8],
            "question_category": "program_specific",
            "program_ids": ["ds"],
        }

        response = self.client.post(
            "/faq-admin/update",
            data=(
                '{"selected_faq_id":8,"question":"Updated FAQ?",'
                '"answer":"Updated answer"}'
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["updated_ids"], [8])
        update_existing_faq.assert_called_once_with(
            {"selected_faq_id": 8, "question": "Updated FAQ?", "answer": "Updated answer"}
        )

    def test_update_endpoint_rejects_a_request_without_a_csrf_token(self):
        csrf_client = Client(enforce_csrf_checks=True)

        response = csrf_client.post(
            "/faq-admin/update",
            data='{"selected_faq_id":8,"question":"Updated FAQ?","answer":"Updated answer"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)

    @mock.patch("faq_admin.views.get_faq_answer")
    def test_answer_endpoint_returns_one_selected_faq_answer(self, get_faq_answer):
        get_faq_answer.return_value = {
            "id": 8,
            "question": "How do I pay fees?",
            "answer": "Pay before the deadline.",
            "program_id": "ae",
            "question_category": "program_specific",
        }

        response = self.client.get("/faq-admin/answer/8")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["question"], "How do I pay fees?")
        self.assertEqual(response.json()["answer"], "Pay before the deadline.")
        get_faq_answer.assert_called_once_with(8)

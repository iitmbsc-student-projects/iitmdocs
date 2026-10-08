from django.test import SimpleTestCase
from unittest import mock


class FaqAdminPageTests(SimpleTestCase):
    def test_page_opens_at_the_internal_url(self):
        response = self.client.get("/faq-admin")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "FAQ Admin")
        self.assertContains(response, "Check similar FAQs")
        self.assertContains(response, 'id="program-id"')
        self.assertContains(response, "/faq-admin.js")

    @mock.patch("faq_admin.views.find_similar_faqs")
    def test_similarity_endpoint_returns_matching_faqs(self, find_similar_faqs):
        find_similar_faqs.return_value = [{"id": 8, "question": "How do I pay fees?", "program_id": "ds", "question_category": "program_specific", "similarity": 0.82}]

        response = self.client.post("/faq-admin/check-similar", data='{"question": "fee payment procedure"}', content_type="application/json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["matches"][0]["id"], 8)

from django.test import SimpleTestCase


class FaqAdminPageTests(SimpleTestCase):
    def test_page_opens_at_the_internal_url(self):
        response = self.client.get("/faq-admin")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "FAQ Admin")
        self.assertContains(response, "Check similar FAQs")

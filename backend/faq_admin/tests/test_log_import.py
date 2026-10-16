import datetime
import json

from django.test import SimpleTestCase

from faq_admin.log_import import read_last_seven_days_test_logs


class TestLogImportTests(SimpleTestCase):
    def test_reads_payloads_from_only_the_last_seven_daily_tables(self):
        """The manual refresh must not scan the complete BigQuery log history."""
        payload = {"message": "conversation_turn", "question": "Can I pay later?"}

        class FakeJob:
            def result(self):
                return [{"payload": json.dumps(payload)}]

        class FakeClient:
            def query(self, query):
                self.query_text = query
                return FakeJob()

        client = FakeClient()
        logs = read_last_seven_days_test_logs(client=client, today=datetime.date(2026, 10, 16))

        self.assertEqual(logs, [payload])
        self.assertIn("20261010", client.query_text)
        self.assertIn("20261016", client.query_text)
        self.assertIn("temp-bq-project.chatbot_logs", client.query_text)

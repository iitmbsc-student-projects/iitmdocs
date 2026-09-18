"""Flow: read the Looker view SQL -> inspect the joined conversation SELECT -> verify its columns."""

from pathlib import Path
import unittest


class ConversationsWithFeedbackViewTests(unittest.TestCase):
    """Protect the analytics view from dropping fields emitted by conversation logs."""

    def test_joined_view_keeps_all_conversation_analytics_fields(self):
        sql_path = Path(__file__).parents[3] / "scripts" / "setup-looker-view.sql"
        sql = sql_path.read_text()
        view_sql = sql.split(
            "CREATE OR REPLACE VIEW `YOUR_PROJECT_ID.chatbot_logs.conversations_with_feedback` AS",
            1,
        )[1].split("FROM `YOUR_PROJECT_ID.chatbot_logs.conversations`", 1)[0]

        expected_fields = {
            "c.original_answer",
            "c.db_faqs",
            "c.tokens",
            "c.total_input_tokens",
            "c.total_output_tokens",
        }

        for field in expected_fields:
            self.assertIn(field, view_sql)


if __name__ == "__main__":
    unittest.main()

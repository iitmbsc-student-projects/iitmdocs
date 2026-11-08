"""Tests for the FAQ-admin question rules that guard the similarity check."""
from django.test import SimpleTestCase

from faq_admin.question_validation import MAX_WORDS, MIN_WORDS, validate_question, word_count


class QuestionValidationTests(SimpleTestCase):
    def test_rejects_emoji(self):
        self.assertIn("plain English", validate_question("\u2705"))

    def test_rejects_emoji_inside_a_long_question(self):
        self.assertIn("plain English", validate_question("How do I pay my fees \u2705 this term"))

    def test_rejects_accented_characters(self):
        self.assertIn("plain English", validate_question("Caf\u00e9 fees for this term please"))

    def test_rejects_non_latin_text(self):
        self.assertIn("plain English", validate_question("\u092b\u0940\u0938 \u0915\u093f\u0924\u0928\u0940 \u0939\u0948 \u0914\u0930 \u0915\u0948\u0938\u0947 \u092d\u0930\u0947"))

    def test_rejects_right_to_left_text(self):
        self.assertIn("plain English", validate_question("\u0643\u0645 \u0647\u064a \u0627\u0644\u0631\u0633\u0648\u0645 \u0627\u0644\u062f\u0631\u0627\u0633\u064a\u0629 \u0644\u0647\u0630\u0627 \u0627\u0644\u0641\u0635\u0644"))

    def test_rejects_unicode_symbols(self):
        self.assertIn("plain English", validate_question("Fee \u2192 payment procedure for this term"))

    def test_accepts_ordinary_punctuation(self):
        self.assertIsNone(validate_question("What is the fee structure for the DS programme, and how do I pay?"))

    def test_rejects_questions_shorter_than_the_minimum(self):
        self.assertIn("too short", validate_question("fee payment procedure"))

    def test_accepts_a_question_at_the_minimum_length(self):
        self.assertIsNone(validate_question("how do i pay the fees"))

    def test_accepts_a_question_at_the_maximum_length(self):
        question = " ".join(["word"] * MAX_WORDS)

        self.assertIsNone(validate_question(question))

    def test_rejects_questions_longer_than_the_maximum(self):
        question = " ".join(["word"] * (MAX_WORDS + 1))

        self.assertIn("too long", validate_question(question))

    def test_rejects_blank_and_missing_values(self):
        for value in ("", "   ", None, 42):
            with self.subTest(value=value):
                self.assertEqual(validate_question(value), "Enter a question first.")

    def test_ignores_extra_whitespace_and_newlines(self):
        self.assertIsNone(validate_question("How do I\n\npay   the fees?"))

    def test_word_count_matches_the_word_limits(self):
        self.assertEqual(word_count("  How do I pay fees?  "), 5)
        self.assertEqual(word_count("how do i pay fees"), MIN_WORDS)

"""Programme-scoped query rewrite: the acceptance criteria of issue #179.

Flow: check that every programme's synonym expansions are keyword-only (no rupee,
salary or CGPA figures, no DS course codes), that each programme's knowledge-base
summary describes exactly the files in its own src/ folder, and that the rewrite
prompt picks the right summary.
"""
import re
from pathlib import Path

from django.test import SimpleTestCase

from programs import REAL_PROGRAM_IDS

from chatbot import business
from chatbot.prompts import build_rewrite_system_prompt

REPO_ROOT = Path(__file__).resolve().parents[3]

DS_COURSE_CODES = ("PDSA", "MLF", "MLT", "MLP", "BDM", "BA", "TDS")
# Rupee amounts, lakh shorthand (2.21L), salaries (10 LPA) and CGPA values.
FIGURE_RE = re.compile(r"\bRs\b|₹|\bLPA\b|\b\d+(\.\d+)?\s*L\b|\bCGPA\s*\d")


class SynonymContentTests(SimpleTestCase):
    def test_every_programme_has_a_list_of_well_formed_entries(self):
        self.assertEqual(set(business.PROGRAM_QUERY_SYNONYMS), set(REAL_PROGRAM_IDS))
        for program_id, entries in business.PROGRAM_QUERY_SYNONYMS.items():
            self.assertTrue(entries, program_id)
            for patterns, expansion in entries:
                self.assertIsInstance(patterns, list, program_id)
                self.assertTrue(all(isinstance(p, str) and p for p in patterns), program_id)
                self.assertIsInstance(expansion, str, program_id)
                self.assertTrue(expansion.strip(), program_id)

    def test_no_ds_course_code_in_any_expansion(self):
        for program_id, entries in business.PROGRAM_QUERY_SYNONYMS.items():
            for _patterns, expansion in entries:
                for code in DS_COURSE_CODES:
                    self.assertIsNone(
                        re.search(rf"\b{code}\b", expansion),
                        f"{program_id}: {code!r} in {expansion!r}",
                    )

    def test_no_currency_salary_or_cgpa_figure_in_any_expansion(self):
        for program_id, entries in business.PROGRAM_QUERY_SYNONYMS.items():
            for _patterns, expansion in entries:
                self.assertIsNone(
                    FIGURE_RE.search(expansion), f"{program_id}: {expansion!r}"
                )

    def test_fee_question_expands_without_figures_for_every_programme(self):
        """The exact repro from issue #179, per programme."""
        query = business.sanitize_query("what is the total fee for this program")
        for program_id in REAL_PROGRAM_IDS:
            expansion = business.find_synonym_match(query, program_id)
            self.assertIsNotNone(expansion, program_id)
            self.assertIsNone(FIGURE_RE.search(expansion), f"{program_id}: {expansion!r}")

    def test_unknown_programme_falls_back_to_default_list(self):
        self.assertEqual(
            business.find_synonym_match("grading policy", "xx"),
            business.find_synonym_match("grading policy", "ds"),
        )


class KnowledgeBaseSummaryTests(SimpleTestCase):
    def test_every_programme_summary_has_one_line_per_source_file(self):
        """The summaries are hand-written; this catches drift when src/ changes."""
        self.assertEqual(set(business.KNOWLEDGE_BASE_SUMMARIES), set(REAL_PROGRAM_IDS))
        for program_id in REAL_PROGRAM_IDS:
            summary = business.knowledge_base_summary(program_id)
            self.assertTrue(summary.startswith("Topics available in knowledge base:"), program_id)
            topic_lines = [line for line in summary.splitlines() if re.match(r"^\d+\. ", line)]
            source_files = list((REPO_ROOT / "src" / program_id).glob("*.md"))
            self.assertEqual(len(topic_lines), len(source_files), program_id)

    def test_rewrite_prompt_uses_the_programmes_own_summary(self):
        es_prompt = build_rewrite_system_prompt("es")
        ds_prompt = build_rewrite_system_prompt("ds")
        self.assertIn("Electronic Systems", es_prompt)
        self.assertNotIn("International Students Information", es_prompt)
        self.assertIn("International Students Information", ds_prompt)
        self.assertNotIn("Qualifier Passing Criteria", ds_prompt)

    def test_unknown_programme_falls_back_to_default_summary(self):
        self.assertEqual(business.knowledge_base_summary("xx"), business.knowledge_base_summary("ds"))

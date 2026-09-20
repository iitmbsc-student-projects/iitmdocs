"""Unit tests for the shared programme registry at the repo root (programs.py)."""
from django.test import SimpleTestCase

import programs


class ValidateProgramIdTests(SimpleTestCase):
    def test_accepts_the_four_real_programs(self):
        for program_id in ("ds", "es", "mg", "ae"):
            self.assertEqual(programs.validate_program_id(program_id), program_id)

    def test_normalizes_whitespace_and_case(self):
        self.assertEqual(programs.validate_program_id(" ES "), "es")

    def test_missing_value_falls_back_to_default(self):
        self.assertEqual(programs.validate_program_id(None), "ds")
        self.assertEqual(programs.validate_program_id(""), "ds")

    def test_unknown_program_is_rejected(self):
        with self.assertRaises(ValueError):
            programs.validate_program_id("xx")

    def test_common_is_rejected_by_default(self):
        # "common" is a storage-only id. Accepting it from a request would let a
        # caller read the shared FAQ pool as if it were a programme.
        with self.assertRaises(ValueError):
            programs.validate_program_id("common")

    def test_common_is_allowed_for_storage_callers(self):
        self.assertEqual(programs.validate_program_id("common", allow_common=True), "common")


class FaqProgramScopeTests(SimpleTestCase):
    def test_scope_is_the_program_plus_common(self):
        self.assertEqual(programs.faq_program_scope("es"), ["es", "common"])


class ProgramConfigTests(SimpleTestCase):
    def test_returns_the_programs_own_contacts(self):
        self.assertEqual(
            programs.program_config("es")["support_email"], "support-es@study.iitm.ac.in"
        )

    def test_unknown_program_falls_back_to_default(self):
        self.assertEqual(programs.program_config("xx"), programs.PROGRAM_CONFIG["ds"])

    def test_every_real_program_has_a_full_entry(self):
        for program_id in programs.REAL_PROGRAM_IDS:
            config = programs.PROGRAM_CONFIG[program_id]
            for key in ("name", "website", "support_email", "support_phone"):
                self.assertTrue(config[key], f"{program_id} is missing {key}")

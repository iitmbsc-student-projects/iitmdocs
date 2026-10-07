"""Unit tests for embed.py: FAQ seed loading and per-programme document tagging.

embed.py runs in its own container and imports the weaviate client at module level.
Nothing here talks to Weaviate, so we stub that import before importing embed - the
alternative is installing the weaviate client just to test file parsing.
"""
import json
import os
import sys
import tempfile
import types
from unittest import mock
from pathlib import Path

from django.test import SimpleTestCase


def _stub_weaviate():
    """Register empty weaviate modules so `import embed` works without the client."""
    for name in (
        "weaviate",
        "weaviate.classes",
        "weaviate.classes.config",
        "weaviate.classes.init",
        "weaviate.classes.query",
    ):
        sys.modules.setdefault(name, types.ModuleType(name))
    for module_name, attributes in (
        ("weaviate.classes.config", ("Configure", "Property", "DataType")),
        ("weaviate.classes.init", ("AdditionalConfig", "Timeout")),
        ("weaviate.classes.query", ("Filter",)),
    ):
        for attribute in attributes:
            setattr(sys.modules[module_name], attribute, object)


_stub_weaviate()
import embed  # noqa: E402  (must follow the stub above)
from pg.faq_api.orm import Faq
from pg.faq_api.repository import assign_seed_question_categories, replace_seed_faqs


REPO_ROOT = Path(embed.__file__).parent


def _write_seed(directory, question_answer_files, diff_answers):
    """Build a complete, valid seed directory under `directory`, then apply overrides.

    `question_answer_files` maps a relative path to a list of {"Question", "Answer"}
    rows; `diff_answers` is the list written to diff_answers.json.
    """
    (directory / "program_specific").mkdir(parents=True, exist_ok=True)
    for relative_path, rows in question_answer_files.items():
        (directory / relative_path).write_text(json.dumps(rows), encoding="utf-8")
    (directory / "diff_answers.json").write_text(json.dumps(diff_answers), encoding="utf-8")


def _minimal_seed():
    """Return the smallest seed that loads successfully: one row everywhere."""
    files = {
        "common.json": [{"Question": "Shared question?", "Answer": "Shared answer"}],
        "timeline_based.json": [{"Question": "When is the exam?", "Answer": "In May"}],
    }
    for program_id in ("ds", "es", "mg", "ae"):
        files[f"program_specific/{program_id}.json"] = [
            {"Question": f"{program_id} question?", "Answer": f"{program_id} answer"}
        ]
    diff = [{"question": "What are the fees?", "answers": {p: f"{p} fees" for p in ("ds", "es", "mg", "ae")}}]
    return files, diff


class SeedDirectoryTests(SimpleTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.seed_dir = Path(self._tmp.name) / "seed"
        self.seed_dir.mkdir()
        self.files, self.diff = _minimal_seed()

    def tearDown(self):
        self._tmp.cleanup()

    def load(self):
        _write_seed(self.seed_dir, self.files, self.diff)
        return embed._load_seed_faqs(str(self.seed_dir))

    def test_loads_every_file_with_the_right_program_id(self):
        rows = self.load()
        # 2 shared + 4 from diff_answers + 4 program-specific
        self.assertEqual(len(rows), 10)
        by_program = {}
        for row in rows:
            by_program.setdefault(row["program_id"], []).append(row["question"])
        self.assertEqual(len(by_program["common"]), 2)
        for program_id in ("ds", "es", "mg", "ae"):
            self.assertEqual(len(by_program[program_id]), 2)

    def test_diff_answers_expands_to_one_row_per_program(self):
        rows = self.load()
        fees = [row for row in rows if row["question"] == "What are the fees?"]
        self.assertEqual({row["program_id"] for row in fees}, {"ds", "es", "mg", "ae"})
        self.assertEqual({row["answer"] for row in fees}, {"ds fees", "es fees", "mg fees", "ae fees"})

    def test_rows_remember_which_seed_category_created_them(self):
        rows = self.load()

        categories = {
            (row["program_id"], row["question"]): row["question_category"]
            for row in rows
        }

        self.assertEqual(categories[("common", "Shared question?")], "common")
        self.assertEqual(categories[("common", "When is the exam?")], "timeline_based")
        self.assertEqual(categories[("ds", "ds question?")], "program_specific")
        self.assertEqual(categories[("ae", "What are the fees?")], "diff_answers")

    def test_a_file_that_is_not_a_directory_is_rejected(self):
        seed_file = Path(self._tmp.name) / "faqs.json"
        seed_file.write_text("[]", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "must be a directory"):
            embed._load_seed_faqs(str(seed_file))

    def test_missing_seed_file_is_named_in_the_error(self):
        del self.files["program_specific/mg.json"]
        with self.assertRaisesRegex(ValueError, "program_specific/mg.json"):
            self.load()

    def test_lowercase_question_key_is_rejected(self):
        # The capitalised keys match the source spreadsheets; a lowercase key is a bug.
        self.files["common.json"] = [{"question": "Oops?", "Answer": "Answer"}]
        with self.assertRaisesRegex(ValueError, "Question"):
            self.load()

    def test_fully_blank_row_is_skipped(self):
        self.files["common.json"].append({"Question": "  ", "Answer": ""})
        rows = self.load()
        self.assertEqual(len(rows), 10)

    def test_half_blank_row_is_an_error(self):
        self.files["common.json"].append({"Question": "Has no answer?", "Answer": "  "})
        with self.assertRaisesRegex(ValueError, "Answer"):
            self.load()

    def test_diff_answers_missing_one_program_is_an_error(self):
        self.diff = [{"question": "Fees?", "answers": {"ds": "a", "es": "b", "mg": "c"}}]
        with self.assertRaisesRegex(ValueError, "answers.ae"):
            self.load()

    def test_same_question_in_two_programs_is_allowed(self):
        self.files["program_specific/ds.json"] = [{"Question": "Same?", "Answer": "ds"}]
        self.files["program_specific/es.json"] = [{"Question": "Same?", "Answer": "es"}]
        rows = self.load()
        same = [row for row in rows if row["question"] == "Same?"]
        self.assertEqual({row["program_id"] for row in same}, {"ds", "es"})

    def test_same_question_twice_in_one_program_is_an_error(self):
        self.files["program_specific/ds.json"] = [
            {"Question": "Same?", "Answer": "first"},
            {"Question": " same? ", "Answer": "second"},
        ]
        with self.assertRaisesRegex(ValueError, "Duplicate FAQ questions"):
            self.load()


class FaqSchemaTests(SimpleTestCase):
    def test_faq_model_has_question_category_column(self):
        """The database must retain source type after JSON stops being live data."""
        self.assertIn("question_category", Faq.__table__.columns)

    def test_seed_replace_keeps_question_category(self):
        """A new database created from seed must retain each row's category."""

        class FakeSession:
            def execute(self, statement):
                self.delete_statement = statement

            def add_all(self, faqs):
                self.faqs = list(faqs)

        session = FakeSession()
        replace_seed_faqs(
            session,
            [
                {
                    "program_id": "common",
                    "question": "Shared question?",
                    "answer": "Shared answer",
                    "question_category": "common",
                }
            ],
        )

        self.assertEqual(session.faqs[0].question_category, "common")

    def test_category_import_labels_existing_rows_without_replacing_them(self):
        """The one-time import must update metadata, not delete FAQ rows."""

        class FakeResult:
            def all(self):
                return [
                    (10, "common", "Shared question?"),
                    (11, "ds", "DS-only question?"),
                ]

        class FakeSession:
            def __init__(self):
                self.statements = []

            def execute(self, statement):
                self.statements.append(statement)
                if len(self.statements) == 1:
                    return FakeResult()

        session = FakeSession()
        updated = assign_seed_question_categories(
            session,
            [
                {
                    "program_id": "common",
                    "question": "Shared question?",
                    "question_category": "common",
                },
                {
                    "program_id": "ds",
                    "question": "DS-only question?",
                    "question_category": "program_specific",
                },
            ],
        )

        self.assertEqual(updated, 2)
        self.assertEqual(len(session.statements), 3)

    def test_category_import_rejects_a_database_row_missing_from_seed(self):
        class FakeResult:
            def all(self):
                return [(10, "common", "Database-only question?")]

        class FakeSession:
            def execute(self, statement):
                return FakeResult()

        with self.assertRaisesRegex(ValueError, "do not match the committed seed"):
            assign_seed_question_categories(
                FakeSession(),
                [
                    {
                        "program_id": "common",
                        "question": "Seed-only question?",
                        "question_category": "common",
                    }
                ],
            )

    @mock.patch("embed.Base.metadata.create_all")
    @mock.patch("embed.inspect")
    def test_schema_migration_adds_category_column_and_allowed_value_check(
        self, inspect_database, create_all
    ):
        """Existing FAQ tables need the same category rule as a new table."""

        inspector = mock.Mock()
        inspector.has_table.return_value = True
        inspector.get_columns.return_value = [
            {"name": "id"},
            {"name": "program_id"},
            {"name": "question"},
            {"name": "answer"},
            {"name": "embedding"},
        ]
        inspector.get_check_constraints.return_value = []
        inspect_database.return_value = inspector
        engine = mock.MagicMock()

        embed._ensure_faq_schema(engine)

        statements = [
            str(call.args[0])
            for call in engine.begin.return_value.__enter__.return_value.execute.call_args_list
        ]
        self.assertTrue(any("ADD COLUMN question_category" in statement for statement in statements))
        self.assertTrue(
            any("ADD CONSTRAINT faqs_question_category_check" in statement for statement in statements)
        )


class FaqBootstrapControlTests(SimpleTestCase):
    @mock.patch.dict(os.environ, {"ENABLE_PG_FAQ_SCHEMA_MIGRATION": "true"}, clear=True)
    @mock.patch("embed._load_seed_faqs")
    @mock.patch("embed._ensure_faq_schema")
    @mock.patch("embed._create_pg_bootstrap_engine")
    def test_normal_schema_migration_does_not_load_or_replace_seed_faqs(
        self, create_engine, ensure_schema, load_seed
    ):
        """A normal deployment may migrate schema but must preserve live FAQs."""
        engine = mock.Mock()
        create_engine.return_value = engine

        embed.maybe_prepare_cloudsql_faq_db("gce")

        ensure_schema.assert_called_once_with(engine)
        load_seed.assert_not_called()
        engine.dispose.assert_called_once()

    @mock.patch.dict(
        os.environ,
        {"FAQ_BOOTSTRAP_EMPTY_DATABASE_FROM_SEED": "true"},
        clear=True,
    )
    @mock.patch("embed.replace_seed_faqs")
    @mock.patch("embed._load_seed_faqs")
    @mock.patch("embed.count_faqs", return_value=1)
    @mock.patch("embed.session_scope")
    @mock.patch("embed.create_session_factory")
    @mock.patch("embed._ensure_faq_schema")
    @mock.patch("embed._create_pg_bootstrap_engine")
    def test_empty_database_bootstrap_refuses_to_read_or_replace_a_live_database(
        self,
        create_engine,
        ensure_schema,
        create_session_factory,
        session_scope,
        count_faqs,
        load_seed,
        replace_seed,
    ):
        engine = mock.Mock()
        create_engine.return_value = engine

        with self.assertRaisesRegex(RuntimeError, "only for an empty database"):
            embed.maybe_prepare_cloudsql_faq_db("gce")

        load_seed.assert_not_called()
        replace_seed.assert_not_called()
        engine.dispose.assert_called_once()


class RealSeedTests(SimpleTestCase):
    """Guards the committed pg/seed against an accidental bad edit."""

    def test_committed_seed_loads_with_the_expected_counts(self):
        rows = embed._load_seed_faqs(str(REPO_ROOT / "pg" / "seed"))
        counts = {}
        for row in rows:
            counts[row["program_id"]] = counts.get(row["program_id"], 0) + 1
        self.assertEqual(len(rows), 401)
        self.assertEqual(counts, {"common": 242, "ae": 52, "ds": 35, "es": 39, "mg": 33})


class DocumentProgramIdTests(SimpleTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.src = Path(self._tmp.name) / "src"
        (self.src / "ds").mkdir(parents=True)
        (self.src / "zz").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def test_program_comes_from_the_first_folder(self):
        path = self.src / "ds" / "fees.md"
        self.assertEqual(embed._program_id_for_document(path, self.src), "ds")

    def test_file_directly_in_src_has_no_program(self):
        path = self.src / "fees.md"
        self.assertIsNone(embed._program_id_for_document(path, self.src))

    def test_unknown_folder_has_no_program(self):
        path = self.src / "zz" / "fees.md"
        self.assertIsNone(embed._program_id_for_document(path, self.src))

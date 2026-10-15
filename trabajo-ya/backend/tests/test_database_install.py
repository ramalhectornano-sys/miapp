"""Offline installer contract: these tests do not execute SQL against PostgreSQL."""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("database_install", PROJECT_ROOT / "scripts/build_database_install.py")
installer = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = installer
spec.loader.exec_module(installer)


class DatabaseInstallTests(unittest.TestCase):
    def setUp(self):
        self.migrations = installer.load_migrations(PROJECT_ROOT / "supabase/migrations")

    def test_checked_in_bundle_is_exactly_current_source(self):
        expected = installer.render_bundle(self.migrations)
        installed = (PROJECT_ROOT / "supabase/install-new-project.sql").read_text(encoding="utf-8")
        self.assertEqual(installed, expected)
        self.assertEqual(installer.render_bundle(self.migrations), expected)

    def test_all_migrations_are_ordered_and_preserved(self):
        self.assertEqual([migration.name for migration in self.migrations], [
            "202610120001_initial.sql", "202610120002_manual_search.sql",
            "202610120003_claim_fencing.sql", "202610120004_automatic_sending_policy.sql",
            "202610120005_daily_budget_and_followups.sql",
            "202610130006_persistent_primary_resume.sql",
            "202610140007_web_research_and_locations.sql",
        ])
        bundle = installer.render_bundle(self.migrations)
        positions = []
        for migration in self.migrations:
            start = f"-- ===== INICIO MIGRACIÓN: {migration.name} =====\n"
            finish = f"-- ===== FIN MIGRACIÓN: {migration.name} =====\n"
            positions.append(bundle.index(start))
            actual = bundle.split(start, 1)[1].split(finish, 1)[0]
            self.assertEqual(actual, migration.sql if migration.sql.endswith("\n") else migration.sql + "\n")
            raw = (PROJECT_ROOT / "supabase/migrations" / migration.name).read_bytes()
            self.assertEqual(migration.sha256, hashlib.sha256(raw).hexdigest())
            self.assertIn(f"-- {migration.name}  {migration.sha256}", bundle)
        self.assertEqual(positions, sorted(positions))

    def test_guard_precedes_all_migrations_inside_one_transaction(self):
        bundle = installer.render_bundle(self.migrations)
        transaction = bundle.index("\nBEGIN;\n")
        guard = bundle.index("do $trabajoya_new_project_guard$")
        end_guard = bundle.index("$trabajoya_new_project_guard$;", guard)
        first_migration = bundle.index("-- ===== INICIO MIGRACIÓN:")
        self.assertLess(transaction, guard)
        self.assertLess(end_guard, first_migration)
        self.assertTrue(bundle.endswith("COMMIT;\n"))
        self.assertNotIn("create ", bundle[guard:end_guard].lower())
        self.assertNotIn("drop ", bundle[guard:end_guard].lower())
        self.assertNotIn("truncate ", bundle[guard:end_guard].lower())

    def test_guard_covers_every_owned_table_and_preexisting_users(self):
        guard = installer.render_guard(self.migrations)
        for table in installer.created_objects(self.migrations, "table"):
            self.assertIn(installer.sql_literal(table), guard)
        for function in installer.created_objects(self.migrations, "function"):
            self.assertIn(installer.sql_literal(function), guard)
        self.assertIn("pg_catalog.to_regclass(object_name) is not null", guard)
        self.assertIn("exists (select 1 from auth.users limit 1)", guard)
        self.assertIn("exists (select 1 from storage.buckets where id in ('resumes', 'profile-photos'))", guard)
        self.assertIn("autoempleo_new_user", guard)
        self.assertIn("protect_delivered_resume_object", guard)
        # Standard Supabase objects are prerequisites, not conflicts by existence.
        self.assertIn("pg_catalog.to_regclass('auth.users') is null", guard)
        owned_tables = installer.created_objects(self.migrations, "table")
        self.assertNotIn("auth.users", owned_tables)
        self.assertNotIn("storage.objects", owned_tables)

    def test_cli_check_detects_missing_or_stale_output_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "install.sql"
            args = ["--output", str(output), "--check"]
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(installer.main(args), 1)
                self.assertFalse(output.exists())
                self.assertEqual(installer.main(["--output", str(output)]), 0)
                self.assertEqual(installer.main(args), 0)
                output.write_text("stale content\n", encoding="utf-8")
                self.assertEqual(installer.main(args), 1)
                self.assertEqual(output.read_text(encoding="utf-8"), "stale content\n")

    def test_migration_changes_change_digest_and_stale_output_detection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            migrations = root / "migrations"
            migrations.mkdir()
            for migration in self.migrations:
                (migrations / migration.name).write_text(migration.sql, encoding="utf-8")
            output = root / "install.sql"
            args = ["--migrations-dir", str(migrations), "--output", str(output)]
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(installer.main(args), 0)
                original = output.read_bytes()
                changed = migrations / self.migrations[-1].name
                changed.write_text(changed.read_text(encoding="utf-8") + "\n-- updated migration\n", encoding="utf-8")
                self.assertEqual(installer.main(args + ["--check"]), 1)
                self.assertEqual(output.read_bytes(), original)
                self.assertEqual(installer.main(args), 0)
                self.assertNotEqual(output.read_bytes(), original)

    def test_tests_seeds_and_nested_fixtures_are_not_included(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            migrations = root / "migrations"
            migrations.mkdir()
            for migration in self.migrations:
                (migrations / migration.name).write_text(migration.sql, encoding="utf-8")
            (root / "seed.sql").write_text("TEST_FIXTURE_NEVER_INSTALL", encoding="utf-8")
            nested = migrations / "tests"
            nested.mkdir()
            (nested / "202610120006_fixture.sql").write_text("PRIVATE_FIXTURE_NEVER_INSTALL", encoding="utf-8")
            bundle = installer.render_bundle(installer.load_migrations(migrations))
            self.assertNotIn("TEST_FIXTURE_NEVER_INSTALL", bundle)
            self.assertNotIn("PRIVATE_FIXTURE_NEVER_INSTALL", bundle)
            self.assertEqual(len(installer.load_migrations(migrations)), len(self.migrations))

    def test_invalid_duplicate_versions_and_incomplete_sources_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("202610120001_first.sql", "202610120001_second.sql"):
                (root / name).write_text("select 1;\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                installer.load_migrations(root)
            (root / "202610120001_second.sql").unlink()
            with self.assertRaises(ValueError):
                installer.render_bundle(installer.load_migrations(root))
            (root / "seed.sql").write_text("select 1;\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                installer.load_migrations(root)

    def test_guard_values_escape_sql_quotes(self):
        self.assertEqual(installer.sql_literal("don't"), "'don''t'")
        self.assertEqual(installer.sql_array(("one", "don't")), "array['one','don''t']::text[]")


if __name__ == "__main__":
    unittest.main()

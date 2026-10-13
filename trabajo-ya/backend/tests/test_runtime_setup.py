"""Runtime setup checks must be useful offline and must never leak secrets."""
import base64
from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/check_runtime.py"
SPEC = importlib.util.spec_from_file_location("trabajo_ya_runtime_check", SCRIPT)
runtime = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runtime
SPEC.loader.exec_module(runtime)


class RuntimeSetupTests(unittest.TestCase):
    def setUp(self):
        self.backend = {
            "SUPABASE_URL": "https://project-real.supabase.co",
            "SUPABASE_ANON_KEY": "public-test-key",
            "SUPABASE_SERVICE_ROLE_KEY": "secret-test-service-key",
            "AI_PROVIDER": "ollama", "AI_BASE_URL": "http://ollama:11434", "AI_MODEL": "qwen2.5:7b",
            "GOOGLE_CLIENT_ID": "123.apps.googleusercontent.com", "GOOGLE_CLIENT_SECRET": "secret-google-client-key",
            "GOOGLE_REDIRECT_URI": "https://api.trabajoya.com/api/mail/google/callback",
            "TOKEN_ENCRYPTION_KEY": base64.urlsafe_b64encode(b"k" * 32).decode(),
            "MAIL_SEND_ENABLED": "false",
            "AUTHORIZED_JOB_FEEDS": json.dumps([{"id": "partner", "url": "https://jobs.partner.com/feed.json",
                "authorized": True, "recipient_verification": "source_attestation"}]),
        }
        self.mobile = {"EXPO_PUBLIC_DEMO_MODE": "false", "EXPO_PUBLIC_BACKEND_URL": "https://api.trabajoya.com",
            "EXPO_PUBLIC_SUPABASE_URL": self.backend["SUPABASE_URL"], "EXPO_PUBLIC_SUPABASE_ANON_KEY": self.backend["SUPABASE_ANON_KEY"]}

    def errors(self, **kwargs):
        return [check.name for check in runtime.validate_runtime(self.backend, self.mobile, **kwargs) if check.status == "error"]

    def test_consistent_configuration_is_not_claimed_as_live_verification(self):
        checks = runtime.validate_runtime(self.backend, self.mobile)
        self.assertEqual(self.errors(), [])
        self.assertTrue(any(check.name == "Verificaciones pendientes" for check in checks))
        self.assertTrue(any(check.name == "Envíos reales" and check.status == "warning" for check in checks))

    def test_example_and_empty_configuration_are_not_real_setup(self):
        self.assertGreater(len(runtime.validate_runtime({}, {})), 10)
        errors = [check for check in runtime.validate_runtime({}, {}) if check.status == "error"]
        self.assertTrue(errors)
        self.backend["SUPABASE_URL"] = "https://your-project.supabase.co"
        self.assertIn("Supabase URL", self.errors())

    def test_demo_mode_needs_no_server_and_is_clearly_identified(self):
        checks = runtime.validate_runtime({}, {"EXPO_PUBLIC_DEMO_MODE": "true"}, mode="demo")
        self.assertFalse(any(check.status == "error" for check in checks))
        self.assertTrue(any("no llama a la IA" in check.detail for check in checks))
        self.assertIn("Modo de la aplicación", self.errors(mode="demo"))

    def test_supabase_mismatch_is_rejected(self):
        self.mobile["EXPO_PUBLIC_SUPABASE_URL"] = "https://different.supabase.co"
        self.assertIn("Proyecto móvil/backend", self.errors())
        self.backend["SUPABASE_SERVICE_ROLE_KEY"] = self.backend["SUPABASE_ANON_KEY"]
        self.assertIn("Supabase clave de servicio", self.errors())

    def test_modern_publishable_fallback_matches_mobile_behavior(self):
        self.backend["SUPABASE_ANON_KEY"] = "sb_publishable_public-test-key"
        self.mobile["EXPO_PUBLIC_SUPABASE_ANON_KEY"] = " "
        self.mobile["EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY"] = self.backend["SUPABASE_ANON_KEY"]
        self.assertEqual(self.errors(), [])

    def test_secret_key_and_service_role_jwt_cannot_be_public(self):
        payload = base64.urlsafe_b64encode(json.dumps({"role": "service_role"}).encode()).decode().rstrip("=")
        for value in ("sb_secret_secret-test-key", f"header.{payload}.signature"):
            with self.subTest(value_format=value.split(".")[0]):
                self.backend["SUPABASE_ANON_KEY"] = value
                self.mobile["EXPO_PUBLIC_SUPABASE_ANON_KEY"] = value
                self.assertIn("Supabase clave pública", self.errors())
                self.assertIn("Proyecto móvil/backend", self.errors())

    def test_server_secrets_are_rejected_in_public_vars_by_name_and_value(self):
        self.mobile["EXPO_PUBLIC_OTHER"] = self.backend["GOOGLE_CLIENT_SECRET"]
        self.assertIn("Secretos del servidor", self.errors())
        self.mobile.pop("EXPO_PUBLIC_OTHER")
        self.mobile["EXPO_PUBLIC_SERVICE_ROLE_KEY"] = "some-other-secret"
        self.assertIn("Secretos del servidor", self.errors())

    def test_android_local_backend_only_allowed_for_development(self):
        self.mobile["EXPO_PUBLIC_BACKEND_URL"] = "http://10.0.2.2:8000"
        self.assertIn("API desde Android", self.errors())
        self.assertNotIn("API desde Android", self.errors(profile="development"))

    def test_compose_domain_requires_own_dns_and_consistent_endpoints(self):
        self.backend["API_DOMAIN"] = "api.trabajoya.com"
        self.backend["ACME_EMAIL"] = "administracion@trabajoya.com"
        self.assertEqual(self.errors(), [])
        self.backend["GOOGLE_REDIRECT_URI"] = "https://different.trabajoya.com/api/mail/google/callback"
        self.assertIn("Dominio de app y OAuth", self.errors())

    def test_compose_placeholders_and_protocol_in_domain_are_rejected(self):
        self.backend["ACME_EMAIL"] = "administracion@tu-dominio.com"
        for value in ("api.tu-dominio.com", "https://api.trabajoya.com", "api.trabajoya.com:443", "api.trabajoya.com/path"):
            self.backend["API_DOMAIN"] = value
            self.assertIn("Dominio HTTPS de Compose", self.errors())
        self.assertIn("Contacto de certificados", self.errors())

    def test_fake_private_or_unverified_feed_is_rejected(self):
        for changes in ({"url": "https://127.0.0.1/jobs"}, {"url": "https://partner.example/feed"},
                        {"url": "https://user:password@jobs.partner.com/feed"}, {"authorized": "true"},
                        {"recipient_verification": "guessed"}):
            with self.subTest(changes=changes):
                source = {"id": "partner", "url": "https://jobs.partner.com/feed", "authorized": True,
                    "recipient_verification": "source_attestation", **changes}
                self.backend["AUTHORIZED_JOB_FEEDS"] = json.dumps([source])
                self.assertIn("Fuentes y destinatarios", self.errors())
        self.backend["AUTHORIZED_JOB_FEEDS"] = "[invalid-secret-json"
        self.assertIn("Fuentes y destinatarios", self.errors())

    def test_invalid_encryption_and_callback_are_rejected(self):
        self.backend["TOKEN_ENCRYPTION_KEY"] = "secret-not-a-fernet-key"
        self.backend["GOOGLE_REDIRECT_URI"] = "https://api.trabajoya.com/wrong-path"
        self.assertIn("Cifrado de tokens", self.errors())
        self.assertIn("Callback OAuth", self.errors())

    def test_env_parser_preserves_json_and_never_expands_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.env"
            path.write_text('# comment\nexport A="hello world" # note\nSOURCES=[{"authorized":true}]\nB=plain # comment\n', encoding="utf-8")
            self.assertEqual(runtime.read_env(path), {"A": "hello world", "SOURCES": '[{"authorized":true}]', "B": "plain"})
            path.write_text("A=$(touch unsafe)\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                runtime.read_env(path)

    def test_cli_output_never_contains_secret_values_and_does_not_verify_services(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            backend_path, mobile_path = Path(directory) / "backend.env", Path(directory) / "mobile.env"
            backend_path.write_text("\n".join(f"{key}={value}" for key, value in self.backend.items()), encoding="utf-8")
            mobile_path.write_text("\n".join(f"{key}={value}" for key, value in self.mobile.items()), encoding="utf-8")
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                status = runtime.main(["--backend-env", str(backend_path), "--mobile-env", str(mobile_path), "--json"])
            self.assertEqual(status, 0)
            output = stdout.getvalue()
            for key in ("SUPABASE_SERVICE_ROLE_KEY", "GOOGLE_CLIENT_SECRET", "TOKEN_ENCRYPTION_KEY"):
                self.assertNotIn(self.backend[key], output)
            report = json.loads(output)
            self.assertTrue(report["configuration_valid"])
            self.assertFalse(report["services_verified"])
            self.assertFalse(report["mail_operation_performed"])


if __name__ == "__main__":
    unittest.main()

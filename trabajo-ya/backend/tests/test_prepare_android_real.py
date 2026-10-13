"""Offline contracts for APK configuration; no cloud, HTTP or APK build occurs."""
from contextlib import redirect_stderr, redirect_stdout
import base64
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError


PROJECT_ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("prepare_android_real", PROJECT_ROOT / "scripts/prepare_android_real.py")
prepare = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = prepare
spec.loader.exec_module(prepare)


def public_config():
    return {"backend_url": "https://trabajo-ya-123.us-central1.run.app", "supabase_url": "https://projectreference.supabase.co", "supabase_public_key": "sb_publishable_offlineTestKeyOnly123"}


def jwt(role):
    def encode(data):
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    return f"{encode({'alg': 'HS256'})}.{encode({'role': role})}.testsignature"


class PrepareAndroidRealTests(unittest.TestCase):
    def make_mobile(self, root, config=None):
        mobile = Path(root) / "mobile"
        mobile.mkdir()
        (mobile / "services.public.json").write_text(json.dumps(config or public_config()), encoding="utf-8")
        (mobile / "app.json").write_text(json.dumps({"expo": {"name": "Trabajo YA", "version": "9.8.7", "android": {"package": prepare.ANDROID_PACKAGE, "versionCode": 98}}}), encoding="utf-8")
        return mobile

    def test_example_stays_unconfigured_until_actual_services_are_entered(self):
        example = PROJECT_ROOT / "mobile/services.public.json.example"
        self.assertEqual(set(json.loads(example.read_text())), prepare.PUBLIC_FIELDS)
        with self.assertRaises(prepare.ConfigurationError):
            prepare.load_public_services(example)

    def test_publishable_and_legacy_anon_keys_are_public_only(self):
        self.assertEqual(prepare.public_supabase_key(public_config()["supabase_public_key"]), public_config()["supabase_public_key"])
        self.assertEqual(prepare.public_supabase_key(jwt("anon")), jwt("anon"))
        for key in (jwt("service_role"), jwt("authenticated"), "sb_secret_privateValueNeverPrint", "gsk_privateValueNeverPrint", "", "sb_publishable_short", "not-a-jwt", "sb_publishable_thisHasALineBreak\nFORGED_VAR=secret"):
            with self.subTest(key_kind=key.split("_")[0]):
                with self.assertRaises(prepare.ConfigurationError) as error:
                    prepare.public_supabase_key(key)
                self.assertNotIn(key or "PLACEHOLDER_NOT_PRESENT", str(error.exception))

    def test_private_extra_fields_are_rejected_without_values_in_errors(self):
        for field in ("ai_api_key", "service_role", "google_client_secret", "gmail_refresh_token", "mail_send_enabled", "demo"):
            with tempfile.TemporaryDirectory() as directory, self.subTest(field=field):
                config = public_config()
                config[field] = "PRIVATE_VALUE_MUST_NOT_APPEAR"
                mobile = self.make_mobile(directory, config)
                output = io.StringIO()
                errors = io.StringIO()
                with redirect_stdout(output), redirect_stderr(errors):
                    result = prepare.main(["--mobile-dir", str(mobile)])
                self.assertEqual(result, 1)
                self.assertNotIn("PRIVATE_VALUE_MUST_NOT_APPEAR", output.getvalue() + errors.getvalue())

    def test_public_urls_reject_local_example_credentials_and_unsafe_forms(self):
        invalid = ["http://real.run.app", "https://localhost", "https://10.0.2.2", "https://127.1", "https://127.0.0.1", "https://192.168.2.3", "https://172.20.4.1", "https://169.254.169.254", "https://[::1]", "https://[fd00::1]", "https://0.0.0.0", "https://demo.example.com", "https://project.test", "https://backend.example", "https://backend.internal", "https://backend", "https://user:PRIVATE@real.run.app", "https://real.run.app?key=PRIVATE", "https://real.run.app#PRIVATE", "https://real.run.app/api", "https://real.run.app:8000", "https://real.run.app/\nFORGED_VAR=PRIVATE", " https://real.run.app"]
        for url in invalid:
            with self.subTest(url_kind=url.split(":")[0]):
                with self.assertRaises(prepare.ConfigurationError) as error:
                    prepare.public_https_url("backend_url", url)
                self.assertNotIn("PRIVATE", str(error.exception))
        for url in ("https://real.run.app", "https://real.run.app/", "https://project.supabase.co", "https://backend.mycompany.com"):
            self.assertEqual(prepare.public_https_url("backend_url", url), url.rstrip("/"))

    def test_duplicate_missing_and_oversized_json_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "services.json"
            for raw in ('{"backend_url": "one", "backend_url": "two"}', '{}', '[]', '{not valid', 'x' * (prepare.MAX_CONFIG_BYTES + 1)):
                path.write_text(raw, encoding="utf-8")
                with self.assertRaises(prepare.ConfigurationError):
                    prepare.load_public_services(path)
            path.unlink()
            with self.assertRaises(prepare.ConfigurationError):
                prepare.load_public_services(path)

    def test_github_env_forces_real_and_derives_version_from_app_json(self):
        with tempfile.TemporaryDirectory() as directory:
            mobile = self.make_mobile(directory)
            destination = Path(directory) / "github-env"
            destination.write_text("EXISTING_PUBLIC=value\n")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(prepare.main(["--mobile-dir", str(mobile), "--github-env", str(destination)]), 0)
            variables = dict(line.split("=", 1) for line in destination.read_text().splitlines())
            self.assertEqual(variables["EXISTING_PUBLIC"], "value")
            self.assertEqual(variables["EXPO_PUBLIC_DEMO_MODE"], "false")
            self.assertEqual(variables["TRABAJO_YA_BUILD_MODE"], "real")
            self.assertEqual(variables["TRABAJO_YA_APK_FILE"], "Trabajo-YA-9.8.7-real.apk")
            self.assertEqual(variables["TRABAJO_YA_RELEASE_TAG"], "trabajo-ya-v9.8.7-real")
            self.assertEqual(variables["TRABAJO_YA_VERSION_CODE"], "98")
            self.assertEqual(variables["EXPO_PUBLIC_SUPABASE_ANON_KEY"], "")
            self.assertEqual(variables["EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY"], public_config()["supabase_public_key"])

    def test_local_env_contains_public_values_and_no_console_key_output(self):
        with tempfile.TemporaryDirectory() as directory:
            config = public_config()
            config["supabase_public_key"] = jwt("anon")
            mobile = self.make_mobile(directory, config)
            destination = mobile / ".env.local"
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(prepare.main(["--mobile-dir", str(mobile), "--env-file", str(destination)]), 0)
            self.assertIn("EXPO_PUBLIC_SUPABASE_ANON_KEY=" + config["supabase_public_key"], destination.read_text())
            self.assertNotIn(config["supabase_public_key"], output.getvalue())
            self.assertNotIn("verified=true", output.getvalue())

    def test_incomplete_services_fail_before_probe_or_environment_write(self):
        with tempfile.TemporaryDirectory() as directory:
            config = public_config()
            config["backend_url"] = ""
            mobile = self.make_mobile(directory, config)
            destination = mobile / ".env.local"
            with patch.object(prepare, "probe_health") as probe, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                result = prepare.main(["--mobile-dir", str(mobile), "--check-health", "--env-file", str(destination)])
            self.assertEqual(result, 1)
            self.assertFalse(destination.exists())
            probe.assert_not_called()

    def test_health_requires_configured_real_ai_and_supabase_not_merely_ok(self):
        cases = [{"status": "ok"}, {"status": "ok", "integrations": {"supabase": "configured", "ai": "demo"}}, {"status": "ok", "integrations": {"supabase": "not_configured", "ai": "configured_unverified"}}, {"status": "error", "integrations": {"supabase": "configured", "ai": "configured_unverified"}}]
        for health in cases:
            response = Mock(status=200)
            response.read.return_value = json.dumps(health).encode()
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            with patch.object(prepare, "build_opener") as opener, self.subTest(health=health):
                opener.return_value.open.return_value = response
                with self.assertRaises(prepare.ConfigurationError):
                    prepare.probe_health(public_config()["backend_url"])

    def test_health_probe_never_sends_auth_and_does_not_claim_ai_verified(self):
        response = Mock(status=200)
        response.read.return_value = json.dumps({"status": "ok", "integrations": {"supabase": "configured", "ai": "configured_unverified"}}).encode()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch.object(prepare, "build_opener") as opener:
            opener.return_value.open.return_value = response
            self.assertIsNone(prepare.probe_health(public_config()["backend_url"]))
            args, kwargs = opener.return_value.open.call_args
            request = args[0]
            self.assertEqual(request.full_url, public_config()["backend_url"] + "/health")
            self.assertFalse(request.has_header("Authorization"))
            self.assertNotIn("supabase", str(request.header_items()).lower())
            self.assertEqual(kwargs["timeout"], prepare.HEALTH_PROBE_TIMEOUT_SECONDS)
            self.assertIsInstance(opener.call_args.args[0], prepare.NoRedirect)

    def test_redirect_and_provider_failure_are_redacted_and_do_not_write_env(self):
        with tempfile.TemporaryDirectory() as directory:
            mobile = self.make_mobile(directory)
            destination = mobile / ".env.local"
            error = HTTPError("https://PRIVATE", 302, "PRIVATE_RESPONSE", {}, None)
            with patch.object(prepare, "build_opener") as opener, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as errors:
                opener.return_value.open.side_effect = error
                result = prepare.main(["--mobile-dir", str(mobile), "--check-health", "--env-file", str(destination)])
            self.assertEqual(result, 1)
            self.assertFalse(destination.exists())
            self.assertNotIn("PRIVATE", errors.getvalue())
            self.assertIsNone(prepare.NoRedirect().redirect_request(None, None, 302, "", {}, "https://localhost"))

    def test_invalid_app_metadata_cannot_inject_artifact_or_release_names(self):
        with tempfile.TemporaryDirectory() as directory:
            mobile = self.make_mobile(directory)
            path = mobile / "app.json"
            original = json.loads(path.read_text())
            for field, value in (("version", "1.2.3/PRIVATE"), ("version", "1.2.3\nFORGED_VAR=secret"), ("name", "Another app")):
                data = json.loads(json.dumps(original))
                data["expo"][field] = value
                path.write_text(json.dumps(data))
                with self.assertRaises(prepare.ConfigurationError):
                    prepare.app_metadata(mobile)
            data = json.loads(json.dumps(original))
            data["expo"]["android"]["versionCode"] = True
            path.write_text(json.dumps(data))
            with self.assertRaises(prepare.ConfigurationError):
                prepare.app_metadata(mobile)

    def test_workflow_checks_services_before_dependencies_and_never_uses_demo(self):
        workflow = (PROJECT_ROOT / ".github/workflows/android-real.yml").read_text()
        preflight = workflow.index("scripts/prepare_android_real.py")
        self.assertLess(preflight, workflow.index("actions/setup-node@"))
        self.assertLess(preflight, workflow.index("android-actions/setup-android@"))
        self.assertLess(workflow.index("configure.validateRealBuild(process.env)"), workflow.index("npx expo prebuild"))
        self.assertIn("EXPO_PUBLIC_DEMO_MODE: 'false'", workflow)
        self.assertIn("TRABAJO_YA_BUILD_MODE: real", workflow)
        self.assertNotIn("EXPO_PUBLIC_DEMO_MODE: 'true'", workflow)
        self.assertIn('--prerelease --target "$GITHUB_SHA"', workflow)
        self.assertIn("apksigner\" verify", workflow)
        self.assertIn("aapt\" dump badging", workflow)
        self.assertNotIn("Trabajo-YA-0.3", workflow)


if __name__ == "__main__":
    unittest.main()

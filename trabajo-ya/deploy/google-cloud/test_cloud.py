"""Local deployment safety checks; never invoke real gcloud or cloud resources."""
import base64
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import cloud


def token(role):
    payload = base64.urlsafe_b64encode(json.dumps({"role": role}).encode()).decode().rstrip("=")
    return f"example.{payload}.test-only"


def config():
    return cloud.validate_config({
        "project_id": "trabajo-ya-pruebas", "supabase_url": "https://abcxyz.supabase.co",
        "supabase_anon_key": token("anon"),
        "google_client_id": "123456-pruebas.apps.googleusercontent.com",
    })


FEED = [{"id": "empresa", "url": "https://empleos.empresa.com/feed.json?token=never-print-this",
         "authorized": True, "recipient_verification": "source_attestation"}]


class FakeCloud(cloud.Cloud):
    def __init__(self, current=None):
        super().__init__(current or config())
        self.calls = []
        self.env_files = []
        self.payload = json.dumps(FEED)
        self.enabled = False
        self.schedule_state = None
        self.known_exclusion = False
        self.probe_failure = False
        self.live_service = {"status": {
            "latestReadyRevisionName": "trabajo-ya-api-00001-ready",
            "latestCreatedRevisionName": "trabajo-ya-api-00001-ready",
            "conditions": [{"type": "Ready", "status": "True"}],
            "traffic": [{"revisionName": "trabajo-ya-api-00001-ready", "percent": 100}],
        }}
        self.live_revision = {"spec": {"containers": [{
            "image": "us-central1-docker.pkg.dev/trabajo-ya-pruebas/trabajo-ya/backend@sha256:" + "b" * 64,
            "env": [
                {"name": "AI_PROVIDER", "value": "openai_compatible"},
                {"name": "AI_BASE_URL", "value": cloud.GROQ_AI["ai_base_url"]},
                {"name": "AI_MODEL", "value": cloud.GROQ_AI["ai_model"]},
                {"name": "AI_API_KEY", "valueFrom": {"secretKeyRef": {
                    "name": cloud.SECRET_NAMES["AI_API_KEY"], "key": "3"}}},
                {"name": "SUPABASE_SERVICE_ROLE_KEY", "valueFrom": {"secretKeyRef": {
                    "name": cloud.SECRET_NAMES["SUPABASE_SERVICE_ROLE_KEY"], "key": "7"}}},
                {"name": "GOOGLE_CLIENT_SECRET", "valueFrom": {"secretKeyRef": {
                    "name": cloud.SECRET_NAMES["GOOGLE_CLIENT_SECRET"], "key": "7"}}},
                {"name": "MAIL_SEND_ENABLED", "value": "true"},
            ],
        }]}}

    def run(self, args, *, data=None):
        self.calls.append((args, data))
        for arg in args:
            if arg.startswith("--env-vars-file="):
                self.env_files.append(json.loads(Path(arg.split("=", 1)[1]).read_text()))
        if args[:3] == ["secrets", "versions", "list"]:
            return json.dumps([{"name": f"projects/project/secrets/{args[3]}/versions/7", "state": "ENABLED"}])
        if args[:3] == ["secrets", "versions", "access"]:
            return self.payload
        if args[:4] == ["artifacts", "docker", "images", "describe"]:
            return "sha256:" + "a" * 64
        if args[:3] == ["run", "services", "describe"]:
            if "--format=json" in args:
                return json.dumps(self.live_service)
            return "https://trabajo-ya-api-abcd.us-central1.run.app"
        if args[:3] == ["run", "revisions", "describe"]:
            return json.dumps(self.live_revision)
        if args[:3] == ["run", "jobs", "execute"] and args[3].endswith("-ai-check") and self.probe_failure:
            raise cloud.SetupError("La comprobación real de IA terminó con error.")
        if args[:3] == ["run", "jobs", "describe"]:
            return json.dumps({"spec": {"template": {"spec": {"template": {"spec": {"containers": [{"env": [
                {"name": "MAIL_SEND_ENABLED", "value": str(self.enabled).lower()},
                {"name": "AUTHORIZED_JOB_FEEDS", "valueFrom": {"secretKeyRef": {
                    "name": cloud.SECRET_NAMES["AUTHORIZED_JOB_FEEDS"], "key": "7"}}},
            ]}]}}}}}})
        if args[:3] == ["logging", "sinks", "describe"]:
            exclusions = [{"name": "trabajo-ya-api-oauth-callback", "disabled": True}] if self.known_exclusion else []
            return json.dumps({"exclusions": exclusions, "filter": "existing filter must stay"})
        if args[:3] == ["scheduler", "jobs", "list"] and self.schedule_state:
            return json.dumps([{"name": "projects/project/locations/us-central1/jobs/trabajo-ya-cada-15-min",
                                "state": self.schedule_state}])
        if "list" in args:
            return "[]"
        return ""


class DeploymentSafetyTests(unittest.TestCase):
    def test_setup_without_cloud_shell_never_creates_config_or_resources(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "public.json"
            with patch.object(cloud.shutil, "which", return_value=None), patch.object(cloud, "Cloud") as remote:
                with self.assertRaises(cloud.SetupError):
                    cloud.setup(target)
            remote.assert_not_called()
            self.assertFalse(target.exists())

    def test_failed_setup_preflight_never_mutates_cloud(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "public.json"
            target.write_text(json.dumps(config()))
            remote = MagicMock()
            remote.preflight.side_effect = cloud.SetupError("Facturación no habilitada.")
            with patch.object(cloud.shutil, "which", return_value="gcloud"), patch.object(cloud, "Cloud", return_value=remote):
                with self.assertRaises(cloud.SetupError):
                    cloud.setup(target)
            remote.prepare.assert_not_called()
            remote.setup_secrets.assert_not_called()
            remote.deploy.assert_not_called()
            remote.export_mobile.assert_not_called()

    def test_setup_never_activates_mail_or_scheduler_and_preserves_secrets(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "public.json"
            target.write_text(json.dumps(config()))
            fake = FakeCloud()
            with patch.object(cloud.shutil, "which", return_value="gcloud"), \
                    patch.object(cloud, "Cloud", return_value=fake), \
                    patch.object(fake, "preflight"), patch.object(cloud, "GENERATED", Path(folder) / "generated"), \
                    patch.object(cloud, "read_secret") as read, redirect_stdout(io.StringIO()):
                cloud.setup(target)
            read.assert_not_called()
            self.assertFalse(any(args[:3] in (["scheduler", "jobs", "create"], ["scheduler", "jobs", "resume"])
                                 or "--update-env-vars=MAIL_SEND_ENABLED=true" in args for args, _ in fake.calls))
            self.assertTrue((Path(folder) / "generated/mobile.env").exists())

    def test_mobile_export_contains_only_public_values_and_keeps_existing_mobile_files(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / "generated"
            user_settings = Path(folder) / ".env.local"
            user_settings.write_text("keep my existing settings")
            fake = FakeCloud()
            with patch.object(cloud, "GENERATED", directory), redirect_stdout(io.StringIO()):
                exported = fake.export_mobile()
            lines = [line for line in exported.read_text().splitlines() if line and not line.startswith("#")]
            values = {line.split("=", 1)[0]: json.loads(line.split("=", 1)[1]) for line in lines}
            self.assertEqual(set(values), {"EXPO_PUBLIC_DEMO_MODE", "EXPO_PUBLIC_BACKEND_URL", "EXPO_PUBLIC_SUPABASE_URL", "EXPO_PUBLIC_SUPABASE_ANON_KEY"})
            self.assertEqual(values["EXPO_PUBLIC_DEMO_MODE"], "false")
            self.assertFalse(set(values).intersection(cloud.SECRET_NAMES))
            self.assertEqual(user_settings.read_text(), "keep my existing settings")

    def test_public_config_rejects_private_key_and_unknown_secret_fields(self):
        for change in ({"supabase_anon_key": token("service_role")},
                       {"supabase_anon_key": "sb_secret_dont-store-private"},
                       {"google_client_secret": "dont-store-private"}):
            with self.subTest(change=list(change)), self.assertRaises(cloud.SetupError):
                cloud.validate_config(config() | change)

    def test_production_config_rejects_placeholders_and_private_ia_urls(self):
        for change in ({"project_id": "tu-proyecto-google"},
                       {"supabase_url": "https://tu-proyecto.supabase.co"},
                       {"google_client_id": "TU_CLIENT_ID.apps.googleusercontent.com"},
                       {"ai_provider": "ollama", "ai_base_url": "https://127.0.0.1", "ai_model": "chosen"},
                       {"ai_provider": "openai_compatible", "ai_base_url": "https://user:password@ia.empresa.com/v1", "ai_model": "chosen"}):
            with self.subTest(change=list(change)), self.assertRaises(cloud.SetupError):
                cloud.validate_config(config() | change)

    def test_sources_require_authorized_unique_public_integrations(self):
        cloud.validate_secret("AUTHORIZED_JOB_FEEDS", json.dumps(FEED))
        cloud.validate_secret("AUTHORIZED_JOB_FEEDS", "[]")  # Allowed only during preparation.
        for payload in ([FEED[0], FEED[0]], [FEED[0] | {"authorized": False}],
                        [FEED[0] | {"id": 42}], [FEED[0] | {"url": "https://192.168.1.5/feed"}],
                        [FEED[0] | {"url": "https://metadata.google.internal/feed"}],
                        [FEED[0] | {"url": "https://jobs.partner.example/feed"}]):
            with self.subTest(payload=payload), self.assertRaises(cloud.SetupError):
                cloud.validate_secret("AUTHORIZED_JOB_FEEDS", json.dumps(payload))

    def test_getpass_refuses_non_tty_before_reading_credentials(self):
        with patch.object(cloud.sys.stdin, "isatty", return_value=False), patch.object(cloud.getpass, "getpass") as prompt:
            with self.assertRaises(cloud.SetupError):
                cloud.read_secret("private key")
            prompt.assert_not_called()

    def test_configure_rejects_misplaced_service_key_without_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "cloud-config.json"
            with patch.object(cloud.sys.stdin, "isatty", return_value=True), \
                    patch("builtins.input", side_effect=["trabajo-ya-pruebas", "https://abcxyz.supabase.co",
                                                       "123-pruebas.apps.googleusercontent.com"]), \
                    patch.object(cloud, "read_secret", return_value=token("service_role")):
                with self.assertRaises(cloud.SetupError):
                    cloud.configure(output)
            self.assertFalse(output.exists())

    def test_existing_cipher_and_secret_versions_are_preserved(self):
        fake = FakeCloud()
        with patch.object(cloud, "read_secret") as prompt, redirect_stdout(io.StringIO()):
            fake.setup_secrets()
        prompt.assert_not_called()
        self.assertFalse(any(args[:3] == ["secrets", "versions", "add"] for args, _ in fake.calls))
        with self.assertRaises(cloud.SetupError):
            fake.set_secret("TOKEN_ENCRYPTION_KEY")

    def test_secret_update_uses_stdin_and_never_prints_value(self):
        fake = FakeCloud()
        private_payload = json.dumps(FEED)
        log = io.StringIO()
        with patch.object(cloud, "read_secret", return_value=private_payload), redirect_stdout(log):
            fake.set_secret("AUTHORIZED_JOB_FEEDS")
        args, data = fake.calls[-1]
        self.assertEqual(data, private_payload)
        self.assertIn("--data-file=-", args)
        self.assertNotIn("never-print-this", " ".join(args) + log.getvalue())

    def test_api_and_worker_pin_same_image_and_secret_versions_without_auto_schedule(self):
        current = config() | {"ai_provider": "openai_compatible", "ai_base_url": "https://ia.empresa.com/v1",
                              "ai_model": "chosen", "ai_api_key_required": True}
        fake = FakeCloud(cloud.validate_config(current))
        with redirect_stdout(io.StringIO()):
            fake.deploy()
        api = next(args for args, _ in fake.calls if args[:2] == ["run", "deploy"])
        worker = next(args for args, _ in fake.calls if args[:3] == ["run", "jobs", "deploy"])
        def value(args, key):
            return next(arg.split("=", 1)[1] for arg in args if arg.startswith(key + "="))
        self.assertEqual(value(api, "--image"), value(worker, "--image"))
        self.assertIn("@sha256:", value(api, "--image"))
        api_refs = dict(item.split("=", 1) for item in value(api, "--set-secrets").split(","))
        worker_refs = dict(item.split("=", 1) for item in value(worker, "--set-secrets").split(","))
        callback_update = next(args for args, _ in fake.calls if args[:3] == ["run", "services", "update"])
        self.assertEqual(value(callback_update, "--set-secrets"), value(api, "--set-secrets"))
        self.assertEqual(worker_refs, {key: val for key, val in api_refs.items() if key != "AI_API_KEY"})
        self.assertTrue(all(ref.endswith(":7") for ref in api_refs.values()))
        self.assertNotIn("AI_API_KEY", worker_refs)
        self.assertIn("--no-access-log", value(api, "--args"))
        self.assertIn("--max-retries=0", worker)
        self.assertIn("--task-timeout=1200s", worker)
        self.assertFalse(any(args[:3] == ["scheduler", "jobs", "create"] for args, _ in fake.calls))
        self.assertTrue(all(row["MAIL_SEND_ENABLED"] == "false" and row["WORKER_BATCH_SIZE"] == "1" for row in fake.env_files))
        self.assertTrue(all(not set(row).intersection(cloud.SECRET_NAMES) for row in fake.env_files))
        self.assertEqual(fake.env_files[-1]["GOOGLE_REDIRECT_URI"],
                         "https://trabajo-ya-api-abcd.us-central1.run.app/api/mail/google/callback")

    def test_redeployment_pauses_active_schedule_before_build_and_never_resumes(self):
        fake = FakeCloud()
        fake.schedule_state = "ENABLED"
        with redirect_stdout(io.StringIO()):
            fake.deploy()
        calls = [args[:3] for args, _ in fake.calls]
        build_index = next(index for index, call in enumerate(calls) if call[:2] == ["builds", "submit"])
        self.assertLess(calls.index(["scheduler", "jobs", "pause"]), build_index)
        self.assertNotIn(["scheduler", "jobs", "resume"], calls)

    def test_source_upload_excludes_private_files_even_without_ignore_rules(self):
        with tempfile.TemporaryDirectory() as folder:
            backend = Path(folder)
            (backend / "app" / "services").mkdir(parents=True)
            (backend / "app" / "__pycache__").mkdir()
            for path in ("Dockerfile", "requirements.txt", "app/main.py", "app/worker.py", "app/services/__init__.py"):
                (backend / path).write_text("public code")
            for path in (".env", "app/cv.pdf", "app/tokens.json", "app/notes.txt", "app/__pycache__/cached.py"):
                (backend / path).write_text("private contents")
            with patch.object(cloud, "BACKEND", backend), cloud.backend_source() as staged:
                included = {str(path.relative_to(staged)) for path in staged.rglob("*") if path.is_file()}
                self.assertEqual(included, {"Dockerfile", "requirements.txt", "app/main.py", "app/worker.py", "app/services/__init__.py"})
            self.assertFalse(staged.exists())

    def test_callback_log_exclusion_preserves_other_sink_filters(self):
        fake = FakeCloud()
        fake.known_exclusion = True
        fake.exclude_oauth_logs()
        args = fake.calls[-1][0]
        flag = next(arg for arg in args if arg.startswith("--update-exclusion="))
        self.assertIn('resource.labels.service_name="trabajo-ya-api"', flag)
        self.assertIn('/api/mail/google/callback', flag)
        self.assertTrue(flag.endswith(",disabled="))
        self.assertFalse(any(arg.startswith(("--log-filter", "--clear-exclusions", "--remove-exclusions")) for arg in args))

    def test_empty_deployed_feed_blocks_mail_enable_and_scheduler(self):
        for action in (lambda fake: fake.set_mail(True), lambda fake: fake.scheduler("enable"),
                       lambda fake: fake.scheduler("resume")):
            fake = FakeCloud()
            fake.payload = "[]"
            with self.assertRaises(cloud.SetupError):
                action(fake)
            self.assertFalse(any("--update-env-vars=MAIL_SEND_ENABLED=true" in args for args, _ in fake.calls))
            self.assertFalse(any(args[:3] in (["scheduler", "jobs", "create"], ["scheduler", "jobs", "resume"]) for args, _ in fake.calls))

    def test_feed_check_uses_actual_pinned_version_without_logging_private_urls(self):
        fake = FakeCloud()
        output = io.StringIO()
        with redirect_stdout(output):
            fake.scheduler("enable")
        access = next(args for args, _ in fake.calls if args[:3] == ["secrets", "versions", "access"])
        self.assertEqual(access[3], "7")
        scheduler = next(args for args, _ in fake.calls if args[:3] == ["scheduler", "jobs", "create"])
        self.assertIn("--schedule=*/15 * * * *", scheduler)
        self.assertIn("--time-zone=Etc/UTC", scheduler)
        self.assertTrue(any(arg.startswith("--oauth-service-account-email=") for arg in scheduler))
        self.assertNotIn("never-print-this", output.getvalue())

    def test_manual_worker_requires_explicit_confirmation_when_mail_already_enabled(self):
        fake = FakeCloud()
        fake.enabled = True
        with self.assertRaises(cloud.SetupError):
            fake.test_worker()
        self.assertFalse(any(args[:3] == ["run", "jobs", "execute"] for args, _ in fake.calls))
        with redirect_stdout(io.StringIO()):
            fake.test_worker(allow_sending=True)
        self.assertTrue(any(args[:3] == ["run", "jobs", "execute"] for args, _ in fake.calls))

    def test_activation_without_confirmation_does_not_call_gcloud(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "public.json"
            path.write_text(json.dumps(config()))
            with patch.object(cloud.Cloud, "preflight") as check, patch.object(cloud.Cloud, "run") as run, \
                    patch.object(cloud.sys, "stderr", io.StringIO()):
                self.assertEqual(cloud.main(["scheduler-enable", "--config", str(path)]), 1)
            check.assert_not_called()
            run.assert_not_called()

    def test_ai_activation_checks_access_before_changing_public_config(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cloud-config.json"
            original = json.dumps(config())
            path.write_text(original)
            remote = MagicMock()
            remote.preflight.side_effect = cloud.SetupError("Sin acceso al proyecto.")
            with patch.object(cloud, "Cloud", return_value=remote):
                with self.assertRaises(cloud.SetupError):
                    cloud.activate_ai(path)
            self.assertEqual(path.read_text(), original)
            remote.prepare.assert_not_called()
            remote.setup_secrets.assert_not_called()
            remote.deploy.assert_not_called()
            remote.test_ai.assert_not_called()

    def test_ai_activation_requires_config_and_never_creates_accounts(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(cloud, "Cloud") as remote:
            with self.assertRaises(cloud.SetupError):
                cloud.activate_ai(Path(folder) / "missing.json")
            remote.assert_not_called()

    def test_ai_activation_stores_only_public_groq_settings_and_preserves_private_versions(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cloud-config.json"
            path.write_text(json.dumps(config()))
            fake = FakeCloud()
            def create_remote(settings):
                fake.config = settings
                return fake
            output = io.StringIO()
            with patch.object(cloud, "Cloud", side_effect=create_remote), \
                    patch.object(fake, "preflight") as check, \
                    patch.object(cloud, "GENERATED", Path(folder) / "generated"), \
                    patch.object(cloud, "read_secret") as prompt, redirect_stdout(output):
                cloud.activate_ai(path)
            check.assert_called_once()
            saved = json.loads(path.read_text())
            self.assertTrue(all(saved[key] == value for key, value in cloud.GROQ_AI.items()))
            self.assertEqual(saved["supabase_anon_key"], config()["supabase_anon_key"])
            self.assertFalse(set(saved).intersection(cloud.SECRET_NAMES))
            prompt.assert_not_called()
            self.assertFalse(any(args[:3] == ["secrets", "versions", "add"] for args, _ in fake.calls))
            self.assertFalse(any(args[:3] in (["scheduler", "jobs", "create"], ["scheduler", "jobs", "resume"])
                                 or "--update-env-vars=MAIL_SEND_ENABLED=true" in args for args, _ in fake.calls))
            self.assertIn("IA verificada mediante una respuesta real", output.getvalue())

    def test_ai_probe_uses_live_revision_image_key_and_isolates_mail_and_database(self):
        fake = FakeCloud()  # Local config says demo; the deployed API is real.
        output = io.StringIO()
        with redirect_stdout(output):
            fake.test_ai()
        probe = next(args for args, _ in fake.calls if args[:3] == ["run", "jobs", "deploy"])
        self.assertIn("--image=" + fake.live_revision["spec"]["containers"][0]["image"], probe)
        self.assertIn("--set-secrets=AI_API_KEY=trabajo-ya-ai-api-key:3", probe)
        self.assertIn("--args=-m,app.check_ai", probe)
        self.assertIn("--max-retries=0", probe)
        self.assertIn("--task-timeout=180s", probe)
        self.assertEqual(fake.env_files, [{"AI_PROVIDER": "openai_compatible",
                                          "AI_BASE_URL": cloud.GROQ_AI["ai_base_url"],
                                          "AI_MODEL": cloud.GROQ_AI["ai_model"]}])
        self.assertFalse(any(args[:3] == ["secrets", "versions", "access"] for args, _ in fake.calls))
        self.assertFalse(any(args[:3] in (["scheduler", "jobs", "create"], ["scheduler", "jobs", "resume"],
                                         ["run", "services", "update"])
                                 for args, _ in fake.calls))
        self.assertIn("IA verificada mediante una respuesta real", output.getvalue())

    def test_failed_real_ai_probe_never_claims_it_is_verified(self):
        fake = FakeCloud()
        fake.probe_failure = True
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(cloud.SetupError):
            fake.test_ai()
        self.assertNotIn("IA verificada", output.getvalue())

    def test_probe_rejects_demo_unpinned_or_exposed_keys_before_job_creation(self):
        for change in ({"AI_PROVIDER": {"name": "AI_PROVIDER", "value": "demo"}},
                       {"AI_API_KEY": {"name": "AI_API_KEY", "value": "never-store-me"}},
                       {"AI_API_KEY": {"name": "AI_API_KEY", "valueFrom": {"secretKeyRef": {
                           "name": cloud.SECRET_NAMES["AI_API_KEY"], "key": "latest"}}}},
                       {"AI_BASE_URL": {"name": "AI_BASE_URL", "value": "https://127.0.0.1"}}):
            with self.subTest(fields=list(change)):
                fake = FakeCloud()
                container = fake.live_revision["spec"]["containers"][0]
                container["env"] = [change.get(row["name"], row) for row in container["env"]]
                with self.assertRaises(cloud.SetupError):
                    fake.test_ai()
                self.assertFalse(any(args[:3] == ["run", "jobs", "deploy"] for args, _ in fake.calls))

    def test_probe_rejects_unready_split_or_mutable_revision(self):
        for scenario in ("unready", "old-ready", "split", "tag"):
            with self.subTest(scenario=scenario):
                fake = FakeCloud()
                status = fake.live_service["status"]
                if scenario == "unready":
                    status["conditions"][0]["status"] = "False"
                elif scenario == "old-ready":
                    status["latestCreatedRevisionName"] = "trabajo-ya-api-00002-failed"
                elif scenario == "split":
                    status["traffic"][0]["percent"] = 50
                else:
                    fake.live_revision["spec"]["containers"][0]["image"] = "repository/backend:latest"
                with self.assertRaises(cloud.SetupError):
                    fake.test_ai()
                self.assertFalse(any(args[:3] == ["run", "jobs", "deploy"] for args, _ in fake.calls))

    def test_probe_can_read_v2_revision_environment_and_versioned_reference(self):
        fake = FakeCloud()
        container = fake.live_revision["spec"]["containers"][0]
        for row in container["env"]:
            if row["name"] == "AI_API_KEY":
                row["valueSource"] = {"secretKeyRef": {"secret": cloud.SECRET_NAMES["AI_API_KEY"], "version": "3"}}
                del row["valueFrom"]
        fake.live_revision = {"containers": [container]}
        with redirect_stdout(io.StringIO()):
            fake.test_ai()
        probe = next(args for args, _ in fake.calls if args[:3] == ["run", "jobs", "deploy"])
        self.assertIn("--set-secrets=AI_API_KEY=trabajo-ya-ai-api-key:3", probe)

    def test_ai_key_creation_is_hidden_and_does_not_rotate_existing_cipher(self):
        fake = FakeCloud(cloud.validate_config(config() | cloud.GROQ_AI))
        original = fake.latest_version
        fake.latest_version = lambda name: None if name == cloud.SECRET_NAMES["AI_API_KEY"] else original(name)
        output = io.StringIO()
        with patch.object(cloud, "read_secret", return_value="gsk_test-private-never-echo") as prompt, redirect_stdout(output):
            fake.setup_secrets()
        prompt.assert_called_once_with("Clave privada del proveedor IA")
        additions = [(args, data) for args, data in fake.calls if args[:3] == ["secrets", "versions", "add"]]
        self.assertEqual(len(additions), 1)
        args, data = additions[0]
        self.assertEqual(args[3], cloud.SECRET_NAMES["AI_API_KEY"])
        self.assertEqual(data, "gsk_test-private-never-echo")
        self.assertNotIn(data, " ".join(args) + output.getvalue())

    def test_test_ai_command_runs_preflight_and_failed_job_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cloud-config.json"
            path.write_text(json.dumps(config()))
            fake = FakeCloud()
            fake.probe_failure = True
            with patch.object(cloud, "Cloud", return_value=fake), patch.object(fake, "preflight") as check, \
                    patch.object(cloud.sys, "stderr", io.StringIO()), redirect_stdout(io.StringIO()):
                result = cloud.main(["test-ai", "--config", str(path)])
            check.assert_called_once()
            self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()

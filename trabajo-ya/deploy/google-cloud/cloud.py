#!/usr/bin/env python3
"""Cloud Shell deployment without third-party dependencies or plaintext secrets.

Only explicit subcommands mutate Google Cloud. Config is public JSON, never
executed as shell code. Secrets enter getpass/stdin and are stored in Secret
Manager; versions and image digests are pinned consistently for API and worker.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import getpass
import ipaddress
import json
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlparse
import warnings


HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1] / "backend"
GENERATED = HERE / "generated"
APIS = (
    "run.googleapis.com", "cloudbuild.googleapis.com",
    "artifactregistry.googleapis.com", "secretmanager.googleapis.com",
    "cloudscheduler.googleapis.com", "iam.googleapis.com",
    "logging.googleapis.com", "gmail.googleapis.com",
)
SECRET_NAMES = {
    "SUPABASE_SERVICE_ROLE_KEY": "trabajo-ya-supabase-service-role",
    "GOOGLE_CLIENT_SECRET": "trabajo-ya-google-client-secret",
    "TOKEN_ENCRYPTION_KEY": "trabajo-ya-token-encryption-key",
    "AUTHORIZED_JOB_FEEDS": "trabajo-ya-authorized-job-feeds",
    "AI_API_KEY": "trabajo-ya-ai-api-key",
}
CONFIG_KEYS = {
    "project_id", "region", "api_name", "worker_name", "scheduler_name",
    "artifact_repository", "supabase_url", "supabase_anon_key",
    "google_client_id", "google_redirect_uri", "cors_origins", "ai_provider",
    "ai_base_url", "ai_model", "ai_api_key_required",
}
GROQ_AI = {
    "ai_provider": "openai_compatible",
    "ai_base_url": "https://api.groq.com/openai/v1",
    "ai_model": "openai/gpt-oss-20b",
    "ai_api_key_required": True,
}


class SetupError(Exception):
    """A safe actionable error; messages never contain credential values."""


def jwt_role(value):
    try:
        part = value.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))).get("role")
    except (ValueError, IndexError, TypeError, AttributeError):
        return None


def https_url(value, label, *, path=None):
    if not isinstance(value, str):
        raise SetupError(f"{label} debe ser texto.")
    parsed = urlparse(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment
            or (path is not None and parsed.path != path)):
        raise SetupError(f"{label} debe ser una URL HTTPS sin claves, query ni fragmentos.")
    public_hostname(parsed.hostname, label)
    return value.rstrip("/")


def public_hostname(hostname, label):
    hostname = hostname.lower().rstrip(".")
    if (hostname in {"localhost", "example.com", "example.org", "example.net"}
            or hostname.endswith((".localhost", ".local", ".internal", ".invalid", ".test", ".example"))
            or "tu-proyecto" in hostname or "your-project" in hostname or "tu-dominio" in hostname):
        raise SetupError(f"{label} debe apuntar a un dominio público real; reemplazá los ejemplos.")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        if "." not in hostname:
            raise SetupError(f"{label} no puede apuntar a un nombre de red local.")
    else:
        if not address.is_global:
            raise SetupError(f"{label} no puede apuntar a una dirección privada o reservada.")


def read_secret(label):
    if not sys.stdin.isatty():
        raise SetupError("Ingresá secretos desde la terminal interactiva de Cloud Shell; se rechaza la entrada sin TTY para evitar mostrarla.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            return getpass.getpass(f"{label} (entrada oculta): ").strip()
    except (getpass.GetPassWarning, EOFError, KeyboardInterrupt) as error:
        raise SetupError("No se pudo usar entrada oculta. No se guardó ningún secreto; volvé a intentarlo en Cloud Shell.") from error


@contextmanager
def backend_source():
    """Upload an explicit source set, independent of ignore-file semantics."""
    if (BACKEND / "app").is_symlink():
        raise SetupError("El directorio app debe contener código local, sin enlaces simbólicos.")
    with tempfile.TemporaryDirectory(prefix="trabajo-ya-backend-source-") as folder:
        target_root = Path(folder)
        sources = [BACKEND / "Dockerfile", BACKEND / "requirements.txt"]
        sources.extend(sorted((BACKEND / "app").rglob("*.py")))
        for source in sources:
            relative = source.relative_to(BACKEND)
            if "__pycache__" in relative.parts or any(part.startswith(".") for part in relative.parts):
                continue
            if source.is_symlink() or not source.is_file():
                raise SetupError("El backend debe contener archivos de código reales, sin enlaces simbólicos.")
            destination = target_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        for module in ("main.py", "worker.py"):
            if not (target_root / "app" / module).is_file():
                raise SetupError("Falta código de API o worker en el backend; no se subió ninguna fuente.")
        yield target_root


def load_config(path):
    try:
        config = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SetupError("Creá cloud-config.json a partir del ejemplo y completá sus datos públicos.") from error
    return validate_config(config)


def save_config(path, config):
    """Replace only validated public configuration, atomically and privately."""
    validated = validate_config(config)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=".trabajo-ya-public-", delete=False) as output:
        temporary = Path(output.name)
        try:
            output.write(json.dumps(validated, indent=2, ensure_ascii=False) + "\n")
            output.flush()
            temporary.chmod(0o600)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def validate_config(config):
    if not isinstance(config, dict) or set(config) - CONFIG_KEYS:
        raise SetupError("La configuración admite únicamente las claves públicas del archivo de ejemplo.")
    defaults = {
        "region": "us-central1", "api_name": "trabajo-ya-api",
        "worker_name": "trabajo-ya-worker", "scheduler_name": "trabajo-ya-cada-15-min",
        "artifact_repository": "trabajo-ya", "google_redirect_uri": "",
        "cors_origins": [], "ai_provider": "demo", "ai_base_url": "",
        "ai_model": "", "ai_api_key_required": False,
    }
    config = defaults | config
    for key, pattern in {
        "project_id": r"[a-z][a-z0-9-]{4,28}[a-z0-9]",
        "region": r"[a-z]+-[a-z]+[0-9]+",
        "api_name": r"[a-z][a-z0-9-]{0,47}[a-z0-9]",
        "worker_name": r"[a-z][a-z0-9-]{0,47}[a-z0-9]",
        "scheduler_name": r"[a-z][a-z0-9-]{0,47}[a-z0-9]",
        "artifact_repository": r"[a-z][a-z0-9-]{0,47}[a-z0-9]",
    }.items():
        if not isinstance(config.get(key), str) or not re.fullmatch(pattern, config[key]):
            raise SetupError(f"Completá correctamente {key}.")
    if config["project_id"].startswith("tu-proyecto"):
        raise SetupError("Reemplazá project_id por el ID real de tu proyecto de Google.")
    config["supabase_url"] = https_url(config.get("supabase_url", ""), "supabase_url")
    anon = config.get("supabase_anon_key", "")
    if (not isinstance(anon, str) or (jwt_role(anon) != "anon"
            and not (anon.startswith("sb_publishable_") and len(anon) > 20))):
        raise SetupError("supabase_anon_key debe ser la clave pública anon/publishable; nunca service_role/secret.")
    if (not isinstance(config.get("google_client_id"), str)
            or not re.fullmatch(r"[A-Za-z0-9_-]+\.apps\.googleusercontent\.com", config["google_client_id"])):
        raise SetupError("Completá google_client_id con el ID público del cliente OAuth web.")
    if config["google_client_id"].startswith("TU_CLIENT_ID"):
        raise SetupError("Reemplazá google_client_id por el ID real de tu cliente OAuth web.")
    if config["google_redirect_uri"]:
        https_url(config["google_redirect_uri"], "google_redirect_uri", path="/api/mail/google/callback")
    origins = config["cors_origins"]
    if not isinstance(origins, list) or len(origins) > 20:
        raise SetupError("cors_origins debe ser una lista de hasta 20 orígenes HTTPS; Android no requiere CORS.")
    for origin in origins:
        https_url(origin, "cors_origins")
        if urlparse(origin).path not in ("", "/"):
            raise SetupError("Cada cors_origins debe ser un origen HTTPS sin ruta.")
    if config["ai_provider"] not in ("demo", "openai_compatible", "ollama"):
        raise SetupError("ai_provider debe ser demo, openai_compatible u ollama.")
    if not isinstance(config["ai_api_key_required"], bool):
        raise SetupError("ai_api_key_required debe ser true o false.")
    if config["ai_provider"] != "demo":
        https_url(config["ai_base_url"], "ai_base_url")
        if not isinstance(config["ai_model"], str) or not config["ai_model"].strip():
            raise SetupError("Completá ai_model con el modelo disponible en tu proveedor.")
    elif config["ai_api_key_required"]:
        raise SetupError("El modo demo no necesita una clave de IA.")
    return config


def configure(path):
    path = Path(path)
    if path.exists():
        raise SetupError("cloud-config.json ya existe. Editá sólo sus datos públicos; configure no lo sobrescribe.")
    if not sys.stdin.isatty():
        raise SetupError("Abrí una terminal interactiva de Cloud Shell para configurar el proyecto.")
    try:
        config = {
            "project_id": input("ID del proyecto de Google Cloud: ").strip(),
            "supabase_url": input("URL HTTPS de tu proyecto Supabase: ").strip(),
            "supabase_anon_key": read_secret("Clave pública anon/publishable de Supabase; nunca service_role"),
            "google_client_id": input("ID público del cliente OAuth web de Google: ").strip(),
        }
    except (EOFError, KeyboardInterrupt) as error:
        raise SetupError("Configuración cancelada. No se guardó ningún archivo.") from error
    # All validation precedes writes. Accidentally pasting service_role at the
    # anon prompt cannot place it in this configuration file.
    validated = validate_config(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(validated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    path.chmod(0o600)
    print(f"Configuración pública guardada: {path}. IA en modo demo; envíos desactivados.")


class Cloud:
    def __init__(self, config):
        self.config = config

    def run(self, args, *, data=None):
        command = ["gcloud", "--quiet", f"--project={self.config['project_id']}", *args]
        try:
            result = subprocess.run(command, input=data, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, check=True, text=True)
        except FileNotFoundError as error:
            raise SetupError("Ejecutá estos pasos en Google Cloud Shell, donde gcloud ya está instalado.") from error
        except subprocess.CalledProcessError as error:
            # Input data is never logged. gcloud receives credential values only
            # through stdin, so errors/command lists cannot echo those values.
            raise SetupError(f"Falló gcloud {' '.join(args[:3])}. Revisá permisos y estado en la consola de Google.") from error
        return result.stdout.strip()

    def exists(self, list_args, field, value):
        rows = json.loads(self.run([*list_args, "--format=json"]))
        return any(str(row.get(field, "")).rsplit("/", 1)[-1] == value for row in rows)

    def preflight(self):
        if not shutil.which("gcloud"):
            raise SetupError("Abrí Google Cloud Shell desde tu navegador; estos scripts necesitan gcloud.")
        if not self.run(["auth", "list", "--filter=status:ACTIVE", "--format=value(account)"]):
            raise SetupError("Autorizá Cloud Shell con tu cuenta propietaria del proyecto.")
        # Read-only checks precede every resource mutation. Billing-enabled
        # means charges are possible; a free allowance is not a cost ceiling.
        self.run(["projects", "describe", self.config["project_id"], "--format=value(projectId)"])
        if self.run(["billing", "projects", "describe", self.config["project_id"],
                     "--format=value(billingEnabled)"]).lower() != "true":
            raise SetupError("Vinculá una cuenta de facturación al proyecto y configurá alertas de presupuesto antes de desplegar.")

    def account(self, account_id):
        return f"{account_id}@{self.config['project_id']}.iam.gserviceaccount.com"

    def required_secrets(self):
        names = {key: value for key, value in SECRET_NAMES.items() if key != "AI_API_KEY"}
        if self.config["ai_api_key_required"]:
            names["AI_API_KEY"] = SECRET_NAMES["AI_API_KEY"]
        return names

    def prepare(self):
        self.run(["services", "enable", *APIS])
        for account_id, title in (
            ("trabajo-ya-runtime", "Trabajo YA API y worker"),
            ("trabajo-ya-scheduler", "Trabajo YA planificador"),
            ("trabajo-ya-build", "Trabajo YA construcción sin acceso a secretos"),
        ):
            if not self.exists(["iam", "service-accounts", "list"], "email", self.account(account_id)):
                self.run(["iam", "service-accounts", "create", account_id, f"--display-name={title}"])
        if not self.exists(["artifacts", "repositories", "list", f"--location={self.config['region']}"],
                           "name", self.config["artifact_repository"]):
            self.run(["artifacts", "repositories", "create", self.config["artifact_repository"],
                      f"--location={self.config['region']}", "--repository-format=docker"])
        self.run(["projects", "add-iam-policy-binding", self.config["project_id"],
                  f"--member=serviceAccount:{self.account('trabajo-ya-build')}",
                  "--role=roles/cloudbuild.builds.builder", "--condition=None"])
        for name in self.required_secrets().values():
            if not self.exists(["secrets", "list"], "name", name):
                self.run(["secrets", "create", name, "--replication-policy=automatic"])
            self.run(["secrets", "add-iam-policy-binding", name,
                      f"--member=serviceAccount:{self.account('trabajo-ya-runtime')}",
                      "--role=roles/secretmanager.secretAccessor", "--condition=None"])
        self.exclude_oauth_logs()
        print("Infraestructura preparada. No se creó Scheduler ni se activó ningún envío.")

    def exclude_oauth_logs(self):
        exclusion = f"{self.config['api_name']}-oauth-callback"
        sink = json.loads(self.run(["logging", "sinks", "describe", "_Default", "--format=json"]))
        known = any(row.get("name") == exclusion for row in sink.get("exclusions", []))
        log_filter = (f'resource.type="cloud_run_revision" AND '
                      f'resource.labels.service_name="{self.config["api_name"]}" AND '
                      f'logName="projects/{self.config["project_id"]}/logs/run.googleapis.com%2Frequests" AND '
                      'httpRequest.requestUrl:"/api/mail/google/callback"')
        # Only this named exclusion changes; existing sink filters, destination
        # and all other exclusions remain untouched. The values contain no commas.
        value = f"name={exclusion},filter={log_filter}"
        if known:
            # gcloud explicitly enables a disabled exclusion with an empty
            # disabled key; "false" is still a nonempty disabling value.
            value += ",disabled="
        self.run(["logging", "sinks", "update", "_Default",
                  f"--{'update' if known else 'add'}-exclusion={value}"])

    def latest_version(self, name):
        rows = json.loads(self.run(["secrets", "versions", "list", name,
            "--filter=state:ENABLED", "--format=json"]))
        versions = [int(row["name"].rsplit("/", 1)[-1]) for row in rows
                    if row.get("state") == "ENABLED"]
        return str(max(versions)) if versions else None

    def setup_secrets(self):
        for key, name in self.required_secrets().items():
            if self.latest_version(name):
                print(f"{name}: se conserva la versión existente.")
                continue
            if key == "TOKEN_ENCRYPTION_KEY":
                value = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")
            else:
                label = {
                    "SUPABASE_SERVICE_ROLE_KEY": "Clave privada service_role/secret de Supabase",
                    "GOOGLE_CLIENT_SECRET": "Secreto privado del cliente OAuth web Google",
                    "AUTHORIZED_JOB_FEEDS": "JSON de fuentes autorizadas; [] si todavía no tenés una fuente",
                    "AI_API_KEY": "Clave privada del proveedor IA",
                }[key]
                value = read_secret(label)
                validate_secret(key, value)
            self.run(["secrets", "versions", "add", name, "--data-file=-"], data=value)
            print(f"{name}: guardado en Secret Manager; valor oculto.")
        print("La clave de cifrado se conserva entre despliegues. No regenerarla con correos vinculados.")

    def set_secret(self, key):
        # Explicit updates support adding a real feed after an initial [] setup.
        # Cipher rotation requires migration of encrypted tokens, so it is
        # deliberately unavailable through this convenience command.
        if key == "TOKEN_ENCRYPTION_KEY":
            raise SetupError("No se puede rotar la clave de cifrado con este comando. Requiere migrar los tokens existentes.")
        if key not in self.required_secrets():
            raise SetupError("Ese secreto no forma parte de la configuración actual.")
        value = read_secret(f"Nuevo valor para {key}")
        validate_secret(key, value)
        self.run(["secrets", "versions", "add", SECRET_NAMES[key], "--data-file=-"], data=value)
        print("Nueva versión guardada, sin mostrar su valor. Ejecutá deploy para fijarla en API y worker.")

    def secret_refs(self):
        refs = {}
        for key, name in self.required_secrets().items():
            version = self.latest_version(name)
            if version is None:
                raise SetupError(f"Falta una versión habilitada de {name}. Ejecutá primero secrets.")
            refs[key] = f"{name}:{version}"
        return refs

    def service_url(self):
        value = self.run(["run", "services", "describe", self.config["api_name"],
                          f"--region={self.config['region']}", "--format=value(status.url)"])
        return https_url(value, "URL de Cloud Run")

    def public_env(self, redirect, *, mail_enabled=False):
        return {
            "SUPABASE_URL": self.config["supabase_url"],
            "SUPABASE_ANON_KEY": self.config["supabase_anon_key"],
            "GOOGLE_CLIENT_ID": self.config["google_client_id"],
            "GOOGLE_REDIRECT_URI": redirect,
            "DEFAULT_TIMEZONE": "America/Argentina/Buenos_Aires",
            "CORS_ORIGINS": json.dumps(self.config["cors_origins"], separators=(",", ":")),
            "AI_PROVIDER": self.config["ai_provider"],
            "AI_BASE_URL": self.config["ai_base_url"],
            "AI_MODEL": self.config["ai_model"],
            "WORKER_BATCH_SIZE": "1", "MAIL_SEND_ENABLED": str(mail_enabled).lower(),
        }

    @contextmanager
    def env_file(self, env):
        # JSON is also accepted by gcloud --env-vars-file as YAML's JSON subset.
        with tempfile.TemporaryDirectory(prefix="trabajo-ya-public-env-") as folder:
            path = Path(folder) / "env.json"
            path.write_text(json.dumps(env), encoding="utf-8")
            path.chmod(0o600)
            yield str(path)

    def deploy(self):
        refs = self.secret_refs()  # Resolve ONCE before either resource changes.
        # Keep an existing schedule paused through redeployment. It is never
        # resumed implicitly; an in-flight execution can still finish.
        schedules = json.loads(self.run(["scheduler", "jobs", "list", f"--location={self.config['region']}", "--format=json"]))
        if any(row.get("name", "").rsplit("/", 1)[-1] == self.config["scheduler_name"]
               and row.get("state") == "ENABLED" for row in schedules):
            self.run(["scheduler", "jobs", "pause", self.config["scheduler_name"],
                      f"--location={self.config['region']}"])
        tag = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        image_root = (f"{self.config['region']}-docker.pkg.dev/{self.config['project_id']}/"
                      f"{self.config['artifact_repository']}/backend")
        image_tag = f"{image_root}:{tag}"
        print("Construyendo imagen privada en Cloud Build; puede tardar varios minutos.")
        with backend_source() as source_directory:
            self.run(["builds", "submit", str(source_directory), f"--config={HERE / 'cloudbuild.yaml'}",
                      f"--substitutions=_IMAGE={image_tag}",
                      f"--service-account=projects/{self.config['project_id']}/serviceAccounts/{self.account('trabajo-ya-build')}"])
        digest = self.run(["artifacts", "docker", "images", "describe", image_tag,
                           "--format=value(image_summary.digest)"])
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise SetupError("Cloud Build no confirmó el digest de la imagen; no se desplegó la API ni el worker.")
        image = f"{image_root}@{digest}"
        # gcloud list JSON uses nested metadata.name.
        services = json.loads(self.run(["run", "services", "list", f"--region={self.config['region']}", "--format=json"]))
        existing = any(row.get("metadata", {}).get("name") == self.config["api_name"] for row in services)
        redirect = self.config["google_redirect_uri"] or (
            f"{self.service_url()}/api/mail/google/callback" if existing else "")
        with self.env_file(self.public_env(redirect)) as env_path:
            self.run(["run", "deploy", self.config["api_name"], f"--image={image}",
                f"--region={self.config['region']}", f"--service-account={self.account('trabajo-ya-runtime')}",
                "--allow-unauthenticated", "--ingress=all", "--min=0", "--max=1",
                "--min-instances=0", "--max-instances=1", "--cpu=1", "--memory=512Mi",
                "--concurrency=8", "--timeout=1200", "--cpu-throttling", "--no-cpu-boost",
                "--port=8000", "--command=uvicorn",
                "--args=app.main:app,--host,0.0.0.0,--port,8000,--no-access-log",
                f"--env-vars-file={env_path}", f"--set-secrets={format_refs(refs)}"])
        url = self.service_url()
        redirect = self.config["google_redirect_uri"] or f"{url}/api/mail/google/callback"
        with self.env_file(self.public_env(redirect)) as env_path:
            self.run(["run", "services", "update", self.config["api_name"],
                      f"--region={self.config['region']}", f"--env-vars-file={env_path}",
                      f"--set-secrets={format_refs(refs)}"])
            # The worker does not call AI. Omitting its key reduces secret reads
            # and avoids unnecessary exposure; other four versions are identical.
            worker_refs = {key: value for key, value in refs.items() if key != "AI_API_KEY"}
            self.run(["run", "jobs", "deploy", self.config["worker_name"], f"--image={image}",
                f"--region={self.config['region']}", f"--service-account={self.account('trabajo-ya-runtime')}",
                "--tasks=1", "--parallelism=1", "--max-retries=0", "--task-timeout=1200s",
                "--cpu=1", "--memory=512Mi", "--command=python", "--args=-m,app.worker,--once",
                f"--env-vars-file={env_path}", f"--set-secrets={format_refs(worker_refs)}"])
        self.run(["run", "jobs", "add-iam-policy-binding", self.config["worker_name"],
                  f"--region={self.config['region']}",
                  f"--member=serviceAccount:{self.account('trabajo-ya-scheduler')}", "--role=roles/run.invoker"])
        print(f"API HTTPS: {url}\nCallback Google exacto: {redirect}")
        print("Envíos desactivados. Scheduler no se creó ni se reanudó. Revisá la guía antes de activarlos.")

    def set_mail(self, enabled):
        # Use the deployed URL, but preserve the current service's other envs
        # with update-env-vars. A missing deployment fails before mail is enabled.
        self.service_url()
        if enabled:
            self.require_real_feed()
        flag = f"--update-env-vars=MAIL_SEND_ENABLED={str(enabled).lower()}"
        self.run(["run", "services", "update", self.config["api_name"],
                  f"--region={self.config['region']}", flag])
        self.run(["run", "jobs", "update", self.config["worker_name"],
                  f"--region={self.config['region']}", flag])
        print("Envíos habilitados para postulaciones autorizadas." if enabled else "Envíos desactivados en API y worker.")

    def scheduler(self, action):
        location = f"--location={self.config['region']}"
        name = self.config["scheduler_name"]
        if action == "enable":
            self.require_real_feed()
            if self.exists(["scheduler", "jobs", "list", location], "name", name):
                raise SetupError("El planificador ya existe. Usá scheduler-status y scheduler-resume si estaba pausado.")
            # This explicit command is the ONLY place that creates the schedule.
            # No create-then-pause race during preparation or deployment.
            self.run(["scheduler", "jobs", "create", "http", name, location,
                "--schedule=*/15 * * * *", "--time-zone=Etc/UTC",
                f"--uri=https://run.googleapis.com/v2/projects/{self.config['project_id']}/locations/{self.config['region']}/jobs/{self.config['worker_name']}:run",
                "--http-method=POST", "--headers=Content-Type=application/json", "--message-body={}",
                f"--oauth-service-account-email={self.account('trabajo-ya-scheduler')}",
                "--oauth-token-scope=https://www.googleapis.com/auth/cloud-platform",
                "--attempt-deadline=180s", "--max-retry-attempts=0", "--max-retry-duration=0s"])
            print("Scheduler activo: consulta tareas pendientes cada 15 minutos, aunque Android esté apagado.")
        elif action == "status":
            value = self.run(["scheduler", "jobs", "describe", name, location,
                              "--format=json(name,state,schedule,timeZone,lastAttemptTime,status)"])
            print(value)
        else:
            if action == "resume":
                self.require_real_feed()
            self.run(["scheduler", "jobs", action, name, location])
            print(f"Scheduler: {action}. Una ejecución en curso continúa; disable-mail bloquea futuros envíos.")

    def worker_env(self):
        job = json.loads(self.run(["run", "jobs", "describe", self.config["worker_name"],
                                  f"--region={self.config['region']}", "--format=json"]))
        return find_environment(job)

    def require_real_feed(self):
        # Inspect the actually deployed, pinned worker secret, not a newer
        # secret version that the worker may not yet be using. Its value stays
        # in process memory and is never printed or written to a local file.
        env = self.worker_env()
        reference = env.get("AUTHORIZED_JOB_FEEDS", {}).get("valueFrom", {}).get("secretKeyRef", {})
        name, version = reference.get("name"), reference.get("key")
        if name != SECRET_NAMES["AUTHORIZED_JOB_FEEDS"] or not str(version).isdigit():
            raise SetupError("El worker no tiene una fuente fijada a una versión de Secret Manager. Ejecutá deploy.")
        payload = self.run(["secrets", "versions", "access", str(version), f"--secret={name}"])
        validate_secret("AUTHORIZED_JOB_FEEDS", payload)
        if not json.loads(payload):
            raise SetupError("La fuente desplegada está vacía. Guardá una integración real autorizada con set-secret y volvé a desplegar.")

    def export_mobile(self):
        values = {
            "EXPO_PUBLIC_DEMO_MODE": "false",
            "EXPO_PUBLIC_BACKEND_URL": self.service_url(),
            "EXPO_PUBLIC_SUPABASE_URL": self.config["supabase_url"],
            "EXPO_PUBLIC_SUPABASE_ANON_KEY": self.config["supabase_anon_key"],
        }
        GENERATED.mkdir(parents=True, exist_ok=True)
        destination = GENERATED / "mobile.env"
        # JSON quoting keeps each value on a single physical dotenv line.
        content = "# Variables públicas para Android; no contiene claves del servidor.\n"
        content += "\n".join(f"{key}={json.dumps(value)}" for key, value in values.items()) + "\n"
        destination.write_text(content, encoding="utf-8")
        destination.chmod(0o600)
        print(f"Configuración pública Android preparada: {destination}")
        print("Copiala a mobile/.env.local y cargá esas mismas variables públicas en EAS antes de compilar.")
        return destination

    def test_worker(self, *, allow_sending=False):
        enabled = self.worker_env().get("MAIL_SEND_ENABLED", {}).get("value", "false") == "true"
        if enabled and not allow_sending:
            raise SetupError("El worker tiene envíos habilitados. Usá disable-mail para una prueba sin envíos o confirmá fuente y consentimiento con el flag explícito.")
        self.run(["run", "jobs", "execute", self.config["worker_name"],
                  f"--region={self.config['region']}", "--wait"])
        print("Cloud Run confirmó que el worker terminó. Revisá job_search_runs en Supabase para comprobar qué búsquedas ejecutó.")

    def deployed_ai(self):
        """Read the ready revision actually serving API traffic, not local intent."""
        service = json.loads(self.run(["run", "services", "describe", self.config["api_name"],
                                      f"--region={self.config['region']}", "--format=json"]))
        revision = active_service_revision(service)
        deployed = json.loads(self.run(["run", "revisions", "describe", revision,
                                       f"--region={self.config['region']}", "--format=json"]))
        containers = find_containers(deployed)
        if len(containers) != 1:
            raise SetupError("La revisión de la API debe tener un único contenedor para verificar su IA.")
        container = containers[0]
        env = find_environment(container)
        values = {key: env.get(key, {}).get("value", "")
                  for key in ("AI_PROVIDER", "AI_BASE_URL", "AI_MODEL")}
        if values["AI_PROVIDER"] not in ("openai_compatible", "ollama"):
            raise SetupError("La API desplegada todavía usa IA de demostración. Ejecutá activate-ai o configurá un proveedor real y desplegalo.")
        https_url(values["AI_BASE_URL"], "AI_BASE_URL desplegada")
        if not isinstance(values["AI_MODEL"], str) or not values["AI_MODEL"].strip():
            raise SetupError("La API desplegada no tiene un modelo de IA configurado.")
        image = deployed.get("status", {}).get("imageDigest") or container.get("image", "")
        if not isinstance(image, str) or not re.fullmatch(r"[^\s]+@sha256:[0-9a-f]{64}", image):
            raise SetupError("La revisión de la API no confirmó una imagen inmutable; volvé a desplegar antes de verificar IA.")
        refs = {}
        secret_row = env.get("AI_API_KEY", {})
        if secret_row:
            reference = (secret_row.get("valueFrom", {}).get("secretKeyRef")
                         or secret_row.get("valueSource", {}).get("secretKeyRef", {}))
            name = reference.get("name", reference.get("secret"))
            version = reference.get("key", reference.get("version"))
            if name != SECRET_NAMES["AI_API_KEY"] or not str(version).isdigit():
                raise SetupError("La API debe guardar AI_API_KEY en una versión fija de Secret Manager; ejecutá deploy.")
            refs["AI_API_KEY"] = f"{name}:{version}"
        if (values["AI_PROVIDER"] == "openai_compatible" and not refs):
            raise SetupError("La API compatible necesita AI_API_KEY desde Secret Manager para esta prueba.")
        return image, values, refs

    def test_ai(self):
        image, env, refs = self.deployed_ai()
        name = f"{self.config['api_name']}-ai-check"
        with self.env_file(env) as env_path:
            # Replacing the whole env/secret set prevents a stale probe job
            # from retaining Supabase keys, Gmail tokens, or mail flags.
            secret_flag = f"--set-secrets={format_refs(refs)}" if refs else "--clear-secrets"
            self.run(["run", "jobs", "deploy", name, f"--image={image}",
                      f"--region={self.config['region']}",
                      f"--service-account={self.account('trabajo-ya-runtime')}",
                      "--tasks=1", "--parallelism=1", "--max-retries=0", "--task-timeout=180s",
                      "--cpu=1", "--memory=512Mi", "--command=python", "--args=-m,app.check_ai",
                      f"--env-vars-file={env_path}", secret_flag])
        self.run(["run", "jobs", "execute", name, f"--region={self.config['region']}", "--wait"])
        # The check module exits zero only after a real provider response is
        # parsed and its Spanish sample instruction is semantically validated.
        print(f"IA verificada mediante una respuesta real: {env['AI_MODEL']} ({env['AI_PROVIDER']}).")
        print("La prueba no consultó la base de datos ni envió correos; no creó ni reanudó Scheduler.")


def setup(path):
    """Prepare the deployment; sending and scheduling remain separate actions."""
    if not shutil.which("gcloud"):
        raise SetupError("Abrí Google Cloud Shell para ejecutar setup; gcloud no está instalado aquí.")
    if not Path(path).exists():
        configure(path)
    current = Cloud(load_config(path))
    current.preflight()
    current.prepare()
    current.setup_secrets()
    current.deploy()
    current.export_mobile()
    print("Registrá el callback en Google. Después comprobá Gmail, fuentes y permisos antes de activar tareas y correo.")


def activate_ai(path):
    """Activate a real open-model provider only in the user's authorized cloud."""
    current = Cloud(validate_config(load_config(path) | GROQ_AI))
    current.preflight()  # No local writes or cloud mutations if access fails.
    save_config(path, current.config)
    current.prepare()
    current.setup_secrets()  # Existing Supabase/Gmail/cipher versions survive.
    current.deploy()  # Mail remains disabled; existing schedules stay paused.
    current.test_ai()
    current.export_mobile()


def format_refs(refs):
    return ",".join(f"{key}={value}" for key, value in sorted(refs.items()))


def find_environment(value):
    """Locate container env inside gcloud Cloud Run v1 service/job envelopes."""
    if isinstance(value, dict):
        if isinstance(value.get("env"), list):
            return {row["name"]: row for row in value["env"] if isinstance(row, dict) and row.get("name")}
        for child in value.values():
            found = find_environment(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_environment(child)
            if found:
                return found
    return {}


def find_containers(value):
    """Find container definitions in Cloud Run v1/v2 resource envelopes."""
    if isinstance(value, dict):
        if isinstance(value.get("containers"), list):
            return value["containers"]
        for child in value.values():
            found = find_containers(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_containers(child)
            if found:
                return found
    return []


def active_service_revision(service):
    status = service.get("status", service)
    ready = status.get("latestReadyRevisionName", status.get("latestReadyRevision", ""))
    created = status.get("latestCreatedRevisionName", status.get("latestCreatedRevision", ""))
    conditions = status.get("conditions", [])
    if not any(row.get("type") == "Ready" and str(row.get("status")).lower() == "true"
               or row.get("type") == "Ready" and row.get("state") == "CONDITION_SUCCEEDED"
               for row in conditions):
        raise SetupError("La API aún no está lista. Revisá el despliegue antes de probar la IA.")
    if not isinstance(ready, str) or not ready or ready != created:
        raise SetupError("La última revisión de la API no está lista; no se puede verificar la configuración nueva.")
    ready_name = ready.rsplit("/", 1)[-1]
    traffic = status.get("traffic", status.get("trafficStatuses", []))
    serving = sum(row.get("percent", 0) for row in traffic
                  if row.get("revisionName", row.get("revision", "")).rsplit("/", 1)[-1] == ready_name)
    if serving != 100:
        raise SetupError("La API tiene tráfico dividido entre revisiones. Asigná el 100 % a la revisión lista antes de verificar IA.")
    return ready_name


def validate_secret(key, value):
    if not value or "\x00" in value:
        raise SetupError("El secreto no puede estar vacío ni contener caracteres NUL.")
    if key == "SUPABASE_SERVICE_ROLE_KEY" and not (
            jwt_role(value) == "service_role" or value.startswith("sb_secret_")):
        raise SetupError("Ingresá la clave privada service_role/secret; una clave anon no permite ejecutar tareas.")
    if key == "AUTHORIZED_JOB_FEEDS":
        try:
            feeds = json.loads(value)
        except ValueError as error:
            raise SetupError("El secreto de fuentes debe ser JSON válido.") from error
        if not isinstance(feeds, list) or len(feeds) > 20:
            raise SetupError("El secreto de fuentes debe ser una lista de hasta 20 integraciones.")
        seen = set()
        for source in feeds:
            if (not isinstance(source, dict) or not isinstance(source.get("id"), str)
                    or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", source["id"])
                    or source.get("authorized") is not True
                    or source.get("recipient_verification") != "source_attestation"):
                raise SetupError("Cada fuente debe tener id, authorized:true y recipient_verification:source_attestation.")
            if source["id"] in seen:
                raise SetupError("Cada fuente debe tener un id único.")
            seen.add(source["id"])
            if not isinstance(source.get("url"), str):
                raise SetupError("Cada fuente debe tener URL HTTPS de texto.")
            parsed = urlparse(source["url"])
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
                raise SetupError("Las fuentes deben tener URL HTTPS pública sin usuario ni contraseña embebidos.")
            public_hostname(parsed.hostname, "La fuente autorizada")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=(
        "setup", "activate-ai", "test-ai", "configure", "validate", "prepare", "secrets", "set-secret", "deploy", "export-mobile", "test-worker", "enable-mail", "disable-mail",
        "scheduler-enable", "scheduler-pause", "scheduler-resume", "scheduler-status"))
    parser.add_argument("--config", default=str(HERE / "cloud-config.json"))
    parser.add_argument("--secret", choices=tuple(SECRET_NAMES),
                        help="Secreto a actualizar con set-secret; su valor se solicita con entrada oculta.")
    parser.add_argument("--confirmed-real-source-and-consent", action="store_true",
                        help="Confirma prueba real de fuente/Gmail y consentimiento para habilitar envíos/automatización.")
    args = parser.parse_args(argv)
    try:
        if args.command == "setup":
            setup(args.config)
            return 0
        if args.command == "configure":
            configure(args.config)
            return 0
        if args.command == "activate-ai":
            activate_ai(args.config)
            return 0
        config = load_config(args.config)
        if args.command == "validate":
            print("Configuración pública válida. No se consultó ni modificó Google Cloud.")
            return 0
        if args.command in ("enable-mail", "scheduler-enable", "scheduler-resume") and not args.confirmed_real_source_and_consent:
            raise SetupError("Agregá --confirmed-real-source-and-consent después de comprobar la fuente autorizada, Gmail y el consentimiento.")
        cloud = Cloud(config)
        cloud.preflight()
        if args.command == "set-secret":
            if not args.secret:
                raise SetupError("Indicá --secret AUTHORIZED_JOB_FEEDS u otro nombre permitido.")
            cloud.set_secret(args.secret)
        elif args.command == "test-worker":
            cloud.test_worker(allow_sending=args.confirmed_real_source_and_consent)
        elif args.command == "test-ai":
            cloud.test_ai()
        elif args.command.startswith("scheduler-"):
            cloud.scheduler(args.command.removeprefix("scheduler-"))
        elif args.command in ("enable-mail", "disable-mail"):
            cloud.set_mail(args.command == "enable-mail")
        else:
            getattr(cloud, {"secrets": "setup_secrets", "export-mobile": "export_mobile"}.get(args.command, args.command))()
    except SetupError as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

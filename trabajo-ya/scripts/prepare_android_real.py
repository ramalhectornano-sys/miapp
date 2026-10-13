#!/usr/bin/env python3
"""Prepare only public Android configuration; never fall back to demo mode.

Uses the Python standard library. The optional public /health probe checks
configuration, not whether AI, authentication or persistence work end to end.
"""
from __future__ import annotations

import argparse
import base64
import ipaddress
import json
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


PUBLIC_FIELDS = {"backend_url", "supabase_url", "supabase_public_key"}
ANDROID_PACKAGE = "com.trabajoya.autoempleoia"
MAX_CONFIG_BYTES = 16_384
MAX_HEALTH_BYTES = 65_536
HEALTH_PROBE_TIMEOUT_SECONDS = 120  # Render Free can need about a minute to wake.


class ConfigurationError(ValueError):
    """Errors contain field names and instructions, never submitted values."""


def unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ConfigurationError("El JSON contiene campos duplicados.")
        result[key] = value
    return result


def read_json(path: Path, limit: int = MAX_CONFIG_BYTES):
    try:
        raw = path.read_bytes()
        if len(raw) > limit:
            raise ConfigurationError("El archivo de configuración es demasiado grande.")
        return json.loads(raw, object_pairs_hook=unique_fields)
    except ConfigurationError:
        raise
    except (OSError, UnicodeError, ValueError):
        raise ConfigurationError("Falta el archivo requerido o su JSON no es válido.") from None


def public_https_url(field: str, value: str) -> str:
    message = f"{field} requiere la URL HTTPS pública de un servicio desplegado."
    if not isinstance(value, str) or not value or value != value.strip() or re.search(r"\s|[\x00-\x1f\x7f]", value):
        raise ConfigurationError(message)
    try:
        url = urlsplit(value)
        host = (url.hostname or "").lower()
        port = url.port
    except ValueError:
        raise ConfigurationError(message) from None
    if (url.scheme != "https" or not host or url.username is not None or url.password is not None
            or url.query or url.fragment or url.path not in ("", "/") or port not in (None, 443)):
        raise ConfigurationError(message)
    if (host.endswith(".") or host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".example", ".invalid", ".test"))
            or re.search(r"(^|\.)(example\.(com|org|net)|example|invalid|test)$", host)):
        raise ConfigurationError(message)
    try:
        if not ipaddress.ip_address(host).is_global:
            raise ConfigurationError(message)
    except ValueError:
        # Reject ambiguous numeric hosts (for example 127.1), single labels and
        # invalid domain labels. Public IPv6 and IPv4 are handled above.
        if ("." not in host or re.fullmatch(r"[0-9.]+", host)
                or len(host) > 253 or not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in host.split("."))):
            raise ConfigurationError(message) from None
    return value.rstrip("/")


def public_supabase_key(value: str) -> str:
    message = "supabase_public_key requiere una clave pública publishable o anon; no admite claves privadas."
    if not isinstance(value, str) or not value or value != value.strip() or re.search(r"\s|[\x00-\x1f\x7f]", value):
        raise ConfigurationError(message)
    if re.fullmatch(r"sb_publishable_[A-Za-z0-9_-]{12,}", value):
        return value
    try:
        parts = value.split(".")
        if len(parts) != 3 or any(not re.fullmatch(r"[A-Za-z0-9_-]+", part) for part in parts):
            raise ValueError()
        encoded = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.b64decode(encoded, altchars=b"-_", validate=True))
        if not isinstance(payload, dict) or payload.get("role") != "anon":
            raise ValueError()
        return value
    except (ValueError, UnicodeError):
        raise ConfigurationError(message) from None


def load_public_services(path: Path) -> dict[str, str]:
    config = read_json(path)
    if not isinstance(config, dict) or set(config) != PUBLIC_FIELDS:
        raise ConfigurationError("El JSON admite únicamente backend_url, supabase_url y supabase_public_key; quitá los campos adicionales y no incluyas secretos.")
    return {
        "backend_url": public_https_url("backend_url", config["backend_url"]),
        "supabase_url": public_https_url("supabase_url", config["supabase_url"]),
        "supabase_public_key": public_supabase_key(config["supabase_public_key"]),
    }


def app_metadata(mobile_dir: Path) -> dict[str, str]:
    data = read_json(mobile_dir / "app.json")
    try:
        app = data["expo"]
        version = app["version"]
        android = app["android"]
        code = android["versionCode"]
        if (app["name"] != "Trabajo YA" or android["package"] != ANDROID_PACKAGE
                or not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version)
                or type(code) is not int or code < 1):
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise ConfigurationError("Revisá el nombre, paquete, versión y versionCode públicos de mobile/app.json.") from None
    return {
        "TRABAJO_YA_VERSION": version,
        "TRABAJO_YA_VERSION_CODE": str(code),
        "TRABAJO_YA_ANDROID_PACKAGE": ANDROID_PACKAGE,
        "TRABAJO_YA_APK_FILE": f"Trabajo-YA-{version}-real.apk",
        "TRABAJO_YA_RELEASE_TAG": f"trabajo-ya-v{version}-real",
        "TRABAJO_YA_ARTIFACT_NAME": f"Trabajo-YA-{version}-real",
    }


def build_environment(services: dict[str, str], mobile_dir: Path) -> dict[str, str]:
    key = services["supabase_public_key"]
    return {
        "EXPO_PUBLIC_DEMO_MODE": "false",
        "TRABAJO_YA_BUILD_MODE": "real",
        "EXPO_PUBLIC_BACKEND_URL": services["backend_url"],
        "EXPO_PUBLIC_SUPABASE_URL": services["supabase_url"],
        "EXPO_PUBLIC_SUPABASE_ANON_KEY": "" if key.startswith("sb_publishable_") else key,
        "EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY": key if key.startswith("sb_publishable_") else "",
        **app_metadata(mobile_dir),
    }


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def probe_health(backend_url: str) -> None:
    request = Request(backend_url + "/health", headers={"Accept": "application/json", "User-Agent": "Trabajo-YA-Android-Preflight/1"})
    try:
        with build_opener(NoRedirect()).open(request, timeout=HEALTH_PROBE_TIMEOUT_SECONDS) as response:
            if response.status != 200:
                raise ConfigurationError("El backend no respondió correctamente a /health.")
            raw = response.read(MAX_HEALTH_BYTES + 1)
            if len(raw) > MAX_HEALTH_BYTES:
                raise ConfigurationError("La respuesta de /health excede el tamaño permitido.")
            health = json.loads(raw)
    except (HTTPError, URLError, TimeoutError, OSError, UnicodeError, ValueError):
        raise ConfigurationError("No se pudo comprobar el backend real mediante /health; no se compilará una demo.") from None
    if (not isinstance(health, dict) or health.get("status") != "ok"
            or not isinstance(health.get("integrations"), dict)
            or health["integrations"].get("supabase") != "configured"
            or health["integrations"].get("ai") != "configured_unverified"):
        raise ConfigurationError("El backend requiere Supabase configurado y un proveedor de IA real. /health no acredita una respuesta del modelo ni persistencia.")


def render_environment(environment: dict[str, str]) -> str:
    return "".join(f"{name}={value}\n" for name, value in environment.items())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Preparar configuración pública para Trabajo YA real, sin secretos ni modo demo.")
    parser.add_argument("--mobile-dir", type=Path, default=Path("mobile"))
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--github-env", type=Path, help="Agregar las variables públicas al archivo GITHUB_ENV del runner.")
    output.add_argument("--env-file", type=Path, help="Guardar las variables públicas en .env.local para una compilación propia.")
    parser.add_argument("--check-health", action="store_true", help="Consultar /health público; no prueba autenticación, IA ni persistencia.")
    args = parser.parse_args(argv)
    try:
        services = load_public_services(args.mobile_dir / "services.public.json")
        environment = build_environment(services, args.mobile_dir)
        if args.check_health:
            probe_health(services["backend_url"])
        content = render_environment(environment)
        if args.github_env:
            with args.github_env.open("a", encoding="utf-8") as handle:
                handle.write(content)
        elif args.env_file:
            args.env_file.write_text(content, encoding="utf-8")
    except (ConfigurationError, OSError) as error:
        # OSError text may include user-controlled paths; report no raw details.
        message = str(error) if isinstance(error, ConfigurationError) else "No se pudo guardar el archivo de variables públicas."
        print(message, file=sys.stderr)
        return 1
    print("Configuración pública validada. Compilación real: demo=false. La conexión completa debe probarse en Android.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

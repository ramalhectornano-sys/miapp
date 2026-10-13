#!/usr/bin/env python3
"""Check runtime configuration offline, without exposing values or making requests.

Exit code 0 means that configuration passed the requested checks. It does not
prove migrations, model availability, OAuth authorization, email delivery or a
running scheduler. No setting is written and no message is sent.
"""
from __future__ import annotations

import argparse
import base64
from dataclasses import asdict, dataclass
import ipaddress
import json
import os
from pathlib import Path
import re
from typing import Mapping
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str


def read_env(path: Path) -> dict[str, str]:
    """Read the one-line .env subset used by the project's examples.

    No shell execution or variable expansion is performed. Unsupported syntax
    raises a fixed message that cannot include a secret or an offending line.
    """
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ValueError("El archivo .env debe contener asignaciones de una línea.")
        if value.startswith(("'", '"')):
            quote = value[0]
            closing = value.rfind(quote)
            if closing == 0 or (value[closing + 1:].strip() and not value[closing + 1:].strip().startswith("#")):
                raise ValueError("Hay una asignación .env con comillas incompletas.")
            value = value[1:closing]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
        if "${" in value or "$(" in value:
            raise ValueError("Usá valores completos en .env; este comprobador no expande variables.")
        result[key] = value
    return result


def configured(value: str) -> bool:
    clean = value.strip()
    return bool(clean and clean.lower() not in {"changeme", "replace-me", "your-key", "your-api-key", "todo"}
        and not clean.startswith("<"))


def public_key_valid(value: str) -> bool:
    """Reject known secret-key formats; this does not authenticate a JWT."""
    value = value.strip()
    if not configured(value) or value.startswith("sb_secret_"):
        return False
    parts = value.split(".")
    if len(parts) == 3:
        try:
            payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
            if isinstance(payload, dict) and payload.get("role") in {"service_role", "supabase_admin"}:
                return False
        except (ValueError, UnicodeError):
            pass
    return True


def valid_url(value: str, *, https: bool = False, public: bool = False) -> bool:
    try:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
        _ = parsed.port
        if parsed.scheme not in ({"https"} if https else {"http", "https"}):
            return False
        if not host or parsed.username or parsed.password or parsed.fragment:
            return False
        if (host.endswith((".example", ".invalid", ".test")) or host in {"example.com", "example.org", "example.net"}
            or "your-project" in host or host in {"tu-proyecto.supabase.co", "api.tu-dominio.com"}):
            return False
        if public:
            if host in {"localhost", "localhost.localdomain"} or host.endswith((".localhost", ".local")):
                return False
            try:
                if not ipaddress.ip_address(host).is_global:
                    return False
            except ValueError:
                pass  # DNS is deliberately not resolved in an offline check.
        return True
    except (ValueError, TypeError):
        return False


def validate_runtime(backend: Mapping[str, str], mobile: Mapping[str, str], *, mode: str = "real", profile: str = "production") -> list[Check]:
    checks: list[Check] = []
    production = profile == "production"

    def require(name: str, condition: bool, failure: str, success: str = "Valor configurado; disponibilidad no comprobada."):
        checks.append(Check(name, "ok" if condition else "error", success if condition else failure))

    demo = mobile.get("EXPO_PUBLIC_DEMO_MODE", "").strip().lower()
    require("Modo de la aplicación", demo == ("true" if mode == "demo" else "false"),
        f"Configurar EXPO_PUBLIC_DEMO_MODE={'true' if mode == 'demo' else 'false'}.",
        "Modo de demostración local." if mode == "demo" else "Modo real seleccionado; necesita servicios activos.")
    leaked = any(configured(value) for key, value in mobile.items()
        if key.startswith("EXPO_PUBLIC_") and any(token in key.upper() for token in ("SERVICE_ROLE", "SECRET", "TOKEN_ENCRYPTION", "AI_API_KEY", "ACCESS_TOKEN", "REFRESH_TOKEN")))
    server_secret_values = {backend.get(key, "") for key in ("SUPABASE_SERVICE_ROLE_KEY", "GOOGLE_CLIENT_SECRET", "TOKEN_ENCRYPTION_KEY", "AI_API_KEY") if configured(backend.get(key, ""))}
    leaked = leaked or any(value in server_secret_values for key, value in mobile.items() if key.startswith("EXPO_PUBLIC_") and configured(value))
    require("Secretos del servidor", not leaked, "Quitar secretos del servidor de EXPO_PUBLIC_ y rotar los que se hayan publicado.", "No se detectaron secretos del servidor en las variables públicas revisadas.")
    if mode == "demo":
        checks.append(Check("Integraciones reales", "warning", "La demostración no llama a la IA, no crea usuarios y no busca ni envía correos reales."))
        return checks

    require("Supabase URL", valid_url(backend.get("SUPABASE_URL", ""), https=production), "Configurar SUPABASE_URL real; producción requiere HTTPS.")
    require("Supabase clave pública", public_key_valid(backend.get("SUPABASE_ANON_KEY", "")), "Completar SUPABASE_ANON_KEY con anon o sb_publishable del proyecto; nunca usar service_role ni sb_secret.")
    require("Supabase clave de servicio", configured(backend.get("SUPABASE_SERVICE_ROLE_KEY", ""))
        and backend.get("SUPABASE_SERVICE_ROLE_KEY") != backend.get("SUPABASE_ANON_KEY"),
        "Completar SUPABASE_SERVICE_ROLE_KEY únicamente en el servidor; debe ser distinta de la clave pública.")
    mobile_public_key = mobile.get("EXPO_PUBLIC_SUPABASE_ANON_KEY", "").strip() or mobile.get("EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "").strip()
    require("Proyecto móvil/backend", mobile.get("EXPO_PUBLIC_SUPABASE_URL", "").rstrip("/") == backend.get("SUPABASE_URL", "").rstrip("/")
        and mobile_public_key == backend.get("SUPABASE_ANON_KEY", "").strip()
        and public_key_valid(mobile_public_key),
        "EXPO_PUBLIC_SUPABASE_URL y la clave anon o publishable deben coincidir con el proyecto del backend.")
    require("API desde Android", valid_url(mobile.get("EXPO_PUBLIC_BACKEND_URL", ""), https=production, public=production),
        "Completar EXPO_PUBLIC_BACKEND_URL accesible desde Android; producción requiere una dirección HTTPS pública.")
    if "API_DOMAIN" in backend:
        domain = backend.get("API_DOMAIN", "").strip().lower()
        domain_valid = bool(re.fullmatch(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}", domain)) and valid_url(f"https://{domain}", https=True, public=True)
        require("Dominio HTTPS de Compose", domain_valid,
            "Configurar API_DOMAIN con un dominio propio, sin protocolo, puerto ni ruta; configurar su DNS hacia el servidor.")
        acme_email = backend.get("ACME_EMAIL", "").strip()
        require("Contacto de certificados", bool(re.fullmatch(r"[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+", acme_email))
            and not acme_email.endswith("@tu-dominio.com"), "Configurar ACME_EMAIL con el correo del administrador para los certificados HTTPS.")
        try:
            domain_consistent = (domain_valid and urlparse(mobile.get("EXPO_PUBLIC_BACKEND_URL", "")).hostname == domain
                and urlparse(backend.get("GOOGLE_REDIRECT_URI", "")).hostname == domain)
        except ValueError:
            domain_consistent = False
        require("Dominio de app y OAuth", domain_consistent,
            "EXPO_PUBLIC_BACKEND_URL y GOOGLE_REDIRECT_URI deben utilizar el mismo API_DOMAIN de Caddy.")

    provider = backend.get("AI_PROVIDER", "demo")
    require("Proveedor IA", provider in {"ollama", "openai_compatible"}, "Elegir AI_PROVIDER=ollama u openai_compatible; demo no usa un modelo real.")
    require("Endpoint IA", valid_url(backend.get("AI_BASE_URL", ""), https=production and provider == "openai_compatible"),
        "Configurar AI_BASE_URL accesible desde el servidor; una API externa en producción requiere HTTPS.")
    require("Modelo IA", configured(backend.get("AI_MODEL", "")), "Completar AI_MODEL con un modelo instalado o disponible en el proveedor.")
    if provider == "openai_compatible" and not configured(backend.get("AI_API_KEY", "")):
        checks.append(Check("Autenticación del proveedor IA", "warning", "AI_API_KEY está vacía; comprobar que el endpoint elegido permite solicitudes sin clave."))

    require("Cliente OAuth Google", configured(backend.get("GOOGLE_CLIENT_ID", "")) and backend.get("GOOGLE_CLIENT_ID", "").endswith(".apps.googleusercontent.com"),
        "Configurar GOOGLE_CLIENT_ID de un cliente OAuth web propio en Google Cloud.")
    require("Secreto OAuth Google", configured(backend.get("GOOGLE_CLIENT_SECRET", "")), "Completar GOOGLE_CLIENT_SECRET únicamente en el servidor.")
    callback = backend.get("GOOGLE_REDIRECT_URI", "")
    require("Callback OAuth", valid_url(callback, https=production, public=production)
        and urlparse(callback).path == "/api/mail/google/callback" and not urlparse(callback).query,
        "GOOGLE_REDIRECT_URI debe terminar en /api/mail/google/callback y registrarse exactamente en Google Cloud; producción requiere HTTPS público.")
    try:
        key = backend.get("TOKEN_ENCRYPTION_KEY", "").encode("ascii")
        encryption_valid = len(base64.b64decode(key, altchars=b"-_", validate=True)) == 32
    except (ValueError, UnicodeError):
        encryption_valid = False
    require("Cifrado de tokens", encryption_valid, "Generar TOKEN_ENCRYPTION_KEY con Fernet y conservarla estable en el servidor.", "Formato Fernet válido; la custodia y el respaldo deben verificarse al desplegar.")
    mail_switch = backend.get("MAIL_SEND_ENABLED", "false").strip().lower()
    require("Interruptor de correo", mail_switch in {"true", "false"}, "MAIL_SEND_ENABLED solo admite true o false.")
    if mail_switch != "true":
        checks.append(Check("Envíos reales", "warning", "Envíos deshabilitados. Mantener MAIL_SEND_ENABLED=false hasta validar OAuth, fuentes y una prueba controlada autorizada."))

    try:
        sources = json.loads(backend.get("AUTHORIZED_JOB_FEEDS", "[]"))
        valid_sources = isinstance(sources, list) and 1 <= len(sources) <= 20
        identifiers: set[str] = set()
        if valid_sources:
            for source in sources:
                source_id = source.get("id") if isinstance(source, dict) else None
                if (not isinstance(source_id, str) or not source_id.strip() or source_id in identifiers
                    or source.get("authorized") is not True or not valid_url(source.get("url", ""), https=True, public=True)
                    or source.get("recipient_verification") != "source_attestation"):
                    valid_sources = False
                    break
                identifiers.add(source_id)
    except (ValueError, TypeError):
        valid_sources = False
    require("Fuentes y destinatarios", valid_sources,
        "AUTHORIZED_JOB_FEEDS necesita 1–20 fuentes JSON HTTPS públicas, IDs únicos, authorized:true y recipient_verification:source_attestation respaldado por el proveedor.",
        "Contrato de fuentes configurado; falta comprobar permisos, DNS, vigencia y correos verificados con cada proveedor.")
    try:
        ZoneInfo(backend.get("DEFAULT_TIMEZONE", "America/Argentina/Buenos_Aires"))
        timezone_valid = True
    except (ZoneInfoNotFoundError, ValueError):
        timezone_valid = False
    require("Zona horaria", timezone_valid, "DEFAULT_TIMEZONE debe ser una zona IANA existente.")
    try:
        worker_valid = 1 <= int(backend.get("WORKER_BATCH_SIZE", "10")) <= 50
    except ValueError:
        worker_valid = False
    require("Lote del worker", worker_valid, "WORKER_BATCH_SIZE debe ser un entero entre 1 y 50.")
    try:
        cors = json.loads(backend.get("CORS_ORIGINS", "[]"))
        cors_valid = isinstance(cors, list) and all(isinstance(origin, str) and valid_url(origin, https=production) for origin in cors)
    except (ValueError, TypeError):
        cors_valid = False
    require("Orígenes web", cors_valid, "CORS_ORIGINS debe ser un array JSON de orígenes HTTP/HTTPS explícitos; producción requiere HTTPS.", "Orígenes web explícitos; Android nativo no requiere CORS.")
    checks.append(Check("Verificaciones pendientes", "warning", "Aplicar migraciones, configurar SMTP/OTP, probar IA real, conectar Gmail por usuario, comprobar fuentes, ejecutar API y worker y probar Android. Este script no verifica ni ejecuta esas operaciones."))
    return checks


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-env", type=Path, default=root / "backend/.env")
    parser.add_argument("--mobile-env", type=Path, default=root / "mobile/.env")
    parser.add_argument("--mode", choices=("demo", "real"), default="real")
    parser.add_argument("--profile", choices=("development", "production"), default="production")
    parser.add_argument("--json", action="store_true", help="Salida JSON sin valores de configuración ni secretos.")
    args = parser.parse_args(argv)
    try:
        backend, mobile = read_env(args.backend_env), read_env(args.mobile_env)
        for key, value in os.environ.items():
            if key.startswith("EXPO_PUBLIC_"):
                mobile[key] = value
            else:
                backend[key] = value
        checks = validate_runtime(backend, mobile, mode=args.mode, profile=args.profile)
    except (ValueError, OSError):
        checks = [Check("Lectura .env", "error", "No se pudo leer un archivo .env válido; revisar permisos y asignaciones de una línea sin expansión de variables.")]
    passed = not any(check.status == "error" for check in checks)
    if args.json:
        print(json.dumps({"configuration_valid": passed, "services_verified": False, "mail_operation_performed": False,
            "checks": [asdict(check) for check in checks]}, ensure_ascii=False, indent=2))
    else:
        for check in checks:
            label = {"ok": "OK", "warning": "PENDIENTE", "error": "FALTA"}[check.status]
            print(f"[{label}] {check.name}: {check.detail}")
        print("Configuración coherente; verificación real pendiente." if passed else "Configuración incompleta; las integraciones reales aún no están preparadas.")
        print("No se hicieron solicitudes de red ni envíos; los valores y secretos no se muestran.")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

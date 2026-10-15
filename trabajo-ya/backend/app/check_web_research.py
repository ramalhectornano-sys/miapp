"""Run a real, bounded Tavily/Groq job investigation without DB or Gmail access.

Keys are read only from environment variables. Reports contain public findings,
provider receipts and timestamps, never headers, prompts, CVs or credentials.
Unit tests use MockTransport; only a report with real provider responses is
evidence of a live run. See docs/PRUEBA_WEB_REAL.md.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

import httpx

from .config import Settings

DEFAULT_SEARCH = {
    "roles": ["Chofer"], "cities": ["Rincón de los Sauces"],
    "city": "Rincón de los Sauces", "province": "Neuquén", "country": "Argentina",
    "radius_km": 100, "research_mode": "general",
}
EVENT_FIELDS = frozenset({
    "kind", "event", "event_id", "provider", "source_id", "status", "query",
    "query_index", "query_kind", "started_at", "finished_at", "http_status",
    "provider_response_received", "request_id", "credits", "result_count",
    "result_urls", "source_hosts", "error", "url", "reason", "source_url",
    "model", "batch_index", "input_count", "discarded_count", "usage",
})
LOCATION_FIELDS = frozenset({
    "id", "city", "province", "province_id", "country", "country_code",
    "latitude", "longitude", "provider", "source_url", "resolved_at",
    "attribution", "coordinate_type", "verified", "distance_km",
})
GEOGRAPHY_FIELDS = frozenset({
    "location_verified", "distance_km", "within_radius", "distance_type",
    "location_status", "warnings",
})
PAGE_FIELDS = frozenset({
    "status", "url", "final_url", "http_status", "checked_at", "fetched_at",
    "reason", "robots_allowed", "terms_allowed", "source", "error",
})


def _now():
    return datetime.now(timezone.utc).isoformat()


def _secrets(settings):
    return tuple(value for name, value in vars(settings).items()
        if any(part in name for part in ("key", "secret", "token"))
        and isinstance(value, str) and value)


def _public(value, private):
    """Defense in depth, including provider errors that echo a configured key."""
    if isinstance(value, str):
        for secret in private:
            value = value.replace(secret, "[REDACTADO]")
        return value[:8000]
    if isinstance(value, dict):
        return {str(name): _public(item, private) for name, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_public(item, private) for item in value[:250]]
    return value if value is None or type(value) in (bool, int, float) else None


def _safe_url(value):
    from .services.web_search import public_result_url
    return value if isinstance(value, str) and public_result_url(value) else None


def _pick(value, names):
    return {key: value[key] for key in names if key in value} if isinstance(value, dict) else {}


def _public_location(value):
    return _pick(value, LOCATION_FIELDS)


def _public_job(job):
    if not isinstance(job, dict) or not _safe_url(job.get("url")):
        return None
    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
    geography = job.get("geography", payload.get("geography", {}))
    verification = job.get("page_verification", payload.get("page_verification", {}))
    result = _pick(job, {"company", "title", "city", "province", "country", "requirements", "application_method", "published_at", "valid_until"})
    result.update({"url": job["url"], "source_host": urlsplit(job["url"]).hostname,
        "geography": _pick(geography, GEOGRAPHY_FIELDS),
        "page_verification": _pick(verification, PAGE_FIELDS),
        "validity": _pick(payload.get("validity", {}), {"status", "published_at", "valid_until"}),
        "application": _pick(payload.get("application", {}), {"method", "url"}),
        "requires_manual_review": True, "email_sent": False})
    if isinstance(geography, dict) and isinstance(geography.get("location"), dict):
        result["geography"]["location"] = _public_location(geography["location"])
    application_url = _safe_url(job.get("application_url"))
    if application_url:
        result["application_url"] = application_url
    # Email addresses are unnecessary to prove discovery. No recipient is
    # endorsed by this report and no CV or user profile is involved.
    return result


def _provider(url):
    host, path = (url.host or "").lower(), url.path
    if host == "api.tavily.com" and path == "/search":
        return "tavily"
    if host == "api.groq.com" and path.startswith("/openai/"):
        return "groq"
    if host == "apis.datos.gob.ar" and path.startswith("/georef/"):
        return "georef_ar"
    return "public_page"


def preflight(settings):
    missing = [name for name, value in (
        ("WEB_SEARCH_API_KEY", settings.web_search_api_key), ("AI_API_KEY", settings.ai_api_key)) if not value.strip()]
    invalid = []
    if settings.web_search_provider != "tavily":
        invalid.append("WEB_SEARCH_PROVIDER")
    if settings.ai_provider != "openai_compatible":
        invalid.append("AI_PROVIDER")
    try:
        base = urlsplit(settings.ai_base_url)
        valid_groq = (base.scheme == "https" and base.hostname == "api.groq.com"
            and base.port in {None, 443} and base.username is None and base.password is None
            and not base.query and not base.fragment and base.path.rstrip("/") == "/openai/v1")
    except ValueError:
        valid_groq = False
    if not valid_groq:
        invalid.append("AI_BASE_URL")
    return missing, invalid


async def check(settings, search=None, *, max_queries=8, max_pages=6, runner=None, transport=None):
    """Return an auditable report, including an explicit report on preflight failure."""
    search = dict(DEFAULT_SEARCH if search is None else search)
    started = _now()
    missing, invalid = preflight(settings)
    report = {
        "schema_version": 1, "test": "Trabajo YA: investigación web real Tavily + Groq",
        "started_at": started, "finished_at": None, "search": search,
        "budget": {"max_tavily_queries": max_queries, "max_public_pages": max_pages,
            "tavily_search_depth": "basic", "automatic_retries": False},
        "missing_environment_variables": missing, "invalid_environment_variables": invalid,
        "actual_tavily_calls": 0, "tavily_response_count": 0, "provider_consulted": False,
        "groq_response_count": 0, "georef_response_count": 0,
        "test_passed": False, "status": "preflight_failed" if missing or invalid else "running",
        "results": [], "discoveries": [], "audit_events": [], "http_events": [], "failures": [],
        "email_sent": False, "database_accessed": False,
        "limitations": ["Una búsqueda no garantiza vacantes disponibles.",
            "Las distancias usan centroides y kilómetros aéreos aproximados, no trayectos por carretera.",
            "Este informe no autoriza ni ejecuta postulaciones ni verifica destinatarios de correo."],
    }
    if missing or invalid:
        report["finished_at"] = _now()
        report["failures"] = ["Falta completar la configuración indicada. No se consultó Tavily ni Groq."]
        return report
    if type(max_queries) is not int or not 1 <= max_queries <= 12 or type(max_pages) is not int or not 1 <= max_pages <= 6:
        raise ValueError("El presupuesto excede los límites de la prueba.")
    settings.web_search_max_queries = max_queries
    settings.public_page_max_reads = max_pages
    private = _secrets(settings)

    async def audit(event):
        if isinstance(event, dict):
            report["audit_events"].append(_public(_pick(event, EVENT_FIELDS), private))

    async def request_hook(request):
        provider = _provider(request.url)
        report["http_events"].append({"event": "request_started", "provider": provider,
            "at": _now(), "method": request.method,
            "endpoint": str(request.url.copy_with(query=None, fragment=None))})

    async def response_hook(response):
        request = response.request
        report["http_events"].append({"event": "response_received", "provider": _provider(request.url),
            "at": _now(), "http_status": response.status_code,
            "endpoint": str(request.url.copy_with(query=None, fragment=None))})

    try:
        if runner is None:
            from .services.research import run_research
            runner = run_research
        async with httpx.AsyncClient(follow_redirects=False, transport=transport,
                event_hooks={"request": [request_hook], "response": [response_hook]}) as client:
            data = await runner(settings, client, search, audit=audit)
        if not isinstance(data, dict):
            raise ValueError("No research envelope")
        enriched = data.get("search", {})
        if isinstance(enriched, dict):
            report["search_location"] = _public_location(enriched.get("location"))
            report["geography_warnings"] = enriched.get("geography_warnings", [])
            report["nearby_cities"] = [_public_location(value) for value in enriched.get("nearby_cities", []) if isinstance(value, dict)]
        report["results"] = [result for job in data.get("results", []) if (result := _public_job(job))]
        for value in data.get("discoveries", []):
            if isinstance(value, dict) and _safe_url(value.get("url")):
                report["discoveries"].append({"url": value["url"], "title": value.get("title"),
                    "source_host": urlsplit(value["url"]).hostname,
                    "page_verification": _pick(value.get("page_verification", {}), PAGE_FIELDS),
                    "status": "pending_review"})
        report["failures"].extend(data.get("failures", []) if isinstance(data.get("failures"), list) else [])
        report["coverage_warnings"] = data.get("warnings", []) if isinstance(data.get("warnings"), list) else []
        outside = data.get("outside_radius_count", 0)
        report["outside_radius_count"] = outside if type(outside) is int and outside >= 0 else 0
        report["status"] = "evaluating"
    except Exception:
        # No exception text/traceback: upstream errors may include a URL, header
        # or token. Sanitized service audit events preserve the actual cause.
        report["status"] = "failed"
        report["failures"].append("La investigación no terminó. Revisá los errores saneados del historial y la configuración de los proveedores.")
    requests = [event for event in report["http_events"] if event["event"] == "request_started"]
    responses = [event for event in report["http_events"] if event["event"] == "response_received"]
    report["actual_tavily_calls"] = sum(event["provider"] == "tavily" for event in requests)
    for provider, name in (("tavily", "tavily_response_count"), ("groq", "groq_response_count"), ("georef_ar", "georef_response_count")):
        report[name] = sum(event["provider"] == provider for event in responses)
    report["provider_consulted"] = report["tavily_response_count"] > 0
    report["tavily_successful_queries"] = sum(event.get("kind") == "tavily_query"
        and event.get("event") == "completed" and event.get("status") == "succeeded"
        and event.get("http_status") == 200 and event.get("provider_response_received") is True
        for event in report["audit_events"])
    report["tavily_credits_reported"] = sum(event.get("credits", 0) for event in report["audit_events"]
        if event.get("kind") == "tavily_query" and event.get("event") == "completed"
        and type(event.get("credits")) in (int, float))
    report["verified_within_radius_count"] = sum(job["geography"].get("within_radius") is True
        and job["geography"].get("location_verified") is True
        and job["page_verification"].get("status") == "verified_link" for job in report["results"])
    required = {
        "tavily": report["tavily_successful_queries"] > 0 and report["provider_consulted"],
        "groq": any(event["provider"] == "groq" and event["http_status"] == 200 for event in responses)
            and any(event.get("kind") == "analysis" and event.get("provider") == "groq"
                and event.get("status") == "succeeded" and event.get("http_status") == 200
                for event in report["audit_events"]),
        "georef": report.get("search_location", {}).get("verified") is True
            and any(event["provider"] == "georef_ar" and event["http_status"] == 200 for event in responses),
    }
    report["provider_proofs"] = required
    if report["status"] != "failed":
        if not all(required.values()) or report["failures"]:
            report["status"] = "partial"
        elif not report["verified_within_radius_count"]:
            report["status"] = "no_verified_opportunities"
        else:
            report["status"] = "completed"
            report["test_passed"] = True
    if not report["test_passed"] and not report["failures"]:
        report["failures"].append("No se pudo demostrar una oferta con enlace original y ubicación verificados dentro del radio solicitado. No se marca la función como terminada.")
    report["finished_at"] = _now()
    return _public(report, private)


def markdown(report):
    """Link-only readable companion; the JSON is the primary evidence artifact."""
    lines = ["# Trabajo YA — prueba web real", "", f"Estado: `{report['status']}`.",
        f"Inicio UTC: {report['started_at']}. Fin UTC: {report['finished_at']}.", "",
        f"Intentos HTTP a Tavily: {report['actual_tavily_calls']}; respuestas: {report['tavily_response_count']}.",
        f"Respuestas Groq: {report['groq_response_count']}; GeoRef: {report['georef_response_count']}.",
        f"Ofertas con enlace y ubicación verificados dentro del radio: {report.get('verified_within_radius_count', 0)}.",
        "", "No se enviaron correos ni se accedió a perfiles, CV o base de datos.", "", "## Ofertas analizadas", ""]
    for job in report["results"]:
        geography = job.get("geography", {})
        lines.append(f"- {job.get('title', 'Sin título')} — {job.get('company', 'Sin empresa')} — {job.get('city', 'Ubicación pendiente')}: {job['url']} · ubicación `{geography.get('location_status', 'pending_review')}`, dentro del radio `{geography.get('within_radius')}`.")
    if not report["results"]:
        lines.append("No hay ofertas verificadas para mostrar. Los descubrimientos no son vacantes confirmadas.")
    lines.extend(["", "## Enlaces descubiertos, pendientes de revisión", ""])
    lines.extend(f"- {item['url']}" for item in report["discoveries"])
    lines.extend(["", "## Consultas y comprobantes", ""])
    for event in report["audit_events"]:
        if event.get("kind") == "tavily_query" and event.get("event") == "completed":
            lines.append(f"- {event.get('finished_at')} · `{event.get('query')}` · HTTP `{event.get('http_status')}` · estado `{event.get('status')}` · request_id `{event.get('request_id', 'no informado')}` · créditos `{event.get('credits', 'no informados')}`.")
    if report["missing_environment_variables"]:
        lines.extend(["", "Faltan secretos: " + ", ".join(report["missing_environment_variables"]) + "."])
    if report["invalid_environment_variables"]:
        lines.extend(["", "Configuración por revisar: " + ", ".join(report["invalid_environment_variables"]) + "."])
    if report["failures"]:
        lines.extend(["", "## Límites y errores", ""])
        lines.extend(f"- {message}" for message in report["failures"])
    return "\n".join(lines) + "\n"


def _integer_between(minimum, maximum):
    def bounded(value):
        number = int(value)
        if not minimum <= number <= maximum:
            raise argparse.ArgumentTypeError(f"Debe estar entre {minimum} y {maximum}.")
        return number
    return bounded


def main(argv=None):
    parser = argparse.ArgumentParser(description="Prueba real Tavily/Groq sin base de datos ni envíos de correo.")
    parser.add_argument("--role", default="Chofer")
    parser.add_argument("--city", default="Rincón de los Sauces")
    parser.add_argument("--province", default="Neuquén")
    parser.add_argument("--country", default="Argentina")
    parser.add_argument("--radius-km", type=_integer_between(0, 1000), default=100)
    parser.add_argument("--max-queries", type=_integer_between(1, 12), default=8)
    parser.add_argument("--max-pages", type=_integer_between(1, 6), default=6)
    parser.add_argument("--output", default="web-research-report.json")
    args = parser.parse_args(argv)
    search = {"roles": [args.role], "cities": [args.city], "city": args.city,
        "province": args.province, "country": args.country, "radius_km": args.radius_km,
        "research_mode": "general"}
    try:
        settings = Settings.from_env()
    except Exception:
        # Invalid JSON/numeric environment values must not produce a traceback
        # that could echo the offending private configuration.
        settings = Settings(web_search_provider="tavily", ai_provider="openai_compatible",
            ai_base_url="https://api.groq.com/openai/v1")
        report = asyncio.run(check(settings, search,
            max_queries=args.max_queries, max_pages=args.max_pages))
        report["missing_environment_variables"] = []
        report["invalid_environment_variables"] = ["SERVER_ENVIRONMENT"]
        report["failures"] = ["No se pudo interpretar la configuración privada del entorno. No se consultó ningún proveedor."]
    else:
        report = asyncio.run(check(settings, search,
            max_queries=args.max_queries, max_pages=args.max_pages))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output.with_suffix(".md").write_text(markdown(report), encoding="utf-8")
    # A small fixed allowlist is sufficient in CI logs; the full public report
    # is an artifact. Do not print environment/config objects or tracebacks.
    print(json.dumps({key: report[key] for key in ("status", "test_passed", "actual_tavily_calls",
        "tavily_response_count", "groq_response_count", "georef_response_count",
        "missing_environment_variables", "invalid_environment_variables")}, ensure_ascii=False))
    return 0 if report["test_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

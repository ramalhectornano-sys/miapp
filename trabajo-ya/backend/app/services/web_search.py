"""Bounded web discovery via a configured search API, followed by grounded IA.

Only the fixed provider endpoint is requested. Result links are never fetched,
and a web excerpt can never authorize an email or an automatic application.
"""
import ipaddress
import json
import re
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlsplit

import httpx
from fastapi import HTTPException

from ..config import Settings
from .job_evidence import MAX_RESULTS, extract_job_evidence

TAVILY_ENDPOINT = "https://api.tavily.com/search"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_QUERY_RESULTS = 5
MAX_QUERY_PART_CHARS = 160
MAX_RESULT_TITLE_CHARS = 300
MAX_RESULT_CONTENT_CHARS = 1600
PRIVATE_QUERY_KEYS = frozenset({"access_token", "refresh_token", "token", "key", "api_key", "secret", "password", "code"})
SEARCH_FAILURE = "No se pudo consultar el buscador web. La búsqueda no se completó."


def public_result_url(value) -> bool:
    """Validate public HTTPS syntax without DNS requests or URL normalization."""
    try:
        if not isinstance(value, str) or len(value) > 2000 or any(char.isspace() for char in value):
            return False
        parsed = urlsplit(value)
        hostname = (parsed.hostname or "").lower().rstrip(".")
        if (parsed.scheme != "https" or not hostname or parsed.username is not None
                or parsed.password is not None or parsed.fragment or parsed.port == 0):
            return False
        if any(key.casefold() in PRIVATE_QUERY_KEYS for key, _ in parse_qsl(parsed.query)):
            return False
        try:
            return ipaddress.ip_address(hostname).is_global
        except ValueError:
            return ("." in hostname and not re.fullmatch(r"[0-9.]+", hostname)
                and hostname not in {"localhost", "localhost.localdomain"}
                and not hostname.endswith((".local", ".internal", ".localhost", ".lan", ".home", ".invalid", ".test")))
    except (TypeError, ValueError):
        return False


def _queries(search: dict, limit: int) -> tuple[list[str], bool]:
    parts = {}
    for field in ("roles", "cities"):
        raw = search.get(field)
        if not isinstance(raw, list) or not 1 <= len(raw) <= 20:
            raise HTTPException(503, "La búsqueda web requiere puestos y ciudades guardados.")
        values = []
        for value in raw:
            if not isinstance(value, str) or not value.strip() or len(value) > MAX_QUERY_PART_CHARS:
                raise HTTPException(503, "La búsqueda web requiere puestos y ciudades válidos.")
            value = " ".join(value.split())
            if value not in values:
                values.append(value)
        if not values:
            raise HTTPException(503, "La búsqueda web requiere puestos y ciudades guardados.")
        parts[field] = values
    # Rotating roles and cities exposes both dimensions before repeating one.
    # Each pair is queried at most once, even when the lists have duplicates.
    all_pairs = [(role, city) for role in parts["roles"] for city in parts["cities"]]
    pairs = []
    for index in range(max(len(parts["roles"]), len(parts["cities"]))):
        pair = (parts["roles"][index % len(parts["roles"])], parts["cities"][index % len(parts["cities"])])
        if pair not in pairs:
            pairs.append(pair)
    pairs.extend(pair for pair in all_pairs if pair not in pairs)
    return [f'vacantes empleo "{role}" "{city}"' for role, city in pairs[:limit]], len(pairs) > limit


def _provider_failure(status_code: int) -> str:
    if status_code in {401, 403}:
        return "El buscador web no aceptó la clave configurada en el servidor."
    if status_code == 429:
        return "El buscador web alcanzó su límite temporal de consultas."
    if status_code in {432, 433}:
        return "El buscador web agotó su cupo de consultas."
    if status_code in {400, 422}:
        return "El buscador web rechazó la configuración de la consulta."
    return "El buscador web no respondió correctamente."


def _safe_metadata(payload: dict, query: str, fetched_at: str, private_values: tuple[str, ...]) -> dict:
    metadata = {"provider": "tavily", "query": query, "fetched_at": fetched_at}
    request_id = payload.get("request_id")
    if (isinstance(request_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", request_id)
            and not any(secret in request_id for secret in private_values)):
        metadata["request_id"] = request_id
    usage = payload.get("usage")
    credits = usage.get("credits") if isinstance(usage, dict) else None
    if type(credits) in {int, float} and 0 <= credits <= 1000:
        metadata["credits"] = credits
    return metadata


async def _query(client: httpx.AsyncClient, key: str, query: str, private_values: tuple[str, ...]) -> list[dict]:
    try:
        async with client.stream("POST", TAVILY_ENDPOINT,
                headers={"Authorization": f"Bearer {key}"},
                json={"query": query, "search_depth": "basic", "auto_parameters": False,
                    "topic": "general", "max_results": MAX_QUERY_RESULTS,
                    "include_answer": False, "include_raw_content": False, "include_usage": True},
                follow_redirects=False, timeout=30) as response:
            if response.status_code != 200:
                raise HTTPException(502, _provider_failure(response.status_code))
            length, chunks = 0, []
            async for chunk in response.aiter_bytes():
                length += len(chunk)
                if length > MAX_RESPONSE_BYTES:
                    raise HTTPException(502, "El buscador web devolvió una respuesta demasiado grande.")
                chunks.append(chunk)
        payload = json.loads(b"".join(chunks))
        if (not isinstance(payload, dict) or payload.get("error") or not isinstance(payload.get("results"), list)
                or len(payload["results"]) > MAX_QUERY_RESULTS):
            raise ValueError("Respuesta sin resultados válidos.")
        metadata = _safe_metadata(payload, query, datetime.now(timezone.utc).isoformat(), private_values)
        results = []
        for raw in payload["results"]:
            if not isinstance(raw, dict) or not public_result_url(raw.get("url")):
                continue
            title, content = raw.get("title", ""), raw.get("content", "")
            if not isinstance(title, str) or not isinstance(content, str) or not (title.strip() or content.strip()):
                continue
            if any(secret in value for secret in private_values for value in (raw["url"], title, content)):
                continue
            results.append({"url": raw["url"], "title": title[:MAX_RESULT_TITLE_CHARS],
                "content": content[:MAX_RESULT_CONTENT_CHARS], "web_search": metadata})
        return results
    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError, TypeError, KeyError, OverflowError):
        raise HTTPException(502, SEARCH_FAILURE) from None


async def discover_web_jobs(settings: Settings, client: httpx.AsyncClient, search: dict,
        source_id: str = "web:tavily") -> tuple[list[dict], list[str]]:
    """Return evidence-backed discoveries and safe warnings about partial work.

    Credentials and provider failures never reach the saved evidence. Successful
    empty results are valid; failed provider requests or extraction are not.
    """
    if getattr(settings, "web_search_provider", "disabled") != "tavily":
        raise HTTPException(503, "No hay un buscador web real configurado en el servidor.")
    key = getattr(settings, "web_search_api_key", "").strip()
    if not key:
        raise HTTPException(503, "Falta configurar la clave privada del buscador web en el servidor.")
    configured_limit = getattr(settings, "web_search_max_queries", 2)
    if type(configured_limit) is not int:
        raise HTTPException(503, "El límite de consultas del buscador web no es válido.")
    queries, limited = _queries(search, min(max(configured_limit, 1), 6))
    private_values = tuple(value for value in (key, settings.ai_api_key) if isinstance(value, str) and value)
    if any(secret in query for secret in private_values for query in queries):
        raise HTTPException(503, "La consulta contiene información privada que no puede enviarse al buscador web.")
    batches, failures, failed_queries, reasons = [], [], 0, []
    for index, query in enumerate(queries, 1):
        try:
            batches.append(await _query(client, key, query, private_values))
        except HTTPException as error:
            failed_queries += 1
            reasons.append(error.detail)
            failures.append(f"{source_id}: consulta {index} no completada")
    if failed_queries == len(queries):
        reason = reasons[0] if reasons and all(value == reasons[0] for value in reasons) else SEARCH_FAILURE
        raise HTTPException(502, f"{reason} No se completó ninguna consulta web.") from None
    if limited:
        failures.append(f"{source_id}: quedaron combinaciones sin consultar por el límite de consultas")
    # Round robin prevents the first query's results from filling the IA budget.
    results, seen = [], set()
    for row_index in range(MAX_QUERY_RESULTS):
        for batch in batches:
            if row_index < len(batch) and batch[row_index]["url"] not in seen:
                result = batch[row_index]
                seen.add(result["url"])
                results.append(result)
                if len(results) == MAX_RESULTS:
                    break
        if len(results) == MAX_RESULTS:
            break
    if not results:
        return [], failures
    jobs = await extract_job_evidence(settings, client, search, results, source_id)
    metadata_by_url = {result["url"]: result["web_search"] for result in results}
    for job in jobs:
        # Defense in depth: web discoveries cannot become source attestations,
        # even if a future extractor accidentally adds a verification flag.
        job["recipient_verified"] = False
        job.pop("recipient_verified_at", None)
        job["requires_manual_review"] = True
        job.setdefault("payload", {})["requires_manual_verification"] = True
        job["payload"]["requires_manual_review"] = True
        job["payload"]["web_search"] = metadata_by_url.get(job.get("url"), {})
    return jobs, failures

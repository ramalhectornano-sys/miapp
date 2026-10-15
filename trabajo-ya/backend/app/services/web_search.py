"""Bounded web discovery via a configured search API, followed by grounded IA.

Only the fixed provider endpoint is requested. Result links are never fetched,
and a web excerpt can never authorize an email or an automatic application.
"""
import ipaddress
import json
import re
from datetime import datetime, timezone
from typing import Awaitable, Callable
from uuid import uuid4
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from fastapi import HTTPException

from ..config import Settings
from .job_evidence import MAX_RESULTS, extract_job_evidence
from .query_planner import (MAX_PLAN_QUERIES, employer_follow_up, has_geographic_context,
    legacy_queries, plan_queries)

TAVILY_ENDPOINT = "https://api.tavily.com/search"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_QUERY_RESULTS = 5
MAX_DISCOVERY_RESULTS = 24
AuditCallback = Callable[[dict], Awaitable[None]]
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
    """Compatibility helper for legacy callers; rich plans use plan_queries."""
    return legacy_queries(search, limit)


def canonical_result_url(value: str) -> str:
    """Deduplicate public tracking variants without inventing an original URL."""
    parsed = urlsplit(value)
    query = [(key, content) for key, content in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_") and key.casefold() not in {
            "gclid", "fbclid", "msclkid", "mc_cid", "mc_eid"}]
    host = (parsed.hostname or "").lower()
    host = f"[{host}]" if ":" in host else host
    netloc = host if parsed.port in {None, 443} else f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path.rstrip("/") or "/", urlencode(sorted(query)), ""))


async def _audit(callback: AuditCallback | None, event: dict):
    if callback is not None:
        # An audit write failure stops the research; it must not erase failures
        # or permit a run to be shown as verified without its request history.
        try:
            await callback(dict(event))
        except Exception:
            raise HTTPException(503, "No se pudo guardar el historial de consultas web. La investigación no se completó.") from None


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


async def _query(client: httpx.AsyncClient, key: str, query: str, private_values: tuple[str, ...],
        *, audit: AuditCallback | None = None, query_index: int = 1, query_kind: str = "general_vacancies",
        source_id: str = "web:tavily") -> list[dict]:
    started_at = datetime.now(timezone.utc).isoformat()
    context = {"kind": "tavily_query", "event_id": str(uuid4()), "provider": "tavily", "source_id": source_id, "query": query, "query_index": query_index,
        "query_kind": query_kind, "started_at": started_at}
    # started is an intent/attempt record, not proof that Tavily responded.
    await _audit(audit, {**context, "event": "started", "status": "started", "provider_response_received": False})
    status_code = None
    metadata = {}
    try:
        async with client.stream("POST", TAVILY_ENDPOINT,
                headers={"Authorization": f"Bearer {key}"},
                json={"query": query, "search_depth": "basic", "auto_parameters": False,
                    "topic": "general", "max_results": MAX_QUERY_RESULTS,
                    "include_answer": False, "include_raw_content": False, "include_usage": True},
                follow_redirects=False, timeout=30) as response:
            status_code = response.status_code
            if status_code != 200:
                raise HTTPException(502, _provider_failure(status_code))
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
        metadata.update({"query_kind": query_kind, "query_index": query_index, "http_status": status_code})
        results = []
        for raw in payload["results"]:
            if not isinstance(raw, dict) or not public_result_url(raw.get("url")):
                continue
            title, content = raw.get("title", ""), raw.get("content", "")
            if not isinstance(title, str) or not isinstance(content, str) or not (title.strip() or content.strip()):
                continue
            if any(secret in value for secret in private_values for value in (raw["url"], title, content)):
                continue
            result = {"url": raw["url"], "title": title[:MAX_RESULT_TITLE_CHARS],
                "content": content[:MAX_RESULT_CONTENT_CHARS], "web_search": metadata}
            published = raw.get("published_date")
            if (isinstance(published, str) and len(published) <= 100
                    and not any(secret in published for secret in private_values)):
                result["published_date"] = published
            results.append(result)
    except HTTPException as error:
        await _audit(audit, {**context, "event": "completed", "status": "failed",
            "finished_at": datetime.now(timezone.utc).isoformat(), "http_status": status_code,
            "provider_response_received": status_code is not None, "error": str(error.detail),
            "result_urls": [], "source_hosts": []})
        raise
    except (httpx.HTTPError, ValueError, TypeError, KeyError, OverflowError):
        await _audit(audit, {**context, "event": "completed", "status": "failed",
            "finished_at": datetime.now(timezone.utc).isoformat(), "http_status": status_code,
            "provider_response_received": status_code is not None, "error": SEARCH_FAILURE,
            "result_urls": [], "source_hosts": []})
        raise HTTPException(502, SEARCH_FAILURE) from None
    await _audit(audit, {**context, "event": "completed", "status": "succeeded",
        "finished_at": metadata["fetched_at"], "http_status": status_code,
        "provider_response_received": True, "request_id": metadata.get("request_id"),
        "credits": metadata.get("credits"), "result_count": len(results),
        "result_urls": [value["url"] for value in results],
        "source_hosts": sorted({urlsplit(value["url"]).hostname for value in results})})
    return results


async def discover_web_results(settings: Settings, client: httpx.AsyncClient, search: dict,
        source_id: str = "web:tavily", *, audit: AuditCallback | None = None) -> tuple[list[dict], list[str]]:
    """Query the general web and record provider receipts through an optional audit.

    Credentials and raw provider failures never reach saved evidence. Successful
    empty results are valid; failed provider requests are not. The legacy small
    budget remains compatible, while geographic and >=3-query plans investigate
    companies, consultancies, public postings and optional portals.
    """
    if getattr(settings, "web_search_provider", "disabled") != "tavily":
        raise HTTPException(503, "No hay un buscador web real configurado en el servidor.")
    key = getattr(settings, "web_search_api_key", "").strip()
    if not key:
        raise HTTPException(503, "Falta configurar la clave privada del buscador web en el servidor.")
    configured_limit = getattr(settings, "web_search_max_queries", 6)
    if type(configured_limit) is not int:
        raise HTTPException(503, "El límite de consultas del buscador web no es válido.")
    geographic = has_geographic_context(search)
    legacy = not geographic and configured_limit <= 2
    # Old unscoped configurations were capped at six. New geographic runs can
    # spend at most twelve basic Tavily credits, including one follow-up.
    limit = min(max(configured_limit, 1), MAX_PLAN_QUERIES if geographic or 3 <= configured_limit <= MAX_PLAN_QUERIES else 6)
    if legacy:
        queries, limited = _queries(search, limit)
        plan = [{"query": query, "kind": "general_vacancies"} for query in queries]
    else:
        limit_plan = limit - 1 if limit >= 8 else limit
        plan = plan_queries(search, limit_plan)
        queries = [row["query"] for row in plan]
        limited = len(plan_queries(search, MAX_PLAN_QUERIES)) > len(plan)
    private_values = tuple(value for value in (key, settings.ai_api_key,
        getattr(settings, "supabase_service_role_key", ""), getattr(settings, "google_client_secret", ""),
        getattr(settings, "token_encryption_key", "")) if isinstance(value, str) and value)
    if any(secret in query for secret in private_values for query in queries):
        raise HTTPException(503, "La consulta contiene información privada que no puede enviarse al buscador web.")
    batches, failures, failed_queries, reasons = [], [], 0, []
    for index, row in enumerate(plan, 1):
        try:
            batches.append(await _query(client, key, row["query"], private_values, audit=audit,
                query_index=index, query_kind=row["kind"], source_id=source_id))
        except HTTPException as error:
            if error.status_code == 503:
                raise
            failed_queries += 1
            reasons.append(error.detail)
            failures.append(f"{source_id}: consulta {index} no completada")
    if not legacy and len(plan) < limit:
        follow_up = employer_follow_up(search, [result for batch in batches for result in batch], queries)
        if follow_up and not any(secret in follow_up["query"] for secret in private_values):
            plan.append(follow_up)
            index = len(plan)
            try:
                batches.append(await _query(client, key, follow_up["query"], private_values,
                    audit=audit, query_index=index, query_kind=follow_up["kind"], source_id=source_id))
            except HTTPException as error:
                if error.status_code == 503:
                    raise
                failed_queries += 1
                reasons.append(error.detail)
                failures.append(f"{source_id}: consulta {index} no completada")
    if failed_queries == len(plan):
        reason = reasons[0] if reasons and all(value == reasons[0] for value in reasons) else SEARCH_FAILURE
        raise HTTPException(502, f"{reason} No se completó ninguna consulta web.") from None
    if limited:
        failures.append(f"{source_id}: quedaron combinaciones sin consultar por el límite de consultas")
    # Round robin prevents the first query from filling the discovery budget.
    # The original link is retained even when tracking variants are deduplicated.
    results, seen = [], set()
    max_results = MAX_RESULTS if legacy else MAX_DISCOVERY_RESULTS
    for row_index in range(MAX_QUERY_RESULTS):
        for batch in batches:
            if row_index < len(batch):
                result = batch[row_index]
                canonical = canonical_result_url(result["url"])
                if canonical in seen:
                    continue
                seen.add(canonical)
                results.append(result)
                if len(results) == max_results:
                    break
        if len(results) == max_results:
            break
    return results, failures


async def extract_web_jobs(settings: Settings, client: httpx.AsyncClient, search: dict,
        results: list[dict], source_id: str = "web:tavily", *, audit: AuditCallback | None = None) -> list[dict]:
    """Extract manual-review jobs; snippets never become recipient proof."""
    if not results:
        return []
    jobs = await extract_job_evidence(settings, client, search, results, source_id, **({"audit": audit} if audit else {}))
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
    return jobs


async def discover_web_jobs(settings: Settings, client: httpx.AsyncClient, search: dict,
        source_id: str = "web:tavily", *, audit: AuditCallback | None = None) -> tuple[list[dict], list[str]]:
    """Compatible manual-discovery entry point, including IA failure semantics."""
    results, failures = await discover_web_results(settings, client, search, source_id, audit=audit)
    jobs = await extract_web_jobs(settings, client, search, results, source_id, audit=audit)
    return jobs, failures

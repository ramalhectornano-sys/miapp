"""Persist only bounded public request facts under the current worker lease."""
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

from fastapi import HTTPException

from .web_search import public_result_url


class ResearchAuditError(HTTPException):
    audit_failed = True

    def __init__(self):
        super().__init__(503, "No se pudo guardar el historial de consultas. La investigación no se completó; revisá la migración 007 y la reserva de la tarea.")


META_KEYS = frozenset({"query_kind", "parent_url", "content_sha256", "reason", "result_count", "query_index",
    "location_id", "role", "city", "province", "country", "radius_km", "source_id", "attempt",
    "provider_method", "verification_status", "allowed_by", "from_cache", "language", "depth", "http_calls",
    "discovered_count", "eligible_count", "pages_considered", "pages_verified", "geocoding_provider", "model",
    "latency_ms", "timeout_seconds", "error_code"})
PRIVATE_MARKERS = re.compile(r"gsk_[A-Za-z0-9_-]+|tvly-(?:dev-|prod-)?[A-Za-z0-9_-]+|sb_secret_[A-Za-z0-9_-]+|Bearer\s+\S+", re.I)


def sanitized_event(settings, event):
    secrets = tuple(value for value in (settings.web_search_api_key, settings.ai_api_key,
        settings.supabase_service_role_key, settings.google_client_secret, settings.token_encryption_key)
        if isinstance(value, str) and value)

    def safe_text(value, limit):
        if not isinstance(value, str):
            return None
        for secret in secrets:
            value = value.replace(secret, "[dato privado]")
        return PRIVATE_MARKERS.sub("[dato privado]", value).replace("\x00", "")[:limit]

    def safe_url(value):
        if not isinstance(value, str) or not public_result_url(value):
            return None
        # History does not need tracking, fragments or potentially private
        # query parameters. Actual original job links remain in the owned job.
        parsed = urlsplit(value)
        clean = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
        return clean if safe_text(clean, 2048) == clean else None

    try:
        identifier = str(UUID(str(event.get("event_id"))))
    except (ValueError, TypeError):
        identifier = str(uuid4())
    status = event.get("status")
    if status not in {"started", "succeeded", "failed", "blocked"}:
        raise ResearchAuditError()
    started = event.get("started_at") or event.get("checked_at") or datetime.now(timezone.utc).isoformat()
    normalized = {"event_id": identifier, "kind": event.get("kind"),
        "provider": safe_text(event.get("provider"), 80), "query": safe_text(event.get("query"), 1000),
        "url": safe_url(event.get("url")), "status": status, "started_at": started,
        "http_status": event.get("http_status"),
        "provider_request_id": safe_text(event.get("provider_request_id", event.get("request_id")), 128),
        "credits": event.get("credits"), "error": safe_text(event.get("error"), 1000),
        "result_urls": [url for value in event.get("result_urls", [])[:20] if (url := safe_url(value))],
        "source_hosts": [host for value in event.get("source_hosts", [])[:20]
            if (host := safe_text(value, 253)) and re.fullmatch(r"[A-Za-z0-9.-]+", host)],
        "metadata": {}}
    if status != "started":
        normalized["finished_at"] = event.get("finished_at") or event.get("checked_at") or datetime.now(timezone.utc).isoformat()
    meta = {**(event.get("metadata") if isinstance(event.get("metadata"), dict) else {}),
        **{key: value for key, value in event.items() if key in META_KEYS}}
    for key, value in meta.items():
        if key not in META_KEYS:
            continue
        if key == "parent_url":
            value = safe_url(value)
        elif isinstance(value, str):
            value = safe_text(value, 1000)
        if value is not None and type(value) in {str, bool, int, float}:
            normalized["metadata"][key] = value
    return {key: value for key, value in normalized.items() if value is not None}


def database_audit(db, search):
    async def record(event):
        try:
            saved = await db.rpc("record_web_research_event", {
                "p_search_id": search["id"], "p_run_id": search["run_id"],
                "p_claim_token": search["claim_token"], "p_event": sanitized_event(db.settings, event)})
        except Exception:
            raise ResearchAuditError() from None
        if saved is not True:
            raise ResearchAuditError()
    return record

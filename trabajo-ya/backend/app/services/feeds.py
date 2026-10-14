"""Permitted JSON feeds and configured web-search APIs; no simulated discovery."""
import asyncio
import hashlib
import ipaddress
import json
import re
import socket
from datetime import datetime, timezone
from urllib.parse import urlparse
import httpx
from fastapi import HTTPException

from ..db import Database, User
from .ai import normalize


def fingerprint(job: dict) -> str:
    # URL when supplied is the source's stable canonical vacancy URL.
    identity = [normalize(str(job.get(key, ""))).strip() for key in ("company", "title", "city")]
    if job.get("url"):
        identity.append(job["url"].split("?")[0].rstrip("/"))
    return hashlib.sha256("\x1f".join(identity).encode()).hexdigest()


async def safe_feed_url(url: str):
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise HTTPException(503, "La fuente autorizada debe usar una URL HTTPS pública.")
    try:
        literal = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        literal = None
    if literal is not None:
        if not literal.is_global:
            raise HTTPException(503, "La fuente no puede apuntar a una red privada.")
        return
    try:
        addresses = await asyncio.to_thread(socket.getaddrinfo, parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise HTTPException(503, "La fuente no puede apuntar a una red privada.")
    except socket.gaierror:
        raise HTTPException(502, "No se pudo resolver la fuente de empleos.")


def normalize_job(raw: dict, source: dict, user_id: str) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("La vacante debe ser un objeto.")
    if "is_active" in raw and not isinstance(raw["is_active"], bool):
        raise ValueError("La vigencia de la vacante debe ser booleana.")
    status = raw.get("status", "")
    if not isinstance(status, str):
        raise ValueError("El estado de la vacante debe ser texto.")
    if raw.get("is_active") is False or normalize(status.strip()) in {
        "closed", "inactive", "expired", "filled", "cancelled", "canceled",
        "cerrado", "cerrada", "inactivo", "inactiva", "vencido", "vencida",
        "cubierto", "cubierta", "cancelado", "cancelada",
    }:
        raise ValueError("La vacante ya no está vigente.")
    if raw.get("valid_until"):
        if not isinstance(raw["valid_until"], str):
            raise ValueError("La fecha de vigencia debe ser ISO 8601.")
        expiry = datetime.fromisoformat(raw["valid_until"].replace("Z", "+00:00"))
        if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
            raise ValueError("La vacante venció o tiene una fecha sin zona horaria.")
    def text(key, limit, required=False):
        value = raw.get(key, "")
        if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
            raise ValueError(f"Campo inválido: {key}")
        return value.strip()
    # Web discoveries and legitimate feeds may explicitly provide null when
    # applications belong on a portal. Keep those jobs for manual review.
    email = "" if raw.get("recipient_email") is None else text("recipient_email", 254).casefold()
    verified = bool(source.get("kind") != "web_search" and email and re.fullmatch(r"[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+", email)
        and raw.get("recipient_verified") is True and source.get("recipient_verification") == "source_attestation")
    row = {"user_id": user_id, "source": source["id"], "external_id": str(raw["id"])[:200] if raw.get("id") is not None else None,
        "company": text("company", 200, True), "title": text("title", 200, True), "city": text("city", 160, True),
        "url": text("url", 2000) or None, "recipient_email": email or None,
        "recipient_verified_at": datetime.now(timezone.utc).isoformat() if verified else None,
        "source_authorized": True, "is_active": True,
        "last_seen_at": datetime.now(timezone.utc).isoformat(), "description": text("description", 10000),
        "payload": {"integration_id": source["id"], "verification_method": "source_attestation" if verified else None}}
    if row["url"] and urlparse(row["url"]).scheme != "https":
        raise ValueError("Las vacantes deben usar URL HTTPS.")
    if source.get("kind") == "web_search":
        payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else {}
        row["payload"].update({key: payload[key] for key in (
            "evidence", "discovery_origin", "source_id", "observed_at", "validity", "web_search") if key in payload})
        row["payload"]["requires_manual_review"] = True
        row["payload"]["validity_confirmed"] = False
    row["fingerprint"] = fingerprint(row)
    return row


async def find_jobs(db: Database, search: dict) -> tuple[list[dict], list[str]]:
    sources = db.settings.job_sources
    if not sources:
        raise HTTPException(503, "No hay fuentes reales autorizadas configuradas. No se ejecutó ninguna búsqueda.")
    matches, failures, completed_sources = [], [], 0
    for source in sources[:20]:
        try:
            if not source.get("id") or not source.get("authorized"):
                raise ValueError("La fuente no tiene autorización declarada.")
            if source.get("kind") == "web_search":
                from .web_search import discover_web_jobs
                rows, partial_failures = await discover_web_jobs(db.settings, db.client, search, source["id"])
                failures.extend(partial_failures)
            else:
                rows = await read_json_feed(db, source)
            completed_sources += 1
            for raw in rows:
                try:
                    row = normalize_job(raw, source, search["user_id"])
                except (TypeError, ValueError, KeyError):
                    continue
                if any(normalize(role) in normalize(row["title"]) for role in search["roles"]) and any(normalize(city) == normalize(row["city"]) for city in search["cities"]):
                    matches.append(row)
        except (KeyError, ValueError, httpx.HTTPError, HTTPException):
            failures.append(source.get("id", "fuente sin identificador"))
    if not completed_sources:
        raise HTTPException(502, "No se pudo consultar ninguna fuente autorizada. La búsqueda no se completó.")
    unique = {}
    for job in matches:
        previous = unique.get(job["fingerprint"])
        # Prefer a current source attestation to an unverified duplicate. Keep
        # one complete source record: never assemble verification from one
        # integration and a recipient or description from another.
        if previous and previous.get("recipient_verified_at") and not job.get("recipient_verified_at"):
            continue
        unique[job["fingerprint"]] = job
    return list(unique.values()), failures


async def read_json_feed(db: Database, source: dict):
    await safe_feed_url(source["url"])
    async with db.client.stream("GET", source["url"], follow_redirects=False, timeout=30) as response:
        response.raise_for_status()
        chunks, length = [], 0
        async for chunk in response.aiter_bytes():
            length += len(chunk)
            if length > 5 * 1024 * 1024:
                raise ValueError("Fuente demasiado grande")
            chunks.append(chunk)
    payload = json.loads(b"".join(chunks))
    rows = payload.get("jobs") if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or len(rows) > 2000:
        raise ValueError("La fuente requiere un array de hasta 2000 vacantes")
    return rows


RUN_MAX_SECONDS = 900
MAX_JOBS_PER_RUN = 200
PAGE_SIZE = 1000


async def assert_claim(db: Database, search: dict):
    valid = await db.rpc("assert_search_claim", {"p_search_id": search["id"], "p_claim_token": search["claim_token"]})
    if not valid:
        raise HTTPException(409, "La reserva de la tarea venció o fue reemplazada. Se detuvo el procesamiento.")


async def known_records(db: Database, search: dict, table: str, columns: str):
    """Bound every read; the outer deadline also bounds a large user's full scan."""
    rows, offset = [], 0
    while True:
        await assert_claim(db, search)
        page = await db.select(table, None, params={"user_id": f"eq.{search['user_id']}",
            "select": columns, "order": "id", "limit": str(PAGE_SIZE), "offset": str(offset)})
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
        offset += PAGE_SIZE


async def process_automatic_drafts(db: Database, search: dict, user: User):
    """Drain this search's unattempted drafts, including those made before consent.

    The database rechecks the current search and consent and selects its CV and
    sender atomically. A stale worker snapshot cannot restore revoked consent.
    Existing attempts and another search's drafts are never retried or adopted.
    """
    from .mail import send_application
    await assert_claim(db, search)
    current = await db.owned("job_searches", search["id"], user, service=True)
    if current.get("status") != "enabled" or not current.get("auto_apply"):
        return 0, 0
    # A missing configuration must leave drafts pending without claiming attempts.
    if not db.settings.mail_send_enabled:
        return 0, 0
    params = {
        "user_id": f"eq.{user.id}", "search_id": f"eq.{search['id']}",
        "status": "eq.pending", "send_attempt_id": "is.null",
        "delivery_uncertain": "eq.false", "order": "created_at.asc,id.asc",
        "recipient_verified_at": "not.is.null", "recipient_email": "not.is.null",
        "parent_application_id": "is.null",
        "limit": str(PAGE_SIZE),
    }
    allowed_sources = {source["id"] for source in db.settings.job_sources
        if isinstance(source, dict) and source.get("id") and source.get("authorized")}
    prepared_ids, offset = [], 0
    while len(prepared_ids) < MAX_JOBS_PER_RUN:
        if offset:
            await assert_claim(db, search)
        drafts = await db.select("applications", None, params={**params, "offset": str(offset)})
        for draft in drafts:
            await assert_claim(db, search)
            job = await db.owned("jobs", draft["job_id"], user, service=True)
            # Administrator removal of an integration takes effect for old drafts too.
            if job.get("source") not in allowed_sources:
                continue
            prepared = await db.rpc("prepare_automatic_application", {
                "p_application_id": draft["id"], "p_user_id": user.id})
            if prepared:
                prepared_ids.append(draft["id"])
            if len(prepared_ids) >= MAX_JOBS_PER_RUN:
                break
        if len(drafts) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    # Scan before sending: changing pending -> sent during offset pagination
    # would skip rows. Ineligible old drafts must not starve newer valid drafts.
    sent, errors = 0, 0
    for application_id in prepared_ids:
        await assert_claim(db, search)
        try:
            result = await send_application(db, user, application_id, manual=False)
            if result.get("status") in ("sent", "responded"):
                sent += 1
        except HTTPException:
            # A rejected reservation is still pending. Only a reserved, recorded
            # failure is an error; never report that Gmail sent without a receipt.
            updated = await db.owned("applications", application_id, user, service=True)
            if updated.get("send_attempt_id") and updated.get("status") == "error":
                errors += 1
    return sent, errors


async def process_automatic_followups(db: Database, search: dict, user: User, matched_job_ids: set[str]):
    """Make a separate, auditable delivery after fresh first applications.

    The database owns the 72-hour recipient cooldown, global daily budget and
    current consent/observation checks. A receipt or attempted row is never
    cleared to create a resend. Preparing a new child is not a confirmed send.
    """
    from .mail import send_application
    if not matched_job_ids or not db.settings.mail_send_enabled:
        return 0, 0
    await assert_claim(db, search)
    current = await db.owned("job_searches", search["id"], user, service=True)
    if current.get("status") != "enabled" or not current.get("auto_apply") or not current.get("consent_id"):
        return 0, 0
    consent = await db.owned("sending_consents", current["consent_id"], user, service=True)
    if not consent.get("repeat_enabled") or consent.get("policy_version") != "v3":
        return 0, 0
    params = {"user_id": f"eq.{user.id}", "search_id": f"eq.{search['id']}",
        "parent_application_id": "is.null", "status": "eq.sent",
        "provider_message_id": "not.is.null", "provider_confirmed_at": "not.is.null",
        "order": "provider_confirmed_at.asc,id.asc", "limit": str(PAGE_SIZE)}
    candidate_ids, offset = [], 0
    while len(candidate_ids) < MAX_JOBS_PER_RUN:
        await assert_claim(db, search)
        roots = await db.select("applications", None, params={**params, "offset": str(offset)})
        candidate_ids.extend(row["id"] for row in roots if row["job_id"] in matched_job_ids)
        if len(roots) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    sent, errors = 0, 0
    for root_id in candidate_ids[:MAX_JOBS_PER_RUN]:
        await assert_claim(db, search)
        prepared = await db.rpc("prepare_followup_application", {
            "p_root_application_id": root_id, "p_user_id": user.id,
            "p_search_id": search["id"], "p_run_id": search["run_id"],
            "p_claim_token": search["claim_token"]})
        if not prepared:
            continue
        await assert_claim(db, search)
        try:
            result = await send_application(db, user, prepared["id"], manual=False)
            if result.get("status") in ("sent", "responded"):
                sent += 1
        except HTTPException:
            updated = await db.owned("applications", prepared["id"], user, service=True)
            if updated.get("send_attempt_id") and updated.get("status") == "error":
                errors += 1
    return sent, errors


async def execute_claim(db: Database, search: dict):
    from .schedule import next_occurrence
    found, status, message = 0, "error", "La búsqueda no se completó."
    remaining = RUN_MAX_SECONDS
    if search.get("lease_expires_at"):
        expiry = datetime.fromisoformat(search["lease_expires_at"].replace("Z", "+00:00"))
        remaining = min(RUN_MAX_SECONDS, (expiry - datetime.now(timezone.utc)).total_seconds() - 90)
    try:
        if remaining <= 0:
            raise HTTPException(409, "La reserva no tiene tiempo suficiente para iniciar el procesamiento.")
        # The deadline ends before lease expiry, including queries, parsing and sending.
        async with asyncio.timeout(remaining):
            await assert_claim(db, search)
            jobs, failures = await find_jobs(db, search)
            old_jobs = await known_records(db, search, "jobs", "id,fingerprint,source,external_id")
            by_fingerprint = {row["fingerprint"]: row["id"] for row in old_jobs}
            by_external = {(row["source"], row["external_id"]): row["id"] for row in old_jobs if row.get("external_id")}
            old_applications = await known_records(db, search, "applications", "id,job_id,parent_application_id,provider_confirmed_at")
            applied_jobs = {row["job_id"] for row in old_applications}
            latest_confirmation = {}
            for application in old_applications:
                if application.get("provider_confirmed_at"):
                    confirmed = datetime.fromisoformat(application["provider_confirmed_at"].replace("Z", "+00:00")).timestamp()
                    latest_confirmation[application["job_id"]] = max(
                        latest_confirmation.get(application["job_id"], float("-inf")), confirmed)
            candidates, refresh_candidates = [], []
            for row in jobs:
                old_id = by_fingerprint.get(row["fingerprint"]) or by_external.get((row["source"], row.get("external_id")))
                if old_id and (old_id in applied_jobs or not search.get("preferred_resume_id")):
                    refresh_candidates.append((row, old_id))
                    continue
                candidates.append((row, old_id))
            # When a user has many vacancies, rotate the bounded refresh queue
            # by the most recent actual receipt. Feed ordering must not keep
            # the same first 200 companies ahead of older due reminders.
            refresh_candidates.sort(key=lambda candidate: (
                candidate[1] not in applied_jobs,
                latest_confirmation.get(candidate[1], float("-inf"))))
            # Existing fingerprints are excluded before the bound, so future runs make progress.
            pending_count = max(0, len(candidates) - MAX_JOBS_PER_RUN)
            profiles = await db.select("profiles", None, params={"user_id": f"eq.{search['user_id']}", "limit": "1"})
            full_name = profiles[0].get("full_name", "").strip() if profiles else ""
            user = User(search["user_id"], "")
            matched_job_ids = set()
            # Keep new vacancies ahead of recurring ones within this execution.
            # Rediscovery refreshes verification even when an original delivery
            # exists, and produces an observation tied to this exact live run.
            for row, old_id in candidates[:MAX_JOBS_PER_RUN] + refresh_candidates[:MAX_JOBS_PER_RUN]:
                await assert_claim(db, search)
                if old_id:
                    updated = await db.patch("jobs", row, params={"id": f"eq.{old_id}", "user_id": f"eq.{user.id}"})
                    if not updated:
                        continue
                    job = updated[0]
                else:
                    inserted = await db.insert("jobs", row, conflict="user_id,fingerprint")
                    if inserted:
                        found += 1
                        job = inserted[0]
                    else:
                        existing = await db.select("jobs", None, params={"user_id": f"eq.{search['user_id']}",
                            "fingerprint": f"eq.{row['fingerprint']}", "limit": "1"})
                        if not existing:
                            continue
                        job = existing[0]
                await assert_claim(db, search)
                observations = await db.insert("job_search_matches", {"user_id": user.id,
                    "job_id": job["id"], "search_id": search["id"], "run_id": search["run_id"],
                    "roles_snapshot": search.get("roles", []), "cities_snapshot": search.get("cities", [])})
                if not observations:
                    continue
                matched_job_ids.add(job["id"])
                resume_id = search.get("preferred_resume_id")
                if not resume_id or job["id"] in applied_jobs:
                    continue
                connection_params = {"user_id": f"eq.{search['user_id']}", "status": "eq.connected", "limit": "1"}
                if search.get("auto_apply") and search.get("consent_id"):
                    consent = await db.owned("sending_consents", search["consent_id"], user, service=True)
                    connection_params["id"] = f"eq.{consent['email_connection_id']}"
                connections = await db.select("email_connections", None, params=connection_params)
                draft = {"user_id": search["user_id"], "job_id": job["id"], "search_id": search["id"], "resume_id": resume_id,
                    "email_connection_id": connections[0]["id"] if connections else None, "company": job["company"], "job_title": job["title"],
                    "recipient_email": job.get("recipient_email"), "recipient_verified_at": job.get("recipient_verified_at"),
                    "subject": f"Postulación: {job['title']}", "body": f"Hola,\n\n{('Mi nombre es ' + full_name + '. ') if full_name else ''}Me gustaría postularme al puesto de {job['title']} en {job['company']}. Adjunto mi currículum para su consideración.\n\nGracias por su tiempo.\n{full_name}", "status": "pending",
                    "job_match_id": observations[0]["id"]}
                await assert_claim(db, search)
                await db.rpc("create_initial_application", {"p_application": draft})
            sent, send_errors = await process_automatic_drafts(db, search, user)
            repeated, repeat_errors = await process_automatic_followups(db, search, user, matched_job_ids)
            status = "completed"
            message = f"Se consultaron fuentes reales autorizadas: {found} vacantes nuevas."
            if sent:
                message += f" El proveedor confirmó {sent} envíos de postulaciones."
            if repeated:
                message += f" El proveedor confirmó {repeated} recordatorios con un intervalo mínimo de 72 horas."
            if send_errors + repeat_errors:
                message += f" {send_errors + repeat_errors} intentos de envío tienen error; revisá Mis postulaciones."
            if pending_count:
                message += f" Se alcanzó el límite de {MAX_JOBS_PER_RUN} registros; {pending_count} quedan para próximas ejecuciones."
            if failures:
                message += f" {len(failures)} consultas o fuentes no se completaron; resultados parciales."
    except TimeoutError:
        status, message = "error", "Se alcanzó el tiempo máximo de procesamiento. Los resultados parciales se conservan; no se reintentan envíos reservados."
    except HTTPException as error:
        status = "blocked" if error.status_code == 503 else "error"
        message = str(error.detail)
    except Exception:
        status, message = "error", "Ocurrió un error al procesar la fuente. La búsqueda no se completó."
    finally:
        complete = await db.rpc("complete_search_run", {"p_search_id": search["id"], "p_claim_token": search["claim_token"],
            "p_run_id": search["run_id"], "p_status": status, "p_next_run_at": next_occurrence(search).isoformat(),
            "p_found_count": found, "p_message": message})
    if not complete:
        status = "error"
        message = "No se confirmó el registro de la ejecución porque la reserva cambió. Revisá el historial; los resultados parciales pueden haberse conservado."
    return {"run_id": search["run_id"], "status": status, "found_count": found, "message": message,
        "recorded": bool(complete), "mode": "live"}

"""Read published Greenhouse jobs and attest an explicit CV-by-email channel.

Discovery excerpts, model output and general contact addresses never authorize
delivery. Only a fresh official Job Board API response can supply this evidence.
This attests the employer's published instruction, not mailbox deliverability.
"""
import html
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlsplit
from uuid import uuid4

import httpx
from fastapi import HTTPException

from .ai import normalize

SOURCE_ID = "verified:greenhouse"
API_BASE = "https://boards-api.greenhouse.io/v1/boards"
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_DISCOVERIES = 8
BOARD_PATTERN = r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}"
JOB_ID_PATTERN = r"[1-9][0-9]{0,18}"
HOSTS = frozenset({"boards.greenhouse.io", "job-boards.greenhouse.io"})
EMAIL = re.compile(r"(?<![\w.+-])([A-Za-z0-9][A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{0,63}@[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?\.[A-Za-z]{2,63})(?![\w@-])")
SEND_TO_EMAIL = re.compile(r"\b(?:enviar|envia|envie|envies|envianos|envienos|mandar|manda|mande|remitir|remita|send|submit|email|e-mail)\b(?:\s+(?:tu|su|el|un|your|the|a|updated|actualizado|actualizada)){0,4}\s+(?:cv|curriculum(?: vitae)?|resume|application|postulacion)\b(?:\s+(?:actualizado|updated))?(?:\s+(?:por correo|por email|por e-mail|by email|via email|by e-mail|via e-mail))?\s+(?:a|al|to)\s*(?:(?:correo(?: electronico)?|email|e-mail)\s*)?:?\s*$")
APPLY_BY_EMAIL = re.compile(r"\b(?:postulate|postularte|postularse|postular|postula|aplica|aplicar|aplique|apply)\s+(?:por correo|por email|por e-mail|by email|via email|by e-mail|via e-mail)\b(?:\s+(?:a|al|to))?\s*:?\s*$")
NEGATED_ACTION = re.compile(r"\b(?:no|not|never|don't|dont|cannot|can't|shouldn't|shouldnt|mustn't|mustnt|won't|wont|couldn't|couldnt|evitar|evite|avoid|without)(?:\s+\w+){0,5}\s+(?:send|submit|email|e-mail|enviar|envia|envie|mandar|remitir|postulate|postularte|postularse|postular|postula|aplica|aplicar|aplique|apply)\b")
EXCLUDED = re.compile(
    r"\b(?:soporte|support|privacidad|privacy|legal|accesibilidad|accessibility|"
    r"accommodation|accommodations|disability|disabilities|discapacidad|"
    r"ajustes razonables|reasonable adjustment|denuncia|report fraud|fraud|fraude|"
    r"technical assistance|asistencia tecnica|data protection|proteccion de datos|"
    r"no enviar|no envie|no envies|no mandes|no remitir|do not send|don't send|"
    r"no aceptamos|no se aceptan|not accept|never send|no unsolicited|"
    r"formulario|apply online|online application|application portal|portal de empleo|"
    r"questions|inquiries|consultas|preguntas|contact information|informacion de contacto|except|excepto|"
    r"prohibido|prohibida|forbidden|not allowed|not permitted)\b"
)
CLOSED = re.compile(r"\b(?:applications closed|no longer accepting|position filled|job closed|"
    r"vacante (?:cerrada|cubierta|vencida)|oferta (?:cerrada|vencida)|"
    r"no acepta(?:mos|n)? postulaciones|convocatoria finalizada)\b")
REFUSES_EMAIL = re.compile(
    r"\b(?:no\s+(?:se\s+)?(?:aceptan?|aceptamos|admiten?|admitimos|reciben?|recibimos)|"
    r"(?:do not|don't|dont|will not|cannot|can't|never)\s+accept|not accepting)\b"
    r"[^.!?\n]{0,60}\b(?:applications?|resumes?|cvs?|postulaciones?|curriculum|curriculos)\b"
    r"[^.!?\n]{0,40}\b(?:by email|via email|by e-mail|via e-mail|por correo|por email|por e-mail)\b"
)
REFUSES_FOLLOWUP = re.compile(r"\b(?:no follow[- ]?ups?|no follow[- ]?up emails?|no reenvios|no recordatorios|"
    r"one application only|only apply once|do not reapply|do not follow[- ]?up|don't follow[- ]?up|"
    r"no volver a postular|no enviar recordatorios|no envie recordatorios|no envies recordatorios)\b")
INELIGIBLE = "La publicación no confirma una vacante vigente con un canal de CV por correo. Prepará la postulación manualmente."
UNAVAILABLE = "No se pudo verificar la publicación en la API oficial de Greenhouse. No se autorizaron envíos."


def _normalized(value: str) -> str:
    return " ".join(normalize(value).replace("’", "'").replace("‘", "'").split())


def _text(value, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 and c not in "\n\r\t" for c in value):
        raise HTTPException(409, INELIGIBLE)
    return value.strip()


def _identity(url):
    """Validate hosted URL syntax; no DNS lookup or arbitrary URL is requested."""
    if not isinstance(url, str) or len(url) > 2000 or any(c.isspace() or ord(c) < 32 for c in url):
        return None
    try:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc not in HOSTS or parsed.fragment:
            return None
        match = re.fullmatch(r"/((?:" + BOARD_PATTERN + r"))/jobs/(" + JOB_ID_PATTERN + r")/?", parsed.path)
        if not match or any(key != "gh_src" or len(value) > 200 for key, value in parse_qsl(parsed.query, keep_blank_values=True)):
            return None
        board, job_id = match.group(1), int(match.group(2))
        return board, job_id, f"https://{parsed.netloc}/{board}/jobs/{job_id}"
    except (ValueError, TypeError):
        return None


def parse_job_url(url):
    """Public canonical identity for source-preserving vacancy deduplication."""
    return _identity(url)


class _Blocks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "template", "footer", "nav", "aside", "header"}:
            self.skip_depth += 1
        if not self.skip_depth and tag in {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "tr", "section", "footer"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "template", "footer", "nav", "aside", "header"} and self.skip_depth:
            self.skip_depth -= 1
        if not self.skip_depth and tag in {"p", "div", "li", "h1", "h2", "h3", "h4", "tr", "section", "footer"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip_depth:
            self.parts.append(data)


def _description(value) -> str:
    raw = _text(value, MAX_RESPONSE_BYTES)
    parser = _Blocks()
    parser.feed(html.unescape(raw))
    parser.close()
    blocks = [" ".join(part.split()) for part in "".join(parser.parts).splitlines()]
    return _text("\n".join(part for part in blocks if part), 10000)


def _email_evidence(description: str):
    candidates = {}
    for block in description.splitlines():
        if len(block) > 600:
            # Long paragraphs may contain unrelated policy/template addresses.
            continue
        normalized = _normalized(block)
        if EXCLUDED.search(normalized) or NEGATED_ACTION.search(normalized):
            continue
        emails = list(EMAIL.finditer(block))
        if len(emails) > 1:
            raise HTTPException(409, INELIGIBLE)
        if not emails:
            continue
        before_email = _normalized(block[:emails[0].start()])
        # The instruction must directly address this email in the same clause.
        # A directive for a portal plus a directory address elsewhere is manual.
        if not (SEND_TO_EMAIL.search(before_email) or APPLY_BY_EMAIL.search(before_email)):
            continue
        email = emails[0].group(1).casefold()
        local, domain = email.rsplit("@", 1)
        if len(email) > 254 or local.startswith(".") or local.endswith(".") or ".." in email:
            continue
        if any(not label or label.startswith("-") or label.endswith("-") or len(label) > 63 for label in domain.split(".")):
            continue
        # A support/legal-looking mailbox stays manual even without a disclaimer.
        if re.search(r"(?:support|soporte|privacy|privacidad|legal|accessibility|accommod|disability|fraud|abuse|noreply|no-reply)", local):
            continue
        candidates[email] = block
    if len(candidates) != 1:
        raise HTTPException(409, INELIGIBLE)
    return next(iter(candidates.items()))


async def _get_json(client: httpx.AsyncClient, endpoint: str, *, audit=None):
    context = {"event_id": str(uuid4()), "kind": "public_page", "provider": "greenhouse",
        "url": endpoint, "started_at": datetime.now(timezone.utc).isoformat()}
    status, succeeded = None, False
    if audit:
        await audit({**context, "status": "started"})
    try:
        async with client.stream("GET", endpoint, headers={"Accept": "application/json"}, timeout=30,
                follow_redirects=False) as response:
            status = response.status_code
            if response.status_code in {404, 410}:
                raise HTTPException(409, INELIGIBLE)
            if response.status_code != 200:
                raise HTTPException(502, UNAVAILABLE)
            chunks, size = [], 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise HTTPException(502, UNAVAILABLE)
                chunks.append(chunk)
        payload = json.loads(b"".join(chunks))
        if not isinstance(payload, dict):
            raise HTTPException(502, UNAVAILABLE)
        succeeded = True
        return payload
    except (httpx.HTTPError, ValueError, TypeError, UnicodeError):
        raise HTTPException(502, UNAVAILABLE) from None
    finally:
        if audit:
            await audit({**context, "status": "succeeded" if succeeded else "failed", "http_status": status,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                **({"error": UNAVAILABLE} if not succeeded else {})})


def _deadline(value):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 40:
        raise HTTPException(409, INELIGIBLE)
    try:
        expiry = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
            raise ValueError("Deadline is not current and timezone-aware")
        return expiry.isoformat()
    except ValueError:
        raise HTTPException(409, INELIGIBLE) from None


async def _published_job(client: httpx.AsyncClient, board: str, job_id: int, url: str, *, audit=None) -> dict:
    endpoint = f"{API_BASE}/{board}/jobs/{job_id}"
    raw = await _get_json(client, endpoint, audit=audit)
    if type(raw.get("id")) is not int or raw["id"] != job_id or type(raw.get("internal_job_id")) is not int or raw["internal_job_id"] <= 0:
        raise HTTPException(409, INELIGIBLE)
    title = _text(raw.get("title"), 200)
    location = raw.get("location")
    city = _text(location.get("name") if isinstance(location, dict) else None, 160)
    expiry = _deadline(raw.get("application_deadline"))
    description = _description(raw.get("content"))
    normalized_description = _normalized(description)
    # A separate paragraph can withdraw the email channel or prohibit repeats.
    # Such mixed instructions stay manual rather than authorizing an ambiguity.
    if CLOSED.search(normalized_description) or REFUSES_EMAIL.search(normalized_description) or REFUSES_FOLLOWUP.search(normalized_description):
        raise HTTPException(409, INELIGIBLE)
    email, quote = _email_evidence(description)
    if raw.get("company_name"):
        company = _text(raw["company_name"], 200)
    else:
        company = _text((await _get_json(client, f"{API_BASE}/{board}", audit=audit)).get("name"), 200)
    evidence = {"board": board, "job_id": job_id, "endpoint": endpoint,
        "email_quote": quote, "fetched_at": datetime.now(timezone.utc).isoformat()}
    if expiry:
        evidence["valid_until"] = expiry
    job = {"id": f"{board}:{job_id}", "company": company, "title": title, "city": city, "url": url,
        "description": description, "recipient_email": email, "recipient_verified": True,
        "is_active": True, "payload": {"integration_id": SOURCE_ID,
            "verification_method": "publisher_api_explicit_email", "greenhouse": evidence}}
    if expiry:
        job["valid_until"] = expiry
    return job


async def verify_discoveries(client: httpx.AsyncClient, results: list[dict], search: dict, *, audit=None) -> tuple[list[dict], list[str]]:
    """Return only independently attested jobs; all other discoveries stay manual."""
    identities = {}
    for result in results[:MAX_DISCOVERIES]:
        identity = _identity(result.get("url") if isinstance(result, dict) else None)
        if identity:
            identities[(identity[0], identity[1])] = identity
    jobs, failures, completed = [], [], 0
    for board, job_id, url in identities.values():
        try:
            job = await _published_job(client, board, job_id, url, audit=audit)
            completed += 1
            from .query_planner import role_terms
            general = search.get("research_mode") == "general"
            if (any(_normalized(role) in _normalized(job["title"]) for role in (role_terms(search) if general else search.get("roles", [])) if isinstance(role, str) and role.strip())
                    and (general or any(_normalized(city) == _normalized(job["city"]) for city in search.get("cities", []) if isinstance(city, str) and city.strip()))):
                jobs.append(job)
        except HTTPException as error:
            if getattr(error, "audit_failed", False):
                raise
            if error.status_code == 409:
                completed += 1
            else:
                failures.append("Greenhouse: una publicación no pudo verificarse en su API oficial.")
    if identities and not completed:
        raise HTTPException(502, UNAVAILABLE)
    return jobs, failures


async def revalidate_job(client: httpx.AsyncClient, job: dict) -> None:
    """Recheck origin, validity and the exact application identity before delivery."""
    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
    proof = payload.get("greenhouse") if isinstance(payload.get("greenhouse"), dict) else {}
    identity = _identity(job.get("url"))
    if (job.get("source") not in {None, SOURCE_ID} or not identity
            or payload.get("integration_id") != SOURCE_ID
            or payload.get("verification_method") != "publisher_api_explicit_email"
            or proof.get("board") != identity[0] or type(proof.get("job_id")) is not int
            or proof["job_id"] != identity[1]
            or proof.get("endpoint") != f"{API_BASE}/{identity[0]}/jobs/{identity[1]}"):
        raise HTTPException(409, INELIGIBLE)
    if not isinstance(proof.get("email_quote"), str) or (job.get("recipient_email") or "").casefold() not in proof["email_quote"].casefold():
        raise HTTPException(409, INELIGIBLE)
    current = await _published_job(client, *identity)
    if _normalized(current["payload"]["greenhouse"]["email_quote"]) != _normalized(proof["email_quote"]):
        raise HTTPException(409, "Cambió la instrucción de postulación. Revisala antes de enviar.")
    for field in ("company", "title", "city", "recipient_email"):
        saved = job.get(field)
        if not isinstance(saved, str) or _normalized(current[field]) != _normalized(saved):
            raise HTTPException(409, "Cambió la publicación o su destinatario. Revisá la postulación antes de enviar.")

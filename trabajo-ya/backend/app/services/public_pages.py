"""Read a small number of permitted public pages, without authorizing mail.

DNS is checked on *every* connection and the TCP destination is pinned to a
checked address while TLS still verifies the original publisher hostname.
Search excerpts and publisher claims are evidence, never recipient consent or
proof that an employer is legitimate. No cookies, logins, forms or scripts run.
"""
import asyncio
import hashlib
import inspect
import ipaddress
import json
import os
import re
import socket
import time
import unicodedata
import uuid
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from urllib.parse import parse_qsl, quote, unquote, urljoin, urlsplit, urlunsplit

import httpx

USER_AGENT = "TrabajoYA-Research/0.5"
ROBOTS_AGENT = "TrabajoYA-Research"
MAX_HTML_BYTES = 1024 * 1024
MAX_ROBOTS_BYTES = 512 * 1024
MAX_TEXT_CHARS = 20_000
MAX_INITIAL_PAGES = 6
MAX_FOLLOWED_PAGES = 2
MAX_REDIRECTS = 2
MAX_REQUEST_SECONDS = 15
MAX_CRAWL_DELAY_SECONDS = 15
PRIVATE_QUERY_KEYS = frozenset({"access_token", "refresh_token", "token", "key", "api_key", "secret", "password", "code", "session", "auth", "signature"})
# Discovery through a licensed search API remains possible. These services do
# not permit this application's direct automated page copying.
RESTRICTED_DOMAINS = ("linkedin.com", "licdn.com", "computrabajo.com")
SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "head", "footer", "nav", "header", "aside", "form"}
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
BLOCK_TAGS = {"p", "div", "section", "article", "main", "li", "ul", "ol", "h1", "h2", "h3", "h4", "br", "tr"}
CAREER_LINK = re.compile(r"\b(?:empleos?|vacantes?|trabaja con nosotros|trabaja con nosotras|trabaj[aá] con nosotros|careers?|jobs?|oportunidades laborales|busquedas laborales|bolsa de trabajo|ofertas de trabajo)\b", re.I)
CLOSED = re.compile(r"\b(?:vacante|oferta|puesto|convocatoria|position)\s+(?:ya\s+)?(?:cerrad[ao]|vencid[ao]|cubiert[ao]|closed|expired|filled)\b|\b(?:no longer accepting|applications closed|no acepta(?:mos|n)? postulaciones)\b", re.I)
BLOCKED_CONTENT = re.compile(r"(?:verify (?:that )?you(?:'re| are) (?:a )?human|verify that you(?:'re| are) not a robot|verifica(?:r| que) (?:eres|sos) (?:un )?humano|iniciar sesi[oó]n para (?:continuar|ver)|sign in to (?:continue|view)|subscribe to (?:continue|read)|cf-chl-|challenge-platform|captcha required)", re.I)
EMAIL_INSTRUCTION = re.compile(r"\b(?:envi[aáe]|enviar|manda|mandar|remitir|send|submit)\b.*?\b(?:cv|curr[ií]culum|resume|application)\b", re.I)
EMAIL = re.compile(r"\b[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?\.[A-Za-z]{2,}\b")


class PageReadError(Exception):
    """A fixed, non-private reason safe to show in query history."""


def _public_address(value) -> bool:
    address = ipaddress.ip_address(value)
    # is_global alone includes multicast; transitional IPv6 can embed another
    # destination. Neither is a normal public publisher endpoint.
    return (address.is_global and not address.is_multicast and not address.is_reserved
        and not address.is_loopback and not address.is_link_local and not address.is_unspecified
        and not getattr(address, "is_site_local", False)
        and not getattr(address, "sixtofour", None) and not getattr(address, "teredo", None))


def public_page_url(value) -> bool:
    try:
        if not isinstance(value, str) or len(value) > 2000 or any(char.isspace() or ord(char) < 32 for char in value):
            return False
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        if (parsed.scheme != "https" or not host or parsed.port not in {None, 443}
                or parsed.username is not None or parsed.password is not None or parsed.fragment
                or any(key.casefold() in PRIVATE_QUERY_KEYS for key, _ in parse_qsl(parsed.query))
                or "\\" in value or "%" in host):
            return False
        try:
            return _public_address(host)
        except ValueError:
            return ("." in host and not re.fullmatch(r"[0-9.]+", host)
                and not host.endswith((".local", ".internal", ".localhost", ".lan", ".home", ".invalid", ".test"))
                and host != "localhost.localdomain")
    except (ValueError, TypeError):
        return False


def _restricted(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    return any(host == domain or host.endswith("." + domain) for domain in RESTRICTED_DOMAINS)


async def _resolve_public_addresses(host: str) -> list[str]:
    """Reject mixed public/private answers; never let httpx resolve again."""
    try:
        literal = ipaddress.ip_address(host)
        addresses = [str(literal)]
    except ValueError:
        try:
            records = await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(
                host, 443, type=socket.SOCK_STREAM), timeout=5)
        except (OSError, asyncio.TimeoutError):
            raise PageReadError("No se pudo comprobar el DNS público del enlace.") from None
        addresses = list(dict.fromkeys(record[4][0] for record in records))
    try:
        if not addresses or any(not _public_address(address) for address in addresses):
            raise ValueError
    except ValueError:
        raise PageReadError("El DNS del enlace incluye una dirección que no es pública.") from None
    return addresses


class _PinnedPublicTransport(httpx.AsyncBaseTransport):
    """Connect only to a resolved public IP, with publisher Host and TLS SNI.

    A configured egress proxy must provide its own SSRF protection. We refuse
    reads rather than silently bypassing that proxy or trusting proxy DNS.
    HTTPX's TLS verification/environment CA trust remain enabled.
    """
    def __init__(self, delegate=None):
        self._delegate = delegate
        self._hostname_transports = {}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        original_url = str(request.url)
        if not public_page_url(original_url) or _restricted(original_url):
            raise PageReadError("El enlace no permite una lectura pública automatizada.")
        host = request.url.host
        addresses = await _resolve_public_addresses(host)
        # Rebinding cannot change the destination after this check: the transport
        # receives the validated literal IP, not a hostname to resolve again.
        pinned_url = request.url.copy_with(host=addresses[0])
        headers = {"Host": host, "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8", "Accept-Encoding": "identity"}
        extensions = {**request.extensions, "sni_hostname": host}
        pinned_request = httpx.Request("GET", pinned_url, headers=headers, extensions=extensions)
        if self._delegate is not None:
            delegate = self._delegate
        else:
            # The TCP origin is an IP. Without this separation two publishers
            # sharing an IP could reuse a TLS connection verified for only one
            # of them, because SNI is not part of httpcore's connection key.
            if host not in self._hostname_transports:
                self._hostname_transports[host] = httpx.AsyncHTTPTransport(
                    verify=True, trust_env=True, retries=0,
                    limits=httpx.Limits(max_connections=1, max_keepalive_connections=0))
            delegate = self._hostname_transports[host]
        return await delegate.handle_async_request(pinned_request)

    async def aclose(self):
        if self._delegate is not None:
            await self._delegate.aclose()
        for delegate in self._hostname_transports.values():
            await delegate.aclose()


def _proxy_present() -> bool:
    return any(os.environ.get(name) for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"))


class _PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.links, self.json_documents = [], [], []
        self.stack = []
        self.current_link = None
        self.json_depth = None
        self.json_chunks = []
        self.text_size = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        parent_hidden = bool(self.stack and self.stack[-1][1])
        marker = " ".join(str(attrs.get(key, "")) for key in ("id", "class"))
        hidden = (parent_hidden or tag in SKIP_TAGS or "hidden" in attrs
            or (attrs.get("aria-hidden") or "").casefold() == "true"
            or bool(re.search(r"(?:display\s*:\s*none|visibility\s*:\s*hidden)", attrs.get("style") or "", re.I))
            or bool(re.search(r"\b(?:cookie|cookies|consent-banner|cookie-banner)\b", marker, re.I)))
        if tag == "script" and (attrs.get("type") or "").casefold() == "application/ld+json" and len(self.json_documents) < 8:
            self.json_depth = len(self.stack)
            self.json_chunks = []
        if tag not in VOID_TAGS:
            self.stack.append((tag, hidden))
        if not hidden:
            if tag in BLOCK_TAGS:
                self._append("\n")
            if tag == "a" and len(self.links) < 100:
                self.current_link = {"href": attrs.get("href", ""), "text": "", "depth": len(self.stack)}

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag == "script" and self.json_depth is not None:
            try:
                self.json_documents.append(json.loads("".join(self.json_chunks)))
            except (ValueError, TypeError, RecursionError):
                pass
            self.json_depth = None
        if tag == "a" and self.current_link is not None:
            self.links.append(self.current_link)
            self.current_link = None
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                self.stack = self.stack[:index]
                break
        if tag in BLOCK_TAGS and not (self.stack and self.stack[-1][1]):
            self._append("\n")

    def handle_data(self, data):
        if self.json_depth is not None:
            if sum(map(len, self.json_chunks)) < 150_000:
                self.json_chunks.append(data[:150_000])
            return
        if not (self.stack and self.stack[-1][1]):
            self._append(data)
            if self.current_link is not None:
                self.current_link["text"] += data[:500]

    def _append(self, value):
        if self.text_size < MAX_TEXT_CHARS:
            chunk = value[:MAX_TEXT_CHARS - self.text_size]
            self.parts.append(chunk)
            self.text_size += len(chunk)

    @property
    def text(self):
        return "\n".join(line for line in (" ".join(part.split()) for part in "".join(self.parts).splitlines()) if line)[:MAX_TEXT_CHARS]


def _plain(value, limit=3000):
    if not isinstance(value, str):
        return ""
    parser = _PageParser()
    parser.feed(value[:20_000])
    return parser.text[:limit]


def _job_postings(documents):
    collected, visited = [], 0

    def visit(value, depth=0):
        nonlocal visited
        visited += 1
        if visited > 120 or depth > 6 or len(collected) >= 8:
            return
        if isinstance(value, list):
            for child in value[:30]:
                visit(child, depth + 1)
        elif isinstance(value, dict):
            types = value.get("@type")
            if types == "JobPosting" or isinstance(types, list) and "JobPosting" in types:
                collected.append(value)
            for key in ("@graph", "mainEntity", "itemListElement", "item"):
                if key in value:
                    visit(value[key], depth + 1)

    for document in documents:
        visit(document)
    facts = []
    for job in collected:
        fact = {key: _plain(job.get(key), 3000 if key == "description" else 500)
            for key in ("title", "description", "qualifications", "experienceRequirements", "skills", "educationRequirements")}
        organization = job.get("hiringOrganization")
        if isinstance(organization, dict):
            fact["company"] = _plain(organization.get("name"), 200)
        locations = job.get("jobLocation")
        locations = locations if isinstance(locations, list) else [locations]
        fact["locations"] = []
        for location in locations[:10]:
            address = location.get("address") if isinstance(location, dict) else None
            if not isinstance(address, dict):
                continue
            item = {key: _plain(address.get(key), 160) for key in ("addressLocality", "addressRegion", "addressCountry", "streetAddress")}
            country = address.get("addressCountry")
            if isinstance(country, dict):
                item["addressCountry"] = _plain(country.get("name"), 160)
            if any(item.values()):
                fact["locations"].append(item)
        fact["dates"] = {}
        for source, key in (("datePosted", "published_at"), ("validThrough", "valid_until")):
            value = job.get(source)
            if isinstance(value, str) and len(value) <= 80:
                try:
                    datetime.fromisoformat(value.replace("Z", "+00:00"))
                    fact["dates"][key] = value
                except ValueError:
                    pass
        # directApply is a publisher flag, not an authorized API or permission to
        # automate a form. Never map it to automatic email capability.
        fact["publisher_claim"] = True
        fact["recipient_verified"] = False
        # Preserve the familiar schema.org structure for grounded extractors;
        # all values have already been bounded and HTML removed above.
        if fact.get("company"):
            fact["hiringOrganization"] = {"name": fact["company"]}
        fact["jobLocation"] = [{"address": location} for location in fact["locations"]]
        if "published_at" in fact["dates"]:
            fact["datePosted"] = fact["dates"]["published_at"]
        if "valid_until" in fact["dates"]:
            fact["validThrough"] = fact["dates"]["valid_until"]
        facts.append(fact)
    return facts


def _publisher_text(text, facts):
    pieces = []
    for fact in facts:
        values = [fact.get(key, "") for key in ("company", "title", "description", "qualifications", "experienceRequirements", "skills", "educationRequirements")]
        values += [" ".join(value for value in location.values() if value) for location in fact["locations"]]
        values += [f"{key}: {value}" for key, value in fact["dates"].items()]
        pieces.append("\n".join(value for value in values if value))
    pieces.append(text)
    return "\n".join(pieces)[:MAX_TEXT_CHARS]


def _expired(facts, now):
    if not facts:
        return False
    expired = []
    for fact in facts:
        value = fact["dates"].get("valid_until")
        if not value:
            expired.append(False)
            continue
        try:
            if len(value) == 10:
                expired.append(date.fromisoformat(value) < now.date())
            else:
                deadline = datetime.fromisoformat(value.replace("Z", "+00:00"))
                expired.append(deadline.tzinfo is not None and deadline <= now)
        except ValueError:
            expired.append(False)
    return all(expired)


def _application_method(text, links, url):
    for line in text.splitlines():
        if EMAIL_INSTRUCTION.search(line) and EMAIL.search(line):
            return {"kind": "published_email_pending_review", "evidence": line[:1200], "recipient_verified": False}
    for link in links:
        if re.search(r"\b(?:postular(?:me|se)?|postulate|aplicar|apply|inscribirme)\b", link["text"], re.I):
            target = urljoin(url, link["href"]).split("#", 1)[0]
            if public_page_url(target):
                return {"kind": "manual_link", "url": target, "evidence": link["text"][:500], "recipient_verified": False}
    return {"kind": "unknown", "recipient_verified": False}


def _robots_groups(text):
    groups, agents, directives = [], [], []
    for line in text.splitlines():
        value = line.split("#", 1)[0].strip()
        if ":" not in value:
            continue
        key, value = (part.strip() for part in value.split(":", 1))
        key = key.casefold()
        if key == "user-agent":
            if directives:
                groups.append((agents, directives))
                agents, directives = [], []
            agents.append(value.casefold())
        elif agents and key in {"allow", "disallow", "crawl-delay"}:
            directives.append((key, value))
    if agents:
        groups.append((agents, directives))
    matches, specificity = [], -1
    for agents, directives in groups:
        current = max((0 if agent == "*" else len(agent) for agent in agents
            if agent == "*" or agent in ROBOTS_AGENT.casefold()), default=-1)
        if current > specificity:
            matches, specificity = list(directives), current
        elif current == specificity and current >= 0:
            matches.extend(directives)
    return matches


def _robots_path(value):
    # Preserve reserved octets and decode only RFC3986 unreserved characters.
    value = quote(value, safe="/%?=&:+-._~!$'(),;*@")
    return re.sub(r"%([0-9a-fA-F]{2})", lambda match: chr(int(match[1], 16))
        if chr(int(match[1], 16)) in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
        else "%" + match[1].upper(), value)


def _robots_permission(text, url):
    parsed = urlsplit(url)
    path = _robots_path(parsed.path or "/") + ("?" + _robots_path(parsed.query) if parsed.query else "")
    matches, delay = [], 0.0
    for kind, value in _robots_groups(text):
        if kind == "crawl-delay":
            try:
                delay = max(delay, float(value))
            except (ValueError, OverflowError):
                pass
        elif value:
            rule = _robots_path(value)
            end = rule.endswith("$")
            pattern = re.escape(rule[:-1] if end else rule).replace(r"\*", ".*")
            if re.match("^" + pattern + ("$" if end else ""), path):
                matches.append((len(rule.replace("*", "").rstrip("$")), kind == "allow"))
    allowed = max(matches)[1] if matches else True
    return allowed, delay


async def _audit(callback, event):
    if callback is not None:
        value = callback(event)
        if inspect.isawaitable(value):
            await value


async def _http_get(client, url, *, robots=False, audit=None):
    if not public_page_url(url) or _restricted(url):
        raise PageReadError("El enlace no permite una lectura pública automatizada.")
    status, content_hash = None, None
    error = None
    event_id = str(uuid.uuid4())
    base_event = {"kind": "public_page", "provider": "publisher", "event_id": event_id,
        "operation": "robots_fetch" if robots else "page_fetch", "url": url}
    await _audit(audit, {**base_event, "checked_at": datetime.now(timezone.utc).isoformat(), "status": "started"})
    try:
        client.cookies.clear()
        # HTTPX's read timeout is per chunk. Bound the whole request as well so
        # a slow trickle cannot retain the scheduled search indefinitely.
        async with asyncio.timeout(MAX_REQUEST_SECONDS):
            async with client.stream("GET", url, follow_redirects=False, timeout=10,
                    headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}) as response:
                status = response.status_code
                headers = dict(response.headers)
                size, chunks = 0, []
                maximum = MAX_ROBOTS_BYTES if robots else MAX_HTML_BYTES
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > maximum:
                        raise PageReadError("La página supera el límite permitido de lectura.")
                    chunks.append(chunk)
                content = b"".join(chunks)
                content_hash = hashlib.sha256(content).hexdigest()
                return status, headers, content, content_hash
    except PageReadError as failure:
        error = str(failure)
        raise
    except asyncio.CancelledError:
        error = "La lectura fue interrumpida antes de completarse."
        raise
    except (httpx.HTTPError, OSError, ValueError, TimeoutError):
        error = "No se pudo leer el enlace público mediante una conexión segura."
        raise PageReadError(error) from None
    finally:
        await _audit(audit, {**base_event,
            "checked_at": datetime.now(timezone.utc).isoformat(), "http_status": status,
            "status": "failed" if error or status is not None and status >= 400 else "succeeded", "content_sha256": content_hash,
            **({"reason": error} if error else
                {"reason": f"El editor respondió HTTP {status}."} if status is not None and status >= 400 else {})})


class _Investigation:
    def __init__(self, client, audit):
        self.client, self.audit, self.robots, self.last_read = client, audit, {}, {}

    async def _read_robots(self, origin):
        current = origin + "/robots.txt"
        for index in range(MAX_REDIRECTS + 1):
            status, headers, content, _ = await _http_get(self.client, current, robots=True, audit=self.audit)
            self.last_read[origin] = time.monotonic()
            if status in {301, 302, 303, 307, 308}:
                current = urljoin(current, headers.get("location", ""))
                if not public_page_url(current) or _restricted(current) or index == MAX_REDIRECTS:
                    raise PageReadError("No se pudo comprobar robots.txt sin superar los límites de redirección.")
                continue
            if status != 200 or "html" in headers.get("content-type", "").casefold():
                raise PageReadError("No se pudo comprobar el permiso de lectura de robots.txt.")
            text = content.decode("utf-8", errors="strict")
            if not text.strip() or "<html" in text.casefold():
                raise PageReadError("robots.txt no contiene un permiso de lectura comprobable.")
            return text
        raise PageReadError("No se pudo comprobar robots.txt.")

    async def allowed(self, url):
        if not public_page_url(url) or _restricted(url):
            raise PageReadError("El sitio requiere revisión manual; no permite esta lectura automatizada.")
        parsed = urlsplit(url)
        origin = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
        if origin not in self.robots:
            try:
                self.robots[origin] = await self._read_robots(origin)
            except (PageReadError, UnicodeDecodeError) as failure:
                self.robots[origin] = failure
        if isinstance(self.robots[origin], Exception):
            raise PageReadError("No se pudo comprobar el permiso de lectura de robots.txt.")
        allowed, delay = _robots_permission(self.robots[origin], url)
        if not allowed:
            raise PageReadError("robots.txt no permite leer esta página.")
        if not 0 <= delay <= MAX_CRAWL_DELAY_SECONDS:
            raise PageReadError("El intervalo solicitado por robots.txt supera el presupuesto de esta investigación.")
        remaining = self.last_read.get(origin, 0) + delay - time.monotonic()
        if remaining > 0:
            await asyncio.sleep(remaining)
        self.last_read[origin] = time.monotonic()

    async def page(self, item):
        current = item["url"]
        status, headers, content, digest = None, {}, b"", None
        for index in range(MAX_REDIRECTS + 1):
            await self.allowed(current)
            status, headers, content, digest = await _http_get(self.client, current, audit=self.audit)
            if status not in {301, 302, 303, 307, 308}:
                break
            target = urljoin(current, headers.get("location", ""))
            if not public_page_url(target) or index == MAX_REDIRECTS:
                raise PageReadError("La página redirige a un destino que no se puede verificar.")
            current = target
        proof = {"status": "pending_review", "checked_at": datetime.now(timezone.utc).isoformat(),
            "http_status": status, "final_url": current, "content_sha256": digest,
            "reason": "La lectura del enlace no verifica al empleador ni autoriza correos.", "dates": {}}
        if status in {404, 410}:
            proof.update(status="unavailable", reason="La publicación ya no está disponible en ese enlace.")
            return {**item, "page_verification": proof}, []
        if status != 200:
            proof["reason"] = "El sitio no permite leer la publicación sin intervención manual."
            return {**item, "page_verification": proof}, []
        content_type = headers.get("content-type", "").split(";", 1)[0].casefold()
        if content_type not in {"text/html", "application/xhtml+xml", "text/plain"}:
            proof["reason"] = "El formato requiere revisión manual y no se procesa automáticamente."
            return {**item, "page_verification": proof}, []
        text = content.decode("utf-8", errors="replace")
        parser = _PageParser()
        parser.feed(text)
        facts = _job_postings(parser.json_documents)
        publisher_text = _publisher_text(parser.text, facts)
        if BLOCKED_CONTENT.search(text) or len(publisher_text.strip()) < 40:
            proof["reason"] = "La página requiere acceso humano o no contiene texto público suficiente."
            return {**item, "page_verification": proof}, []
        proof["status"] = "closed" if CLOSED.search(parser.text) or _expired(facts, datetime.now(timezone.utc)) else "verified_link"
        if proof["status"] == "closed":
            proof["reason"] = "El editor indica que la publicación está cerrada o vencida."
        proof["job_postings"] = facts
        if len(facts) == 1:
            proof["dates"] = facts[0]["dates"]
            proof["job_posting"] = facts[0]
        proof["application_links"] = []
        for link in parser.links:
            target = urljoin(current, link["href"]).split("#", 1)[0]
            if (public_page_url(target) and re.search(r"\b(?:postular(?:me|se)?|postulate|aplicar|apply|inscribirme)\b", link["text"], re.I)):
                proof["application_links"].append({"url": target, "evidence": link["text"][:500]})
                if len(proof["application_links"]) == 10:
                    break
        proof["application_method"] = _application_method(parser.text, parser.links, current)
        proof["requirements"] = [line[:1200] for line in parser.text.splitlines()
            if re.search(r"\b(?:requisitos?|licencia|experiencia|certificacion|qualifications|requirements)\b", line, re.I)][:8]
        result = {**item, "raw_content": publisher_text, "page_verification": proof}
        candidates = []
        for link in parser.links:
            href = link["href"]
            if not isinstance(href, str):
                continue
            target = urljoin(current, href).split("#", 1)[0]
            searchable = unicodedata.normalize("NFKD", unquote(href) + " " + link["text"])
            searchable = "".join(character for character in searchable if not unicodedata.combining(character))
            if (public_page_url(target) and urlsplit(target).hostname == urlsplit(current).hostname
                    and CAREER_LINK.search(searchable) and target not in {current, item["url"]}):
                candidates.append({"url": target, "title": link["text"][:300], "content": "",
                    "web_search": item.get("web_search", {}), "discovery_parent_url": item["url"], "parent_url": item["url"]})
        # These are literal observed links, not URLs invented by the analyzer.
        # Their own robots and DNS checks still happen before any follow-up.
        proof["allowed_links"] = [{"url": candidate["url"], "evidence": candidate["title"]}
            for candidate in candidates[:MAX_FOLLOWED_PAGES]]
        return result, candidates


def _read_priority(item, search):
    """Prioritize likely adverts without changing verification or permissions."""
    if _restricted(item["url"]):
        return 3
    path = unquote(urlsplit(item["url"]).path).casefold()
    if re.search(r"/(?:trabajo-(?:de|en)-|empleos-en-|q-[^/]*empleos|trabajo-chofer)", path):
        return 2
    title = "".join(char for char in unicodedata.normalize("NFD", str(item.get("title", "")).casefold())
        if unicodedata.category(char) != "Mn")
    roles = ["".join(char for char in unicodedata.normalize("NFD", str(role).casefold())
        if unicodedata.category(char) != "Mn") for role in search.get("roles", [])]
    return 0 if any(role and role in title for role in roles) else 1


async def investigate_pages(settings, client, results: list[dict], search: dict, *, audit=None) -> tuple[list[dict], list[str]]:
    """Retain discoveries even when reading is blocked; never invent vacancies.

    LinkedIn/Computrabajo are additional discovery sources via Tavily, with links
    for human review. Public reading is finite (six pages total, including up to
    two same-publisher career links); it never follows recursively or enables
    auto-sending. Robots and redirects have independent finite request limits.
    ``client`` may carry provider secrets: no real publisher requests use it.
    MockTransport is reused solely for deterministic, network-free tests.
    """
    enriched, failures, seen, followups = [], [], set(), []
    maximum = getattr(settings, "public_page_max_reads", MAX_INITIAL_PAGES)
    maximum = min(maximum, MAX_INITIAL_PAGES) if type(maximum) is int and maximum > 0 else MAX_INITIAL_PAGES
    enabled = getattr(settings, "public_page_reads_enabled", True) is True
    mock = getattr(client, "_transport", None)
    mock = mock if isinstance(mock, httpx.MockTransport) else None
    unavailable = not enabled or _proxy_present() and mock is None
    transport = mock or _PinnedPublicTransport()
    async with httpx.AsyncClient(transport=transport, trust_env=True,
            follow_redirects=False, timeout=10, cookies=None) as reader:
        investigator = _Investigation(reader, audit)
        attempted_pages = 0

        async def read(item, limited=False):
            nonlocal attempted_pages
            if _restricted(item["url"]):
                reason = "El sitio requiere revisión manual; no permite esta lectura automatizada."
                failures.append(reason)
                proof = {"status": "pending_review", "checked_at": datetime.now(timezone.utc).isoformat(), "reason": reason}
                await _audit(audit, {"kind": "public_page", "provider": "publisher", "event_id": str(uuid.uuid4()),
                    "operation": "page_fetch", "url": item["url"], **proof, "status": "blocked"})
                return {**item, "page_verification": proof}, []
            limited = limited or attempted_pages >= maximum
            if unavailable or limited:
                reason = ("La lectura pública está desactivada." if not enabled else
                    "El proxy de salida requiere un lector con protección de DNS antes de verificar páginas." if unavailable else
                    "La página quedó pendiente por el límite de lecturas de esta investigación.")
                proof = {"status": "pending_review", "checked_at": datetime.now(timezone.utc).isoformat(), "reason": reason}
                await _audit(audit, {"kind": "public_page", "provider": "publisher", "event_id": str(uuid.uuid4()),
                    "operation": "page_fetch", "url": item["url"], **proof, "status": "blocked"})
                return {**item, "page_verification": proof}, []
            attempted_pages += 1
            try:
                return await investigator.page(item)
            except PageReadError as failure:
                reason = str(failure)
                failures.append(reason)
                proof = {"status": "pending_review", "checked_at": datetime.now(timezone.utc).isoformat(), "reason": reason}
                await _audit(audit, {"kind": "public_page", "provider": "publisher", "event_id": str(uuid.uuid4()),
                    "operation": "page_fetch", "url": item["url"], **proof, "status": "blocked"})
                return {**item, "page_verification": proof}, []

        ordered = sorted((item for item in results[:30] if isinstance(item, dict)
            and public_page_url(item.get("url"))), key=lambda item: _read_priority(item, search))
        for item in ordered:
            if not isinstance(item, dict) or not public_page_url(item.get("url")) or item["url"] in seen:
                continue
            seen.add(item["url"])
            result, links = await read(item)
            enriched.append(result)
            followups.extend(links)
        followed = 0
        for item in followups:
            if followed >= MAX_FOLLOWED_PAGES or attempted_pages >= maximum:
                break
            if item["url"] in seen:
                continue
            seen.add(item["url"])
            result, _ = await read(item)
            enriched.append(result)
            followed += 1
    # Keep provider order in the returned history; only request order changes.
    positions = {item["url"]: index for index, item in enumerate(results[:30])
        if isinstance(item, dict) and isinstance(item.get("url"), str)}
    enriched.sort(key=lambda item: positions.get(item["url"], 30))
    return enriched, list(dict.fromkeys(failures))

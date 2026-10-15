"""Bounded general Internet queries, independent of a portal allowlist.

The plan uses saved job/location preferences, never a CV or a person's contact
information. Query variants discover candidates; they do not prove hiring,
location, distance, recipient legitimacy, or a site's permission to be fetched.
"""
import ipaddress
import re
import unicodedata
from urllib.parse import urlsplit

from fastapi import HTTPException

MAX_QUERY_PART_CHARS = 160
MAX_PLAN_QUERIES = 12
PORTAL_DOMAINS = ("linkedin.com", "ar.computrabajo.com")


def _normalized(value: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFD", value.casefold())
        if unicodedata.category(char) != "Mn")


def _part(value) -> str:
    if (not isinstance(value, str) or not value.strip() or len(value) > MAX_QUERY_PART_CHARS
            or any(ord(char) < 32 and not char.isspace() for char in value)):
        raise HTTPException(503, "La búsqueda web requiere puestos y ciudades válidos.")
    return " ".join(value.split())


def saved_preferences(search: dict) -> dict[str, list[str]]:
    parts = {}
    for field in ("roles", "cities"):
        raw = search.get(field)
        if not isinstance(raw, list) or not 1 <= len(raw) <= 20:
            raise HTTPException(503, "La búsqueda web requiere puestos y ciudades guardados.")
        values = []
        for value in raw:
            value = _part(value)
            if value not in values:
                values.append(value)
        parts[field] = values
    return parts


def role_terms(search: dict) -> list[str]:
    """Original titles plus narrow equivalents; never infer a new profession.

    In particular camionero is only added for an explicitly truck/cargo role.
    AI-provided arbitrary keywords and page instructions are not query inputs.
    """
    roles = saved_preferences(search)["roles"]
    terms = list(roles)
    for original in roles:
        norm = _normalized(original)
        additions = []
        if any(re.search(r"\b" + word + r"\b", norm) for word in ("chofer", "conductor")):
            additions = ["conductor", "chofer", "conductor profesional"]
            if re.search(r"\b(?:camion|camiones|cargas?|pesado|camionero)\b", norm):
                additions += ["chofer de camión", "camionero"]
            elif re.search(r"\b(?:reparto|repartidor|distribucion)\b", norm):
                additions += ["chofer de reparto", "conductor de reparto"]
        elif re.search(r"\belectricista\b", norm):
            additions = ["técnico electricista"]
        elif re.search(r"\bvendedor\b", norm):
            additions = ["asesor de ventas"]
        for value in additions:
            if value not in terms:
                terms.append(value)
    return terms[:40]


def _location(search: dict) -> dict:
    value = search.get("location", search.get("geography", {}))
    return value if isinstance(value, dict) else {}


def has_geographic_context(search: dict) -> bool:
    location = _location(search)
    return any(search.get(field) or location.get(field) for field in (
        "province", "country", "radius_km", "nearby_cities", "latitude", "longitude"))


def _scope(search: dict, city: str) -> str:
    location = _location(search)
    values = [city]
    for field in ("province", "country"):
        value = search.get(field, location.get(field))
        if isinstance(value, str) and value.strip():
            value = _part(value)
            if _normalized(value) not in {_normalized(item) for item in values}:
                values.append(value)
    return " ".join(f'"{item.replace(chr(34), " ")}"' for item in values)


def verified_nearby_cities(search: dict) -> list[str]:
    """Only geocoder-confirmed points supplied by the geography service.

    A free text mention or model-generated list cannot expand a radius search.
    Distance is enforced separately against original posting locations.
    """
    location = _location(search)
    raw = search.get("nearby_cities", location.get("nearby_cities", []))
    if not isinstance(raw, list):
        return []
    radius = search.get("radius_km", location.get("radius_km"))
    center_city = location.get("city")
    if not isinstance(center_city, str):
        cities = search.get("cities")
        center_city = cities[0] if isinstance(cities, list) and cities and isinstance(cities[0], str) else ""
    center_city = _normalized(" ".join(center_city.split()))
    center_id = location.get("id")
    results = []
    seen = {center_city}
    for value in raw[:20]:
        if not isinstance(value, dict) or value.get("verified") is not True:
            continue
        distance = value.get("distance_km")
        if (type(distance) not in {int, float} or not 0 <= distance <= 1000
                or (type(radius) in {int, float} and distance > radius)):
            continue
        name = value.get("city", value.get("name"))
        try:
            name = _part(name)
        except HTTPException:
            continue
        normalized_name = _normalized(name)
        if (normalized_name in seen
                or isinstance(center_id, str) and center_id and value.get("id") == center_id):
            continue
        seen.add(normalized_name)
        results.append(name)
    return results[:8]


def _pairs(parts: dict) -> list[tuple[str, str]]:
    all_pairs = [(role, city) for role in parts["roles"] for city in parts["cities"]]
    pairs = []
    for index in range(max(len(parts["roles"]), len(parts["cities"]))):
        pair = (parts["roles"][index % len(parts["roles"])], parts["cities"][index % len(parts["cities"])])
        if pair not in pairs:
            pairs.append(pair)
    return pairs + [pair for pair in all_pairs if pair not in pairs]


def legacy_queries(search: dict, limit: int) -> tuple[list[str], bool]:
    pairs = _pairs(saved_preferences(search))
    return [f'vacantes empleo "{role}" "{city}"' for role, city in pairs[:limit]], len(pairs) > limit


def _additional_domains(search: dict) -> list[str]:
    raw = search.get("additional_sources", [])
    if not isinstance(raw, list):
        return []
    domains = []
    for value in raw[:8]:
        if not isinstance(value, str):
            continue
        try:
            parsed = urlsplit(value if "://" in value else "https://" + value)
            host = (parsed.hostname or "").lower().rstrip(".")
            if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in {None, 443}
                    or not re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+", host)
                    or host.endswith((".local", ".internal", ".localhost", ".invalid", ".test", ".lan"))):
                continue
            try:
                ipaddress.ip_address(host)
                continue
            except ValueError:
                pass
            if host not in domains and host not in PORTAL_DOMAINS:
                domains.append(host)
        except ValueError:
            continue
    return domains


def plan_queries(search: dict, limit: int = 6) -> list[dict]:
    """General queries first, then optional portals and employer investigation.

    Domains belong to individual supplemental queries. No global include_domains
    list restricts general discovery to known employment portals.
    """
    parts = saved_preferences(search)
    if type(limit) is not int or not 1 <= limit <= MAX_PLAN_QUERIES:
        raise HTTPException(503, "El límite de consultas del buscador web no es válido.")
    pairs = _pairs(parts)
    roles = role_terms(search)
    first_role, first_city = pairs[0]
    scope = _scope(search, first_city)
    nearby = verified_nearby_cities(search)
    plan, seen = [], set()

    def add(query, kind, reason, domains=None):
        query = " ".join(query.split())
        if query not in seen:
            seen.add(query)
            row = {"query": query, "kind": kind, "reason": reason}
            if domains:
                row["domains"] = domains
            plan.append(row)

    for role, city in pairs[:min(max(len(parts["roles"]), len(parts["cities"])), 2)]:
        add(f'vacantes empleo "{role}" {_scope(search, city)}', "general_vacancies",
            "Buscar anuncios públicos en toda la web, sin restringir portales.")
    aliases = " OR ".join(f'"{value.replace(chr(34), " ")}"' for value in roles[:5])
    add(f'({aliases}) trabajo se busca {scope}', "role_synonyms",
        "Buscar títulos equivalentes sin inventar una profesión diferente.")
    nearby_scope = " OR ".join(f'"{city}"' for city in nearby[:4])
    area = f'("{first_city}" OR {nearby_scope})' if nearby_scope else scope
    nearby_country = ""
    if nearby_scope:
        location = _location(search)
        country = search.get("country", location.get("country"))
        if isinstance(country, str) and country.strip():
            nearby_country = f' "{_part(country).replace(chr(34), " ")}"'
        # A radius may cross province borders. Appending the center's province
        # to every neighboring locality would narrow out legitimate nearby
        # places. Original-city queries retain its province; area queries use
        # the verified locality names and country and are geofiltered later.
        area += nearby_country
    sector = "transporte logística" if re.search(r"\b(?:chofer|conductor|camionero)\b", _normalized(first_role)) else "contratación"
    add(f'"{first_role}" empresas {sector} empleo {area}', "nearby_employers" if nearby else "employers",
        "Investigar empresas; un resultado de empresa no se convierte en vacante sin evidencia.")
    add(f'"{first_role}" consultora bolsa de trabajo convocatoria {scope}', "consultancies_boards",
        "Buscar consultoras, bolsas laborales y convocatorias públicas fuera de los portales conocidos.")
    for domain in PORTAL_DOMAINS:
        target = f"{domain}/jobs" if domain == "linkedin.com" else domain
        exclude_profiles = " -site:linkedin.com/in/ -site:linkedin.com/pub/" if domain == "linkedin.com" else ""
        add(f'site:{target} ({aliases}) {scope}{exclude_profiles}', "additional_portal",
            "Añadir un portal solicitado, manteniendo las consultas generales.", [domain])
    if nearby:
        add(f'({aliases}) vacantes ({nearby_scope}){nearby_country}', "nearby_cities",
            "Investigar localidades geocodificadas dentro del radio; cada oferta requiere comprobar su ubicación.")
    add(f'({aliases}) "trabajá con nosotros" empleo {scope}', "company_careers",
        "Investigar páginas públicas de empresas que puedan publicar búsquedas propias.")
    add(f'({aliases}) búsqueda laboral publicado requisitos {scope}', "public_postings",
        "Buscar publicaciones públicas y requisitos de la contratación.")
    for role, city in pairs[1:]:
        add(f'vacantes empleo "{role}" {_scope(search, city)}', "general_vacancies",
            "Ampliar combinaciones de puestos y ciudades guardados.")
    for domain in _additional_domains(search):
        add(f'site:{domain} ({aliases}) {scope}', "user_additional_source",
            "Investigar una fuente adicional indicada por el usuario; sin autorización implícita de acceso o envío.", [domain])
    return plan[:limit]


def employer_follow_up(search: dict, results: list[dict], known_queries: list[str]) -> dict | None:
    """A single bounded follow-up investigates an observed host, not a guessed company."""
    parts = saved_preferences(search)
    for result in results:
        try:
            host = (urlsplit(result.get("url", "")).hostname or "").lower()
        except (TypeError, ValueError):
            continue
        if (not re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+", host)
                or any(host == domain or host.endswith("." + domain) for domain in PORTAL_DOMAINS)
                or host.endswith((".local", ".internal", ".localhost", ".invalid", ".test", ".lan"))):
            continue
        query = f'site:{host} "{parts["roles"][0]}" vacantes requisitos postulación {_scope(search, parts["cities"][0])}'
        if query not in known_queries:
            return {"query": query, "kind": "employer_follow_up", "domains": [host],
                "reason": "Investigar un sitio observado en los resultados; no presupone que sea la empresa ni una oferta vigente."}
    return None

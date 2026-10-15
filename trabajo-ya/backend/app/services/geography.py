"""Official place identity and approximate aerial distances; never model coordinates.

GeoRef's public CC BY 4.0 locality centroids are the coordinate source. A place
being real does not prove that an employer's job is located there: callers must
retain and verify the location quoted by the publication independently.
"""
from collections import OrderedDict, deque
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
import re
import time
import unicodedata
from uuid import uuid4

import httpx
from fastapi import HTTPException

GEOREF_ENDPOINT = "https://apis.datos.gob.ar/georef/api/v2.0/localidades"
GEOREF_SOURCE = "https://www.argentina.gob.ar/georef"
ATTRIBUTION = "Servicio Georef – argentina.gob.ar/georef (CC BY 4.0)"
MAX_RESPONSE_BYTES = 3 * 1024 * 1024
MAX_LOOKUPS_PER_SEARCH = 8
MAX_NEARBY_CITIES = 50
PAGE_SIZE = 5000
MAX_CATALOG_PAGES = 3
CACHE_TTL = 24 * 60 * 60
MAX_CACHE_ENTRIES = 256
EARTH_RADIUS_KM = 6371.0088
_cache = OrderedDict()
_request_times = deque()


def _normalized(value):
    if not isinstance(value, str):
        return ""
    value = unicodedata.normalize("NFKD", value.casefold())
    return " ".join("".join(c for c in value if not unicodedata.combining(c)).split())


def _text(value, limit=120):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 for c in value):
        return ""
    return value.strip()


def _country(value):
    return "Argentina" if _normalized(value) in {"argentina", "ar", "arg", "republica argentina"} else ""


def _provider(settings):
    return getattr(settings, "geocoder_provider", "georef_ar") == "georef_ar"


def _radius(value):
    if type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 1000:
        raise HTTPException(422, "El radio debe ser un número entre 0 y 1000 kilómetros.")
    return float(value)


def _coordinates(latitude, longitude):
    if type(latitude) not in {int, float} or type(longitude) not in {int, float}:
        raise ValueError("Coordenadas inválidas")
    if not math.isfinite(latitude) or not math.isfinite(longitude) or not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("Coordenadas inválidas")
    return float(latitude), float(longitude)


def haversine_km(latitude_a, longitude_a, latitude_b, longitude_b):
    """Great-circle distance between centroids, not driving/road distance."""
    lat_a, lon_a = _coordinates(latitude_a, longitude_a)
    lat_b, lon_b = _coordinates(latitude_b, longitude_b)
    latitude_delta, longitude_delta = math.radians(lat_b - lat_a), math.radians(lon_b - lon_a)
    a = math.sin(latitude_delta / 2) ** 2 + math.cos(math.radians(lat_a)) * math.cos(math.radians(lat_b)) * math.sin(longitude_delta / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.atan2(math.sqrt(min(1, max(0, a))), math.sqrt(max(0, 1 - a)))


def clear_geography_cache():
    """Used by deterministic tests and administrative cache refreshes."""
    _cache.clear()
    _request_times.clear()


def _cached(key):
    item = _cache.get(key)
    if item is None:
        return None
    if time.monotonic() - item[0] >= CACHE_TTL:
        _cache.pop(key, None)
        return None
    _cache.move_to_end(key)
    return deepcopy(item[1])


def _remember(key, payload):
    _cache[key] = (time.monotonic(), deepcopy(payload))
    _cache.move_to_end(key)
    while len(_cache) > MAX_CACHE_ENTRIES:
        _cache.popitem(last=False)


def _reserve_request(budget):
    if budget is not None:
        count = budget.get("geography_request_count", 0)
        if type(count) is not int or count >= MAX_LOOKUPS_PER_SEARCH:
            raise HTTPException(429, "Se alcanzó el límite de verificaciones geográficas de esta búsqueda; las restantes requieren revisión.")
    now = time.monotonic()
    while _request_times and now - _request_times[0] >= 86400:
        _request_times.popleft()
    # All checks happen before the first await, so concurrent tasks cannot
    # overbook this process. Multiple servers need a shared provider quota.
    for window, maximum in ((1, 10), (60, 40), (3600, 2000), (86400, 10000)):
        if sum(now - previous < window for previous in _request_times) >= maximum:
            raise HTTPException(429, "Se alcanzó la cuota de consultas de GeoRef; la ubicación queda pendiente de revisión.")
    _request_times.append(now)
    if budget is not None:
        budget["geography_request_count"] = count + 1


async def _audit_request(budget, event):
    callback = budget.get("_research_audit") if isinstance(budget, dict) else None
    if callback is None:
        return
    try:
        await callback(dict(event))
    except Exception as error:
        # A failed history write is not a geocoding outage. It must stop the
        # whole research instead of returning an unaudited, apparent success.
        if getattr(error, "audit_failed", False):
            raise
        failure = HTTPException(503, "No se pudo guardar el historial de verificación geográfica. La investigación no se completó.")
        failure.audit_failed = True
        raise failure from None


async def _request(client, params, budget=None):
    key = ("query", tuple(sorted((name, str(value)) for name, value in params.items())))
    hit = _cached(key)
    if hit is not None:
        return hit
    _reserve_request(budget)
    query = ", ".join(value for key in ("nombre", "provincia") if (value := _text(params.get(key))))
    context = {"kind": "geocode", "provider": "georef", "event_id": str(uuid4()),
        "url": GEOREF_ENDPOINT, "query": query or "Catálogo localidades",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "metadata": {"from_cache": False, "geocoding_provider": "georef_ar", "provider_method": "GET",
            "query_index": budget.get("geography_request_count", 1) if isinstance(budget, dict) else 1}}
    # Only a cache miss reserves quota and creates an HTTP-attempt record.
    # Cache consumers retain the original _georef_fetched_at and emit no new
    # provider response, so a cached coordinate cannot look freshly queried.
    await _audit_request(budget, {**context, "status": "started", "provider_response_received": False})
    status_code, size = None, 0
    try:
        async with client.stream("GET", GEOREF_ENDPOINT, params=params,
                headers={"Accept": "application/json"}, timeout=20, follow_redirects=False) as response:
            status_code = response.status_code
            if response.status_code == 429:
                raise HTTPException(429, "GeoRef alcanzó su cuota de consultas; la ubicación queda pendiente de revisión.")
            if response.status_code != 200:
                raise HTTPException(502, "No se pudo consultar GeoRef. No se confirmaron coordenadas ni distancias.")
            chunks = []
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise HTTPException(502, "GeoRef devolvió una respuesta demasiado grande. No se confirmaron coordenadas.")
                chunks.append(chunk)
        payload = json.loads(b"".join(chunks))
        if (not isinstance(payload, dict) or not isinstance(payload.get("localidades"), list)
                or len(payload["localidades"]) > int(params["max"])
                or type(payload.get("total")) is not int or payload["total"] < len(payload["localidades"])
                or type(payload.get("inicio", 0)) is not int or payload.get("inicio", 0) != int(params.get("inicio", 0))):
            raise HTTPException(502, "GeoRef devolvió datos inválidos. No se confirmaron coordenadas.")
        payload["_georef_fetched_at"] = datetime.now(timezone.utc).isoformat()
    except HTTPException as error:
        if getattr(error, "audit_failed", False):
            raise
        await _audit_request(budget, {**context, "status": "failed",
            "finished_at": datetime.now(timezone.utc).isoformat(), "http_status": status_code,
            "provider_response_received": status_code is not None, "response_bytes": size,
            "error": str(error.detail)})
        raise
    except (httpx.HTTPError, ValueError, TypeError, UnicodeError):
        detail = "No se pudo consultar GeoRef. No se confirmaron coordenadas ni distancias."
        await _audit_request(budget, {**context, "status": "failed",
            "finished_at": datetime.now(timezone.utc).isoformat(), "http_status": status_code,
            "provider_response_received": status_code is not None, "response_bytes": size,
            "error": detail})
        raise HTTPException(502, detail) from None
    await _audit_request(budget, {**context, "status": "succeeded",
        "finished_at": payload["_georef_fetched_at"], "http_status": status_code,
        "provider_response_received": True, "response_bytes": size,
        "result_count": len(payload["localidades"])})
    # Only fully recorded HTTP successes may populate the local cache. A
    # failed terminal write must not let later runs reuse unaudited responses.
    _remember(key, payload)
    return payload


def _location(raw, source_url, fetched_at):
    if not isinstance(raw, dict):
        return None
    identifier, city = raw.get("id"), _text(raw.get("nombre"))
    province = raw.get("provincia") if isinstance(raw.get("provincia"), dict) else {}
    province_id, province_name = province.get("id"), _text(province.get("nombre"))
    centroid = raw.get("centroide") if isinstance(raw.get("centroide"), dict) else {}
    if (not isinstance(identifier, str) or not re.fullmatch(r"[0-9]{8,12}", identifier)
            or not isinstance(province_id, str) or not re.fullmatch(r"[0-9]{2}", province_id)
            or not identifier.startswith(province_id) or not city or not province_name):
        return None
    try:
        latitude, longitude = _coordinates(centroid.get("lat"), centroid.get("lon"))
    except ValueError:
        return None
    # Mainland and national island localities cannot have coordinates at the
    # equator or on the other side of the world. Antarctica is not a city here.
    if not -60 <= latitude <= -20 or not -80 <= longitude <= -50:
        return None
    return {"id": identifier, "city": city, "province": province_name, "province_id": province_id,
        "country": "Argentina", "country_code": "AR", "latitude": latitude, "longitude": longitude,
        "provider": "georef_ar", "source_url": source_url,
        "resolved_at": fetched_at, "attribution": ATTRIBUTION,
        "coordinate_type": "locality_centroid", "verified": True}


def _source_url(params):
    return str(httpx.URL(GEOREF_ENDPOINT, params=params))


def _matches(location, city, province):
    return _normalized(location["city"]) == _normalized(city) and (
        not province or _normalized(location["province"]) == _normalized(province) or location["province_id"] == province)


async def resolve_locations(settings, client, city, province=None, country=None, *, budget=None):
    """Return exact official candidates. Fuzzy API suggestions are not proof."""
    if province is not None and (not isinstance(province, str) or (province and not _text(province))):
        return []
    city, province = _text(city), _text(province) if province else ""
    if not _provider(settings) or not city or not _country(country):
        return []
    catalog = _cached(("catalog", "AR"))
    if catalog is not None and catalog["complete"] and not catalog["invalid_count"]:
        return [place for place in catalog["locations"] if _matches(place, city, province)][:20]
    params = {"nombre": city, "campos": "id,nombre,centroide,provincia", "max": 20, "exacto": "true", "orden": "id"}
    if province:
        params["provincia"] = province
    payload = await _request(client, params, budget)
    locations = [_location(raw, _source_url(params), payload["_georef_fetched_at"]) for raw in payload["localidades"]]
    exact = [place for place in locations if place and _matches(place, city, province)]
    if exact and any(place is None for place in locations):
        raise HTTPException(409, {"code": "location_ambiguous", "message": "GeoRef devolvió candidatos incompletos. No se puede confirmar una localidad única sin revisar sus datos.", "candidates": exact})
    # A truncated list cannot establish uniqueness, even if one candidate fits.
    if payload["total"] > len(payload["localidades"]):
        raise HTTPException(409, {"code": "location_ambiguous", "message": "Hay demasiadas localidades posibles. Indicá la provincia para confirmar la ubicación.", "candidates": exact})
    return exact


def _proposal_value(proposal, key, default=None):
    return proposal.get(key, default) if isinstance(proposal, dict) else getattr(proposal, key, default)


async def resolve_search_location(settings, client, proposal):
    city = _proposal_value(proposal, "city")
    province = _proposal_value(proposal, "province")
    country = _proposal_value(proposal, "country")
    identifier = _proposal_value(proposal, "location_id")
    if not _provider(settings) or not _country(country):
        raise HTTPException(409, {"code": "geocoder_unavailable", "message": "La geocodificación disponible cubre Argentina. Para este país falta un proveedor geográfico autorizado; no se guardaron coordenadas.", "candidates": []})
    locations = await resolve_locations(settings, client, city, province, country)
    if identifier:
        locations = [location for location in locations if location["id"] == identifier]
    if len(locations) != 1:
        raise HTTPException(409, {"code": "location_ambiguous" if locations else "location_unresolved",
            "message": "Seleccioná una localidad y provincia verificadas." if locations else "No se pudo confirmar esa localidad y provincia en GeoRef. Revisá el nombre; no se inventaron coordenadas.",
            "candidates": locations})
    return locations[0]


async def _catalog(client, budget):
    hit = _cached(("catalog", "AR"))
    if hit is not None:
        return hit
    locations, identifiers, complete, invalid_count = [], set(), False, 0
    for page in range(MAX_CATALOG_PAGES):
        params = {"campos": "id,nombre,centroide,provincia", "max": PAGE_SIZE, "inicio": page * PAGE_SIZE, "orden": "id"}
        payload = await _request(client, params, budget)
        for raw in payload["localidades"]:
            location = _location(raw, _source_url(params), payload["_georef_fetched_at"])
            if location and location["id"] not in identifiers:
                identifiers.add(location["id"])
                locations.append(location)
            elif not location:
                invalid_count += 1
        if params["inicio"] + len(payload["localidades"]) >= payload["total"]:
            complete = True
            break
        if len(payload["localidades"]) != PAGE_SIZE:
            break
    result = {"locations": locations, "complete": complete, "invalid_count": invalid_count}
    _remember(("catalog", "AR"), result)
    return result


async def prepare_search_geography(settings, client, search):
    """Reconfirm saved identity and derive nearby cities across province borders."""
    enriched = deepcopy(search)
    enriched["geography_warnings"] = []
    enriched["nearby_cities"] = []
    enriched["geography_request_count"] = 0
    enriched["distance_type"] = "air_centroid"
    radius = enriched.get("radius_km", 0)
    enriched["radius_km"] = _radius(0 if radius is None else radius)
    saved = search.get("location") if isinstance(search.get("location"), dict) else {}
    cities = search.get("cities") if isinstance(search.get("cities"), list) else []
    city = search.get("city") or saved.get("city") or (cities[0] if cities else None)
    province = search.get("province") or saved.get("province")
    country = search.get("country") or saved.get("country")
    if not city or not country or not _provider(settings):
        enriched["location"] = None
        enriched["geography_warnings"].append("La búsqueda no tiene localidad y país verificables. No se pueden confirmar distancias ni el radio; las ofertas requieren revisión.")
        return enriched
    try:
        places = await resolve_locations(settings, client, city, province, country, budget=enriched)
        identifier = search.get("location_id") or saved.get("id")
        if identifier:
            places = [place for place in places if place["id"] == identifier]
        if len(places) != 1:
            raise HTTPException(409, "La ubicación de la búsqueda es ambigua o no se pudo verificar. Confirmá la localidad y provincia.")
        center = places[0]
        enriched["location"] = center
        enriched["location_id"] = center["id"]
        enriched["country"], enriched["province"] = center["country"], center["province"]
        if enriched["radius_km"] == 0:
            enriched["nearby_cities"] = [{**center, "distance_km": 0.0}]
            return enriched
        catalog = await _catalog(client, enriched)
        nearby = []
        for place in catalog["locations"]:
            distance = haversine_km(center["latitude"], center["longitude"], place["latitude"], place["longitude"])
            if distance <= enriched["radius_km"]:
                nearby.append({**place, "distance_km": round(distance, 3)})
        if center["id"] not in {place["id"] for place in nearby}:
            nearby.append({**center, "distance_km": 0.0})
        nearby.sort(key=lambda place: (place["distance_km"], place["id"]))
        enriched["nearby_cities"] = nearby[:MAX_NEARBY_CITIES]
        if not catalog["complete"]:
            enriched["geography_warnings"].append("El catálogo de localidades quedó incompleto. No se afirma una cobertura completa del radio.")
        if catalog["invalid_count"]:
            enriched["geography_warnings"].append("Algunas localidades del catálogo no tienen coordenadas válidas; no se afirma una cobertura completa del radio.")
        if len(nearby) > MAX_NEARBY_CITIES:
            enriched["geography_warnings"].append("Se usan las 50 localidades más cercanas para planificar consultas; no se afirma que se investigó todo el radio.")
        enriched["geography_warnings"].append("El radio y las distancias usan centroides de localidades y distancia aérea aproximada; no son kilómetros por carretera ni la dirección del puesto.")
    except HTTPException as error:
        if getattr(error, "audit_failed", False):
            raise
        if not isinstance(enriched.get("location"), dict) or "center" not in locals():
            enriched["location"] = None
        elif not enriched["nearby_cities"]:
            enriched["nearby_cities"] = [{**center, "distance_km": 0.0}]
        detail = error.detail.get("message") if isinstance(error.detail, dict) else error.detail
        enriched["geography_warnings"].append(str(detail))
    return enriched


def _job_place_fields(job):
    # Only publication-derived fields are eligible. Never inherit the country
    # or province of the search, nor coordinates/IDs supplied by a model.
    city, province, country = job.get("city"), job.get("province"), job.get("country")
    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
    evidence = payload.get("location_evidence") if isinstance(payload.get("location_evidence"), dict) else {}
    city = city or evidence.get("city")
    province = province or evidence.get("province")
    country = country or evidence.get("country")
    # An origin's explicit comma-separated location is acceptable input;
    # source extraction still needs to attest that it names the work location.
    if isinstance(city, str) and "," in city:
        parts = [part.strip() for part in city.split(",")]
        if len(parts) == 3 and _country(parts[2]):
            city, province, country = parts[0], province or parts[1], country or parts[2]
        elif len(parts) == 2 and _country(parts[1]):
            city, country = parts[0], country or parts[1]
    return city, province, country


async def classify_job_location(settings, client, job, search):
    """Classify a sourced place; unknown/ambiguous places cannot qualify mail."""
    result = {"location_verified": False, "location": None, "distance_km": None, "within_radius": None,
        "distance_type": "air_centroid", "location_status": "pending_review", "warnings": []}
    city, province, country = _job_place_fields(job)
    if not _text(city) or not _country(country):
        result["warnings"].append("La publicación no confirma una localidad y país verificables. No se estimó la distancia desde la consulta.")
        return result
    try:
        places = await resolve_locations(settings, client, city, province, country, budget=search)
        if len(places) != 1:
            result["warnings"].append("La ubicación publicada es ambigua o no aparece en GeoRef; requiere revisión.")
            return result
        location = places[0]
        result["location"] = location
        result["location_verified"] = True
        result["location_status"] = "verified"
        center = search.get("location") if isinstance(search.get("location"), dict) else {}
        # Re-resolve center by identity instead of trusting saved/client/AI
        # coordinates. Geocoding successes are cached and budgeted.
        centers = await resolve_locations(settings, client, center.get("city"), center.get("province"), center.get("country"), budget=search)
        centers = [place for place in centers if place["id"] == center.get("id")]
        if len(centers) != 1:
            result["warnings"].append("No se pudo confirmar el centro de la búsqueda; el radio queda pendiente de revisión.")
            return result
        center = centers[0]
        distance = haversine_km(center["latitude"], center["longitude"], location["latitude"], location["longitude"])
        radius = _radius(search.get("radius_km", 0))
        within = location["id"] == center["id"] if radius == 0 else distance <= radius
        result["distance_km"] = round(distance, 3)
        result["within_radius"] = within
        result["location_status"] = "verified" if within else "outside_radius"
    except HTTPException as error:
        if getattr(error, "audit_failed", False):
            raise
        detail = error.detail.get("message") if isinstance(error.detail, dict) else error.detail
        result["warnings"].append(str(detail))
    return result

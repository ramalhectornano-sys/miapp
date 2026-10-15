"""General, bounded Internet research; the CLI and scheduler use this same path."""
from copy import deepcopy
from urllib.parse import urlsplit

from fastapi import HTTPException

from .geography import classify_job_location, prepare_search_geography
from .public_pages import investigate_pages
from .query_planner import role_terms
from .web_search import canonical_result_url, discover_web_results, extract_web_jobs
from .ai import normalize


async def qualify_geography(settings, client, raw, search):
    row = deepcopy(raw)
    classification = await classify_job_location(settings, client, row, search)
    if classification["within_radius"] is False:
        return None
    payload = row.setdefault("payload", {})
    classification.update({"search_id": search.get("id"), "radius_km": search.get("radius_km", 0),
        "search_center": search.get("location")})
    payload["geography"] = classification
    if classification.get("location"):
        row["province"] = classification["location"]["province"]
        row["country"] = classification["location"]["country"]
    payload["research_mode"] = "general"
    if classification["within_radius"] is not True:
        row["recipient_verified"] = False
        row.pop("recipient_verified_at", None)
        payload["requires_manual_review"] = True
        payload["requires_manual_verification"] = True
    return row


def automatic_geography_allowed(job, search):
    """A shared job's last distance must not authorize another search's area."""
    if search.get("research_mode") != "general":
        return True
    proof = (job.get("payload") or {}).get("geography")
    if not isinstance(proof, dict) or proof.get("within_radius") is not True or proof.get("location_verified") is not True:
        return False
    center = proof.get("search_center")
    if not isinstance(center, dict) or proof.get("search_id") != search.get("id") or proof.get("radius_km") != search.get("radius_km", 0):
        return False
    if not any(normalize(str(city)) == normalize(str(center.get("city", ""))) for city in search.get("cities", [])):
        return False
    return all(not search.get(field) or normalize(str(search[field])) == normalize(str(center.get(field, "")))
        for field in ("province", "country"))


def merge_jobs(rows):
    """Keep a complete best-evidenced record; never mix recipient/source proofs."""
    unique = {}
    for row in rows:
        identity = (canonical_result_url(row["url"]) if row.get("url") else "",
            str(row.get("company", "")).casefold(), str(row.get("title", "")).casefold(),
            str(row.get("city", "")).casefold())
        previous = unique.get(identity)
        if previous and previous.get("recipient_verified") and not row.get("recipient_verified"):
            continue
        unique[identity] = row
    return list(unique.values())


async def run_research(settings, client, search, *, audit=None):
    if not settings.web_search_ready:
        raise HTTPException(503, "Falta configurar Tavily en el servidor. No se ejecutó ninguna consulta web.")
    working = deepcopy(search)
    if audit:
        working["_research_audit"] = audit
    working = await prepare_search_geography(settings, client, working)
    discoveries, failures = await discover_web_results(settings, client, working, audit=audit)
    enriched, page_failures = await investigate_pages(settings, client, discoveries, working, audit=audit)
    failures.extend(page_failures)
    try:
        jobs = await extract_web_jobs(settings, client, working, enriched, audit=audit)
    except HTTPException as failure:
        # Keep already observed public evidence for the CLI's bounded serializer.
        # The HTTP error remains an error: no partial jobs or mail are authorized.
        failure.research_partial = {"search": {key: value for key, value in working.items()
            if key != "_research_audit"}, "discoveries": enriched, "results": [],
            "failures": list(dict.fromkeys(failures)), "warnings": working.get("geography_warnings", [])}
        raise
    proofs = {result["url"]: result.get("page_verification", {}) for result in enriched}
    qualified, outside_count = [], 0
    for job in jobs:
        proof = proofs.get(job.get("url"), {})
        job.setdefault("payload", {})["page_verification"] = {key: proof[key] for key in (
            "status", "checked_at", "http_status", "final_url", "content_sha256", "reason", "dates") if key in proof}
        result = await qualify_geography(settings, client, job, working)
        if result is None:
            outside_count += 1
        else:
            result["_integration_id"] = "web:tavily"
            result.setdefault("payload", {})["publisher_host"] = urlsplit(result["url"]).hostname
            qualified.append(result)
    working.pop("_research_audit", None)
    warnings = [failure for failure in failures if "quedaron combinaciones sin consultar" in failure]
    failures = [failure for failure in failures if failure not in warnings]
    return {"search": working, "results": merge_jobs(qualified), "discoveries": enriched,
        "failures": list(dict.fromkeys(failures)), "warnings": warnings, "outside_radius_count": outside_count,
        "geography_warnings": working.get("geography_warnings", []),
        "role_terms": role_terms(working)}

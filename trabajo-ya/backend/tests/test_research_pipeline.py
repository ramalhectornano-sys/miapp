"""General-research integration fixtures, never evidence of a live search.

Every coordinate, company and provider response below is synthetic. The tests
exercise the production Tavily -> publisher -> Groq -> GeoRef path via HTTPX
MockTransport, and the separate barriers that prevent unverified mail.
"""
import json
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException

from app.config import Settings
from app.db import User
from app.services.feeds import find_jobs, normalize_job, process_automatic_drafts
from app.services.geography import clear_geography_cache
from app.services.research import qualify_geography, run_research
from app.services.research_audit import ResearchAuditError
from tests.test_geography import place, response
from tests.test_greenhouse_pipeline import GREENHOUSE, verified_job


SEARCH = {"id": "11111111-1111-4111-8111-111111111111", "user_id": "owned-user",
    "run_id": "22222222-2222-4222-8222-222222222222", "claim_token": "fixture-claim",
    "research_mode": "general", "roles": ["Chofer"], "cities": ["Localidad central"],
    "province": "Neuquén", "country": "Argentina", "radius_km": 100}
HOST = "https://empresa.example.org"
SECRETS = ("TEST-PRIVATE-TAVILY", "TEST-PRIVATE-GROQ", "sb_secret_FIXTURE")


def settings(**changes):
    return Settings(**{"web_search_provider": "tavily", "web_search_api_key": SECRETS[0],
        "web_search_max_queries": 6, "ai_provider": "openai_compatible",
        "ai_base_url": "https://api.groq.com/openai/v1", "ai_model": "fixture-model",
        "ai_api_key": SECRETS[1], "supabase_service_role_key": SECRETS[2], **changes})


def candidate(index, city, province=None, country=None):
    location = ", ".join(item for item in (city, province, country) if item)
    ad = f"Transportes Ejemplo busca Conductor profesional en {location}. Licencia profesional vigente."
    item = {"result_index": index, "company": "Transportes Ejemplo", "title": "Conductor profesional",
        "city": city, "description": ad, "requirements": ["Licencia profesional vigente"],
        "evidence": {"company": "Transportes Ejemplo", "title": "Conductor profesional", "city": city,
            "vacancy": ad, "requirements": ["Licencia profesional vigente"]}}
    for key, value in (("province", province), ("country", country)):
        if value:
            item[key] = value
            item["evidence"][key] = value
    return item


class ResearchPipelineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        clear_geography_cache()

    async def test_groq_failure_retains_observed_links_without_returning_or_authorizing_jobs(self):
        saved = {**SEARCH, "location": {"id": "fixture-location", "verified": True}}
        page = {"url": HOST + "/vacante", "title": "Chofer", "raw_content": "Published evidence"}
        with patch("app.services.research.prepare_search_geography", AsyncMock(return_value=saved)), \
                patch("app.services.research.discover_web_results", AsyncMock(return_value=([page], []))) as discovery, \
                patch("app.services.research.investigate_pages", AsyncMock(return_value=([page], []))), \
                patch("app.services.research.extract_web_jobs", AsyncMock(side_effect=HTTPException(429, "Quota"))):
            with self.assertRaises(HTTPException) as caught:
                await run_research(settings(), None, SEARCH)
        discovery.assert_awaited_once()
        self.assertEqual(caught.exception.status_code, 429)
        partial = caught.exception.research_partial
        self.assertEqual(partial["discoveries"][0]["url"], page["url"])
        self.assertTrue(partial["search"]["location"]["verified"])
        self.assertEqual(partial["results"], [])
        self.assertNotIn("_research_audit", partial["search"])

    async def test_actual_adapters_keep_cross_province_nearby_and_unknown_but_drop_outside(self):
        center = place(city="Localidad central")
        # Deliberately synthetic centroids: 0.5 degree (~55.6km) and 2 degrees
        # (~222.4km) from the center. Province borders do not define the radius.
        nearby = place("50035020000", "Localidad vecina", "Mendoza", latitude=-36.5)
        distant = place("58035030000", "Localidad lejana", latitude=-35)
        candidates = [candidate(0, "Localidad vecina", "Mendoza", "Argentina"),
            candidate(1, "Localidad lejana", "Neuquén", "Argentina"),
            candidate(2, "Zona sin precisar")]
        discoveries = [{"url": f"{HOST}/vacantes/{index}", "title": row["title"], "content": row["description"]}
            for index, row in enumerate(candidates)]
        requests, events, query_bodies = [], [], []

        async def record(event):
            events.append(deepcopy(event))

        def provider(request):
            requests.append(request)
            if request.url.host == "apis.datos.gob.ar":
                self.assertNotIn("authorization", request.headers)
                rows = [center] if request.url.params.get("nombre") else [center, nearby, distant]
                return httpx.Response(200, json=response(rows))
            if request.url.host == "api.tavily.com":
                self.assertEqual(request.headers["authorization"], f"Bearer {SECRETS[0]}")
                query_bodies.append(json.loads(request.content))
                return httpx.Response(200, json={"results": discoveries,
                    "request_id": f"MOCK-ONLY-receipt-{len(query_bodies)}", "usage": {"credits": 1}})
            if request.url.host == "empresa.example.org":
                self.assertNotIn("authorization", request.headers)
                self.assertNotIn("apikey", request.headers)
                self.assertNotIn("cookie", request.headers)
                if request.url.path == "/robots.txt":
                    return httpx.Response(200, text="User-agent: *\nAllow: /\n", headers={"content-type": "text/plain"})
                index = int(request.url.path.rsplit("/", 1)[1])
                return httpx.Response(200, text=f"<main><p>{candidates[index]['description']}</p></main>",
                    headers={"content-type": "text/html"})
            self.assertEqual(request.url.host, "api.groq.com")
            self.assertEqual(request.headers["authorization"], f"Bearer {SECRETS[1]}")
            # Analysis starts only after the original links were actually read.
            self.assertEqual(sum(row.url.host == "empresa.example.org" for row in requests), 4)
            return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
                "content": json.dumps({"jobs": candidates})}}]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            report = await run_research(settings(), client, deepcopy(SEARCH), audit=record)
        self.assertEqual(len(query_bodies), 6)
        self.assertNotIn("include_domains", query_bodies[0])
        self.assertTrue(all(not body["query"].startswith("site:") for body in query_bodies[:4]))
        self.assertTrue(any("conductor profesional" in body["query"] for body in query_bodies))
        self.assertTrue(any("empresas" in body["query"] for body in query_bodies))
        self.assertTrue(any("linkedin.com" in body["query"] for body in query_bodies))
        self.assertTrue(any("ar.computrabajo.com" in body["query"] for body in query_bodies))
        self.assertEqual(len(report["discoveries"]), 3)  # same hits across six queries deduplicated
        self.assertEqual(report["outside_radius_count"], 1)
        self.assertEqual({job["city"] for job in report["results"]}, {"Localidad vecina", "Zona sin precisar"})
        near = next(job for job in report["results"] if job["city"] == "Localidad vecina")
        self.assertEqual(near["province"], "Mendoza")
        self.assertTrue(near["payload"]["geography"]["within_radius"])
        self.assertAlmostEqual(near["payload"]["geography"]["distance_km"], 55.598, places=2)
        unknown = next(job for job in report["results"] if job["city"] == "Zona sin precisar")
        self.assertIsNone(unknown["payload"]["geography"]["within_radius"])
        self.assertNotIn("country", unknown)
        self.assertTrue(unknown["payload"]["requires_manual_review"])
        self.assertTrue(all(not job["recipient_verified"] for job in report["results"]))
        self.assertTrue(all(job["payload"]["page_verification"]["status"] == "verified_link" for job in report["results"]))
        completed_queries = [event for event in events if event["kind"] == "tavily_query" and event["status"] == "succeeded"]
        self.assertEqual(len(completed_queries), 6)
        self.assertTrue(all(event["http_status"] == 200 and event["request_id"].startswith("MOCK-ONLY-") for event in completed_queries))
        self.assertTrue(all(any(previous["event_id"] == event["event_id"] and previous["status"] == "started"
            for previous in events) for event in completed_queries))
        self.assertFalse(any("gmail" in row.url.host for row in requests))
        self.assertTrue(all(secret not in json.dumps(events) for secret in SECRETS))
        self.assertNotIn("_research_audit", report["search"])

    async def test_initial_database_audit_failure_prevents_tavily_and_analysis_requests(self):
        rpc = AsyncMock(return_value=False)
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: self.fail("No provider call may precede its durable audit"))) as client:
            db = SimpleNamespace(settings=settings(geocoder_provider="disabled"), client=client, rpc=rpc)
            with self.assertRaises(HTTPException) as failure:
                await find_jobs(db, deepcopy(SEARCH))
        self.assertEqual(failure.exception.status_code, 503)
        self.assertEqual(rpc.await_count, 1)
        operation, payload = rpc.await_args.args
        self.assertEqual(operation, "record_web_research_event")
        self.assertEqual(payload["p_search_id"], SEARCH["id"])
        self.assertEqual(payload["p_run_id"], SEARCH["run_id"])
        self.assertEqual(payload["p_claim_token"], SEARCH["claim_token"])
        self.assertEqual(payload["p_event"]["status"], "started")
        self.assertEqual(payload["p_event"]["provider"], "tavily")

    async def test_unknown_location_clears_even_official_email_attestation(self):
        raw = verified_job()
        classifier = AsyncMock(return_value={"within_radius": None, "location": None,
            "location_verified": False, "location_status": "pending_review", "distance_km": None})
        with patch("app.services.research.classify_job_location", classifier):
            qualified = await qualify_geography(settings(), None, raw, SEARCH)
        normalized = normalize_job(qualified, GREENHOUSE, SEARCH["user_id"])
        self.assertFalse(qualified["recipient_verified"])
        self.assertIsNone(normalized["recipient_verified_at"])
        self.assertTrue(normalized["payload"]["requires_manual_review"])
        self.assertTrue(raw["recipient_verified"])  # never mutate another source's record

    async def test_automatic_drafts_do_not_reserve_or_send_for_unknown_geography(self):
        user = User(SEARCH["user_id"], "worker-session")
        current = {**SEARCH, "status": "enabled", "auto_apply": True, "consent_id": "valid-consent"}
        job = {"id": "official-job", "source": GREENHOUSE["id"],
            "recipient_verified_at": "2026-10-15T12:00:00Z", "payload": {
                "research_mode": "general", "geography": {"within_radius": None}}}

        async def owned(table, *_args, **_kwargs):
            return current if table == "job_searches" else job

        rpc = AsyncMock(return_value=True)
        db = SimpleNamespace(settings=settings(mail_send_enabled=True), rpc=rpc, owned=owned,
            select=AsyncMock(return_value=[{"id": "draft", "job_id": job["id"]}]))
        sender = AsyncMock()
        with patch("app.services.mail.send_application", sender):
            self.assertEqual(await process_automatic_drafts(db, current, user), (0, 0))
        sender.assert_not_awaited()
        self.assertFalse(any(call.args[0] == "prepare_automatic_application" for call in rpc.await_args_list))

    async def test_audit_failure_cannot_be_downgraded_to_an_empty_successful_run(self):
        failure = ResearchAuditError()
        with patch("app.services.research.prepare_search_geography", AsyncMock(side_effect=failure)), \
                patch("app.services.research.discover_web_results", AsyncMock()) as discovery:
            with self.assertRaises(ResearchAuditError):
                await run_research(settings(), None, SEARCH)
        discovery.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()

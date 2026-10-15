"""General-web analysis retains literal evidence and records real call attempts.

All provider responses here are explicit mocks. These tests are not proof of a
live Tavily/Groq query, a verified employer, a geographic match or a mail send.
"""
import json
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID

import httpx
from fastapi import HTTPException

from app.config import Settings
from app.models import ChatRequest
from app.services.ai import SYSTEM as CHAT_SYSTEM, chat
from app.services.job_evidence import MAX_INPUT_CHARS, MAX_RESULTS, extract_job_evidence

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
SEARCH = {"roles": ["chofer"], "cities": ["Rincón de los Sauces"], "location": {
    "city": "Rincón de los Sauces", "province": "Neuquén", "country": "Argentina", "radius_km": 100}}
AD = "Transportes del Sur busca Conductor profesional en Buta Ranquil, Neuquén, Argentina. Licencia profesional vigente."
URL = "https://empleos.example.org/vacantes/456"


def settings(**changes):
    return Settings(**{"ai_provider": "openai_compatible", "ai_base_url": "https://api.groq.com/openai/v1",
        "ai_model": "openai/gpt-oss-20b", "ai_api_key": "TEST-PRIVATE-KEY", **changes})


def raw_job(**changes):
    return {"result_index": 0, "company": "Transportes del Sur", "title": "Conductor profesional",
        "city": "Buta Ranquil", "description": AD, "province": "Neuquén", "country": "Argentina",
        "requirements": ["Licencia profesional vigente"], "evidence": {
            "company": "Transportes del Sur", "title": "Conductor profesional", "city": "Buta Ranquil",
            "province": "Neuquén", "country": "Argentina", "vacancy": AD,
            "requirements": ["Licencia profesional vigente"]}, **changes}


def source(**changes):
    return {"url": URL, "title": "Conductor profesional", "content": AD, **changes}


def completion(jobs, **extra):
    return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"jobs": jobs})}}], **extra}


def structured_source(*, other_city=None, **changes):
    fact = {"company": "Transportes del Sur", "title": "Conductor profesional",
        "description": "Licencia profesional vigente", "hiringOrganization": {"name": "Transportes del Sur"},
        "jobLocation": [{"address": {"addressLocality": other_city or "Buta Ranquil", "addressRegion": "Neuquén",
            "addressCountry": "Argentina"}}]}
    text = "Transportes del Sur\nConductor profesional\nLicencia profesional vigente\nButa Ranquil Neuquén Argentina"
    return source(content="Resumen anterior que no prueba ninguna vacante", raw_content=text,
        page_verification={"status": "verified_link", "job_postings": [fact]}, **changes)


def structured_job(**changes):
    raw = raw_job(description="Licencia profesional vigente")
    raw["evidence"]["vacancy"] = "Conductor profesional"
    raw.update(changes)
    return raw


class GeoEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def extract(self, jobs=None, *, results=None, search=None, envelopes=None, status=200,
            config=None, audit=None):
        self.requests, self.events = [], []
        async def record(event):
            self.events.append(deepcopy(event))
        def transport(request):
            self.requests.append(request)
            envelope = envelopes[len(self.requests) - 1] if envelopes is not None else completion(jobs if jobs is not None else [raw_job()])
            if isinstance(envelope, Exception):
                raise envelope
            return httpx.Response(status, json=envelope)
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            return await extract_job_evidence(config or settings(), client, search or SEARCH,
                results if results is not None else [source()], now=NOW, audit=audit or record)

    async def test_synonym_and_different_city_are_candidates_for_later_radius_verification(self):
        jobs = await self.extract()
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job["city"], "Buta Ranquil")
        self.assertEqual(job["province"], "Neuquén")
        self.assertEqual(job["country"], "Argentina")
        self.assertEqual(job["requirements"], ["Licencia profesional vigente"])
        self.assertFalse(job["recipient_verified"])
        self.assertTrue(job["requires_manual_review"])
        self.assertNotIn("distance_km", job)
        self.assertNotIn("latitude", job)
        query = json.loads(json.loads(self.requests[0].content)["messages"][1]["content"])["query"]
        self.assertEqual(query["radius_km"], 100)
        self.assertEqual(query["province"], "Neuquén")
        self.assertEqual(query["country"], "Argentina")
        self.assertIn("conductor profesional", query["role_terms"])

    async def test_zero_radius_and_unrelated_profession_do_not_expand_city_or_role(self):
        search = deepcopy(SEARCH)
        search["location"]["radius_km"] = 0
        self.assertEqual(await self.extract(search=search), [])
        raw = raw_job(title="Electricista")
        raw["evidence"]["title"] = "Electricista"
        raw["evidence"]["vacancy"] = AD.replace("Conductor profesional", "Electricista")
        raw["description"] = raw["evidence"]["vacancy"]
        self.assertEqual(await self.extract([raw], results=[source(content=raw["description"])]), [])

    async def test_location_is_never_inherited_from_search(self):
        text = AD.replace(", Neuquén, Argentina", "")
        raw = raw_job(description=text)
        raw["evidence"]["vacancy"] = text
        self.assertEqual(await self.extract([raw], results=[source(content=text)]), [])
        raw.pop("province")
        raw.pop("country")
        jobs = await self.extract([raw], results=[source(content=text)])
        self.assertEqual(len(jobs), 1)
        self.assertNotIn("province", jobs[0])
        self.assertNotIn("country", jobs[0])
        self.assertEqual(jobs[0]["payload"]["location_evidence"], {})

    async def test_each_requirement_needs_its_own_exact_quote(self):
        raw = raw_job(requirements=["Licencia profesional vigente", "Cinco años de experiencia"])
        raw["evidence"]["requirements"].append("Cinco años de experiencia")
        self.assertEqual(await self.extract([raw]), [])
        raw = raw_job()
        raw["evidence"]["requirements"] = []
        self.assertEqual(await self.extract([raw]), [])

    async def test_matched_publisher_posting_allows_separate_literals_without_hiring_verb(self):
        jobs = await self.extract([structured_job()], results=[structured_source()])
        self.assertEqual(len(jobs), 1)
        self.assertFalse(jobs[0]["recipient_verified"])
        self.assertEqual(jobs[0]["payload"]["validity"]["status"], "unknown")

    async def test_readable_page_without_matching_structured_ad_keeps_strict_vacancy_requirement(self):
        for proof in ({"status": "pending_review", "job_postings": [structured_source()["page_verification"]["job_postings"][0]]},
                      {"status": "verified_link", "job_postings": []},
                      structured_source(other_city="Neuquén")["page_verification"]):
            with self.subTest(proof=proof):
                item = structured_source()
                item["page_verification"] = proof
                self.assertEqual(await self.extract([structured_job()], results=[item]), [])

    async def test_structured_ad_cannot_borrow_vacancy_or_description_from_another_ad(self):
        item = structured_source()
        item["raw_content"] += "\nOtra empresa ofrece beneficios ajenos"
        raw = structured_job(description="Otra empresa ofrece beneficios ajenos")
        self.assertEqual(await self.extract([raw], results=[item]), [])
        raw = structured_job()
        raw["evidence"]["vacancy"] = "Otra empresa ofrece beneficios ajenos"
        self.assertEqual(await self.extract([raw], results=[item]), [])

    async def test_publisher_date_vetoes_model_omission_and_preserves_literal_new_date(self):
        item = structured_source()
        fact = item["page_verification"]["job_postings"][0]
        fact["dates"] = {"valid_until": "2026-10-14"}
        self.assertEqual(await self.extract([structured_job()], results=[item]), [])
        fact["dates"] = {"published_at": "2026-10-10", "valid_until": "2026-10-31"}
        item["raw_content"] += "\npublished_at: 2026-10-10\nvalid_until: 2026-10-31"
        jobs = await self.extract([structured_job()], results=[item])
        self.assertEqual(jobs[0]["payload"]["validity"]["valid_until"], "2026-10-31")
        self.assertNotIn("valid_until", jobs[0])

    async def test_application_url_is_exact_original_or_observed_publisher_link(self):
        item = structured_source()
        item["raw_content"] += "\nPostulate mediante formulario"
        target = "https://reclutamiento.example.org/456"
        item["page_verification"]["application_links"] = [{"url": target, "evidence": "Postulate mediante formulario"}]
        raw = structured_job(application_method="form", application_url=target)
        raw["evidence"]["application_method"] = "Postulate mediante formulario"
        jobs = await self.extract([raw], results=[item])
        self.assertEqual(jobs[0]["application_url"], target)
        self.assertEqual(jobs[0]["payload"]["application"], {"method": "form", "url": target})
        prompt = json.loads(json.loads(self.requests[0].content)["messages"][1]["content"])
        self.assertEqual(prompt["results"][0]["application_links"][0]["url"], target)
        raw["application_url"] = URL
        self.assertEqual(len(await self.extract([raw], results=[item])), 1)
        raw["application_url"] = "https://inventado.example.org/formulario"
        self.assertEqual(await self.extract([raw], results=[item]), [])

    async def test_unread_page_cannot_approve_model_invented_application_link(self):
        item = source(content=AD + " Postulate mediante formulario.", page_verification={"status": "pending_review",
            "application_links": [{"url": "https://inventado.example.org/apply", "evidence": "Postulate mediante formulario"}]})
        raw = raw_job(application_method="form", application_url="https://inventado.example.org/apply")
        raw["evidence"]["application_method"] = "Postulate mediante formulario"
        self.assertEqual(await self.extract([raw], results=[item]), [])

    async def test_quoted_email_remains_manual_even_if_model_claims_verified(self):
        text = AD + " Enviar CV a seleccion@example.org."
        raw = raw_job(description=text, recipient_email="seleccion@example.org", recipient_verified=True)
        raw["evidence"]["vacancy"] = text
        raw["evidence"]["recipient_email"] = "Enviar CV a seleccion@example.org."
        jobs = await self.extract([raw], results=[source(content=text)])
        self.assertFalse(jobs[0]["recipient_verified"])
        self.assertEqual(jobs[0]["application_method"], "email")
        self.assertTrue(jobs[0]["payload"]["requires_manual_verification"])

    async def test_twenty_four_results_use_three_bounded_batches_with_stable_receipts(self):
        inputs = [source(url=f"https://empleos.example.org/{number}") for number in range(30)]
        jobs = await self.extract([raw_job()], results=inputs)
        self.assertEqual(len(self.requests), 3)
        self.assertEqual(len(jobs), 3)
        self.assertEqual(len(self.events), 6)
        ids = set()
        for batch in range(3):
            begin, done = self.events[batch * 2:batch * 2 + 2]
            self.assertEqual(begin["event_id"], done["event_id"])
            UUID(begin["event_id"])
            ids.add(begin["event_id"])
            self.assertEqual(begin["status"], "started")
            self.assertFalse(begin["provider_response_received"])
            self.assertEqual(done["status"], "succeeded")
            self.assertTrue(done["provider_response_received"])
            self.assertEqual(done["provider"], "groq")
            self.assertEqual(done["batch_index"], batch + 1)
            request = json.loads(self.requests[batch].content)
            prompt = json.loads(request["messages"][1]["content"])
            self.assertLessEqual(len(prompt["results"]), MAX_RESULTS)
            self.assertLessEqual(sum(len(result["text"]) for result in prompt["results"]), MAX_INPUT_CHARS)
        self.assertEqual(len(ids), 3)

    async def test_receipts_preserve_only_bounded_provider_identifiers_and_integer_usage(self):
        envelope = completion([raw_job()], id="chatcmpl-real-provider-receipt", usage={"prompt_tokens": 123,
            "completion_tokens": 45, "total_tokens": 168, "debug": "PRIVATE BODY", "token": "TEST-PRIVATE-KEY"})
        await self.extract(envelopes=[envelope])
        receipt = self.events[-1]
        self.assertEqual(receipt["request_id"], "chatcmpl-real-provider-receipt")
        self.assertEqual(receipt["usage"], {"prompt_tokens": 123, "completion_tokens": 45, "total_tokens": 168})
        self.assertNotIn(AD, json.dumps(self.events))
        self.assertNotIn("PRIVATE", json.dumps(self.events))
        envelope = completion([], id="TEST-PRIVATE-KEY", usage={"prompt_tokens": True,
            "completion_tokens": -1, "total_tokens": 99_999_999})
        await self.extract(envelopes=[envelope])
        self.assertNotIn("request_id", self.events[-1])
        self.assertNotIn("usage", self.events[-1])

    async def test_failure_in_later_batch_is_recorded_and_never_returns_partial_success(self):
        inputs = [source(url=f"https://empleos.example.org/{number}") for number in range(9)]
        with self.assertRaises(HTTPException) as error:
            await self.extract(results=inputs, envelopes=[completion([raw_job()]), {"error": "TEST-PRIVATE-KEY private diagnostic"}])
        self.assertEqual(error.exception.status_code, 502)
        self.assertEqual([event["status"] for event in self.events], ["started", "succeeded", "started", "failed"])
        self.assertEqual(self.events[-1]["http_status"], 200)
        self.assertNotIn("PRIVATE", json.dumps(self.events))

    async def test_http_failure_and_timeout_have_distinct_response_received_evidence(self):
        with self.assertRaises(HTTPException):
            await self.extract(envelopes=[{"error": "TEST-PRIVATE-KEY"}], status=429)
        self.assertEqual(self.events[-1]["http_status"], 429)
        self.assertTrue(self.events[-1]["provider_response_received"])
        with self.assertRaises(HTTPException):
            await self.extract(envelopes=[httpx.ReadTimeout("TEST-PRIVATE-KEY timeout")])
        self.assertIsNone(self.events[-1]["http_status"])
        self.assertFalse(self.events[-1]["provider_response_received"])
        self.assertNotIn("PRIVATE", json.dumps(self.events))

    async def test_failed_audit_stops_before_provider_or_stops_completion(self):
        calls = []
        async def failed(event):
            calls.append(event)
            raise RuntimeError("TEST-PRIVATE-KEY database failure")
        with self.assertRaises(HTTPException) as error:
            await self.extract(audit=failed)
        self.assertEqual(error.exception.status_code, 503)
        self.assertEqual(self.requests, [])
        async def fail_completion(event):
            if event["status"] == "succeeded":
                raise RuntimeError("TEST-PRIVATE-KEY")
        with self.assertRaises(HTTPException) as error:
            await self.extract(audit=fail_completion)
        self.assertEqual(error.exception.status_code, 503)
        self.assertNotIn("PRIVATE", str(error.exception.detail))

    async def test_no_call_or_receipt_is_created_for_empty_or_unsafe_sources(self):
        self.assertEqual(await self.extract(results=[]), [])
        self.assertEqual(self.events, [])
        for url in ("https://example.org:8443/1", "https://example.org/1?session=private", "https://224.0.0.1/1"):
            with self.subTest(url=url):
                self.assertEqual(await self.extract(results=[source(url=url)]), [])
                self.assertEqual(self.requests, [])
                self.assertEqual(self.events, [])

    async def test_verified_publisher_text_is_prioritized_over_long_search_snippet(self):
        item = structured_source()
        item["content"] = "irrelevante " * 20_000
        self.assertEqual(len(await self.extract([structured_job()], results=[item])), 1)
        prompt = json.loads(json.loads(self.requests[0].content)["messages"][1]["content"])
        self.assertTrue(prompt["results"][0]["text"].startswith("Transportes del Sur"))

    async def test_chat_preserves_requested_geography_without_accepting_action_claims(self):
        proposal = {"title": "Chofer en Rincón de los Sauces", "role": "chofer", "city": "Rincón de los Sauces",
            "province": "Neuquén", "country": "Argentina", "radius_km": 100, "frequency": "daily", "time": "09:00"}
        payload = {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({
            "reply": "Ya envié correos a todas las empresas", "proposal": proposal})}}]}
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))) as client:
            response = await chat(settings(), client, ChatRequest(message="Chofer en Rincón de los Sauces, Neuquén, Argentina, a 100 km a las 9"))
        self.assertEqual(response.proposal.radius_km, 100)
        self.assertEqual(response.proposal.province, "Neuquén")
        self.assertIn("100 km en línea recta", response.reply)
        self.assertIn("No se ejecutó ninguna búsqueda ni se enviaron correos", response.reply)
        self.assertNotIn("Ya envié", response.reply)
        self.assertIn("No inventes coordenadas", CHAT_SYSTEM)

    async def test_model_coordinates_are_rejected_by_chat_strict_schema(self):
        proposal = {"title": "Chofer", "role": "chofer", "city": "Rincón de los Sauces", "latitude": -37.0}
        payload = {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"proposal": proposal})}}]}
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))) as client:
            with self.assertRaises(HTTPException):
                await chat(settings(), client, ChatRequest(message="Chofer en Rincón de los Sauces"))


if __name__ == "__main__":
    unittest.main()

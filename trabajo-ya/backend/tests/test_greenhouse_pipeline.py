"""Discovery and official publisher verification stay separate and bounded."""
import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException

from app.config import Settings
from app.services.feeds import find_jobs, normalize_job
from app.services.source_registry import GREENHOUSE_SOURCE_ID, WEB_SOURCE_ID, public_source
from app.services.web_search import discover_web_results


SEARCH = {"user_id": "owned-user", "roles": ["chofer"], "cities": ["Neuquén"]}
URL = "https://job-boards.greenhouse.io/transportesdelta/jobs/123"
WEB = {"id": WEB_SOURCE_ID, "kind": "web_search", "authorized": True,
    "recipient_verification": "manual_review"}
GREENHOUSE = {"id": GREENHOUSE_SOURCE_ID, "kind": "greenhouse_verified", "authorized": True,
    "recipient_verification": "source_attestation"}


def settings(**changes):
    return Settings(ai_provider="openai_compatible", ai_base_url="https://ai.example.com/v1",
        ai_model="fixture-model", ai_api_key="TEST-PRIVATE-IA",
        web_search_provider="tavily", web_search_api_key="TEST-PRIVATE-WEB", **changes)


def verified_job():
    return {"id": "transportesdelta:123", "company": "Transportes Delta", "title": "chofer", "city": "Neuquén",
        "url": URL, "description": "Descripción completa del empleador para el puesto.",
        "recipient_email": "seleccion@delta.example.com", "recipient_verified": True, "is_active": True,
        "payload": {"integration_id": GREENHOUSE_SOURCE_ID,
            "verification_method": "publisher_api_explicit_email", "greenhouse": {
                "board": "transportesdelta", "job_id": 123,
                "endpoint": "https://boards-api.greenhouse.io/v1/boards/transportesdelta/jobs/123",
                "email_quote": "Enviar CV a seleccion@delta.example.com.",
                "fetched_at": "2026-10-14T12:00:00+00:00"}}}


def snippet():
    return {"title": "chofer Transportes Delta Neuquén", "url": URL,
        "content": "Buscamos chofer en Neuquén. Consultas: otros@delta.example.com."}


class GreenhousePipelineTests(unittest.IsolatedAsyncioTestCase):
    def test_registry_has_separate_capabilities_and_reserves_virtual_ids(self):
        configured = settings(authorized_feeds=[
            {"id": WEB_SOURCE_ID, "authorized": True, "recipient_verification": "source_attestation"},
            {"id": GREENHOUSE_SOURCE_ID, "authorized": True, "url": "https://private.example/feed"},
            {"id": "forged-kind", "authorized": True, "kind": "greenhouse_verified"},
            *[{"id": f"partner-{index}", "authorized": True} for index in range(30)],
        ]).job_sources
        self.assertEqual(len(configured), 20)
        self.assertEqual([source["id"] for source in configured].count(GREENHOUSE_SOURCE_ID), 1)
        self.assertNotIn("forged-kind", [source["id"] for source in configured])
        public = {source["id"]: public_source(source) for source in configured}
        self.assertTrue(public[GREENHOUSE_SOURCE_ID]["supports_automatic_email"])
        self.assertFalse(public[WEB_SOURCE_ID]["supports_automatic_email"])
        self.assertIn("Greenhouse", public[GREENHOUSE_SOURCE_ID]["description"])
        self.assertNotIn("TEST-PRIVATE", json.dumps(public))
        self.assertNotIn("private.example", json.dumps(public))
        self.assertEqual(Settings(authorized_feeds=[{"id": GREENHOUSE_SOURCE_ID,
            "authorized": True}]).job_sources, [])

    async def test_tavily_queries_are_reused_by_ia_and_publisher(self):
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={"results": [snippet()], "usage": {"credits": 1}})

        extractor = AsyncMock(return_value=[])
        verifier = AsyncMock(return_value=([verified_job()], []))
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with patch("app.services.web_search.extract_job_evidence", extractor), \
                    patch("app.services.greenhouse.verify_discoveries", verifier):
                jobs, failures = await find_jobs(SimpleNamespace(settings=settings(), client=client),
                    {**SEARCH, "roles": ["chofer", "mecánico"]})
        self.assertEqual(len(requests), 2)
        self.assertTrue(all(request.url.host == "api.tavily.com" for request in requests))
        verifier.assert_awaited_once()
        extractor.assert_awaited_once()
        self.assertEqual(verifier.await_args.args[1], extractor.await_args.args[3])
        self.assertEqual(failures, [])
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["source"], GREENHOUSE_SOURCE_ID)
        self.assertIsNotNone(jobs[0]["recipient_verified_at"])

    async def test_extractor_failure_does_not_block_independent_publisher_api(self):
        verifier = AsyncMock(return_value=([verified_job()], []))
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"results": [snippet()]}))) as client:
            with patch("app.services.web_search.extract_job_evidence", AsyncMock(side_effect=
                    HTTPException(502, "No se pudo analizar la evidencia."))), \
                    patch("app.services.greenhouse.verify_discoveries", verifier):
                jobs, failures = await find_jobs(SimpleNamespace(settings=settings(), client=client), SEARCH)
        verifier.assert_awaited_once()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(failures, [WEB_SOURCE_ID])
        self.assertEqual(jobs[0]["payload"]["verification_method"], "publisher_api_explicit_email")

    async def test_actual_publisher_adapter_and_normalizer_keep_official_email_proof(self):
        requests = []

        def handler(request):
            requests.append(request)
            if request.url.host == "api.tavily.com":
                return httpx.Response(200, json={"results": [snippet()]})
            self.assertEqual(str(request.url),
                "https://boards-api.greenhouse.io/v1/boards/transportesdelta/jobs/123")
            return httpx.Response(200, json={"id": 123, "internal_job_id": 789,
                "company_name": "Transportes Delta", "title": "chofer", "location": {"name": "Neuquén"},
                "content": "<p>Buscamos chofer en Neuquén.</p><p>Enviar CV a seleccion@delta.example.com.</p>"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with patch("app.services.web_search.extract_job_evidence", AsyncMock(return_value=[])):
                jobs, failures = await find_jobs(SimpleNamespace(settings=settings(), client=client), SEARCH)
        self.assertEqual(len(requests), 2)
        self.assertEqual(failures, [])
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job["external_id"], "transportesdelta:123")
        self.assertEqual(job["recipient_email"], "seleccion@delta.example.com")
        self.assertIsNotNone(job["recipient_verified_at"])
        self.assertFalse(job["payload"]["requires_manual_review"])
        self.assertEqual(job["payload"]["verification_method"], "publisher_api_explicit_email")
        self.assertEqual(job["payload"]["greenhouse"]["email_quote"],
            "Enviar CV a seleccion@delta.example.com.")
        self.assertTrue(all(request.url.host != "job-boards.greenhouse.io" for request in requests))

    async def test_all_discovery_queries_fail_without_verifier_or_fake_zero(self):
        requests = []
        verifier, extractor = AsyncMock(), AsyncMock()
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:
                requests.append(request) or httpx.Response(429, text="TEST-PRIVATE-WEB"))) as client:
            with patch("app.services.web_search.extract_job_evidence", extractor), \
                    patch("app.services.greenhouse.verify_discoveries", verifier):
                with self.assertRaises(HTTPException) as error:
                    await find_jobs(SimpleNamespace(settings=settings(), client=client), SEARCH)
        self.assertEqual(len(requests), 1)
        self.assertEqual(error.exception.status_code, 502)
        self.assertNotIn("TEST-PRIVATE", error.exception.detail)
        verifier.assert_not_awaited()
        extractor.assert_not_awaited()

    async def test_partial_discovery_failure_is_reported_once(self):
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(429) if len(requests) == 1 else httpx.Response(200, json={"results": []})

        verifier = AsyncMock(return_value=([], []))
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with patch("app.services.greenhouse.verify_discoveries", verifier):
                jobs, failures = await find_jobs(SimpleNamespace(settings=settings(), client=client),
                    {**SEARCH, "roles": ["chofer", "mecánico"]})
        self.assertEqual(jobs, [])
        self.assertEqual(failures, [f"{WEB_SOURCE_ID}: consulta 1 no completada"])
        self.assertEqual(verifier.await_args.args[1], [])
        self.assertEqual(len(requests), 2)

    async def test_no_greenhouse_hits_keep_manual_web_results(self):
        web_job = {**verified_job(), "payload": {"evidence": {"vacancy": "Buscamos chofer."}}}
        verifier = AsyncMock(return_value=([], []))
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"results": [snippet()]}))) as client:
            with patch("app.services.web_search.extract_job_evidence", AsyncMock(return_value=[web_job])), \
                    patch("app.services.greenhouse.verify_discoveries", verifier):
                jobs, failures = await find_jobs(SimpleNamespace(settings=settings(), client=client), SEARCH)
        self.assertEqual(failures, [])
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["source"], WEB_SOURCE_ID)
        self.assertIsNone(jobs[0]["recipient_verified_at"])
        self.assertTrue(jobs[0]["payload"]["requires_manual_review"])

    async def test_verified_duplicate_wins_without_mixing_provenance_in_either_order(self):
        official = verified_job()
        web_job = {**official, "description": "Descripción corta del buscador.",
            "url": "https://boards.greenhouse.io/transportesdelta/jobs/123?gh_src=public-tracking",
            "recipient_email": "otros@delta.example.com", "payload": {}}
        for source_order in ([WEB, GREENHOUSE], [GREENHOUSE, WEB]):
            with self.subTest(order=[source["id"] for source in source_order]):
                db = SimpleNamespace(settings=SimpleNamespace(job_sources=source_order), client=None)
                with patch("app.services.web_search.discover_web_results", AsyncMock(return_value=([snippet()], []))), \
                        patch("app.services.web_search.extract_web_jobs", AsyncMock(return_value=[web_job])), \
                        patch("app.services.greenhouse.verify_discoveries", AsyncMock(return_value=([official], []))):
                    jobs, failures = await find_jobs(db, SEARCH)
                self.assertEqual(failures, [])
                self.assertEqual(len(jobs), 1)
                self.assertEqual(jobs[0]["source"], GREENHOUSE_SOURCE_ID)
                self.assertEqual(jobs[0]["recipient_email"], official["recipient_email"])
                self.assertEqual(jobs[0]["description"], official["description"])
                self.assertEqual(jobs[0]["payload"]["greenhouse"], official["payload"]["greenhouse"])
                self.assertNotIn("web_search", jobs[0]["payload"])

    async def test_both_extraction_and_official_verification_failure_do_not_complete_search(self):
        with patch("app.services.web_search.discover_web_results", AsyncMock(return_value=([snippet()], []))), \
                patch("app.services.web_search.extract_web_jobs", AsyncMock(side_effect=HTTPException(502, "IA falló"))), \
                patch("app.services.greenhouse.verify_discoveries", AsyncMock(side_effect=HTTPException(502, "API falló"))):
            with self.assertRaises(HTTPException) as error:
                await find_jobs(SimpleNamespace(settings=settings(), client=None), SEARCH)
        self.assertEqual(error.exception.status_code, 502)

    async def test_discovery_entry_point_does_not_run_ia_or_fetch_result_urls(self):
        requests, extractor = [], AsyncMock()
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:
                requests.append(request) or httpx.Response(200, json={"results": [snippet()]}))) as client:
            with patch("app.services.web_search.extract_job_evidence", extractor):
                results, failures = await discover_web_results(settings(), client, SEARCH)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].url.host, "api.tavily.com")
        self.assertEqual(results[0]["url"], URL)
        self.assertEqual(failures, [])
        extractor.assert_not_awaited()

    def test_only_complete_official_proof_allows_greenhouse_verification(self):
        for mutation in (lambda raw: raw["payload"].pop("greenhouse"),
                lambda raw: raw["payload"].update(verification_method="source_attestation"),
                lambda raw: raw["payload"]["greenhouse"].update(endpoint="https://attacker.example/jobs/123"),
                lambda raw: raw["payload"]["greenhouse"].update(email_quote="Contactar otra dirección."),
                lambda raw: raw["payload"]["greenhouse"].update(job_id=True),
                lambda raw: raw.update(id="123"),
                lambda raw: raw.update(url="https://job-boards.greenhouse.io/otroempleador/jobs/123"),
                lambda raw: raw["payload"]["greenhouse"].update(fetched_at="2026-10-14")):
            raw = verified_job()
            mutation(raw)
            with self.subTest(raw=raw):
                job = normalize_job(raw, GREENHOUSE, SEARCH["user_id"])
                self.assertIsNone(job["recipient_verified_at"])
                self.assertTrue(job["payload"]["requires_manual_review"])
                self.assertFalse(job["payload"]["validity_confirmed"])

    def test_greenhouse_proof_allowlist_drops_unknown_fields(self):
        raw = copy.deepcopy(verified_job())
        raw["payload"]["greenhouse"]["private_future_field"] = "PRIVATE"
        raw["payload"]["access_token"] = "PRIVATE"
        row = normalize_job(raw, GREENHOUSE, SEARCH["user_id"])
        self.assertIsNotNone(row["recipient_verified_at"])
        self.assertFalse(row["payload"]["requires_manual_review"])
        self.assertTrue(row["payload"]["validity_confirmed"])
        self.assertEqual(row["payload"]["integration_id"], GREENHOUSE_SOURCE_ID)
        self.assertNotIn("PRIVATE", json.dumps(row))

    def test_equal_job_numbers_on_different_boards_do_not_collide(self):
        first = normalize_job(verified_job(), GREENHOUSE, SEARCH["user_id"])
        second_raw = verified_job()
        second_raw.update(id="otroempleador:123", url="https://boards.greenhouse.io/otroempleador/jobs/123")
        second_raw["payload"]["greenhouse"].update(board="otroempleador",
            endpoint="https://boards-api.greenhouse.io/v1/boards/otroempleador/jobs/123")
        second = normalize_job(second_raw, GREENHOUSE, SEARCH["user_id"])
        self.assertIsNotNone(second["recipient_verified_at"])
        self.assertNotEqual(first["external_id"], second["external_id"])
        self.assertNotEqual(first["fingerprint"], second["fingerprint"])


if __name__ == "__main__":
    unittest.main()

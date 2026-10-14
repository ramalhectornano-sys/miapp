"""Review the actual adapter/extractor/normalizer together without live APIs."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException

from app.config import Settings
from app.services.feeds import find_jobs, normalize_job


AD = "Transportes Delta: buscamos chofer en Rincón de los Sauces."
URL = "https://empresa.example.com/vacantes/123"
SEARCH = {"user_id": "user-owned-search", "roles": ["chofer"], "cities": ["Rincón de los Sauces"]}
SOURCE = {"id": "web:tavily", "kind": "web_search", "authorized": True,
    "recipient_verification": "source_attestation"}


class WebPipelineReviewTests(unittest.IsolatedAsyncioTestCase):
    def settings(self):
        return Settings(ai_provider="openai_compatible", ai_base_url="https://ai.example.com/v1",
            ai_model="test-model", ai_api_key="TEST-PRIVATE-IA",
            web_search_provider="tavily", web_search_api_key="TEST-PRIVATE-WEB")

    def candidate(self):
        return {"result_index": 0, "company": "Transportes Delta", "title": "chofer",
            "city": "Rincón de los Sauces", "description": AD,
            "recipient_verified": True, "recipient_verified_at": "2026-10-14T00:00:00Z",
            "evidence": {"company": "Transportes Delta", "title": "chofer",
                "city": "Rincón de los Sauces", "vacancy": AD}}

    async def test_web_vacancy_without_email_survives_actual_pipeline_for_manual_review(self):
        requests = []

        def handler(request):
            requests.append(request)
            if request.url.host == "api.tavily.com":
                return httpx.Response(200, json={"results": [{"url": URL,
                    "title": "Vacante chofer", "content": AD}]})
            self.assertEqual(request.url.host, "ai.example.com")
            return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
                "message": {"content": json.dumps({"jobs": [self.candidate()]})}}]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            rows, failures = await find_jobs(SimpleNamespace(settings=self.settings(), client=client), SEARCH)
        self.assertEqual(len(requests), 2)
        self.assertEqual(failures, [])
        self.assertEqual(len(rows), 1)
        job = rows[0]
        self.assertEqual(job["user_id"], SEARCH["user_id"])
        self.assertEqual(job["url"], URL)
        self.assertEqual(job["source"], "web:tavily")
        self.assertIsNone(job["recipient_email"])
        self.assertIsNone(job["recipient_verified_at"])
        self.assertIsNone(job["payload"]["verification_method"])
        self.assertIs(job["payload"]["requires_manual_review"], True)
        self.assertIs(job["payload"]["validity_confirmed"], False)
        self.assertEqual(job["payload"]["evidence"]["vacancy"], AD)
        self.assertEqual(job["payload"]["web_search"]["provider"], "tavily")

    def test_null_optional_email_is_supported_for_authorized_feed(self):
        row = normalize_job({"company": "Transportes Delta", "title": "chofer",
            "city": "Rincón de los Sauces", "recipient_email": None,
            "recipient_verified": True}, {"id": "feed:allowed", "authorized": True,
                "recipient_verification": "source_attestation"}, SEARCH["user_id"])
        self.assertIsNone(row["recipient_email"])
        self.assertIsNone(row["recipient_verified_at"])

    def test_malformed_optional_email_is_still_rejected(self):
        for email in (False, 15, {}, []):
            with self.subTest(email=email), self.assertRaises(ValueError):
                normalize_job({"company": "Transportes Delta", "title": "chofer",
                    "city": "Rincón de los Sauces", "recipient_email": email}, SOURCE, SEARCH["user_id"])

    def test_web_source_can_never_attest_a_recipient_even_if_config_or_model_claims_it(self):
        row = normalize_job({"company": "Transportes Delta", "title": "chofer",
            "city": "Rincón de los Sauces", "recipient_email": "rrhh@delta.example.com",
            "recipient_verified": True, "recipient_verified_at": "2026-10-14T00:00:00Z",
            "payload": {"verification_method": "source_attestation", "validity_confirmed": True}},
            SOURCE, SEARCH["user_id"])
        self.assertIsNone(row["recipient_verified_at"])
        self.assertIsNone(row["payload"]["verification_method"])
        self.assertIs(row["payload"]["requires_manual_review"], True)
        self.assertIs(row["payload"]["validity_confirmed"], False)

    async def test_failed_web_provider_is_not_a_completed_search_with_zero_jobs(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(429, text="TEST-PRIVATE-WEB"))) as client:
            with self.assertRaises(HTTPException) as error:
                await find_jobs(SimpleNamespace(settings=self.settings(), client=client), SEARCH)
        self.assertEqual(error.exception.status_code, 502)
        self.assertIn("no se completó", error.exception.detail.lower())
        self.assertNotIn("TEST-PRIVATE", error.exception.detail)

    async def test_current_attested_feed_wins_duplicate_web_in_both_source_orders_without_merging(self):
        feed_source = {"id": "feed:allowed", "authorized": True,
            "recipient_verification": "source_attestation"}
        feed_job = {"id": "feed-123", "company": "Transportes Delta", "title": "chofer",
            "city": "Rincón de los Sauces", "url": URL,
            "recipient_email": "verified@delta.example.com", "recipient_verified": True,
            "description": "Descripción ofrecida por la integración autorizada."}
        web_job = {**feed_job, "id": "web-123", "recipient_email": "other@delta.example.com",
            "recipient_verified": True, "description": "Descripción del fragmento web.",
            "payload": {"evidence": {"recipient_email": "Enviar CV a other@delta.example.com"}}}
        for sources in ([SOURCE, feed_source], [feed_source, SOURCE]):
            with self.subTest(sources=[source["id"] for source in sources]):
                settings = SimpleNamespace(job_sources=sources)
                db = SimpleNamespace(settings=settings, client=None)
                with patch("app.services.feeds.read_json_feed", AsyncMock(return_value=[feed_job])), \
                     patch("app.services.web_search.discover_web_jobs", AsyncMock(return_value=([web_job], []))):
                    rows, failures = await find_jobs(db, SEARCH)
                self.assertEqual(failures, [])
                self.assertEqual(len(rows), 1)
                job = rows[0]
                self.assertEqual(job["source"], feed_source["id"])
                self.assertEqual(job["external_id"], feed_job["id"])
                self.assertEqual(job["recipient_email"], feed_job["recipient_email"])
                self.assertEqual(job["description"], feed_job["description"])
                self.assertIsNotNone(job["recipient_verified_at"])
                self.assertEqual(job["payload"], {"integration_id": feed_source["id"],
                    "verification_method": "source_attestation"})

    async def test_unverified_current_web_result_cannot_inherit_missing_attestation(self):
        settings = SimpleNamespace(job_sources=[SOURCE])
        job = {"company": "Transportes Delta", "title": "chofer", "city": "Rincón de los Sauces",
            "url": URL, "recipient_email": "verified@delta.example.com", "recipient_verified": True}
        with patch("app.services.web_search.discover_web_jobs", AsyncMock(return_value=([job], []))):
            rows, failures = await find_jobs(SimpleNamespace(settings=settings, client=None), SEARCH)
        self.assertEqual(failures, [])
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["recipient_verified_at"])
        self.assertIsNone(rows[0]["payload"]["verification_method"])


if __name__ == "__main__":
    unittest.main()

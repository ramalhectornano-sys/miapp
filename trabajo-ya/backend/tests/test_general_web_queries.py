"""Provider transport/audit tests use synthetic responses, not live credentials."""
import json
import unittest
from unittest.mock import AsyncMock

import httpx
from fastapi import HTTPException

from app.config import Settings
from app.services.web_search import TAVILY_ENDPOINT, discover_web_results

SEARCH = {"roles": ["chofer"], "cities": ["Rincón de los Sauces"], "location": {
    "city": "Rincón de los Sauces", "province": "Neuquén", "country": "Argentina", "radius_km": 100}}
WEB_KEY = "TEST-WEB-PRIVATE-KEY"
AI_KEY = "TEST-AI-PRIVATE-KEY"


def config(**changes):
    return Settings(web_search_provider="tavily", web_search_api_key=WEB_KEY,
        ai_api_key=AI_KEY, web_search_max_queries=changes.get("web_search_max_queries", 6))


def payload(index=0, results=None):
    return {"request_id": f"test-provider-receipt-{index}", "usage": {"credits": 1},
        "results": results if results is not None else [{"url": f"https://empresa-publica.example.com/empleo/{index}",
            "title": "Vacante publicada", "content": "Buscamos chofer en Rincón de los Sauces."}]}


class GeneralWebQueryTests(unittest.IsolatedAsyncioTestCase):
    async def test_varied_queries_only_call_provider_and_record_actual_receipts(self):
        requests, events = [], []
        async def audit(event):
            events.append(event)
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json=payload(len(requests)))
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            results, failures = await discover_web_results(config(), client, {**SEARCH,
                "resume_text": "PRIVATE CV", "email": "PRIVATE USER EMAIL"}, audit=audit)
        self.assertEqual(len(requests), 6)
        bodies = [json.loads(request.content) for request in requests]
        self.assertTrue(all(str(request.url) == TAVILY_ENDPOINT for request in requests))
        self.assertTrue(all("include_domains" not in body for body in bodies))
        self.assertTrue(all("site:" not in body["query"] for body in bodies[:4]))
        self.assertIn("site:linkedin.com/jobs ", bodies[4]["query"])
        self.assertIn("-site:linkedin.com/in/", bodies[4]["query"])
        self.assertIn("-site:linkedin.com/pub/", bodies[4]["query"])
        self.assertIn("site:ar.computrabajo.com", bodies[5]["query"])
        completed = [event for event in events if event["event"] == "completed"]
        self.assertEqual(len(events), 12)
        self.assertEqual(len(completed), 6)
        self.assertTrue(all(event["status"] == "succeeded" and event["http_status"] == 200
            and event["provider_response_received"] is True for event in completed))
        self.assertEqual(len({event["event_id"] for event in events}), 6)
        for index, event in enumerate(completed, 1):
            self.assertEqual(event["kind"], "tavily_query")
            self.assertEqual(event["request_id"], f"test-provider-receipt-{index}")
            self.assertEqual(event["credits"], 1)
            self.assertRegex(event["finished_at"], r"\d{4}-\d{2}-\d{2}T")
            self.assertEqual(event["source_hosts"], ["empresa-publica.example.com"])
        self.assertEqual(len(results), 6)
        self.assertNotIn(WEB_KEY, json.dumps(events))
        self.assertNotIn(AI_KEY, json.dumps(events))
        self.assertNotIn("PRIVATE CV", json.dumps(bodies))
        self.assertNotIn("PRIVATE USER EMAIL", json.dumps(bodies))

    async def test_error_history_survives_total_provider_failure(self):
        events = []
        async def audit(event):
            events.append(event)
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(401, text=WEB_KEY))) as client:
            with self.assertRaises(HTTPException) as error:
                await discover_web_results(config(), client, SEARCH, audit=audit)
        self.assertEqual(error.exception.status_code, 502)
        completed = [event for event in events if event["event"] == "completed"]
        self.assertEqual(len(completed), 6)
        self.assertTrue(all(event["status"] == "failed" and event["http_status"] == 401 for event in completed))
        self.assertTrue(all(event["result_urls"] == [] for event in completed))
        self.assertNotIn(WEB_KEY, json.dumps(events))
        self.assertNotIn("request_id", completed[0])

    async def test_timeout_does_not_claim_provider_response_or_empty_success(self):
        events = []
        async def audit(event):
            events.append(event)
        def handler(request):
            raise httpx.ReadTimeout(WEB_KEY, request=request)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(HTTPException):
                await discover_web_results(config(web_search_max_queries=1), client, SEARCH, audit=audit)
        event = events[-1]
        self.assertEqual(event["status"], "failed")
        self.assertIsNone(event["http_status"])
        self.assertFalse(event["provider_response_received"])
        self.assertNotIn(WEB_KEY, json.dumps(events))

    async def test_failed_audit_storage_stops_before_network_and_after_response(self):
        for fail_on in (1, 2):
            requests, calls = [], []
            async def audit(event):
                calls.append(event)
                if len(calls) == fail_on:
                    raise ValueError(WEB_KEY)
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:
                    requests.append(request) or httpx.Response(200, json=payload()))) as client:
                with self.assertRaises(HTTPException) as error:
                    await discover_web_results(config(), client, SEARCH, audit=audit)
            self.assertEqual(error.exception.status_code, 503)
            self.assertEqual(len(requests), fail_on - 1)
            self.assertNotIn(WEB_KEY, error.exception.detail)

    async def test_tracking_variants_deduplicate_while_retaining_original_link(self):
        original = "https://empresa-publica.example.com/empleo/1?utm_source=feed"
        variants = [original, "https://empresa-publica.example.com/empleo/1?utm_source=other",
            "https://empresa-publica.example.com/empleo/1"]
        requests = []
        def handler(request):
            requests.append(request)
            url = variants[(len(requests) - 1) % len(variants)]
            return httpx.Response(200, json=payload(results=[{"url": url, "title": "Vacante", "content": "Buscamos chofer"}]))
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            results, _ = await discover_web_results(config(), client, SEARCH)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"], original)

    async def test_max12_budget_and_one_observed_host_followup(self):
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json=payload(len(requests)))
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await discover_web_results(config(web_search_max_queries=8), client, SEARCH)
        self.assertEqual(len(requests), 8)
        query = json.loads(requests[-1].content)["query"]
        self.assertIn("site:empresa-publica.example.com", query)
        self.assertIn("postulación", query)

    async def test_discovery_has24_result_cap_and_interleaves_all_queries(self):
        requests = []
        def handler(request):
            requests.append(request)
            rows = [{"url": f"https://empresa-publica.example.com/empleo/{len(requests)}-{index}",
                "title": "Vacante", "content": "Buscamos chofer"} for index in range(5)]
            return httpx.Response(200, json=payload(results=rows))
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            results, _ = await discover_web_results(config(web_search_max_queries=12), client, SEARCH)
        self.assertLessEqual(len(requests), 12)
        self.assertEqual(len(results), 24)
        first_round = results[:len(requests)]
        self.assertEqual(len({row["web_search"]["query_index"] for row in first_round}), len(requests))

    async def test_private_token_result_or_receipt_is_not_saved_to_audit(self):
        events = []
        async def audit(event):
            events.append(event)
        response = payload(results=[{"url": "https://empresa-publica.example.com/empleo/1?key=" + WEB_KEY,
            "title": "Vacante", "content": "Buscamos chofer"}])
        response["request_id"] = WEB_KEY
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=response))) as client:
            results, _ = await discover_web_results(config(), client, SEARCH, audit=audit)
        self.assertEqual(results, [])
        self.assertNotIn(WEB_KEY, json.dumps(events))
        self.assertTrue(all(event.get("request_id") is None for event in events))


if __name__ == "__main__":
    unittest.main()

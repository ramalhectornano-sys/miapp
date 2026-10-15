"""Synthetic HTTP fixtures verify geography history; no live provider calls."""
from datetime import datetime
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import UUID

import httpx
from fastapi import HTTPException

from app.services.geography import (GEOREF_ENDPOINT, classify_job_location,
    clear_geography_cache, prepare_search_geography, resolve_locations)
from app.services.query_planner import plan_queries, verified_nearby_cities


SETTINGS = SimpleNamespace(geocoder_provider="georef_ar")


def place(identifier="58035010000", city="Localidad de prueba", latitude=-37):
    return {"id": identifier, "nombre": city, "provincia": {"id": "58", "nombre": "Neuquén"},
        "centroide": {"lat": latitude, "lon": -69}}


def envelope(rows, *, total=None, start=0):
    return {"localidades": rows, "total": len(rows) if total is None else total, "inicio": start}


class GeographyAuditTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        clear_geography_cache()

    async def test_each_real_http_request_has_start_and_terminal_proof_without_credentials(self):
        events, requests = [], []

        async def record(event):
            events.append(event)

        def handler(request):
            self.assertEqual(events[-1]["status"], "started")
            requests.append(request)
            return httpx.Response(200, json=envelope([place()]))

        budget = {"_research_audit": record, "resume_text": "PRIVATE CV", "api_key": "PRIVATE KEY"}
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            first = await resolve_locations(SETTINGS, client, "Localidad de prueba", "Neuquén", "Argentina", budget=budget)
            second = await resolve_locations(SETTINGS, client, "Localidad de prueba", "Neuquén", "Argentina", budget=budget)
        self.assertEqual(len(requests), 1)
        self.assertEqual(len(events), 2)
        started, terminal = events
        self.assertEqual([event["status"] for event in events], ["started", "succeeded"])
        self.assertEqual(started["event_id"], terminal["event_id"])
        self.assertEqual(str(UUID(started["event_id"])), started["event_id"])
        self.assertEqual(terminal["kind"], "geocode")
        self.assertEqual(terminal["provider"], "georef")
        self.assertEqual(terminal["url"], GEOREF_ENDPOINT)
        self.assertEqual(terminal["query"], "Localidad de prueba, Neuquén")
        self.assertEqual(terminal["http_status"], 200)
        self.assertGreater(terminal["response_bytes"], 0)
        self.assertTrue(terminal["provider_response_received"])
        self.assertFalse(started["provider_response_received"])
        self.assertFalse(terminal["metadata"]["from_cache"])
        self.assertEqual(budget["geography_request_count"], 1)
        self.assertEqual(terminal["finished_at"], first[0]["resolved_at"])
        self.assertEqual(first[0]["resolved_at"], second[0]["resolved_at"])
        self.assertLessEqual(datetime.fromisoformat(started["started_at"]), datetime.fromisoformat(terminal["finished_at"]))
        self.assertNotIn("PRIVATE", json.dumps(events))
        self.assertNotIn("centroide", json.dumps(events))

    async def test_http_provider_failures_record_actual_status_without_body_or_following_redirect(self):
        for status in (429, 301, 403, 500):
            with self.subTest(status=status):
                clear_geography_cache()
                events, requests = [], []

                async def record(event):
                    events.append(event)

                async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: requests.append(request) or
                        httpx.Response(status, text="PRIVATE PROVIDER BODY", headers={"Location": "http://127.0.0.1/private"}))) as client:
                    with self.assertRaises(HTTPException):
                        await resolve_locations(SETTINGS, client, "Localidad de prueba", None, "Argentina", budget={"_research_audit": record})
                self.assertEqual(len(requests), 1)
                self.assertEqual([event["status"] for event in events], ["started", "failed"])
                self.assertEqual(events[-1]["http_status"], status)
                self.assertTrue(events[-1]["provider_response_received"])
                self.assertNotIn("PRIVATE", json.dumps(events))

    async def test_timeout_does_not_invent_provider_receipt(self):
        events = []

        async def record(event):
            events.append(event)

        def timeout(request):
            raise httpx.ReadTimeout("PRIVATE EXCEPTION", request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
            with self.assertRaises(HTTPException) as error:
                await resolve_locations(SETTINGS, client, "Localidad de prueba", None, "Argentina", budget={"_research_audit": record})
        self.assertEqual(error.exception.status_code, 502)
        self.assertEqual(events[-1]["status"], "failed")
        self.assertIsNone(events[-1]["http_status"])
        self.assertFalse(events[-1]["provider_response_received"])
        self.assertNotIn("PRIVATE", json.dumps(events))

    async def test_malformed_http_success_is_a_failed_geocoding_attempt(self):
        events = []

        async def record(event):
            events.append(event)

        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text="not json"))) as client:
            with self.assertRaises(HTTPException):
                await resolve_locations(SETTINGS, client, "Localidad de prueba", None, "Argentina", budget={"_research_audit": record})
        self.assertEqual(events[-1]["status"], "failed")
        self.assertEqual(events[-1]["http_status"], 200)
        self.assertTrue(events[-1]["provider_response_received"])
        self.assertEqual(events[-1]["response_bytes"], 8)

    async def test_initial_audit_failure_stops_before_http_and_cannot_be_swallowed_as_geo_warning(self):
        async def fail(event):
            raise RuntimeError("PRIVATE DATABASE ERROR")

        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: self.fail("Audit must precede HTTP"))) as client:
            with self.assertRaises(HTTPException) as error:
                await prepare_search_geography(SETTINGS, client, {"cities": ["Localidad de prueba"], "country": "Argentina",
                    "province": "Neuquén", "radius_km": 100, "_research_audit": fail})
        self.assertEqual(error.exception.status_code, 503)
        self.assertTrue(error.exception.audit_failed)
        self.assertNotIn("PRIVATE", str(error.exception.detail))

    async def test_terminal_audit_failure_does_not_cache_an_unrecorded_success(self):
        events, requests = [], []

        async def fail_terminal(event):
            if event["status"] != "started":
                raise HTTPException(503, "PRIVATE DATABASE ERROR")

        async def record(event):
            events.append(event)

        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: requests.append(request) or
                httpx.Response(200, json=envelope([place()])))) as client:
            with self.assertRaises(HTTPException) as error:
                await resolve_locations(SETTINGS, client, "Localidad de prueba", None, "Argentina", budget={"_research_audit": fail_terminal})
            result = await resolve_locations(SETTINGS, client, "Localidad de prueba", None, "Argentina", budget={"_research_audit": record})
        self.assertTrue(error.exception.audit_failed)
        self.assertEqual(len(requests), 2)
        self.assertEqual(len(result), 1)
        self.assertEqual(events[-1]["status"], "succeeded")

    async def test_catalog_audit_failure_does_not_return_partial_geographic_success(self):
        events = []

        async def record(event):
            events.append(event)
            if event["query"] == "Catálogo localidades" and event["status"] == "succeeded":
                raise RuntimeError("DB WRITE FAILED")

        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=envelope([place()])))) as client:
            with self.assertRaises(HTTPException) as error:
                await prepare_search_geography(SETTINGS, client, {"cities": ["Localidad de prueba"], "country": "Argentina",
                    "province": "Neuquén", "radius_km": 100, "_research_audit": record})
        self.assertEqual(len(events), 4)
        self.assertTrue(error.exception.audit_failed)

    async def test_job_geocoding_propagates_fenced_audit_failure(self):
        failure = HTTPException(503, "No se pudo guardar el historial.")
        failure.audit_failed = True

        async def fail(event):
            raise failure

        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: self.fail("No HTTP after failed fence"))) as client:
            with self.assertRaises(HTTPException) as error:
                await classify_job_location(SETTINGS, client, {"city": "Localidad de prueba", "country": "Argentina"}, {"_research_audit": fail})
        self.assertIs(error.exception, failure)

    async def test_budget_rejection_is_not_logged_as_provider_http_attempt(self):
        events = []

        async def record(event):
            events.append(event)

        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: self.fail("Budget exhausted"))) as client:
            result = await classify_job_location(SETTINGS, client, {"city": "Localidad de prueba", "country": "Argentina"},
                {"_research_audit": record, "geography_request_count": 8})
        self.assertEqual(events, [])
        self.assertEqual(result["location_status"], "pending_review")

    async def test_each_catalog_page_is_audited_and_nearby_city_provenance_reaches_query_planner(self):
        events, requests = [], []
        center, neighbor = place(), place("58035020000", "Localidad vecina", -36.5)

        async def record(event):
            events.append(event)

        def handler(request):
            requests.append(request)
            start = int(request.url.params.get("inicio", "0"))
            rows = [center] if request.url.params.get("nombre") or start == 0 else [neighbor]
            return httpx.Response(200, json=envelope(rows, total=1 if request.url.params.get("nombre") else 2, start=start))

        with patch("app.services.geography.PAGE_SIZE", 1):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                search = await prepare_search_geography(SETTINGS, client, {"roles": ["Chofer"], "cities": ["Localidad de prueba"],
                    "country": "Argentina", "province": "Neuquén", "radius_km": 100, "_research_audit": record})
        self.assertEqual(len(requests), 3)
        self.assertEqual(len(events), 6)
        self.assertEqual(len({event["event_id"] for event in events}), 3)
        self.assertEqual([event["metadata"]["query_index"] for event in events[::2]], [1, 2, 3])
        self.assertEqual([event["query"] for event in events[::2]], ["Localidad de prueba, Neuquén", "Catálogo localidades", "Catálogo localidades"])
        self.assertTrue(all(row["verified"] is True for row in search["nearby_cities"]))
        self.assertIn("Localidad vecina", verified_nearby_cities(search))
        self.assertIn("Localidad vecina", " ".join(row["query"] for row in plan_queries(search, 12)))


if __name__ == "__main__":
    unittest.main()

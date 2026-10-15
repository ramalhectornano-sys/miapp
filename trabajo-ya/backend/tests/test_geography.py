"""Synthetic geocoder fixtures; no real provider call or invented live places."""
import json
import math
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi import HTTPException

from app.services.geography import (GEOREF_ENDPOINT, EARTH_RADIUS_KM,
    MAX_RESPONSE_BYTES, classify_job_location, clear_geography_cache,
    haversine_km, prepare_search_geography, resolve_locations,
    resolve_search_location)


SETTINGS = SimpleNamespace(geocoder_provider="georef_ar")


def place(identifier="58035010000", city="Localidad de prueba", province="Neuquén", latitude=-37.0, longitude=-69.0):
    return {"id": identifier, "nombre": city, "provincia": {"id": identifier[:2], "nombre": province},
        "centroide": {"lat": latitude, "lon": longitude}}


def response(locations, total=None, inicio=0):
    return {"localidades": locations, "cantidad": len(locations), "total": len(locations) if total is None else total,
        "inicio": inicio}


class HaversineTests(unittest.TestCase):
    def test_equator_degree_and_antipodes_have_known_distance(self):
        self.assertAlmostEqual(haversine_km(0, 0, 0, 1), 111.19508, places=4)
        self.assertAlmostEqual(haversine_km(0, 0, 0, 180), math.pi * EARTH_RADIUS_KM, places=6)
        self.assertEqual(haversine_km(-37, -69, -37, -69), 0)

    def test_dateline_does_not_wrap_to_long_distance(self):
        self.assertAlmostEqual(haversine_km(0, 179.5, 0, -179.5), 111.19508, places=4)

    def test_invalid_coordinates_are_rejected(self):
        for values in ((True, 0, 0, 0), (float("nan"), 0, 0, 0), (0, float("inf"), 0, 0), (91, 0, 0, 0), (0, 181, 0, 0)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                haversine_km(*values)


class GeographyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        clear_geography_cache()

    async def test_geocoder_requests_public_only_exact_fields_without_secrets_or_cv(self):
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json=response([place()]))
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await resolve_search_location(SETTINGS, client, {"city": "Localidad de prueba",
                "province": "Neuquén", "country": "Argentina", "resume_text": "PRIVATE CV DNI", "api_key": "PRIVATE"})
        self.assertEqual(len(requests), 1)
        request = requests[0]
        self.assertEqual(str(request.url.copy_with(query=None)), GEOREF_ENDPOINT)
        self.assertEqual(request.url.params["nombre"], "Localidad de prueba")
        self.assertEqual(request.url.params["provincia"], "Neuquén")
        self.assertEqual(request.url.params["exacto"], "true")
        self.assertNotIn("authorization", request.headers)
        self.assertNotIn("apikey", request.headers)
        self.assertNotIn("PRIVATE", str(request.url))
        self.assertEqual(result["id"], "58035010000")
        self.assertEqual(result["provider"], "georef_ar")
        self.assertEqual(result["coordinate_type"], "locality_centroid")
        self.assertIn("Servicio Georef", result["attribution"])
        self.assertTrue(result["resolved_at"].endswith("+00:00"))

    async def test_homonyms_require_explicit_selection_not_first_api_result(self):
        rows = [place(city="San Martín"), place("50035010000", "San Martín", "Mendoza")]
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response(rows)))) as client:
            with self.assertRaises(HTTPException) as error:
                await resolve_search_location(SETTINGS, client, {"city": "San Martín", "country": "Argentina"})
            self.assertEqual(error.exception.status_code, 409)
            self.assertEqual(error.exception.detail["code"], "location_ambiguous")
            self.assertEqual(len(error.exception.detail["candidates"]), 2)
            selected = await resolve_search_location(SETTINGS, client,
                {"city": "San Martin", "country": "Argentina", "location_id": "50035010000"})
            self.assertEqual(selected["province"], "Mendoza")

    async def test_wrong_province_and_fuzzy_names_are_not_verified(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200,
                json=response([place(city="Localidad parecida", province="Mendoza", identifier="50035010000")])))) as client:
            self.assertEqual(await resolve_locations(SETTINGS, client, "Localidad de prueba", "Neuquén", "Argentina"), [])
            with self.assertRaises(HTTPException) as error:
                await resolve_search_location(SETTINGS, client, {"city": "Localidad de prueba", "province": "Neuquén", "country": "Argentina"})
        self.assertEqual(error.exception.detail["code"], "location_unresolved")

    async def test_country_and_disabled_provider_never_invent_places_or_query_argentina(self):
        requests = []
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: requests.append(request))) as client:
            for country in ("Chile", None, ""):
                self.assertEqual(await resolve_locations(SETTINGS, client, "San Martín", None, country), [])
            self.assertEqual(await resolve_locations(SimpleNamespace(geocoder_provider="disabled"), client,
                "San Martín", "Neuquén", "Argentina"), [])
            with self.assertRaises(HTTPException) as error:
                await resolve_search_location(SETTINGS, client, {"city": "Santiago", "country": "Chile"})
        self.assertEqual(error.exception.detail["code"], "geocoder_unavailable")
        self.assertEqual(requests, [])

    async def test_invalid_homonym_does_not_make_first_valid_candidate_unique(self):
        rows = [place(), place("50035010000", province="Mendoza", latitude=0)]
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response(rows)))) as client:
            with self.assertRaises(HTTPException) as error:
                await resolve_search_location(SETTINGS, client, {"city": "Localidad de prueba", "country": "Argentina"})
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(error.exception.detail["code"], "location_ambiguous")

    async def test_incomplete_catalog_records_cannot_establish_unicity_for_a_later_city(self):
        center = place()
        other = place("50035010000", city="Otra localidad", province="Mendoza", latitude=-36.5)
        incomplete = place("62035010000", city="Otra localidad", province="Río Negro", latitude=0)
        requests = []

        def handler(request):
            requests.append(request)
            if request.url.params.get("nombre") == center["nombre"]:
                rows = [center]
            elif request.url.params.get("nombre"):
                rows = [other, incomplete]
            else:
                rows = [center, other, incomplete]
            return httpx.Response(200, json=response(rows))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            search = await prepare_search_geography(SETTINGS, client,
                {"cities": [center["nombre"]], "province": "Neuquén", "country": "Argentina", "radius_km": 100})
            result = await classify_job_location(SETTINGS, client, {"city": "Otra localidad", "country": "Argentina"}, search)
        self.assertEqual(len(requests), 3)
        self.assertFalse(result["location_verified"])
        self.assertIsNone(result["distance_km"])
        self.assertEqual(result["location_status"], "pending_review")

    async def test_model_and_saved_coordinates_are_ignored(self):
        original = place()
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response([original])))) as client:
            search = await prepare_search_geography(SETTINGS, client, {"cities": [original["nombre"]], "country": "Argentina", "radius_km": 0,
                "location": {"id": original["id"], "city": original["nombre"], "province": "Neuquén", "country": "Argentina",
                    "latitude": 0, "longitude": 0}})
            job = {"city": original["nombre"], "country": "Argentina", "latitude": 0, "longitude": 0,
                "location_id": "forged", "payload": {"location": {"latitude": 0, "longitude": 0}}}
            classified = await classify_job_location(SETTINGS, client, job, search)
        self.assertEqual(search["location"]["latitude"], -37)
        self.assertEqual(classified["location"]["latitude"], -37)
        self.assertIs(classified["within_radius"], True)
        self.assertEqual(classified["distance_km"], 0)

    async def test_nearby_radius_crosses_province_boundary_and_excludes_outside(self):
        center = place()
        neighbor = place("50035010000", "Vecina", "Mendoza", -36.5)
        distant = place("62035010000", "Lejana", "Río Negro", -34.0)
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json=response([center] if request.url.params.get("nombre") else [center, neighbor, distant]))
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            search = await prepare_search_geography(SETTINGS, client,
                {"cities": [center["nombre"]], "province": "Neuquén", "country": "Argentina", "radius_km": 100})
            near = await classify_job_location(SETTINGS, client,
                {"city": "Vecina", "province": "Mendoza", "country": "Argentina"}, search)
            far = await classify_job_location(SETTINGS, client,
                {"city": "Lejana", "province": "Río Negro", "country": "Argentina"}, search)
        self.assertEqual([row["city"] for row in search["nearby_cities"]], [center["nombre"], "Vecina"])
        self.assertEqual(near["location_status"], "verified")
        self.assertIs(near["within_radius"], True)
        self.assertGreater(near["distance_km"], 55)
        self.assertEqual(far["location_status"], "outside_radius")
        self.assertIs(far["within_radius"], False)
        self.assertEqual(len(requests), 2)
        self.assertNotIn("provincia", requests[1].url.params)
        self.assertTrue(any("aérea" in warning for warning in search["geography_warnings"]))

    async def test_boundary_uses_full_precision_not_rounded_display_distance(self):
        center = place()
        delta = math.degrees(100.0004 / EARTH_RADIUS_KM)
        outside = place("58035020000", "Limítrofe", latitude=-37 + delta)
        def handler(request):
            return httpx.Response(200, json=response([center] if request.url.params.get("nombre") else [center, outside]))
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            search = await prepare_search_geography(SETTINGS, client,
                {"cities": [center["nombre"]], "province": "Neuquén", "country": "Argentina", "radius_km": 100})
            result = await classify_job_location(SETTINGS, client, {"city": "Limítrofe", "country": "Argentina"}, search)
        self.assertEqual(result["distance_km"], 100.0)
        self.assertIs(result["within_radius"], False)
        self.assertNotIn("Limítrofe", [row["city"] for row in search["nearby_cities"]])

    async def test_country_is_not_inherited_from_search_for_unknown_job_location(self):
        requests = []
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: requests.append(request))) as client:
            result = await classify_job_location(SETTINGS, client, {"city": "Localidad de prueba"},
                {"country": "Argentina", "province": "Neuquén", "radius_km": 100})
        self.assertFalse(result["location_verified"])
        self.assertIsNone(result["distance_km"])
        self.assertIsNone(result["within_radius"])
        self.assertEqual(result["location_status"], "pending_review")
        self.assertEqual(requests, [])

    async def test_explicit_comma_location_can_resolve_without_search_assumptions(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response([place()])))) as client:
            search = await prepare_search_geography(SETTINGS, client,
                {"cities": ["Localidad de prueba"], "province": "Neuquén", "country": "Argentina", "radius_km": 0})
            result = await classify_job_location(SETTINGS, client,
                {"city": "Localidad de prueba, Neuquén, Argentina"}, search)
        self.assertTrue(result["location_verified"])
        self.assertTrue(result["within_radius"])

    async def test_malformed_success_never_proves_coordinates(self):
        invalid_places = [place(latitude=True), place(latitude=math.nan), place(longitude=190),
            {**place(), "id": "invalid"}, {**place(), "centroide": {"lat": 0, "lon": 0}},
            {**place(), "provincia": {"id": "50", "nombre": "Neuquén"}}]
        for raw in invalid_places:
            clear_geography_cache()
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:
                    httpx.Response(200, content=json.dumps(response([raw])).encode()))) as client:
                self.assertEqual(await resolve_locations(SETTINGS, client, "Localidad de prueba", None, "Argentina"), [])
        for payload in ({}, [], {"localidades": [], "total": "0"}, {"localidades": None, "total": 0}):
            clear_geography_cache()
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))) as client:
                with self.assertRaises(HTTPException) as error:
                    await resolve_locations(SETTINGS, client, "Localidad de prueba", None, "Argentina")
                self.assertEqual(error.exception.status_code, 502)

    async def test_http_errors_and_redirect_do_not_leak_payload_or_follow_links(self):
        for status in (429, 301, 403, 500):
            clear_geography_cache()
            requests = []
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: requests.append(request) or
                    httpx.Response(status, text="PRIVATE SECRET", headers={"Location": "http://127.0.0.1/private"}))) as client:
                with self.assertRaises(HTTPException) as error:
                    await resolve_locations(SETTINGS, client, "Localidad de prueba", None, "Argentina")
                self.assertNotIn("PRIVATE", str(error.exception.detail))
                self.assertEqual(len(requests), 1)

    async def test_response_byte_cap_and_timeout_fail_explicitly(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:
                httpx.Response(200, content=b" " * (MAX_RESPONSE_BYTES + 1)))) as client:
            with self.assertRaises(HTTPException) as error:
                await resolve_locations(SETTINGS, client, "Localidad de prueba", None, "Argentina")
            self.assertIn("grande", error.exception.detail)
        clear_geography_cache()
        def timeout(request):
            raise httpx.ReadTimeout("PRIVATE RAW ERROR", request=request)
        async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
            with self.assertRaises(HTTPException) as error:
                await resolve_locations(SETTINGS, client, "Localidad de prueba", None, "Argentina")
        self.assertNotIn("PRIVATE", error.exception.detail)

    async def test_cached_resolved_at_is_original_fetch_time_and_no_api_calls(self):
        requests = []
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: requests.append(request) or
                httpx.Response(200, json=response([place()])))) as client:
            first = await resolve_locations(SETTINGS, client, "Localidad de prueba", "Neuquén", "Argentina")
            second = await resolve_locations(SETTINGS, client, "Localidad de prueba", "Neuquén", "Argentina")
            second[0]["latitude"] = 0
            third = await resolve_locations(SETTINGS, client, "Localidad de prueba", "Neuquén", "Argentina")
        self.assertEqual(len(requests), 1)
        self.assertEqual(first[0]["resolved_at"], third[0]["resolved_at"])
        self.assertEqual(third[0]["latitude"], -37)

    async def test_per_search_budget_retains_pending_locations(self):
        requests = []
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: requests.append(request))) as client:
            result = await classify_job_location(SETTINGS, client,
                {"city": "Localidad de prueba", "country": "Argentina"}, {"geography_request_count": 8})
        self.assertEqual(requests, [])
        self.assertIsNone(result["distance_km"])
        self.assertIn("límite", result["warnings"][0])

    async def test_rate_limit_rejects_more_than_ten_requests_per_second(self):
        requests = []
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: requests.append(request) or
                httpx.Response(200, json=response([])))) as client:
            with patch("app.services.geography.time.monotonic", return_value=1000):
                for index in range(10):
                    await resolve_locations(SETTINGS, client, f"Localidad {index}", None, "Argentina")
                with self.assertRaises(HTTPException) as error:
                    await resolve_locations(SETTINGS, client, "Localidad 11", None, "Argentina")
        self.assertEqual(error.exception.status_code, 429)
        self.assertEqual(len(requests), 10)

    async def test_legacy_search_without_country_explicitly_has_no_distances(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: self.fail("No legacy assumptions"))) as client:
            result = await prepare_search_geography(SETTINGS, client, {"cities": ["Localidad de prueba"]})
        self.assertIsNone(result["location"])
        self.assertEqual(result["nearby_cities"], [])
        self.assertTrue(result["geography_warnings"])

    async def test_invalid_radius_rejected_without_network(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: self.fail("No invalid radius requests"))) as client:
            for radius in (-1, 1001, True, "100", float("nan")):
                with self.subTest(radius=radius), self.assertRaises(HTTPException) as error:
                    await prepare_search_geography(SETTINGS, client, {"cities": ["Localidad de prueba"], "radius_km": radius})
                self.assertEqual(error.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()

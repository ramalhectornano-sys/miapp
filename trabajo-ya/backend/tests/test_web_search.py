"""Web discovery tests use synthetic excerpts and never query real providers."""
import json
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException

from app.config import Settings
from app.services.web_search import (
    MAX_RESPONSE_BYTES, TAVILY_ENDPOINT, discover_web_jobs, public_result_url,
)

SEARCH = {"roles": ["chofer"], "cities": ["Rincón de los Sauces"]}
PRIVATE_WEB_KEY = "TEST-WEB-PRIVATE-KEY"
PRIVATE_AI_KEY = "TEST-IA-PRIVATE-KEY"


def config(**changes):
    settings = Settings(ai_provider="openai_compatible", ai_base_url="https://ai.example.com/v1",
        ai_model="test-model", ai_api_key=PRIVATE_AI_KEY)
    for key, value in {"web_search_provider": "tavily", "web_search_api_key": PRIVATE_WEB_KEY,
            "web_search_max_queries": 2, **changes}.items():
        setattr(settings, key, value)
    return settings


def result(index=0, **changes):
    return {"title": f"Oferta {index}", "content": "Buscamos chofer en Rincón de los Sauces.",
        "url": f"https://empresa.example.com/vacantes/{index}", **changes}


def response(results=None, **changes):
    return {"results": [result()] if results is None else results,
        "request_id": "db2faf86-d389-4dae-a24d-96f2bf683269", "usage": {"credits": 1}, **changes}


class WebSearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_bounded_api_payload_sends_only_saved_role_city(self):
        captured = []

        def handler(request):
            captured.append(request)
            return httpx.Response(200, json=response())

        extractor = AsyncMock(return_value=[{"url": result()["url"], "payload": {}, "recipient_verified": True}])
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with patch("app.services.web_search.extract_job_evidence", extractor):
                jobs, failures = await discover_web_jobs(config(), client, {**SEARCH, "resume_text": "PRIVATE CV DNI",
                    "email": "persona@example.com", "full_name": "PRIVATE FULL NAME"})
        self.assertEqual(len(captured), 1)
        request = captured[0]
        self.assertEqual(str(request.url), TAVILY_ENDPOINT)
        self.assertEqual(request.headers["Authorization"], f"Bearer {PRIVATE_WEB_KEY}")
        payload = json.loads(request.content)
        self.assertEqual(payload["query"], 'vacantes empleo "chofer" "Rincón de los Sauces"')
        self.assertEqual(payload["search_depth"], "basic")
        self.assertIs(payload["auto_parameters"], False)
        self.assertEqual(payload["max_results"], 5)
        self.assertIs(payload["include_answer"], False)
        self.assertIs(payload["include_raw_content"], False)
        self.assertIs(payload["include_usage"], True)
        self.assertNotIn("country", payload)
        self.assertNotIn("time_range", payload)
        self.assertNotIn("PRIVATE CV", json.dumps(payload))
        self.assertNotIn("PRIVATE FULL NAME", json.dumps(payload))
        self.assertNotIn(PRIVATE_WEB_KEY, json.dumps(payload))
        self.assertEqual(failures, [])
        self.assertFalse(jobs[0]["recipient_verified"])
        self.assertTrue(jobs[0]["payload"]["requires_manual_verification"])
        metadata = jobs[0]["payload"]["web_search"]
        self.assertEqual(metadata["request_id"], response()["request_id"])
        self.assertEqual(metadata["credits"], 1)
        self.assertRegex(metadata["fetched_at"], r"\d{4}-\d{2}-\d{2}T.*\+00:00")
        self.assertNotIn("PRIVATE", json.dumps(jobs))

    async def test_interleaving_dedup_and_budget_include_second_query(self):
        queries = []

        def handler(request):
            query = json.loads(request.content)["query"]
            queries.append(query)
            rows = [result(index if len(queries) == 1 else index + 10) for index in range(5)]
            return httpx.Response(200, json=response(rows))

        extractor = AsyncMock(return_value=[])
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with patch("app.services.web_search.extract_job_evidence", extractor):
                jobs, failures = await discover_web_jobs(config(), client,
                    {"roles": ["chofer", "chofer", "electricista"], "cities": ["Neuquén", "Rincón de los Sauces"]})
        self.assertEqual(len(queries), 2)
        self.assertEqual(queries[0], 'vacantes empleo "chofer" "Neuquén"')
        self.assertEqual(queries[1], 'vacantes empleo "electricista" "Rincón de los Sauces"')
        candidates = extractor.await_args.args[3]
        self.assertEqual(len(candidates), 8)
        self.assertEqual([item["url"].split("/")[-1] for item in candidates], ["0", "10", "1", "11", "2", "12", "3", "13"])
        self.assertEqual(jobs, [])
        self.assertEqual(len(failures), 1)
        self.assertIn("sin consultar", failures[0])

    async def test_configured_query_limit_never_exceeds_six(self):
        requests = []
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: requests.append(request) or httpx.Response(200, json=response([])))) as client:
            jobs, failures = await discover_web_jobs(config(web_search_max_queries=500), client,
                {"roles": ["chofer", "electricista", "mecánico"], "cities": ["Neuquén", "Rincón", "Centenario"]})
        self.assertEqual(len(requests), 6)
        self.assertEqual(jobs, [])
        self.assertIn("sin consultar", failures[0])

    async def test_same_url_from_two_queries_is_extracted_once(self):
        extractor = AsyncMock(return_value=[])
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=response()))) as client:
            with patch("app.services.web_search.extract_job_evidence", extractor):
                await discover_web_jobs(config(), client, {**SEARCH, "roles": ["chofer", "electricista"]})
        self.assertEqual(len(extractor.await_args.args[3]), 1)

    async def test_successful_empty_results_do_not_call_ai(self):
        extractor = AsyncMock()
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=response([])))) as client:
            with patch("app.services.web_search.extract_job_evidence", extractor):
                self.assertEqual(await discover_web_jobs(config(), client, SEARCH), ([], []))
        extractor.assert_not_awaited()

    async def test_missing_configuration_fails_without_requests(self):
        for changes in ({"web_search_provider": "disabled"}, {"web_search_api_key": " "},
                {"web_search_max_queries": True}):
            with self.subTest(changes=changes):
                requests = []
                async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: requests.append(request))) as client:
                    with self.assertRaises(HTTPException) as error:
                        await discover_web_jobs(config(**changes), client, SEARCH)
                self.assertEqual(error.exception.status_code, 503)
                self.assertEqual(requests, [])

    async def test_invalid_saved_search_fails_without_requests(self):
        for search in ({}, {"roles": "chofer", "cities": ["Neuquén"]}, {**SEARCH, "roles": []},
                {**SEARCH, "cities": [" "]}, {**SEARCH, "roles": ["a" * 161]},
                {**SEARCH, "roles": ["chofer"] * 21}, {**SEARCH, "roles": [None]}):
            with self.subTest(search=search):
                requests = []
                async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: requests.append(request))) as client:
                    with self.assertRaises(HTTPException):
                        await discover_web_jobs(config(), client, search)
                self.assertEqual(requests, [])

    async def test_no_live_search_key_can_be_put_into_query(self):
        requests = []
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: requests.append(request))) as client:
            with self.assertRaises(HTTPException) as error:
                await discover_web_jobs(config(), client, {**SEARCH, "roles": [PRIVATE_WEB_KEY]})
        self.assertEqual(error.exception.status_code, 503)
        self.assertNotIn(PRIVATE_WEB_KEY, error.exception.detail)
        self.assertEqual(requests, [])

    async def test_upstream_statuses_are_safe_and_never_zero_vacancies(self):
        for status, phrase in ((401, "clave"), (403, "clave"), (429, "límite temporal"),
                (432, "cupo"), (433, "cupo"), (400, "configuración"), (422, "configuración"),
                (500, "respondió"), (302, "respondió")):
            with self.subTest(status=status):
                requests = []
                async with httpx.AsyncClient(transport=httpx.MockTransport(
                        lambda request: requests.append(request) or httpx.Response(status,
                            text=f"{PRIVATE_WEB_KEY} RAW PRIVATE ERROR", headers={"Location": "https://other.example.com"}))) as client:
                    with self.assertRaises(HTTPException) as error:
                        await discover_web_jobs(config(), client, SEARCH)
                self.assertEqual(error.exception.status_code, 502)
                self.assertIn(phrase, error.exception.detail)
                self.assertNotIn("PRIVATE", error.exception.detail)
                self.assertEqual(len(requests), 1)

    async def test_failed_query_and_successful_empty_query_report_partial_results(self):
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(429, text=PRIVATE_WEB_KEY) if len(requests) == 1 else httpx.Response(200, json=response([]))
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            jobs, failures = await discover_web_jobs(config(), client, {**SEARCH, "roles": ["chofer", "electricista"]})
        self.assertEqual(jobs, [])
        self.assertEqual(failures, ["web:tavily: consulta 1 no completada"])
        self.assertNotIn(PRIVATE_WEB_KEY, json.dumps(failures))

    async def test_one_failed_query_does_not_discard_successful_results(self):
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(500) if len(requests) == 2 else httpx.Response(200, json=response())
        extractor = AsyncMock(return_value=[{"url": result()["url"], "payload": {}}])
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with patch("app.services.web_search.extract_job_evidence", extractor):
                jobs, failures = await discover_web_jobs(config(), client, {**SEARCH, "roles": ["chofer", "electricista"]})
        self.assertEqual(len(jobs), 1)
        self.assertEqual(failures, ["web:tavily: consulta 2 no completada"])

    async def test_timeout_is_failure_without_private_exception_context(self):
        def handler(request):
            raise httpx.ReadTimeout(PRIVATE_WEB_KEY, request=request)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(HTTPException) as error:
                await discover_web_jobs(config(), client, SEARCH)
        self.assertEqual(error.exception.status_code, 502)
        self.assertNotIn("PRIVATE", error.exception.detail)

    async def test_malformed_success_responses_are_not_successful_empty_search(self):
        for payload in ([], {}, {"results": None}, {"results": [result()] * 6}, {"error": "PRIVATE", "results": []}):
            with self.subTest(payload=payload):
                async with httpx.AsyncClient(transport=httpx.MockTransport(
                        lambda request: httpx.Response(200, json=payload))) as client:
                    with self.assertRaises(HTTPException) as error:
                        await discover_web_jobs(config(), client, SEARCH)
                self.assertEqual(error.exception.status_code, 502)
                self.assertNotIn("PRIVATE", error.exception.detail)

    async def test_stream_response_size_is_bounded(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=b" " * (MAX_RESPONSE_BYTES + 1)))) as client:
            with self.assertRaises(HTTPException) as error:
                await discover_web_jobs(config(), client, SEARCH)
        self.assertEqual(error.exception.status_code, 502)
        self.assertIn("demasiado grande", error.exception.detail)

    async def test_extraction_failure_is_not_zero_vacancies(self):
        extractor = AsyncMock(side_effect=HTTPException(502, "La IA no pudo analizar las vacantes con evidencia verificable."))
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=response()))) as client:
            with patch("app.services.web_search.extract_job_evidence", extractor):
                with self.assertRaises(HTTPException) as error:
                    await discover_web_jobs(config(), client, SEARCH)
        self.assertEqual(error.exception.status_code, 502)

    async def test_snippets_truncated_and_raw_content_never_forwarded(self):
        extractor = AsyncMock(return_value=[])
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=response([result(title="t" * 1000,
                    content="c" * 4000, raw_content="PRIVATE FULL WEB PAGE")])))) as client:
            with patch("app.services.web_search.extract_job_evidence", extractor):
                await discover_web_jobs(config(), client, SEARCH)
        candidate = extractor.await_args.args[3][0]
        self.assertEqual(len(candidate["title"]), 300)
        self.assertEqual(len(candidate["content"]), 1600)
        self.assertNotIn("raw_content", candidate)

    async def test_invalid_urls_are_never_requested_or_passed_to_ia(self):
        for url in ("http://empresa.example.com/job", "https://localhost/job", "https://127.0.0.1/job",
                "https://[::1]/job", "https://192.168.1.10/job", "https://example.internal/job",
                "https://example.local/job", "https://user:pass@empresa.example.com/job", "https://empresa.example.com/job#token",
                "https://empresa.example.com/job?access_token=PRIVATE", "https://127.1/job"):
            with self.subTest(url=url):
                requests = []
                extractor = AsyncMock()
                async with httpx.AsyncClient(transport=httpx.MockTransport(
                        lambda request: requests.append(request) or httpx.Response(200, json=response([result(url=url)])))) as client:
                    with patch("app.services.web_search.extract_job_evidence", extractor):
                        self.assertEqual(await discover_web_jobs(config(), client, SEARCH), ([], []))
                self.assertEqual(len(requests), 1)
                self.assertEqual(str(requests[0].url), TAVILY_ENDPOINT)
                extractor.assert_not_awaited()

    async def test_private_provider_values_not_preserved_as_results_or_request_ids(self):
        extractor = AsyncMock(return_value=[{"url": result()["url"], "payload": {}}])
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=response([result(), result(1, content=PRIVATE_WEB_KEY)],
                    request_id=PRIVATE_WEB_KEY)))) as client:
            with patch("app.services.web_search.extract_job_evidence", extractor):
                jobs, _ = await discover_web_jobs(config(), client, SEARCH)
        self.assertEqual(len(extractor.await_args.args[3]), 1)
        self.assertNotIn("request_id", jobs[0]["payload"]["web_search"])
        self.assertNotIn(PRIVATE_WEB_KEY, json.dumps(jobs))

    async def test_web_excerpts_never_attest_recipient_even_if_extractor_attempts_to(self):
        malicious = {"url": result()["url"], "recipient_email": "rrhh@empresa.example.com", "recipient_verified": True,
            "recipient_verified_at": "2026-10-14T13:00:00+00:00", "payload": {"requires_manual_verification": False}}
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=response()))) as client:
            with patch("app.services.web_search.extract_job_evidence", AsyncMock(return_value=[malicious])):
                jobs, _ = await discover_web_jobs(config(), client, SEARCH)
        self.assertFalse(jobs[0]["recipient_verified"])
        self.assertNotIn("recipient_verified_at", jobs[0])
        self.assertTrue(jobs[0]["requires_manual_review"])
        self.assertTrue(jobs[0]["payload"]["requires_manual_review"])
        self.assertTrue(jobs[0]["payload"]["requires_manual_verification"])

    async def test_real_extractor_receives_quotes_and_returns_unverified_job(self):
        requests = []
        excerpt = "Transportes Delta. Buscamos chofer en Rincón de los Sauces. Enviar CV a rrhh@delta.example.com."
        job = {"result_index": 0, "company": "Transportes Delta", "title": "chofer", "city": "Rincón de los Sauces",
            "description": excerpt, "recipient_email": "rrhh@delta.example.com", "evidence": {
                "company": "Transportes Delta", "title": "chofer", "city": "Rincón de los Sauces",
                "vacancy": "Transportes Delta. Buscamos chofer en Rincón de los Sauces.", "recipient_email": "Enviar CV a rrhh@delta.example.com."}}

        def handler(request):
            requests.append(request)
            if request.url.host == "api.tavily.com":
                return httpx.Response(200, json=response([result(title="Vacante chofer", content=excerpt)]))
            self.assertEqual(request.url.host, "ai.example.com")
            body = json.loads(request.content)
            self.assertNotIn("tools", body)
            self.assertNotIn(PRIVATE_WEB_KEY, json.dumps(body))
            self.assertIn(excerpt, body["messages"][1]["content"])
            return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"jobs": [job]})}}]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            jobs, failures = await discover_web_jobs(config(), client, SEARCH)
        self.assertEqual(len(requests), 2)
        self.assertEqual(failures, [])
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["company"], "Transportes Delta")
        self.assertEqual(jobs[0]["recipient_email"], "rrhh@delta.example.com")
        self.assertFalse(jobs[0]["recipient_verified"])
        self.assertEqual(jobs[0]["payload"]["evidence"]["vacancy"], job["evidence"]["vacancy"])
        self.assertEqual(jobs[0]["payload"]["web_search"]["provider"], "tavily")

    def test_public_url_validation_allows_actual_public_https_syntax(self):
        for url in ("https://empresa.example.com/job", "https://empresa.example.com/job?puesto=chofer", "https://8.8.8.8/job"):
            self.assertTrue(public_result_url(url), url)


if __name__ == "__main__":
    unittest.main()

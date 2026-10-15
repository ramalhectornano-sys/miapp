"""Deterministic contract tests. Mocked HTTP is NOT evidence of a live search."""
import json
from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from app.check_web_research import DEFAULT_SEARCH, check, main, markdown, preflight
from app.config import Settings


def configured(**changes):
    values = {"web_search_provider": "tavily", "web_search_api_key": "test-tavily-private-key",
        "ai_provider": "openai_compatible", "ai_base_url": "https://api.groq.com/openai/v1",
        "ai_api_key": "test-groq-private-key"}
    values.update(changes)
    return Settings(**values)


class RealResearchCheckTests(unittest.IsolatedAsyncioTestCase):
    def test_workflow_generated_report_matches_uploaded_artifact_directory(self):
        # GitHub evaluates upload paths from repository root, while the CLI
        # runs from trabajo-ya/backend. A mismatched ../ silently loses proof.
        import re
        workflow = Path(__file__).resolve().parents[2] / ".github/workflows/trabajo-ya-web-real-test.yml"
        content = workflow.read_text()
        working_directory = re.search(r"^\s+working-directory: (.+)$", content, re.MULTILINE).group(1)
        output = re.search(r"--output (\S+)", content).group(1)
        upload = re.search(r"^\s+path: (\S+)", content, re.MULTILINE).group(1)
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            produced = (repository / working_directory / output).resolve()
            uploaded_parent = (repository / upload).parent.resolve()
            self.assertEqual(produced.parent, uploaded_parent)
            self.assertEqual(produced.with_suffix(".md").parent, uploaded_parent)

    async def test_missing_secrets_emit_zero_calls_without_calling_runner(self):
        async def forbidden(*args, **kwargs):
            self.fail("Preflight must prevent all network and research work")
        settings = configured(web_search_api_key="", ai_api_key="")
        report = await check(settings, runner=forbidden)
        self.assertEqual(report["status"], "preflight_failed")
        self.assertEqual(report["missing_environment_variables"], ["WEB_SEARCH_API_KEY", "AI_API_KEY"])
        self.assertEqual(report["actual_tavily_calls"], 0)
        self.assertFalse(report["provider_consulted"])
        self.assertFalse(report["test_passed"])
        self.assertEqual(report["search"], DEFAULT_SEARCH)

    async def test_http_attempt_without_response_is_not_provider_proof(self):
        async def runner(settings, client, search, *, audit):
            await audit({"kind": "tavily_query", "event": "started", "status": "started"})
            await client.post("https://api.tavily.com/search")
        def fail_network(request):
            raise httpx.ConnectError("DNS failed with test-tavily-private-key", request=request)
        report = await check(configured(), runner=runner, transport=httpx.MockTransport(fail_network))
        self.assertEqual(report["actual_tavily_calls"], 1)
        self.assertFalse(report["provider_consulted"])
        self.assertFalse(report["test_passed"])
        self.assertEqual(report["status"], "failed")
        self.assertNotIn("test-tavily-private-key", json.dumps(report))

    async def test_rejected_key_has_response_but_not_successful_query(self):
        async def runner(settings, client, search, *, audit):
            response = await client.post("https://api.tavily.com/search")
            await audit({"kind": "tavily_query", "event": "completed", "status": "failed",
                "http_status": response.status_code, "provider_response_received": True,
                "error": "Clave rechazada test-tavily-private-key", "headers": {"Authorization": "unsafe"}})
            raise ValueError("Provider key test-tavily-private-key")
        report = await check(configured(), runner=runner,
            transport=httpx.MockTransport(lambda request: httpx.Response(401, json={"error": "rejected"})))
        self.assertTrue(report["provider_consulted"])
        self.assertEqual(report["tavily_successful_queries"], 0)
        self.assertFalse(report["test_passed"])
        self.assertNotIn("test-tavily-private-key", json.dumps(report))
        self.assertNotIn("Authorization", json.dumps(report))

    async def test_completed_report_requires_all_provider_and_job_proofs(self):
        report = await check(configured(), runner=self.success_runner,
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})))
        self.assertEqual(report["status"], "completed")
        self.assertTrue(report["test_passed"])
        self.assertEqual(report["verified_within_radius_count"], 1)
        self.assertEqual(report["tavily_credits_reported"], 1)
        self.assertFalse(report["email_sent"])
        self.assertFalse(report["database_accessed"])
        self.assertNotIn("secret_in_header", json.dumps(report))
        self.assertNotIn("person@example.org", json.dumps(report))
        self.assertIn("https://example.org/empleos/chofer", markdown(report))
        self.assertIn("request_id `real-shaped-id`", markdown(report))

    async def test_healthy_queries_without_verified_job_are_not_completed_feature(self):
        async def runner(settings, client, search, *, audit):
            data = await self.success_runner(settings, client, search, audit=audit)
            data["results"] = []
            return data
        report = await check(configured(), runner=runner,
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})))
        self.assertEqual(report["status"], "no_verified_opportunities")
        self.assertFalse(report["test_passed"])
        self.assertTrue(all(report["provider_proofs"].values()))

    async def test_late_analysis_failure_preserves_public_discovery_and_location_evidence(self):
        from fastapi import HTTPException
        async def runner(settings, client, search, *, audit):
            data = await self.success_runner(settings, client, search, audit=audit)
            data["results"] = []
            data["discoveries"][0]["raw_content"] = "PRIVATE RAW PAGE MUST NOT BE IN REPORT"
            failure = HTTPException(429, "test-groq-private-key")
            failure.research_partial = data
            raise failure
        report = await check(configured(), runner=runner,
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})))
        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["test_passed"])
        self.assertEqual(report["actual_tavily_calls"], 1)
        self.assertTrue(report["search_location"]["verified"])
        self.assertEqual(report["discoveries"][0]["url"], "https://example.org/empleos/chofer")
        self.assertEqual(report["results"], [])
        self.assertNotIn("PRIVATE RAW PAGE", json.dumps(report))
        self.assertNotIn("test-groq-private-key", json.dumps(report))

    async def test_outside_or_unknown_radius_does_not_pass(self):
        for classification in ({"location_verified": True, "within_radius": False},
                               {"location_verified": False, "within_radius": None}):
            async def runner(settings, client, search, *, audit):
                data = await self.success_runner(settings, client, search, audit=audit)
                data["results"][0]["payload"]["geography"] = classification
                return data
            report = await check(configured(), runner=runner,
                transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})))
            self.assertFalse(report["test_passed"])
            self.assertEqual(report["verified_within_radius_count"], 0)

    async def test_groq_or_georef_failure_means_partial(self):
        for failed_provider in ("api.groq.com", "apis.datos.gob.ar"):
            def response(request):
                return httpx.Response(503 if request.url.host == failed_provider else 200, json={})
            report = await check(configured(), runner=self.success_runner,
                transport=httpx.MockTransport(response))
            self.assertEqual(report["status"], "partial")
            self.assertFalse(report["test_passed"])

    async def test_provider_warnings_and_failures_do_not_get_silently_dropped(self):
        async def runner(settings, client, search, *, audit):
            data = await self.success_runner(settings, client, search, audit=audit)
            data["failures"] = ["No se pudo verificar una página original."]
            return data
        report = await check(configured(), runner=runner,
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})))
        self.assertEqual(report["status"], "partial")
        self.assertIn("No se pudo verificar una página original.", report["failures"])

    async def test_over_budget_is_rejected_before_network(self):
        for values in ({"max_queries": 13}, {"max_pages": 11}):
            with self.assertRaises(ValueError):
                await check(configured(), **values)

    def test_only_groq_real_https_endpoint_is_accepted(self):
        for endpoint in ("http://api.groq.com/openai/v1", "https://api.groq.com.evil.org/openai/v1",
                         "https://user:secret@api.groq.com/openai/v1", "https://api.groq.com/openai/v1?key=x"):
            missing, invalid = preflight(configured(ai_base_url=endpoint))
            self.assertEqual(missing, [])
            self.assertIn("AI_BASE_URL", invalid)

    def test_cli_writes_failure_artifacts_and_does_not_echo_bad_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            stdout = io.StringIO()
            with patch("app.check_web_research.Settings.from_env", side_effect=ValueError("private-value-do-not-print")), redirect_stdout(stdout):
                code = main(["--output", str(output)])
            report = json.loads(output.read_text())
            self.assertEqual(code, 1)
            self.assertEqual(report["status"], "preflight_failed")
            self.assertEqual(report["invalid_environment_variables"], ["SERVER_ENVIRONMENT"])
            self.assertEqual(report["actual_tavily_calls"], 0)
            self.assertTrue(output.with_suffix(".md").is_file())
            self.assertNotIn("private-value-do-not-print", stdout.getvalue() + output.read_text())

    async def success_runner(self, settings, client, search, *, audit):
        await client.post("https://api.tavily.com/search", headers={"Authorization": "secret_in_header"})
        await audit({"kind": "tavily_query", "event": "completed", "status": "succeeded",
            "provider": "tavily", "query": "chofer Rincón de los Sauces Neuquén Argentina",
            "http_status": 200, "provider_response_received": True,
            "request_id": "real-shaped-id", "credits": 1, "result_urls": ["https://example.org/empleos/chofer"]})
        await client.post("https://api.groq.com/openai/v1/chat/completions")
        await audit({"kind": "analysis", "provider": "groq", "status": "succeeded",
            "http_status": 200, "provider_response_received": True, "model": "test-model",
            "request_id": "groq-shaped-receipt", "usage": {"total_tokens": 100}})
        await client.get("https://apis.datos.gob.ar/georef/api/v2.0/localidades", params={"nombre": "Rincón de los Sauces"})
        return {"search": {**search, "location": {"id": "58063010", "verified": True,
            "city": "Rincón de los Sauces", "province": "Neuquén", "country": "Argentina"}},
            "results": [{"company": "Empresa de prueba", "title": "Chofer", "city": "Rincón de los Sauces",
                "url": "https://example.org/empleos/chofer", "recipient_email": "person@example.org",
                "payload": {"geography": {"location_verified": True, "within_radius": True,
                    "location_status": "verified", "distance_km": 0.0},
                    "page_verification": {"status": "verified_link"}}}],
            "discoveries": [{"url": "https://example.org/empleos/chofer", "title": "Chofer"}], "failures": []}


if __name__ == "__main__":
    unittest.main()

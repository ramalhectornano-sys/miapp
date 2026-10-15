"""Owned, sanitized query history; provider and Supabase responses are mocks."""
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx

from app.config import Settings
from app.main import create_app
from app.services.research_audit import ResearchAuditError, database_audit, sanitized_event


USER = "11111111-1111-4111-8111-111111111111"
SEARCH = "22222222-2222-4222-8222-222222222222"
RUN = "33333333-3333-4333-8333-333333333333"
FOREIGN = "44444444-4444-4444-8444-444444444444"


def settings():
    return Settings(supabase_url="https://project.example.org", supabase_anon_key="sb_publishable_FIXTURE",
        supabase_service_role_key="sb_secret_PRIVATE_FIXTURE", web_search_api_key="tvly-dev-PRIVATE_FIXTURE",
        ai_api_key="gsk_PRIVATE_FIXTURE", google_client_secret="GMAIL-PRIVATE-FIXTURE",
        token_encryption_key="ENCRYPTION-PRIVATE-FIXTURE")


class ResearchAuditTests(unittest.IsolatedAsyncioTestCase):
    def test_event_records_provider_receipt_and_status_without_private_values(self):
        config = settings()
        identifier = str(uuid4())
        event = {"kind": "tavily_query", "provider": "tavily", "event_id": identifier,
            "status": "failed", "query": f'chofer Argentina {config.web_search_api_key}',
            "url": "https://api.tavily.com/search?utm_source=tracking",
            "http_status": 429, "request_id": "MOCK-ONLY-provider-receipt", "credits": 1,
            "error": f'Bearer private-token {config.ai_api_key}',
            "result_urls": ["https://empleador.example.org/vacante?utm_campaign=test",
                "https://empleador.example.org/vacante?token=private", "https://127.0.0.1/private"],
            "metadata": {"reason": config.google_client_secret, "api_key": config.token_encryption_key,
                "raw_body": "PRIVATE RESPONSE", "query_kind": "general_vacancies", "radius_km": 100,
                "nested": {"secret": "private"}}, "content": "PRIVATE PAGE BODY"}
        result = sanitized_event(config, event)
        self.assertEqual(str(UUID(result["event_id"])), identifier)
        self.assertEqual(result["http_status"], 429)
        self.assertEqual(result["provider_request_id"], "MOCK-ONLY-provider-receipt")
        self.assertEqual(result["url"], "https://api.tavily.com/search")
        self.assertEqual(result["result_urls"], ["https://empleador.example.org/vacante"])
        self.assertEqual(result["metadata"]["radius_km"], 100)
        self.assertIn("finished_at", result)
        serialized = json.dumps(result)
        for secret in (config.web_search_api_key, config.ai_api_key, config.google_client_secret,
                config.token_encryption_key, "private-token", "PRIVATE RESPONSE", "PRIVATE PAGE BODY"):
            self.assertNotIn(secret, serialized)
        self.assertNotIn("raw_body", result["metadata"])
        self.assertNotIn("nested", result["metadata"])

    async def test_database_event_is_bound_to_search_run_and_current_claim(self):
        calls = []

        async def rpc(name, payload):
            calls.append((name, payload))
            return True

        db = SimpleNamespace(settings=settings(), rpc=rpc)
        record = database_audit(db, {"id": SEARCH, "run_id": RUN, "claim_token": "fixture-current-lease"})
        event = {"event_id": str(uuid4()), "kind": "tavily_query", "provider": "tavily",
            "status": "started", "query": "chofer Neuquén Argentina"}
        await record(event)
        self.assertEqual(calls[0][0], "record_web_research_event")
        self.assertEqual(calls[0][1]["p_search_id"], SEARCH)
        self.assertEqual(calls[0][1]["p_run_id"], RUN)
        self.assertEqual(calls[0][1]["p_claim_token"], "fixture-current-lease")
        self.assertNotIn("user_id", calls[0][1]["p_event"])  # SQL derives owner from the claim

    async def test_unconfirmed_database_write_is_a_hard_failure(self):
        for receipt in (False, None, 1, {}, []):
            async def rpc(*_args):
                return receipt

            record = database_audit(SimpleNamespace(settings=settings(), rpc=rpc),
                {"id": SEARCH, "run_id": RUN, "claim_token": "fixture-current-lease"})
            with self.subTest(receipt=receipt), self.assertRaises(ResearchAuditError):
                await record({"kind": "tavily_query", "provider": "tavily", "status": "started"})

    async def test_private_database_exception_is_not_exposed(self):
        async def rpc(*_args):
            raise RuntimeError("PRIVATE SQL CONNECTION STRING")

        record = database_audit(SimpleNamespace(settings=settings(), rpc=rpc),
            {"id": SEARCH, "run_id": RUN, "claim_token": "fixture-current-lease"})
        with self.assertRaises(ResearchAuditError) as caught:
            await record({"kind": "tavily_query", "provider": "tavily", "status": "started"})
        self.assertNotIn("PRIVATE", str(caught.exception.detail))
        self.assertTrue(caught.exception.audit_failed)


class WebHistoryApiTests(unittest.IsolatedAsyncioTestCase):
    async def call(self, path, *, headers=None, missing_owner=False, rejected_session=False):
        calls = []
        event = {"id": str(uuid4()), "search_id": SEARCH, "run_id": RUN, "kind": "tavily_query",
            "provider": "tavily", "status": "succeeded", "http_status": 200,
            "provider_request_id": "MOCK-ONLY-receipt", "credits": 1,
            "started_at": "2026-10-15T12:00:00+00:00", "finished_at": "2026-10-15T12:00:01+00:00"}

        def upstream(request):
            calls.append(request)
            if request.url.path == "/auth/v1/user":
                return httpx.Response(401 if rejected_session else 200, json={"id": USER})
            self.assertEqual(request.headers["authorization"], "Bearer owner-session")
            self.assertEqual(request.headers["apikey"], "sb_publishable_FIXTURE")
            self.assertEqual(request.method, "GET")
            if request.url.path == "/rest/v1/job_searches":
                self.assertEqual(request.url.params["user_id"], f"eq.{USER}")
                self.assertEqual(request.url.params["id"], f"eq.{path.split('/')[3]}")
                return httpx.Response(200, json=[] if missing_owner else [{"id": SEARCH, "user_id": USER}])
            self.assertEqual(request.url.path, "/rest/v1/web_research_events")
            self.assertFalse(missing_owner)
            self.assertEqual(request.url.params["search_id"], f"eq.{SEARCH}")
            self.assertEqual(request.url.params["user_id"], f"eq.{USER}")
            self.assertEqual(request.url.params["limit"], "300")
            self.assertEqual(request.url.params["order"], "started_at.desc,id.desc")
            return httpx.Response(200, json=[event])

        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as provider:
            app = create_app(settings(), provider)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api") as client:
                    result = await client.get(path, headers=headers)
        return result, calls, event

    async def test_owner_reads_bounded_history_using_user_bearer_and_rls_filters(self):
        response, calls, event = await self.call(f"/api/searches/{SEARCH}/web-history",
            headers={"Authorization": "Bearer owner-session"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), [event])
        self.assertEqual(len(calls), 3)
        self.assertNotIn("sb_secret", str([dict(request.headers) for request in calls]))
        self.assertNotIn("PRIVATE", response.text)

    async def test_foreign_search_cannot_trigger_a_history_table_request(self):
        response, calls, _ = await self.call(f"/api/searches/{FOREIGN}/web-history",
            headers={"Authorization": "Bearer owner-session"}, missing_owner=True)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(len(calls), 2)
        self.assertFalse(any(request.url.path.endswith("web_research_events") for request in calls))

    async def test_missing_session_does_not_touch_database_or_providers(self):
        response, calls, _ = await self.call(f"/api/searches/{SEARCH}/web-history")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(calls, [])

    async def test_rejected_session_never_reaches_owned_search_or_history(self):
        response, calls, _ = await self.call(f"/api/searches/{SEARCH}/web-history",
            headers={"Authorization": "Bearer expired-session"}, rejected_session=True)
        self.assertEqual(response.status_code, 401)
        self.assertEqual([request.url.path for request in calls], ["/auth/v1/user"])

    async def test_health_reports_compatible_backend_patch_without_claiming_provider_success(self):
        response, calls, _ = await self.call("/health")
        version = json.loads((Path(__file__).resolve().parents[2] / "mobile" / "app.json").read_text())["expo"]["version"]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["version"], "0.5.3")
        # A server patch can fix research without changing the Android package.
        self.assertEqual(response.json()["version"].split(".")[:2], version.split(".")[:2])
        self.assertEqual(calls, [])
        self.assertNotEqual(response.json()["integrations"]["web_search"], "verified")


if __name__ == "__main__":
    unittest.main()

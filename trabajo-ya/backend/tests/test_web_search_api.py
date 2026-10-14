"""Web search executes only real provider calls; tests replace HTTP transport."""
import json
import unittest
from datetime import datetime, timezone

import httpx

from app.config import Settings
from app.main import create_app
from app.services.source_registry import WEB_SOURCE_ID, public_source
from tests.test_job_evidence import AD, SOURCE, candidate, completion

USER = "11111111-1111-4111-8111-111111111111"
SEARCH_ID = "22222222-2222-4222-8222-222222222222"
RUN_ID = "33333333-3333-4333-8333-333333333333"
JOB_ID = "44444444-4444-4444-8444-444444444444"
SEARCH = {"id": SEARCH_ID, "user_id": USER, "roles": ["chofer"],
    "cities": ["Rincón de los Sauces"], "schedule_time": "09:00",
    "frequency": "daily", "weekdays": [], "timezone": "UTC", "status": "enabled",
    "run_id": RUN_ID, "claim_token": "claim", "preferred_resume_id": None, "auto_apply": False}


class WebSearchApiTests(unittest.IsolatedAsyncioTestCase):
    def settings(self, **changes):
        return Settings(**{"supabase_url": "https://project.invalid",
            "supabase_anon_key": "sb_publishable_TEST", "supabase_service_role_key": "sb_secret_TEST",
            "web_search_provider": "tavily", "web_search_api_key": "PRIVATE-SEARCH-KEY",
            "ai_provider": "openai_compatible", "ai_base_url": "https://api.groq.com/openai/v1",
            "ai_model": "openai/gpt-oss-20b", "ai_api_key": "PRIVATE-AI-KEY", **changes})

    async def test_manual_web_run_records_grounded_job_and_returns_owned_links_without_cv(self):
        stored, completed, paths = [], [], []
        observed = datetime.now(timezone.utc).isoformat()
        def provider(request):
            path = request.url.path
            paths.append(path)
            if path == "/auth/v1/user":
                return httpx.Response(200, json={"id": USER})
            if path == "/rest/v1/job_searches":
                self.assertEqual(request.url.params["user_id"], f"eq.{USER}")
                return httpx.Response(200, json=[SEARCH])
            if path == "/rest/v1/rpc/claim_search_now":
                return httpx.Response(200, json=SEARCH)
            if path == "/rest/v1/rpc/assert_search_claim":
                return httpx.Response(200, json=True)
            if request.url.host == "api.tavily.com":
                query = json.loads(request.content)
                self.assertIn('"chofer"', query["query"])
                self.assertIn('"Rincón de los Sauces"', query["query"])
                return httpx.Response(200, json={"results": [SOURCE], "request_id": "provider-receipt", "usage": {"credits": 1}})
            if request.url.host == "api.groq.com":
                return httpx.Response(200, json=completion({"jobs": [candidate()]}))
            if path == "/rest/v1/jobs":
                if request.method == "GET":
                    return httpx.Response(200, json=stored)
                row = json.loads(request.content)
                row["id"] = JOB_ID
                stored.append(row)
                return httpx.Response(201, json=[row])
            if path == "/rest/v1/applications":
                return httpx.Response(200, json=[])
            if path == "/rest/v1/profiles":
                return httpx.Response(200, json=[{"full_name": "Persona de prueba"}])
            if path == "/rest/v1/job_search_matches":
                if request.method == "POST":
                    return httpx.Response(201, json=[{"id": "match"}])
                self.assertEqual(request.headers["authorization"], "Bearer user-session")
                self.assertEqual(request.url.params["search_id"], f"eq.{SEARCH_ID}")
                self.assertEqual(request.url.params["user_id"], f"eq.{USER}")
                return httpx.Response(200, json=[{"observed_at": observed, "job": stored[0]}])
            if path == "/rest/v1/rpc/complete_search_run":
                completed.append(json.loads(request.content))
                return httpx.Response(200, json=True)
            self.fail(f"Unexpected operation: {request.method} {path}")
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as upstream:
            app = create_app(self.settings(), upstream)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api") as client:
                    headers = {"Authorization": "Bearer user-session"}
                    run = await client.post(f"/api/searches/{SEARCH_ID}/run", headers=headers)
                    self.assertEqual(run.status_code, 200, run.text)
                    results = await client.get(f"/api/searches/{SEARCH_ID}/results", headers=headers)
        self.assertEqual(run.json()["found_count"], 1)
        self.assertTrue(run.json()["recorded"])
        self.assertEqual(completed[0]["p_status"], "completed")
        self.assertIsNone(stored[0]["recipient_verified_at"])
        self.assertEqual(stored[0]["payload"]["web_search"]["request_id"], "provider-receipt")
        self.assertEqual(results.status_code, 200)
        self.assertEqual(results.json()[0]["url"], SOURCE["url"])
        self.assertTrue(results.json()[0]["requires_manual_review"])
        self.assertFalse(results.json()[0]["recipient_verified"])
        self.assertIn(AD, results.json()[0]["evidence"].values())
        self.assertNotIn("PRIVATE", run.text + results.text)
        self.assertNotIn("/gmail/v1/users/me/messages/send", paths)

    async def test_missing_search_key_cannot_claim_or_report_a_run(self):
        paths = []
        def provider(request):
            paths.append(request.url.path)
            return httpx.Response(200, json={"id": USER} if request.url.path == "/auth/v1/user" else [SEARCH])
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as upstream:
            app = create_app(self.settings(web_search_api_key=""), upstream)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api") as client:
                    result = await client.post(f"/api/searches/{SEARCH_ID}/run", headers={"Authorization": "Bearer user"})
        self.assertEqual(result.status_code, 503)
        self.assertNotIn("/rest/v1/rpc/claim_search_now", paths)

    def test_source_registry_preserves_web_slot_and_never_exposes_private_configuration(self):
        settings = self.settings(authorized_feeds=[{"id": f"partner-{index}", "authorized": True,
            "url": "https://PRIVATE.example/feed", "token": "PRIVATE"} for index in range(20)])
        sources = settings.job_sources
        self.assertEqual(len(sources), 20)
        self.assertEqual(sources[-1]["id"], WEB_SOURCE_ID)
        public = [public_source(source) for source in sources]
        self.assertFalse(public[-1]["supports_automatic_email"])
        self.assertNotIn("PRIVATE", json.dumps(public))
        self.assertNotIn(settings.web_search_api_key, json.dumps(public))


if __name__ == "__main__":
    unittest.main()

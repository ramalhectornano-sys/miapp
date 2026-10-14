from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
import unittest
import httpx

from app.config import Settings
from app.main import create_app
from app.services.feeds import execute_claim

USER_ID = "11111111-1111-4111-8111-111111111111"


class SchedulingDatabase:
    def __init__(self, fence_values=None):
        self.settings = Settings()
        self.current_search = {"status": "enabled", "auto_apply": False}
        self.fence_values = iter(fence_values) if fence_values is not None else None
        self.records, self.completions, self.applications, self.matches = [], [], [], []

    async def rpc(self, name, payload, user=None):
        if name == "assert_search_claim":
            return next(self.fence_values) if self.fence_values is not None else True
        if name == "prepare_automatic_application":
            return next(row for row in self.applications if row["id"] == payload["p_application_id"])
        if name == "create_initial_application":
            return (await self.insert("applications", payload["p_application"]))[0]
        if name == "prepare_followup_application":
            return None
        self.completions.append(payload)
        return True

    async def select(self, table, user=None, params=None):
        if table == "jobs": return list(self.records)
        if table == "applications": return list(self.applications)
        if table == "job_search_matches": return list(self.matches)
        if table == "email_connections": return [{"id": "connection"}]
        return []

    async def insert(self, table, data, user=None, conflict=None):
        row = {**data, "id": f"{table}-{len(self.records) + len(self.applications) + len(self.matches)}"}
        {"jobs": self.records, "applications": self.applications, "job_search_matches": self.matches}[table].append(row)
        return [row]

    async def patch(self, table, data, user=None, params=None):
        rows = {"jobs": self.records, "applications": self.applications, "job_search_matches": self.matches}[table]
        result = []
        for row in rows:
            if all(row.get(key) == value[3:] for key, value in (params or {}).items() if value.startswith("eq.")):
                row.update(data)
                result.append(row.copy())
        return result

    async def owned(self, table, item_id, user, service=False):
        if table == "job_searches": return self.current_search
        if table == "jobs": return next(row for row in self.records if row["id"] == item_id)
        return {"email_connection_id": "connection"}


def search():
    return {"id": "search", "user_id": USER_ID, "claim_token": "claim", "run_id": "run",
        "schedule_time": "09:00", "timezone": "UTC", "frequency": "daily", "weekdays": [],
        "preferred_resume_id": None, "auto_apply": False,
        "lease_expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}


def jobs(count=3):
    return [{"user_id": USER_ID, "fingerprint": f"fingerprint-{index}", "source": "partner", "external_id": str(index),
        "company": "Empresa", "title": "Chofer", "city": "Neuquén"} for index in range(count)]


class SchedulerFenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_unrecorded_completion_is_not_reported_as_completed(self):
        class ChangedClaimDatabase(SchedulingDatabase):
            async def rpc(self, name, payload, user=None):
                return False if name == "complete_search_run" else True
        with patch("app.services.feeds.find_jobs", AsyncMock(return_value=([], []))):
            result = await execute_claim(ChangedClaimDatabase(), search())
        self.assertEqual(result["status"], "error")
        self.assertFalse(result["recorded"])

    async def test_invalid_claim_prevents_all_source_and_data_work(self):
        db = SchedulingDatabase([False])
        finder = AsyncMock(return_value=(jobs(), []))
        with patch("app.services.feeds.find_jobs", finder):
            result = await execute_claim(db, search())
        self.assertEqual(result["status"], "error")
        finder.assert_not_awaited()
        self.assertFalse(db.records)

    async def test_lost_claim_before_side_effect_stops_insertion(self):
        db = SchedulingDatabase([True, True, True, False])
        with patch("app.services.feeds.find_jobs", AsyncMock(return_value=(jobs(), []))):
            result = await execute_claim(db, search())
        self.assertEqual(result["status"], "error")
        self.assertFalse(db.records)

    async def test_bounded_batch_makes_progress_on_subsequent_run(self):
        db = SchedulingDatabase()
        with patch("app.services.feeds.find_jobs", AsyncMock(return_value=(jobs(), []))), patch("app.services.feeds.MAX_JOBS_PER_RUN", 2):
            first = await execute_claim(db, search())
            self.assertEqual(len(db.records), 2)
            second = await execute_claim(db, search())
        self.assertEqual(first["found_count"], 2)
        self.assertEqual(second["found_count"], 1)
        self.assertEqual(len(db.records), 3)
        self.assertIn("próximas ejecuciones", first["message"])

    async def test_deadline_keeps_error_without_fake_completion(self):
        db = SchedulingDatabase()
        with patch("app.services.feeds.find_jobs", AsyncMock(side_effect=TimeoutError)):
            result = await execute_claim(db, search())
        self.assertEqual(result["status"], "error")
        self.assertEqual(db.completions[-1]["p_status"], "error")
        self.assertIn("tiempo máximo", result["message"])

    async def test_fence_is_rechecked_immediately_before_automatic_send(self):
        class LostAfterPreparation(SchedulingDatabase):
            prepared = False

            async def rpc(self, name, payload, user=None):
                if name == "prepare_automatic_application":
                    self.prepared = True
                if name == "assert_search_claim":
                    return not self.prepared
                return await super().rpc(name, payload, user)

        db = LostAfterPreparation()
        config = {**search(), "preferred_resume_id": "resume", "auto_apply": True, "consent_id": "consent"}
        db.current_search = {**config, "status": "enabled"}
        db.settings = Settings(mail_send_enabled=True, authorized_feeds=[{"id": "partner", "authorized": True}])
        sender = AsyncMock()
        with patch("app.services.feeds.find_jobs", AsyncMock(return_value=(jobs(1), []))), patch("app.services.mail.send_application", sender):
            result = await execute_claim(db, config)
        self.assertEqual(result["status"], "error")
        self.assertEqual(len(db.applications), 1)
        sender.assert_not_awaited()

    async def test_integrations_exposes_only_safe_metadata(self):
        def provider(request):
            if request.url.path == "/auth/v1/user":
                return httpx.Response(200, json={"id": USER_ID})
            self.assertEqual(request.url.params["user_id"], f"eq.{USER_ID}")
            return httpx.Response(200, json=[{"id": "connection", "provider": "google", "email": "me@example.com", "status": "connected", "connected_at": "2026-10-12", "access_token": "PRIVATE-TOKEN"}])
        settings = Settings(supabase_url="https://test.supabase.co", supabase_anon_key="public",
            authorized_feeds=[{"id": "partner", "name": "Fuente permitida", "authorized": True, "url": "https://private-config.example/feed?key=SECRET"}])
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as upstream:
            app = create_app(settings, upstream)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                    response = await client.get("/api/integrations", headers={"Authorization": "Bearer valid"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["sources"], [{"id": "partner", "name": "Fuente permitida", "description": "", "supports_automatic_email": False}])
        self.assertNotIn("PRIVATE-TOKEN", response.text)
        self.assertNotIn("SECRET", response.text)
        self.assertNotIn("url", response.text)

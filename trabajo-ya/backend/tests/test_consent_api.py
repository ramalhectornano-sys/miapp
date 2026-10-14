"""Consent API contracts are exercised with intercepted Supabase HTTP requests."""
from datetime import datetime, timedelta, timezone
import json
import unittest

import httpx
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app
from app.models import ConsentRequest


USER_ID = "11111111-1111-4111-8111-111111111111"
SEARCH_ID = "22222222-2222-4222-8222-222222222222"
RESUME_ID = "33333333-3333-4333-8333-333333333333"
CONNECTION_ID = "44444444-4444-4444-8444-444444444444"
APPLICATION_ID = "55555555-5555-4555-8555-555555555555"
REPEAT_ACK = "Autorizo los envíos automáticos de esta búsqueda y los recordatorios cada 3 días, con un máximo total de 10 correos por día"


class ConsentApiTests(unittest.IsolatedAsyncioTestCase):
    def consent_payload(self, repeat_days=0):
        return {"search_id": SEARCH_ID, "resume_id": RESUME_ID, "email_connection_id": CONNECTION_ID,
            "allowed_sources": ["partner"], "expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
            "repeat_every_days": repeat_days,
            "acknowledgment": REPEAT_ACK if repeat_days == 3 else "Autorizo los envíos automáticos de esta búsqueda"}

    def test_repetition_requires_its_own_exact_acknowledgment(self):
        payload = self.consent_payload(3)
        self.assertEqual(ConsentRequest(**payload).repeat_every_days, 3)
        payload["acknowledgment"] = "Autorizo los envíos automáticos de esta búsqueda"
        with self.assertRaises(ValidationError):
            ConsentRequest(**payload)
        payload = self.consent_payload(0)
        payload["acknowledgment"] = REPEAT_ACK
        with self.assertRaises(ValidationError):
            ConsentRequest(**payload)
        payload = self.consent_payload()
        del payload["repeat_every_days"]
        self.assertEqual(ConsentRequest(**payload).repeat_every_days, 0)

    async def exercise_source_consent(self, source_id, feeds=None):
        writes = []

        def supabase(request):
            if request.url.path == "/auth/v1/user":
                return httpx.Response(200, json={"id": USER_ID})
            if request.method == "GET":
                return httpx.Response(200, json=[{"id": CONNECTION_ID, "provider": "google", "status": "connected",
                    "scopes": ["https://www.googleapis.com/auth/gmail.send"]}])
            writes.append(json.loads(request.content))
            return httpx.Response(200, json={"consent": {"id": "consent", "repeat_enabled": False},
                "search": {"id": SEARCH_ID, "auto_apply": True}})

        settings = Settings(supabase_url="https://test.supabase.co", supabase_anon_key="public",
            supabase_service_role_key="server-secret", web_search_provider="tavily", web_search_api_key="test-search-key",
            authorized_feeds=feeds or [])
        payload = self.consent_payload()
        payload["allowed_sources"] = [source_id]
        async with httpx.AsyncClient(transport=httpx.MockTransport(supabase)) as upstream:
            app = create_app(settings, upstream)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                    response = await client.post("/api/mail/consents", headers={"Authorization": "Bearer user-session"},
                        json=payload)
        return response, writes

    async def test_official_publisher_channel_can_be_authorized_without_enabling_mail(self):
        response, writes = await self.exercise_source_consent("verified:greenhouse")
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(writes[0]["p_authorized_sources"], ["verified:greenhouse"])
        self.assertIn("envíos habilitados", response.json()["message"])

    async def test_web_snippets_cannot_be_authorized_as_verified_recipients(self):
        response, writes = await self.exercise_source_consent("web:tavily")
        self.assertEqual(response.status_code, 409)
        self.assertFalse(writes)

    async def test_non_attested_json_feed_cannot_bypass_the_disabled_source_choice(self):
        response, writes = await self.exercise_source_consent("partner", [{"id": "partner", "authorized": True}])
        self.assertEqual(response.status_code, 409)
        self.assertFalse(writes)

    async def test_repeat_policy_passes_explicit_choice_to_service_rpc(self):
        writes = []

        def supabase(request):
            if request.url.path == "/auth/v1/user":
                return httpx.Response(200, json={"id": USER_ID})
            if request.method == "GET":
                return httpx.Response(200, json=[{"id": CONNECTION_ID, "provider": "google", "status": "connected",
                    "scopes": ["https://www.googleapis.com/auth/gmail.send"]}])
            writes.append(json.loads(request.content))
            return httpx.Response(200, json={"consent": {"id": "v3-consent", "repeat_enabled": True},
                "search": {"id": SEARCH_ID, "auto_apply": True}})

        settings = Settings(supabase_url="https://test.supabase.co", supabase_anon_key="public",
            supabase_service_role_key="server-secret", authorized_feeds=[{"id": "partner", "authorized": True,
                "recipient_verification": "source_attestation"}])
        async with httpx.AsyncClient(transport=httpx.MockTransport(supabase)) as upstream:
            app = create_app(settings, upstream)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                    response = await client.post("/api/mail/consents", headers={"Authorization": "Bearer user-session"},
                        json=self.consent_payload(3))
        self.assertEqual(response.status_code, 201)
        self.assertTrue(writes[0]["p_repeat_enabled"])
        self.assertEqual(writes[0]["p_authorization_text"], REPEAT_ACK)
        self.assertIn("por usuario", response.json()["message"])

    async def test_stop_followups_verifies_owner_before_service_rpc(self):
        writes = []

        def supabase(request):
            if request.url.path == "/auth/v1/user":
                return httpx.Response(200, json={"id": USER_ID})
            if request.method == "GET":
                self.assertEqual(request.url.path, "/rest/v1/applications")
                self.assertEqual(request.url.params["user_id"], f"eq.{USER_ID}")
                self.assertEqual(request.headers["authorization"], "Bearer user-session")
                return httpx.Response(200, json=[{"id": APPLICATION_ID, "recipient_email": "rrhh@example.com"}])
            self.assertEqual(request.url.path, "/rest/v1/rpc/stop_recipient_followups")
            self.assertEqual(request.headers["authorization"], "Bearer server-secret")
            writes.append(json.loads(request.content))
            return httpx.Response(200, json={"recipient_email": "rrhh@example.com", "reason": "user_request",
                "stopped_at": datetime.now(timezone.utc).isoformat()})

        settings = Settings(supabase_url="https://test.supabase.co", supabase_anon_key="public",
            supabase_service_role_key="server-secret")
        async with httpx.AsyncClient(transport=httpx.MockTransport(supabase)) as upstream:
            app = create_app(settings, upstream)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                    response = await client.post(f"/api/applications/{APPLICATION_ID}/stop-followups",
                        headers={"Authorization": "Bearer user-session"}, json={"reason": "user_request"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["stopped"])
        self.assertEqual(writes, [{"p_application_id": APPLICATION_ID, "p_user_id": USER_ID, "p_reason": "user_request"}])

    async def test_foreign_application_cannot_be_stopped(self):
        writes = []

        def supabase(request):
            if request.url.path == "/auth/v1/user":
                return httpx.Response(200, json={"id": USER_ID})
            if request.method != "GET":
                writes.append(request)
            return httpx.Response(200, json=[])

        settings = Settings(supabase_url="https://test.supabase.co", supabase_anon_key="public",
            supabase_service_role_key="server-secret")
        async with httpx.AsyncClient(transport=httpx.MockTransport(supabase)) as upstream:
            app = create_app(settings, upstream)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                    response = await client.post(f"/api/applications/{APPLICATION_ID}/stop-followups",
                        headers={"Authorization": "Bearer user-session"}, json={"reason": "user_request"})
        self.assertEqual(response.status_code, 404)
        self.assertFalse(writes)

    async def test_grant_uses_atomic_server_rpc_with_verified_owner(self):
        writes = []

        def supabase(request):
            if request.url.path == "/auth/v1/user":
                return httpx.Response(200, json={"id": USER_ID})
            if request.method == "GET":
                self.assertEqual(request.headers["authorization"], "Bearer user-session")
                self.assertEqual(request.url.params["user_id"], f"eq.{USER_ID}")
                return httpx.Response(200, json=[{"id": CONNECTION_ID, "provider": "google", "status": "connected",
                    "scopes": ["https://www.googleapis.com/auth/gmail.send"]}])
            writes.append(request)
            self.assertEqual(request.url.path, "/rest/v1/rpc/grant_sending_consent")
            self.assertEqual(request.headers["authorization"], "Bearer server-secret")
            self.assertEqual(json.loads(request.content)["p_user_id"], USER_ID)
            return httpx.Response(200, json={"consent": {"id": "new-consent", "expires_at": "2026-11-01T00:00:00Z"},
                "search": {"id": SEARCH_ID, "auto_apply": True}})

        settings = Settings(supabase_url="https://test.supabase.co", supabase_anon_key="public",
            supabase_service_role_key="server-secret", authorized_feeds=[{"id": "partner", "authorized": True,
                "recipient_verification": "source_attestation"}])
        async with httpx.AsyncClient(transport=httpx.MockTransport(supabase)) as upstream:
            app = create_app(settings, upstream)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                    response = await client.post("/api/mail/consents", headers={"Authorization": "Bearer user-session"}, json={
                        "search_id": SEARCH_ID, "resume_id": RESUME_ID, "email_connection_id": CONNECTION_ID,
                        "allowed_sources": ["partner"], "expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
                        "acknowledgment": "Autorizo los envíos automáticos de esta búsqueda"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(writes), 1)
        self.assertTrue(response.json()["search"]["auto_apply"])
        self.assertNotIn("server-secret", response.text)

    async def test_list_is_scoped_by_rls_and_marks_active_expired_and_revoked(self):
        now = datetime.now(timezone.utc)
        rows = [{"id": "active", "expires_at": (now + timedelta(days=1)).isoformat(), "revoked_at": None},
            {"id": "expired", "expires_at": (now - timedelta(seconds=1)).isoformat(), "revoked_at": None},
            {"id": "revoked", "expires_at": (now + timedelta(days=1)).isoformat(), "revoked_at": now.isoformat()}]

        def supabase(request):
            if request.url.path == "/auth/v1/user":
                return httpx.Response(200, json={"id": USER_ID})
            self.assertEqual(request.url.path, "/rest/v1/sending_consents")
            self.assertEqual(request.headers["authorization"], "Bearer user-session")
            self.assertEqual(request.url.params["user_id"], f"eq.{USER_ID}")
            return httpx.Response(200, json=rows)

        async with httpx.AsyncClient(transport=httpx.MockTransport(supabase)) as upstream:
            app = create_app(Settings(supabase_url="https://test.supabase.co", supabase_anon_key="public"), upstream)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                    response = await client.get("/api/mail/consents", headers={"Authorization": "Bearer user-session"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["status"] for row in response.json()], ["active", "expired", "revoked"])

"""Offline worker integration: real feed parsing/MIME/token decryption, fake I/O.

The in-memory RPC contract complements the separate PostgreSQL security tests.
No OAuth account or external mail service is contacted by these tests.
"""
import base64
from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import BytesParser
import json
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet
from fastapi import HTTPException
import httpx

from app.config import Settings
from app.services.feeds import process_automatic_drafts
from app.worker import tick


class DailyDatabase:
    def __init__(self, client):
        self.client = client
        self.now = datetime.now(timezone.utc)
        self.settings = Settings(supabase_url="https://storage.example", supabase_service_role_key="test-service",
            token_encryption_key=Fernet.generate_key().decode(), mail_send_enabled=True,
            authorized_feeds=[{"id": "partner", "authorized": True,
                "recipient_verification": "source_attestation", "url": "https://feed.example/jobs"}])
        self.tables = {name: [] for name in ("job_searches", "sending_consents", "jobs", "job_search_matches", "applications", "recipient_suppressions",
            "profiles", "resume_versions", "email_connections")}
        self.secrets = {}
        self.completions = []
        for number in (1, 2):
            user = f"user-{number}"
            self.tables["profiles"].append({"user_id": user, "full_name": f"Persona {number}",
                "sending_timezone": "America/Argentina/Buenos_Aires"})
            self.tables["resume_versions"].append({"id": f"resume-{number}", "user_id": user,
                "mime_type": "application/pdf", "original_filename": f"cv-{number}.pdf",
                "object_path": f"{user}/cv-{number}.pdf"})
            self.tables["email_connections"].append({"id": f"connection-{number}", "user_id": user,
                "provider": "google", "email": f"persona{number}@example.com", "status": "connected",
                "scopes": ["https://www.googleapis.com/auth/gmail.send"]})
            token = {"access_token": f"token-{number}",
                "expires_at": (self.now + timedelta(days=7)).isoformat()}
            self.secrets[f"connection-{number}"] = Fernet(self.settings.token_encryption_key.encode()).encrypt(json.dumps(token).encode()).decode()
            self.tables["job_searches"].append({"id": f"search-{number}", "user_id": user,
                "status": "enabled", "roles": ["Chofer"], "cities": ["Neuquén"],
                "schedule_time": "09:00", "timezone": "America/Argentina/Buenos_Aires",
                "frequency": "daily", "weekdays": [], "preferred_resume_id": f"resume-{number}",
                "auto_apply": False, "consent_id": None,
                "next_run_at": (self.now - timedelta(minutes=1)).isoformat(), "claim_token": None})

    def headers(self, user):
        return {"Authorization": "Bearer test-service"}

    async def select(self, table, user=None, params=None):
        result = list(self.tables[table])
        for key, value in (params or {}).items():
            if key in ("select", "order", "offset", "limit"):
                continue
            if value.startswith("eq."):
                expected = value[3:]
                result = [row for row in result if str(row.get(key)).lower() == expected.lower()]
            elif value == "is.null":
                result = [row for row in result if row.get(key) is None]
            elif value == "not.is.null":
                result = [row for row in result if row.get(key) is not None]
            elif value.startswith("in.("):
                expected = set(value[4:-1].split(","))
                result = [row for row in result if str(row.get(key)) in expected]
        for order in reversed((params or {}).get("order", "").split(",")):
            if order:
                parts = order.split(".")
                result.sort(key=lambda row: str(row.get(parts[0]) or ""), reverse="desc" in parts[1:])
        offset = int((params or {}).get("offset", 0))
        limit = int((params or {}).get("limit", len(result)))
        return [row.copy() for row in result[offset:offset + limit]]

    async def owned(self, table, item_id, user, service=False):
        rows = await self.select(table, params={"id": f"eq.{item_id}", "user_id": f"eq.{user.id}"})
        if not rows:
            raise HTTPException(404, "Registro ajeno o inexistente")
        return rows[0]

    async def insert(self, table, data, user=None, conflict=None):
        if conflict:
            keys = conflict.split(",")
            if any(all(row.get(key) == data.get(key) for key in keys) for row in self.tables[table]):
                return []
        defaults = {"applications": {"parent_application_id": None, "delivery_sequence": 0},
            "jobs": {"is_active": True}, "job_search_matches": {"observed_at": self.now.isoformat()}}
        row = {"id": str(uuid4()), "created_at": self.now.isoformat(), "delivery_uncertain": False,
            **defaults.get(table, {}), **data}
        self.tables[table].append(row)
        return [row.copy()]

    async def patch(self, table, data, user=None, params=None):
        selected = await self.select(table, params=params)
        identifiers = {row["id"] for row in selected}
        result = []
        for row in self.tables[table]:
            if row["id"] in identifiers:
                row.update(data)
                result.append(row.copy())
        return result

    def match_for(self, application, run_id=None):
        if run_id is None:
            search = next(row for row in self.tables["job_searches"] if row["id"] == application["search_id"])
            run_id = search.get("run_id")
        rows = [row for row in self.tables["job_search_matches"] if row["job_id"] == application["job_id"]
            and row["search_id"] == application["search_id"] and row["user_id"] == application["user_id"]
            and (run_id is None or row["run_id"] == run_id)]
        return max(rows, key=lambda row: row["observed_at"]) if rows else None

    def consent_for(self, application, *, repeat=False):
        search = next(row for row in self.tables["job_searches"] if row["id"] == application["search_id"])
        consent = next((row for row in self.tables["sending_consents"] if row["id"] == search.get("consent_id")), None)
        job = next(row for row in self.tables["jobs"] if row["id"] == application["job_id"])
        if not (search["status"] == "enabled" and search["auto_apply"] and consent
                and not consent.get("revoked_at") and datetime.fromisoformat(consent["expires_at"]) > self.now
                and job["source"] in consent["authorized_sources"] and job.get("recipient_verified_at")
                and job.get("is_active", True) and job.get("source_authorized")
                and application.get("recipient_verified_at") and job["recipient_email"] == application["recipient_email"]):
            return None
        if repeat and not (consent.get("policy_version") == "v3" and consent.get("repeat_enabled")
                and consent.get("repeat_interval_days") == 3):
            return None
        return consent

    def can_reserve(self, application, *, followup=False):
        profile = next(row for row in self.tables["profiles"] if row["user_id"] == application["user_id"])
        zone = ZoneInfo(profile["sending_timezone"])
        local_day = self.now.astimezone(zone).date()
        owned = [row for row in self.tables["applications"] if row["user_id"] == application["user_id"]]
        today = [row for row in owned if row.get("send_attempt_started_at")
            and datetime.fromisoformat(row["send_attempt_started_at"]).astimezone(zone).date() == local_day]
        if len(today) >= 10:
            return False
        recipient = application["recipient_email"].strip().lower()
        if followup and any(row["user_id"] == application["user_id"] and row["recipient_email"] == recipient
                for row in self.tables["recipient_suppressions"]):
            return False
        for row in owned:
            if (row.get("recipient_email") or "").strip().lower() != recipient:
                continue
            confirmation = row.get("provider_confirmed_at")
            if row.get("send_attempt_id") and not confirmation and (row["status"] == "pending" or row.get("delivery_uncertain")):
                return False
            if confirmation and self.now - datetime.fromisoformat(confirmation) < timedelta(hours=72):
                return False
            if followup and row["status"] == "responded":
                return False
        return True

    async def rpc(self, name, payload, user=None):
        if name == "claim_due_searches":
            due = [row for row in self.tables["job_searches"] if row["status"] == "enabled"
                and not row.get("claim_token") and datetime.fromisoformat(row["next_run_at"]) <= self.now]
            if not due:
                return []
            row = due[0]
            row.update({"claim_token": str(uuid4()), "run_id": str(uuid4()),
                "lease_expires_at": (self.now + timedelta(hours=1)).isoformat()})
            return [row.copy()]
        if name == "assert_search_claim":
            return any(row["id"] == payload["p_search_id"] and row["claim_token"] == payload["p_claim_token"]
                for row in self.tables["job_searches"])
        if name == "complete_search_run":
            row = next(row for row in self.tables["job_searches"] if row["id"] == payload["p_search_id"])
            row.update({"next_run_at": payload["p_next_run_at"], "claim_token": None})
            self.completions.append(payload.copy())
            return True
        if name == "get_email_secret":
            connection = next(row for row in self.tables["email_connections"] if row["id"] == payload["p_connection_id"])
            if connection["user_id"] != payload["p_user_id"]:
                return None
            return {"encrypted_payload": self.secrets[connection["id"]]}
        if name == "create_initial_application":
            data = payload["p_application"]
            existing = next((row for row in self.tables["applications"] if row["user_id"] == data["user_id"]
                and row["job_id"] == data["job_id"] and not row.get("parent_application_id")), None)
            return existing.copy() if existing else (await self.insert("applications", data))[0]
        if name == "prepare_followup_application":
            root = next(row for row in self.tables["applications"] if row["id"] == payload["p_root_application_id"])
            search = next(row for row in self.tables["job_searches"] if row["id"] == payload["p_search_id"])
            consent = self.consent_for(root, repeat=True)
            match = self.match_for(root, payload["p_run_id"])
            family = [row for row in self.tables["applications"] if row["id"] == root["id"]
                or row.get("parent_application_id") == root["id"]]
            if not (root["user_id"] == payload["p_user_id"] and root["search_id"] == search["id"]
                    and search["claim_token"] == payload["p_claim_token"] and consent and match
                    and root["status"] == "sent" and root.get("provider_message_id") and root.get("provider_confirmed_at")
                    and all(row["status"] != "responded" for row in family) and self.can_reserve(root, followup=True)):
                return None
            confirmed = [row for row in family if row.get("provider_confirmed_at")]
            latest = max(confirmed, key=lambda row: row["provider_confirmed_at"])
            if self.now - datetime.fromisoformat(latest["provider_confirmed_at"]) < timedelta(hours=72):
                return None
            if datetime.fromisoformat(match["observed_at"]) < datetime.fromisoformat(latest["provider_confirmed_at"]):
                return None
            pending = next((row for row in family if row.get("parent_application_id") == root["id"]
                and not row.get("send_attempt_id") and row["status"] == "pending" and not row.get("delivery_uncertain")), None)
            if pending:
                pending.update({"job_match_id": match["id"], "resume_id": consent["resume_id"],
                    "email_connection_id": consent["email_connection_id"]})
                return pending.copy()
            child = {key: root[key] for key in ("user_id", "job_id", "search_id", "company", "job_title",
                "recipient_email", "recipient_verified_at", "subject", "body")}
            child.update({"parent_application_id": root["id"], "delivery_sequence": max(row.get("delivery_sequence", 0)
                for row in family) + 1, "job_match_id": match["id"], "sending_consent_id": consent["id"],
                "resume_id": consent["resume_id"], "email_connection_id": consent["email_connection_id"], "status": "pending"})
            return (await self.insert("applications", child))[0]
        if name in ("prepare_automatic_application", "claim_application_send"):
            row = next(row for row in self.tables["applications"] if row["id"] == payload["p_application_id"])
            manual = name == "claim_application_send" and payload.get("p_explicit_manual_consent")
            consent = self.consent_for(row, repeat=bool(row.get("parent_application_id")))
            match = self.match_for(row)
            if (row["user_id"] != payload["p_user_id"] or row.get("send_attempt_id") or row.get("delivery_uncertain")
                    or row["status"] not in ("pending", "error") or (not manual and (not consent or not match))):
                return None
            if name == "prepare_automatic_application":
                row.update({"resume_id": consent["resume_id"], "email_connection_id": consent["email_connection_id"],
                    "sending_consent_id": consent["id"], "job_match_id": match["id"]})
            else:
                if not self.can_reserve(row, followup=bool(row.get("parent_application_id"))):
                    return None
                if not manual and (row["resume_id"] != consent["resume_id"]
                        or row["email_connection_id"] != consent["email_connection_id"]):
                    return None
                connection = next(item for item in self.tables["email_connections"] if item["id"] == row["email_connection_id"])
                row.update({"send_attempt_id": str(uuid4()), "send_attempt_started_at": self.now.isoformat(),
                    "sender_email": connection["email"], "manual_approved_at": self.now.isoformat() if manual else None})
            return row.copy()
        if name == "stop_recipient_followups":
            application = next((row for row in self.tables["applications"] if row["id"] == payload["p_application_id"]
                and row["user_id"] == payload["p_user_id"]), None)
            if not application:
                return None
            reason = payload.get("p_reason", "user_request")
            if reason == "responded":
                if application["status"] not in ("sent", "responded") or not application.get("provider_confirmed_at"):
                    raise HTTPException(409, "La entrega no está confirmada")
                application["status"] = "responded"
            recipient = application["recipient_email"].strip().lower()
            existing = next((row for row in self.tables["recipient_suppressions"]
                if row["user_id"] == application["user_id"] and row["recipient_email"] == recipient), None)
            if existing:
                if existing["reason"] != "responded": existing["reason"] = reason
                return existing.copy()
            return (await self.insert("recipient_suppressions", {"user_id": application["user_id"],
                "recipient_email": recipient, "stopped_at": self.now.isoformat(), "reason": reason}))[0]
        raise AssertionError(name)

    def grant(self, number, *, repeat=False, search=None):
        search = search or self.tables["job_searches"][number - 1]
        consent = {"id": f"consent-{number}-{len(self.tables['sending_consents'])}", "user_id": f"user-{number}", "search_id": search["id"],
            "resume_id": f"resume-{number}", "email_connection_id": f"connection-{number}",
            "authorized_sources": ["partner"], "expires_at": (self.now + timedelta(days=30)).isoformat(),
            "daily_limit": 10, "policy_version": "v3" if repeat else "v2", "repeat_enabled": repeat,
            "repeat_interval_days": 3, "authorization_text": (
                "Autorizo los envíos automáticos de esta búsqueda y los recordatorios cada 3 días, con un máximo total de 10 correos por día"
                if repeat else "Autorizo los envíos automáticos de esta búsqueda")}
        self.tables["sending_consents"].append(consent)
        search.update({"consent_id": consent["id"], "auto_apply": True})
        return consent

    def next_day(self):
        self.now = max(datetime.fromisoformat(row["next_run_at"]) for row in self.tables["job_searches"])


class DailyAutomationTests(unittest.IsolatedAsyncioTestCase):
    def provider(self, sent, *, verified=True, receipt=True):
        def handle(request):
            if request.url.host == "feed.example":
                return httpx.Response(200, json={"jobs": [{"id": "vacancy-1", "company": "Empresa",
                    "title": "Chofer", "city": "Neuquén", "recipient_email": "rrhh@empresa.example",
                    "recipient_verified": verified}]})
            if request.url.host == "storage.example":
                return httpx.Response(200, content=f"CV privado {request.url.path.split('/')[-2]}".encode())
            if request.url.host == "gmail.googleapis.com":
                payload = json.loads(request.content)
                sent.append((request.headers["authorization"], BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(payload["raw"]))))
                return httpx.Response(200, json={"id": f"receipt-{len(sent)}"} if receipt else {})
            raise AssertionError(f"Solicitud inesperada: {request.url.host}")
        return handle

    async def run_worker(self, db):
        class FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return db.now.astimezone(tz) if tz else db.now.replace(tzinfo=None)
        with patch("app.services.feeds.safe_feed_url", AsyncMock()), \
             patch("app.services.feeds.datetime", FrozenDatetime), \
             patch("app.services.mail.datetime", FrozenDatetime), \
             patch("app.services.schedule.datetime", FrozenDatetime):
            return await tick(db, "offline-test-worker")

    async def test_preexisting_pending_drafts_send_daily_from_each_own_account_without_duplicates(self):
        sent = []
        async with httpx.AsyncClient(transport=httpx.MockTransport(self.provider(sent))) as client:
            db = DailyDatabase(client)
            self.assertEqual(await self.run_worker(db), 2)
            self.assertFalse(sent)
            self.assertEqual(len(db.tables["applications"]), 2)
            # Both drafts existed before either user's initial authorization.
            for application in db.tables["applications"]:
                application["email_connection_id"] = None
            db.grant(1)
            db.grant(2)
            db.next_day()
            self.assertEqual(await self.run_worker(db), 2)
            self.assertEqual(len(sent), 2)
            for number, (authorization, message) in enumerate(sent, start=1):
                self.assertEqual(authorization, f"Bearer token-{number}")
                self.assertEqual(message["From"], f"persona{number}@example.com")
                self.assertEqual(message["To"], "rrhh@empresa.example")
                self.assertEqual(next(message.iter_attachments()).get_payload(decode=True), f"CV privado user-{number}".encode())
            db.next_day()
            self.assertEqual(await self.run_worker(db), 2)
            self.assertEqual(len(sent), 2)
            self.assertTrue(all(row["status"] == "sent" and row["provider_message_id"] for row in db.tables["applications"]))
            self.assertEqual(len(db.tables["jobs"]), 2)

    async def test_revoked_and_expired_consents_leave_drafts_unattempted(self):
        sent = []
        async with httpx.AsyncClient(transport=httpx.MockTransport(self.provider(sent))) as client:
            db = DailyDatabase(client)
            db.grant(1)["revoked_at"] = db.now.isoformat()
            db.grant(2)["expires_at"] = (db.now - timedelta(seconds=1)).isoformat()
            await self.run_worker(db)
            self.assertFalse(sent)
            self.assertTrue(all(row["status"] == "pending" and not row.get("send_attempt_id") for row in db.tables["applications"]))

    async def test_unverified_recipients_stay_for_manual_review(self):
        sent = []
        async with httpx.AsyncClient(transport=httpx.MockTransport(self.provider(sent, verified=False))) as client:
            db = DailyDatabase(client)
            db.grant(1)
            db.grant(2)
            await self.run_worker(db)
            self.assertFalse(sent)
            self.assertEqual(len(db.tables["applications"]), 2)
            self.assertTrue(all(not row.get("send_attempt_id") for row in db.tables["applications"]))

    async def test_missing_provider_receipt_is_error_and_is_never_retried_next_day(self):
        sent = []
        async with httpx.AsyncClient(transport=httpx.MockTransport(self.provider(sent, receipt=False))) as client:
            db = DailyDatabase(client)
            db.grant(1)
            db.grant(2)
            await self.run_worker(db)
            db.next_day()
            await self.run_worker(db)
            self.assertEqual(len(sent), 2)
            self.assertTrue(all(row["status"] == "error" and row["delivery_uncertain"] and not row.get("provider_message_id") for row in db.tables["applications"]))

    async def test_paused_search_is_not_claimed(self):
        sent = []
        async with httpx.AsyncClient(transport=httpx.MockTransport(self.provider(sent))) as client:
            db = DailyDatabase(client)
            db.grant(1)
            db.grant(2)
            db.tables["job_searches"][0]["status"] = "paused"
            self.assertEqual(await self.run_worker(db), 1)
            self.assertEqual(len(sent), 1)
            self.assertEqual(sent[0][1]["From"], "persona2@example.com")

    async def test_ineligible_old_drafts_do_not_starve_newer_valid_drafts_across_pages(self):
        sent = []
        async with httpx.AsyncClient(transport=httpx.MockTransport(self.provider(sent))) as client:
            db = DailyDatabase(client)
            db.grant(1)
            search = db.tables["job_searches"][0]
            search["claim_token"] = "queue-claim"
            search["run_id"] = "queue-run"
            for index in range(7):
                recipient = f"rrhh{index}@empresa.example"
                job = (await db.insert("jobs", {"user_id": "user-1", "source": "removed-source" if index < 5 else "partner",
                    "source_authorized": True, "recipient_verified_at": db.now.isoformat(),
                    "recipient_email": recipient}))[0]
                await db.insert("job_search_matches", {"user_id": "user-1", "job_id": job["id"],
                    "search_id": search["id"], "run_id": search["run_id"], "roles_snapshot": search["roles"],
                    "cities_snapshot": search["cities"]})
                await db.insert("applications", {"user_id": "user-1", "search_id": search["id"],
                    "job_id": job["id"], "resume_id": "resume-1", "email_connection_id": None,
                    "recipient_verified_at": db.now.isoformat(), "recipient_email": recipient,
                    "status": "pending", "subject": "Postulación", "body": "Adjunto mi CV"})
            from app.db import User
            with patch("app.services.feeds.PAGE_SIZE", 2):
                count, errors = await process_automatic_drafts(db, search, User("user-1", ""))
            self.assertEqual((count, errors), (2, 0))
            self.assertEqual(len(sent), 2)
            self.assertEqual(sum(row["status"] == "pending" for row in db.tables["applications"]), 5)

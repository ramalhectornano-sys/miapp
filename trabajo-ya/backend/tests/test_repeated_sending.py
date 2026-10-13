"""Offline feed -> worker -> MIME -> Gmail receipt integration regressions.

The fake RPCs model the safety contract; PostgreSQL tests exercise actual locks
and permissions separately. No external network or real message is used.
"""
import base64
from copy import deepcopy
from datetime import timedelta
from email import policy
from email.parser import BytesParser
import json
import unittest
from unittest.mock import patch

import httpx
from fastapi import HTTPException

from app.db import User
from app.services.mail import send_application
import test_daily_automation as daily

DailyDatabase = daily.DailyDatabase


def vacancy(number, *, city="Neuquén", recipient=None, **fields):
    return {"id": f"vacancy-{number}", "company": f"Empresa {number}", "title": "Chofer",
        "city": city, "recipient_email": recipient or f"rrhh{number}@empresa.example",
        "recipient_verified": True, **fields}


class OfflineProvider:
    def __init__(self, jobs, *, receipt=True):
        self.jobs = jobs
        self.receipt = receipt
        self.sent = []

    def __call__(self, request):
        if request.url.host == "feed.example":
            return httpx.Response(200, json={"jobs": self.jobs})
        if request.url.host == "storage.example":
            return httpx.Response(200, content=f"CV privado {request.url.path.split('/')[-1]}".encode())
        if request.url.host == "gmail.googleapis.com":
            message = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(json.loads(request.content)["raw"]))
            self.sent.append((request.headers["authorization"], message))
            return httpx.Response(200, json={"id": f"receipt-{len(self.sent)}"} if self.receipt else {})
        raise AssertionError(f"Unexpected offline request: {request.url}")


class RepeatedSendingTests(unittest.IsolatedAsyncioTestCase):
    run_worker = daily.DailyAutomationTests.run_worker

    def only_first_user(self, db, *, repeat=True):
        db.tables["job_searches"][1]["status"] = "paused"
        return db.grant(1, repeat=repeat)

    def due_now(self, db, elapsed):
        db.now += elapsed
        for search in db.tables["job_searches"]:
            search["next_run_at"] = db.now.isoformat()

    async def test_ten_daily_reservations_across_searches_for_one_user(self):
        provider = OfflineProvider([vacancy(i, city="Neuquén" if i <= 8 else "Centenario") for i in range(1, 17)])
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            db = DailyDatabase(client)
            self.only_first_user(db)
            other = {**db.tables["job_searches"][0], "id": "search-extra", "cities": ["Centenario"]}
            db.tables["job_searches"].append(other)
            db.grant(1, repeat=True, search=other)
            self.assertEqual(await self.run_worker(db), 2)
            self.assertEqual(len(provider.sent), 10)
            self.assertEqual(len([row for row in db.tables["applications"] if row.get("send_attempt_id")]), 10)
            self.assertEqual(len([row for row in db.tables["applications"] if row["status"] == "pending"]), 6)
            self.due_now(db, timedelta(days=1))
            await self.run_worker(db)
            self.assertEqual(len(provider.sent), 16)
            self.assertTrue(all(row["status"] == "sent" for row in db.tables["applications"]))

    async def test_daily_cap_is_independent_for_each_user(self):
        provider = OfflineProvider([vacancy(i) for i in range(12)])
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            db = DailyDatabase(client)
            db.grant(1, repeat=True)
            db.grant(2, repeat=True)
            await self.run_worker(db)
            self.assertEqual(len(provider.sent), 20)
            for number in (1, 2):
                owned = [row for row in db.tables["applications"] if row["user_id"] == f"user-{number}"]
                self.assertEqual(sum(bool(row.get("send_attempt_id")) for row in owned), 10)
                messages = [message for _, message in provider.sent if message["From"] == f"persona{number}@example.com"]
                self.assertEqual(len(messages), 10)

    async def test_followup_waits_exactly_72_hours_and_keeps_original_history(self):
        provider = OfflineProvider([vacancy(1)])
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            db = DailyDatabase(client)
            self.only_first_user(db)
            await self.run_worker(db)
            original = deepcopy(db.tables["applications"][0])
            self.due_now(db, timedelta(hours=72, seconds=-1))
            await self.run_worker(db)
            self.assertEqual(len(provider.sent), 1)
            self.assertEqual(len(db.tables["applications"]), 1)
            self.due_now(db, timedelta(seconds=1))
            await self.run_worker(db)
            self.assertEqual(len(provider.sent), 2)
            self.assertEqual(db.tables["applications"][0], original)
            child = db.tables["applications"][1]
            self.assertEqual(child["parent_application_id"], original["id"])
            self.assertEqual(child["delivery_sequence"], 1)
            self.assertEqual(child["status"], "sent")
            self.assertNotEqual(child["provider_message_id"], original["provider_message_id"])
            self.assertEqual(child["sender_email"], "persona1@example.com")
            self.assertEqual(child["body"], original["body"])
            self.assertEqual(next(provider.sent[1][1].iter_attachments()).get_filename(), "cv-1.pdf")
            self.due_now(db, timedelta(hours=72))
            await self.run_worker(db)
            self.assertEqual(len(provider.sent), 3)
            self.assertEqual(db.tables["applications"][2]["parent_application_id"], original["id"])
            self.assertEqual(db.tables["applications"][2]["delivery_sequence"], 2)
            self.assertEqual(db.tables["applications"][0], original)

    async def test_current_cv_selected_without_mutating_sent_original(self):
        provider = OfflineProvider([vacancy(1)])
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            db = DailyDatabase(client)
            consent = self.only_first_user(db)
            await self.run_worker(db)
            original = deepcopy(db.tables["applications"][0])
            await db.insert("resume_versions", {"id": "resume-new", "user_id": "user-1", "mime_type": "application/pdf",
                "original_filename": "cv-actualizado.pdf", "object_path": "user-1/cv-actualizado.pdf"})
            consent["resume_id"] = "resume-new"
            db.tables["job_searches"][0]["preferred_resume_id"] = "resume-new"
            self.due_now(db, timedelta(hours=72))
            await self.run_worker(db)
            self.assertEqual(len(provider.sent), 2)
            self.assertEqual(db.tables["applications"][0], original)
            self.assertEqual(db.tables["applications"][1]["resume_id"], "resume-new")
            self.assertEqual(next(provider.sent[1][1].iter_attachments()).get_filename(), "cv-actualizado.pdf")

    async def test_new_vacancies_have_priority_over_due_followups(self):
        provider = OfflineProvider([vacancy(1)])
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            db = DailyDatabase(client)
            self.only_first_user(db)
            await self.run_worker(db)
            self.due_now(db, timedelta(hours=72))
            provider.jobs = [vacancy(i) for i in range(1, 14)]
            await self.run_worker(db)
            self.assertEqual(len(provider.sent), 11)
            self.assertTrue(all(message["To"] != "rrhh1@empresa.example" for _, message in provider.sent[1:]))
            self.assertFalse(any(row.get("parent_application_id") for row in db.tables["applications"]))

    async def test_refresh_bound_prioritizes_oldest_actual_delivery_despite_feed_order(self):
        provider = OfflineProvider([vacancy(1), vacancy(2), vacancy(3)])
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            db = DailyDatabase(client)
            self.only_first_user(db)
            await self.run_worker(db)
            self.assertEqual(len(provider.sent), 3)
            # These two companies receive real, separately confirmed reminders.
            # Company 3's initial delivery is now the oldest actual receipt.
            self.due_now(db, timedelta(hours=72))
            provider.jobs = [vacancy(1), vacancy(2)]
            await self.run_worker(db)
            self.assertEqual(len(provider.sent), 5)
            self.due_now(db, timedelta(seconds=1))
            provider.jobs = [vacancy(1), vacancy(2), vacancy(3)]
            with patch("app.services.feeds.MAX_JOBS_PER_RUN", 1):
                await self.run_worker(db)
            self.assertEqual(len(provider.sent), 6)
            self.assertEqual(provider.sent[-1][1]["To"], "rrhh3@empresa.example")
            self.assertEqual(sum(message["To"] == "rrhh1@empresa.example" for _, message in provider.sent), 2)
            self.assertEqual(sum(message["To"] == "rrhh2@empresa.example" for _, message in provider.sent), 2)

    async def test_lost_claim_before_followup_send_preserves_unattempted_child_for_next_run(self):
        class LostFollowupClaim(DailyDatabase):
            invalidate_after_followup = False
            claim_lost = False

            async def rpc(self, name, payload, user=None):
                if name == "assert_search_claim" and self.claim_lost:
                    return False
                result = await super().rpc(name, payload, user)
                if name == "prepare_followup_application" and result and self.invalidate_after_followup:
                    self.claim_lost = True
                return result

        provider = OfflineProvider([vacancy(1)])
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            db = LostFollowupClaim(client)
            self.only_first_user(db)
            await self.run_worker(db)
            db.invalidate_after_followup = True
            self.due_now(db, timedelta(hours=72))
            await self.run_worker(db)
            self.assertEqual(len(provider.sent), 1)
            self.assertEqual(db.completions[-1]["p_status"], "error")
            self.assertEqual(len(db.tables["applications"]), 2)
            child = db.tables["applications"][1]
            self.assertEqual(child["status"], "pending")
            self.assertIsNone(child.get("send_attempt_id"))
            db.invalidate_after_followup = False
            db.claim_lost = False
            self.due_now(db, timedelta(days=1))
            await self.run_worker(db)
            self.assertEqual(len(provider.sent), 2)
            self.assertEqual(len(db.tables["applications"]), 2)
            self.assertEqual(child["status"], "sent")

    async def test_omitted_closed_inactive_or_mismatched_vacancy_has_no_followup(self):
        for feed in ([], [vacancy(1, status="closed")], [vacancy(1, is_active=False)], [vacancy(1, city="Otra ciudad")]):
            with self.subTest(feed=feed):
                provider = OfflineProvider([vacancy(1)])
                async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
                    db = DailyDatabase(client)
                    self.only_first_user(db)
                    await self.run_worker(db)
                    self.due_now(db, timedelta(hours=72))
                    provider.jobs = feed
                    await self.run_worker(db)
                    self.assertEqual(len(provider.sent), 1)
                    self.assertEqual(len(db.tables["applications"]), 1)

    async def test_pending_draft_requires_fresh_observation_after_authorization(self):
        provider = OfflineProvider([vacancy(1)])
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            db = DailyDatabase(client)
            db.tables["job_searches"][1]["status"] = "paused"
            await self.run_worker(db)
            self.assertFalse(provider.sent)
            self.only_first_user(db)
            self.due_now(db, timedelta(days=1))
            provider.jobs = []
            await self.run_worker(db)
            self.assertFalse(provider.sent)
            self.assertIsNone(db.tables["applications"][0].get("send_attempt_id"))
            self.due_now(db, timedelta(days=1))
            provider.jobs = [vacancy(1)]
            await self.run_worker(db)
            self.assertEqual(len(provider.sent), 1)

    async def test_repeat_requires_new_explicit_consent_and_active_authorization(self):
        for restriction in ("legacy", "expired", "revoked", "paused", "responded"):
            with self.subTest(restriction=restriction):
                provider = OfflineProvider([vacancy(1)])
                async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
                    db = DailyDatabase(client)
                    consent = self.only_first_user(db, repeat=restriction != "legacy")
                    await self.run_worker(db)
                    self.assertEqual(len(provider.sent), 1)
                    self.due_now(db, timedelta(hours=72))
                    if restriction == "expired": consent["expires_at"] = db.now.isoformat()
                    if restriction == "revoked": consent["revoked_at"] = db.now.isoformat()
                    if restriction == "paused": db.tables["job_searches"][0]["status"] = "paused"
                    if restriction == "responded": db.tables["applications"][0]["status"] = "responded"
                    await self.run_worker(db)
                    self.assertEqual(len(provider.sent), 1)
                    self.assertEqual(len(db.tables["applications"]), 1)

    async def test_canonical_recipient_cooldown_applies_to_distinct_vacancies(self):
        provider = OfflineProvider([vacancy(1, recipient="RRHH@Empresa.example"), vacancy(2, recipient="rrhh@empresa.example")])
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            db = DailyDatabase(client)
            self.only_first_user(db, repeat=False)
            await self.run_worker(db)
            self.assertEqual(len(provider.sent), 1)
            self.due_now(db, timedelta(hours=72, seconds=-1))
            await self.run_worker(db)
            self.assertEqual(len(provider.sent), 1)
            self.due_now(db, timedelta(seconds=1))
            await self.run_worker(db)
            self.assertEqual(len(provider.sent), 2)

    async def test_unconfirmed_reserved_recipient_is_never_retried_as_another_vacancy(self):
        provider = OfflineProvider([vacancy(1, recipient="rrhh@empresa.example")], receipt=False)
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            db = DailyDatabase(client)
            self.only_first_user(db)
            await self.run_worker(db)
            uncertain = deepcopy(db.tables["applications"][0])
            self.due_now(db, timedelta(days=10))
            provider.receipt = True
            provider.jobs = [vacancy(1, recipient="rrhh@empresa.example"), vacancy(2, recipient="RRHH@Empresa.example")]
            await self.run_worker(db)
            self.assertEqual(len(provider.sent), 1)
            self.assertEqual(db.tables["applications"][0], uncertain)
            self.assertTrue(uncertain["delivery_uncertain"])
            self.assertFalse(any(row.get("parent_application_id") for row in db.tables["applications"]))

    async def test_stopping_recipient_reminders_keeps_history_and_other_user_active(self):
        for reason in ("user_request", "responded"):
            with self.subTest(reason=reason):
                provider = OfflineProvider([vacancy(1)])
                async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
                    db = DailyDatabase(client)
                    db.grant(1, repeat=True)
                    db.grant(2, repeat=True)
                    await self.run_worker(db)
                    original = next(row for row in db.tables["applications"] if row["user_id"] == "user-1")
                    history = deepcopy(original)
                    await db.rpc("stop_recipient_followups", {"p_application_id": original["id"],
                        "p_user_id": "user-1", "p_reason": reason})
                    self.due_now(db, timedelta(hours=72))
                    await self.run_worker(db)
                    self.assertEqual(len([message for _, message in provider.sent if message["From"] == "persona1@example.com"]), 1)
                    self.assertEqual(len([message for _, message in provider.sent if message["From"] == "persona2@example.com"]), 2)
                    self.assertEqual(original["provider_message_id"], history["provider_message_id"])
                    self.assertEqual(original["body"], history["body"])
                    self.assertEqual(original["resume_id"], history["resume_id"])
                    self.assertEqual(db.tables["recipient_suppressions"][0]["recipient_email"], "rrhh1@empresa.example")
                    # The stop applies to reminders; a newly verified, distinct
                    # vacancy may still receive its first application after 72h.
                    self.due_now(db, timedelta(days=1))
                    provider.jobs = [vacancy(1), vacancy(2, recipient="rrhh1@empresa.example")]
                    await self.run_worker(db)
                    self.assertEqual(len([message for _, message in provider.sent if message["From"] == "persona1@example.com"]), 2)

    async def test_manual_reservation_consumes_same_global_daily_budget(self):
        provider = OfflineProvider([vacancy(i) for i in range(1, 12)])
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            db = DailyDatabase(client)
            self.only_first_user(db)
            manual_job = (await db.insert("jobs", {"user_id": "user-1", "source": "partner", "source_authorized": True,
                "recipient_verified_at": db.now.isoformat(), "recipient_email": "manual@empresa.example", "fingerprint": "manual"}))[0]
            manual_app = (await db.insert("applications", {"user_id": "user-1", "job_id": manual_job["id"], "search_id": "search-1",
                "resume_id": "resume-1", "email_connection_id": "connection-1", "recipient_email": "manual@empresa.example",
                "recipient_verified_at": db.now.isoformat(), "subject": "Postulación manual", "body": "Mi CV", "status": "pending"}))[0]
            await send_application(db, User("user-1", ""), manual_app["id"], manual=True, acknowledgment="Enviar esta postulación")
            await self.run_worker(db)
            self.assertEqual(len(provider.sent), 10)
            pending = next(row for row in db.tables["applications"] if row["status"] == "pending")
            with self.assertRaises(HTTPException) as rejected:
                await send_application(db, User("user-1", ""), pending["id"], manual=True, acknowledgment="Enviar esta postulación")
            self.assertEqual(rejected.exception.status_code, 409)
            self.assertEqual(len(provider.sent), 10)


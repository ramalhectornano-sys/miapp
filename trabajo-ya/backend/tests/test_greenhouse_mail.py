"""Publisher evidence must be refreshed at the real Gmail send boundary."""
import unittest
from unittest.mock import patch

import httpx
from fastapi import HTTPException

from app.config import Settings
from app.db import User
from app.services.mail import send_application
from test_mail_snapshot import SnapshotDatabase, USER_ID


class PublisherDatabase(SnapshotDatabase):
    def __init__(self, client, *, source_enabled=True):
        super().__init__(client)
        self.settings = Settings(mail_send_enabled=True,
            web_search_provider="tavily" if source_enabled else "",
            web_search_api_key="test-private-key" if source_enabled else "")
        self.application.update({"company": "Empresa", "job_title": "Chofer", "search_id": "search"})

    async def owned(self, table, item_id, user, service=False):
        if table == "job_searches":
            return {"id": item_id, "user_id": user.id, "research_mode": "legacy"}
        row = await super().owned(table, item_id, user, service=service)
        if table == "jobs":
            row.update({"source": "verified:greenhouse", "title": "Chofer", "company": "Empresa",
                "city": "Neuquén", "payload": {"greenhouse": {"board": "empresa", "job_id": 123}}})
        return row


class GreenhouseMailTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, validator, *, source_enabled=True, manual=True):
        events = []

        def gmail(request):
            self.assertEqual(request.url.host, "gmail.googleapis.com")
            events.append("gmail")
            return httpx.Response(200, json={"id": "confirmed"})

        async def download(*args, **kwargs):
            events.append("cv")
            return b"pdf"

        async def token(*args, **kwargs):
            events.append("oauth")
            return "test-token"

        async def revalidate(client, job):
            events.append("publisher")
            self.assertEqual(job["source"], "verified:greenhouse")
            if validator:
                raise validator

        async with httpx.AsyncClient(transport=httpx.MockTransport(gmail)) as client:
            db = PublisherDatabase(client, source_enabled=source_enabled)
            with patch("app.services.mail.download_resume", download), \
                    patch("app.services.mail.access_token", token), \
                    patch("app.services.greenhouse.revalidate_job", revalidate):
                if validator or not source_enabled:
                    with self.assertRaises(HTTPException):
                        await send_application(db, User(USER_ID, "jwt"), "app", manual=manual,
                            acknowledgment="Enviar esta postulación" if manual else None)
                    self.assertEqual(db.application["status"], "error")
                    self.assertFalse(db.application["delivery_uncertain"])
                    self.assertNotIn("provider_message_id", db.application)
                    with self.assertRaises(HTTPException):
                        await send_application(db, User(USER_ID, "jwt"), "app", manual=manual,
                            acknowledgment="Enviar esta postulación" if manual else None)
                    self.assertEqual(db.claims, 1)
                else:
                    result = await send_application(db, User(USER_ID, "jwt"), "app", manual=manual,
                        acknowledgment="Enviar esta postulación" if manual else None)
                    self.assertEqual(result["status"], "sent")
                    self.assertEqual(result["provider_message_id"], "confirmed")
        return events

    async def test_refresh_happens_after_cv_and_token_and_before_gmail(self):
        self.assertEqual(await self.exercise(None), ["cv", "oauth", "publisher", "gmail"])

    async def test_automatic_delivery_uses_the_same_publisher_barrier(self):
        self.assertEqual(await self.exercise(None, manual=False), ["cv", "oauth", "publisher", "gmail"])

    async def test_withdrawn_email_cannot_be_sent_or_automatically_retried(self):
        self.assertEqual(await self.exercise(HTTPException(409, "Correo retirado")), ["cv", "oauth", "publisher"])

    async def test_provider_failure_does_not_contact_gmail(self):
        self.assertEqual(await self.exercise(HTTPException(502, "API no disponible")), ["cv", "oauth", "publisher"])

    async def test_removing_source_configuration_also_blocks_old_manual_drafts(self):
        self.assertEqual(await self.exercise(None, source_enabled=False), ["cv", "oauth"])

    async def test_changed_employer_cannot_receive_a_message_prepared_for_the_old_one(self):
        requests = []
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:
                requests.append(request) or httpx.Response(200, json={"id": "must-not-send"}))) as client:
            db = PublisherDatabase(client)
            db.application["company"] = "Empresa anterior"
            with self.assertRaises(HTTPException):
                await send_application(db, User(USER_ID, "jwt"), "app", manual=False)
        self.assertFalse(requests)
        self.assertEqual(db.application["status"], "error")
        self.assertFalse(db.application["delivery_uncertain"])

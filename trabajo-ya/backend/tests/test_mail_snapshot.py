"""Regression tests for the draft-edit race at the mail reservation boundary."""
import asyncio
import base64
from email import policy
from email.parser import BytesParser
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException

from app.config import Settings
from app.db import User
from app.services.mail import send_application


USER_ID = "11111111-1111-4111-8111-111111111111"


class SnapshotDatabase:
    def __init__(self, client):
        self.client = client
        self.settings = Settings(mail_send_enabled=True)
        self.application = {
            "id": "app", "user_id": USER_ID, "job_id": "job", "status": "pending",
            "resume_id": "old-resume", "email_connection_id": "old-connection",
            "recipient_email": "jobs@company.example", "subject": "Asunto anterior",
            "body": "Mensaje anterior",
        }
        self.claims = 0
        self.lookups = []
        self.updates = []

    async def owned(self, table, item_id, user, service=False):
        self.lookups.append((table, item_id))
        if table == "applications":
            return self.application.copy()
        if table == "jobs":
            return {"recipient_email": "jobs@company.example", "source_authorized": True,
                "recipient_verified_at": "2026-10-12T00:00:00Z"}
        if table == "email_connections":
            return {"id": item_id, "provider": "google", "status": "connected",
                "email": "current@example.com" if item_id == "new-connection" else "old@example.com"}
        if table == "resume_versions":
            return {"id": item_id, "mime_type": "application/pdf",
                "original_filename": "actual.pdf" if item_id == "new-resume" else "anterior.pdf"}
        raise AssertionError(table)

    async def rpc(self, name, payload, user=None):
        if name != "claim_application_send":
            raise AssertionError(name)
        self.claims += 1
        # Another request completed its draft PATCH after the first read and
        # before the atomic reservation locked the application's latest row.
        self.application.update({"resume_id": "new-resume", "email_connection_id": "new-connection",
            "subject": "Asunto actual", "body": "Mensaje actual", "send_attempt_id": "attempt"})
        return self.application.copy()

    async def patch(self, table, data, user=None, params=None):
        self.updates.append((data, params))
        self.application.update(data)
        return [self.application.copy()]


class MailSnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_gmail_receives_only_the_atomically_reserved_draft(self):
        requests = []

        def provider(request):
            requests.append(request)
            return httpx.Response(200, json={"id": "gmail-confirmed"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            db = SnapshotDatabase(client)

            async def download(_db, _user, resume, service=False):
                self.assertEqual(db.application["send_attempt_id"], "attempt")
                self.assertEqual(resume["id"], "new-resume")
                return b"CURRENT-CV"

            async def token(_db, connection, _user_id):
                self.assertEqual(connection["id"], "new-connection")
                return "current-token"

            with patch("app.services.mail.download_resume", download), patch("app.services.mail.access_token", token):
                result = await send_application(db, User(USER_ID, "jwt"), "app", manual=True,
                    acknowledgment="Enviar esta postulación")

        import json
        payload = json.loads(requests[0].content)
        message = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(payload["raw"]))
        self.assertEqual(requests[0].headers["authorization"], "Bearer current-token")
        self.assertEqual(message["From"], "current@example.com")
        self.assertEqual(message["Subject"], "Asunto actual")
        self.assertEqual(message.get_body(preferencelist=("plain",)).get_content().strip(), "Mensaje actual")
        attachment = next(message.iter_attachments())
        self.assertEqual(attachment.get_filename(), "actual.pdf")
        self.assertEqual(attachment.get_payload(decode=True), b"CURRENT-CV")
        self.assertEqual(result["resume_id"], "new-resume")
        self.assertEqual(result["status"], "sent")
        self.assertNotIn(("resume_versions", "old-resume"), db.lookups)

    async def test_preparation_failure_is_recorded_without_sending_or_retrying(self):
        requests = []

        def provider(request):
            requests.append(request)
            return httpx.Response(200, json={"id": "should-never-send"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            db = SnapshotDatabase(client)
            failed_download = AsyncMock(side_effect=HTTPException(502, "Archivo no disponible"))
            with patch("app.services.mail.download_resume", failed_download):
                with self.assertRaises(HTTPException):
                    await send_application(db, User(USER_ID, "jwt"), "app", manual=True,
                        acknowledgment="Enviar esta postulación")
                with self.assertRaises(HTTPException) as retry:
                    await send_application(db, User(USER_ID, "jwt"), "app", manual=True,
                        acknowledgment="Enviar esta postulación")

        self.assertEqual(retry.exception.status_code, 409)
        self.assertFalse(requests)
        self.assertEqual(db.claims, 1)
        self.assertEqual(db.application["status"], "error")
        self.assertFalse(db.application["delivery_uncertain"])
        self.assertIn("No se contactó", db.application["error"])
        self.assertEqual(db.updates[0][1]["send_attempt_id"], "eq.attempt")

    async def test_cancellation_while_waiting_for_gmail_records_uncertain_delivery(self):
        contacted = asyncio.Event()
        requests = []

        async def provider(request):
            requests.append(request)
            contacted.set()
            await asyncio.Event().wait()

        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            db = SnapshotDatabase(client)
            with patch("app.services.mail.download_resume", AsyncMock(return_value=b"pdf")), \
                 patch("app.services.mail.access_token", AsyncMock(return_value="token")):
                task = asyncio.create_task(send_application(db, User(USER_ID, "jwt"), "app", manual=True,
                    acknowledgment="Enviar esta postulación"))
                await contacted.wait()
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                with self.assertRaises(HTTPException) as retry:
                    await send_application(db, User(USER_ID, "jwt"), "app", manual=True,
                        acknowledgment="Enviar esta postulación")

        self.assertEqual(retry.exception.status_code, 409)
        self.assertEqual(len(requests), 1)
        self.assertEqual(db.claims, 1)
        self.assertEqual(db.application["status"], "error")
        self.assertTrue(db.application["delivery_uncertain"])
        self.assertNotIn("provider_message_id", db.application)
        self.assertEqual(db.updates[0][1]["send_attempt_id"], "eq.attempt")

    async def test_cancellation_during_preparation_records_no_provider_contact(self):
        preparing = asyncio.Event()
        requests = []

        def provider(request):
            requests.append(request)
            return httpx.Response(200, json={"id": "should-never-send"})

        async def download(*args, **kwargs):
            preparing.set()
            await asyncio.Event().wait()

        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            db = SnapshotDatabase(client)
            with patch("app.services.mail.download_resume", download):
                task = asyncio.create_task(send_application(db, User(USER_ID, "jwt"), "app", manual=True,
                    acknowledgment="Enviar esta postulación"))
                await preparing.wait()
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                with self.assertRaises(HTTPException):
                    await send_application(db, User(USER_ID, "jwt"), "app", manual=True,
                        acknowledgment="Enviar esta postulación")

        self.assertFalse(requests)
        self.assertEqual(db.claims, 1)
        self.assertEqual(db.application["status"], "error")
        self.assertFalse(db.application["delivery_uncertain"])
        self.assertIn("No se contactó", db.application["error"])
        self.assertEqual(db.updates[0][1]["send_attempt_id"], "eq.attempt")


if __name__ == "__main__":
    unittest.main()

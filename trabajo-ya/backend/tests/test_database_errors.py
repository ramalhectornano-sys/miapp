"""Upstream diagnostics are classified without SQL, keys, filenames or IDs."""
import unittest

import httpx
from fastapi import HTTPException

from app.config import Settings
from app.db import Database, User


PRIVATE = "PRIVATE-PERSONAL-CV-SECRET"


class DatabaseErrorTests(unittest.IsolatedAsyncioTestCase):
    async def failure(self, status, code=None, user=None, path="/rest/v1/chat_messages", json_body=True):
        def provider(request):
            body = {"code": code, "message": PRIVATE, "details": PRIVATE, "hint": PRIVATE}
            return httpx.Response(status, json=body) if json_body else httpx.Response(status, text=PRIVATE)
        settings = Settings(supabase_url="https://project.invalid", supabase_anon_key="sb_publishable_PUBLIC",
            supabase_service_role_key="sb_secret_PRIVATE-SERVER-KEY")
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            with self.assertLogs("app.db", level="WARNING") as logs:
                with self.assertRaises(HTTPException) as error:
                    await Database(settings, client).request("POST", path, user, json={"data": PRIVATE})
        self.assertNotIn(PRIVATE, str(error.exception.detail))
        self.assertNotIn(PRIVATE, "\n".join(logs.output))
        return error.exception, "\n".join(logs.output)

    async def test_bulk_format_rejection_has_actionable_safe_message(self):
        error, logs = await self.failure(400, "PGRST102")
        self.assertEqual(error.status_code, 502)
        self.assertIn("actualización", error.detail)
        self.assertIn("status=400 code=PGRST102", logs)
        self.assertIn("path=/rest/v1/chat_messages", logs)

    async def test_missing_schema_is_distinct_from_ai_and_network_failures(self):
        for code in ("PGRST202", "PGRST204", "PGRST205", "42P01"):
            with self.subTest(code=code):
                error, _ = await self.failure(404, code)
                self.assertEqual(error.status_code, 503)
                self.assertIn("base de datos", error.detail)

    async def test_server_denial_reports_server_permissions(self):
        for status, code in ((401, None), (403, None), (400, "42501")):
            with self.subTest(status=status, code=code):
                error, _ = await self.failure(status, code)
                self.assertEqual(error.status_code, 503)
                self.assertIn("servidor", error.detail)
                self.assertNotIn("sesión", error.detail)

    async def test_invalid_user_session_requests_login_without_blame_on_server_key(self):
        error, _ = await self.failure(401, user=User("user", "session"))
        self.assertEqual(error.status_code, 401)
        self.assertIn("sesión", error.detail)

    async def test_unknown_codes_and_non_json_diagnostics_are_not_logged(self):
        for json_body in (True, False):
            with self.subTest(json_body=json_body):
                error, logs = await self.failure(500, PRIVATE, json_body=json_body)
                self.assertEqual(error.status_code, 502)
                self.assertIn("code=UNKNOWN", logs)

    async def test_document_paths_and_account_ids_are_removed_from_logs(self):
        for path in (f"/storage/v1/object/authenticated/resumes/user/{PRIVATE}.pdf",
                f"/auth/v1/admin/users/{PRIVATE}", f"/rest/v1/{PRIVATE}",
                f"/rest/v1/chat_messages?user_id=eq.{PRIVATE}"):
            with self.subTest(path=path):
                await self.failure(404, path=path)


if __name__ == "__main__":
    unittest.main()

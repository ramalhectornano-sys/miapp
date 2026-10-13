"""Supabase API key formats and user sessions, with mocked upstream requests."""
import unittest

import httpx
from fastapi import HTTPException

from app.config import Settings
from app.db import Database, User
from app.main import create_app
from app.services.account import delete_account
from app.services.resumes import download_resume


USER_ID = "00000000-0000-4000-8000-000000000001"
SESSION = "header.user-session.signature"
SECRET = "sb_secret_PRIVATE-SERVER-KEY"
PUBLIC = "sb_publishable_PUBLIC-TEST-KEY"
BASE_URL = "https://project.invalid"


class SupabaseKeyTests(unittest.IsolatedAsyncioTestCase):
    def settings(self, **changes):
        return Settings(**{"supabase_url": BASE_URL, "supabase_anon_key": PUBLIC,
            "supabase_service_role_key": SECRET, **changes})

    def assert_service_headers(self, request):
        self.assertEqual(request.headers["apikey"], SECRET)
        self.assertNotIn("authorization", request.headers)

    def assert_user_headers(self, request):
        self.assertEqual(request.headers["apikey"], PUBLIC)
        self.assertEqual(request.headers["authorization"], f"Bearer {SESSION}")
        self.assertNotIn(SECRET, str(request.headers))

    async def test_modern_secret_rpc_uses_apikey_without_invalid_bearer(self):
        def provider(request):
            self.assert_service_headers(request)
            self.assertEqual(request.method, "POST")
            self.assertEqual(request.url.path, "/rest/v1/rpc/claim_due_searches")
            return httpx.Response(200, json=[])
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            self.assertEqual(await Database(self.settings(), client).rpc("claim_due_searches", {
                "p_worker_id": "job", "p_limit_count": 1, "p_lease_seconds": 3600}), [])

    async def test_modern_publishable_is_not_used_as_bearer_without_session(self):
        def provider(request):
            self.assertEqual(request.headers["apikey"], PUBLIC)
            self.assertNotIn("authorization", request.headers)
            return httpx.Response(200, json=[])
        # Header handling does not upgrade a publishable key's permissions.
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            self.assertEqual(await Database(self.settings(supabase_service_role_key=PUBLIC), client).select("jobs", None), [])

    async def test_user_rls_query_retains_verified_session_and_public_key(self):
        def provider(request):
            self.assert_user_headers(request)
            self.assertEqual(request.url.path, "/rest/v1/resume_versions")
            self.assertEqual(request.url.params["user_id"], f"eq.{USER_ID}")
            return httpx.Response(200, json=[{"id": "cv", "user_id": USER_ID}])
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            row = await Database(self.settings(), client).owned("resume_versions", "cv", User(USER_ID, SESSION))
        self.assertEqual(row["user_id"], USER_ID)

    async def test_legacy_service_role_rpc_keeps_jwt_bearer(self):
        key = "header.legacy-service-role.signature"
        def provider(request):
            self.assertEqual(request.headers["apikey"], key)
            self.assertEqual(request.headers["authorization"], f"Bearer {key}")
            return httpx.Response(200, json=True)
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            self.assertTrue(await Database(self.settings(supabase_service_role_key=key), client).rpc("assert_search_claim", {}))

    async def test_legacy_anon_keeps_user_session_instead_of_anon_bearer(self):
        key = "header.legacy-anon.signature"
        def provider(request):
            self.assertEqual(request.headers["apikey"], key)
            self.assertEqual(request.headers["authorization"], f"Bearer {SESSION}")
            return httpx.Response(200, json=[])
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            self.assertEqual(await Database(self.settings(supabase_anon_key=key), client).select("profiles", User(USER_ID, SESSION)), [])

    async def test_session_validation_and_following_rls_queries_keep_user_bearer(self):
        paths = []
        def provider(request):
            paths.append(request.url.path)
            self.assert_user_headers(request)
            return httpx.Response(200, json={"id": USER_ID} if request.url.path == "/auth/v1/user" else [])
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as upstream:
            app = create_app(self.settings(), upstream)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api") as client:
                    response = await client.get("/api/searches", headers={"Authorization": f"Bearer {SESSION}"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(paths[0], "/auth/v1/user")
        self.assertIn("/rest/v1/job_searches", paths)

    async def test_worker_cv_download_uses_service_apikey_only(self):
        def provider(request):
            self.assert_service_headers(request)
            self.assertEqual(request.url.path, f"/storage/v1/object/authenticated/resumes/{USER_ID}/cv.pdf")
            return httpx.Response(200, content=b"test-cv-bytes")
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            content = await download_resume(Database(self.settings(), client), User(USER_ID, SESSION), {
                "object_path": f"{USER_ID}/cv.pdf"}, service=True)
        self.assertEqual(content, b"test-cv-bytes")

    async def test_user_cv_download_retains_session_for_storage_rls(self):
        def provider(request):
            self.assert_user_headers(request)
            return httpx.Response(200, content=b"test-cv-bytes")
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            content = await download_resume(Database(self.settings(), client), User(USER_ID, SESSION), {
                "object_path": f"{USER_ID}/cv.pdf"})
        self.assertEqual(content, b"test-cv-bytes")

    async def test_account_cleanup_storage_and_auth_admin_use_service_apikey(self):
        paths = []
        def provider(request):
            self.assert_service_headers(request)
            paths.append((request.method, request.url.path))
            return httpx.Response(200, json=[] if request.url.path.startswith("/storage/") else {})
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            result = await delete_account(Database(self.settings(), client), User(USER_ID, SESSION))
        self.assertTrue(result["deleted"])
        self.assertEqual(paths, [("POST", "/storage/v1/object/list/resumes"),
            ("POST", "/storage/v1/object/list/profile-photos"), ("DELETE", f"/auth/v1/admin/users/{USER_ID}")])

    async def test_supabase_failure_does_not_expose_private_diagnostics(self):
        def provider(request):
            return httpx.Response(403, json={"error": f"PRIVATE rejected {SECRET}"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            with self.assertRaises(HTTPException) as error:
                await Database(self.settings(), client).rpc("claim_due_searches", {})
        self.assertEqual(error.exception.status_code, 502)
        self.assertNotIn("PRIVATE", str(error.exception.detail))
        self.assertNotIn(SECRET, str(error.exception.detail))

    async def test_transport_error_does_not_expose_private_url_or_key(self):
        def provider(request):
            raise httpx.RequestError(f"PRIVATE network failure {SECRET}", request=request)
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            with self.assertRaises(HTTPException) as error:
                await Database(self.settings(), client).rpc("claim_due_searches", {})
        self.assertEqual(error.exception.status_code, 502)
        self.assertNotIn("PRIVATE", str(error.exception.detail))


if __name__ == "__main__":
    unittest.main()

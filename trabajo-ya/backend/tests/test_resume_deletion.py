"""CV deletion must let database references protect private historical bytes."""
import unittest

import httpx

from app.config import Settings
from app.main import create_app


USER_ID = "11111111-1111-4111-8111-111111111111"
RESUME_ID = "33333333-3333-4333-8333-333333333333"
OBJECT_PATH = f"{USER_ID}/cv.pdf"


class ResumeDeletionTests(unittest.IsolatedAsyncioTestCase):
    async def remove(self, *, metadata_status=200, metadata_rows=None, storage_status=200):
        deletes = []

        def supabase(request):
            if request.url.path == "/auth/v1/user":
                return httpx.Response(200, json={"id": USER_ID})
            if request.method == "GET":
                self.assertEqual(request.url.params["user_id"], f"eq.{USER_ID}")
                return httpx.Response(200, json=[{"id": RESUME_ID, "object_path": OBJECT_PATH}]
                    if request.url.path == "/rest/v1/resume_versions" else [])
            self.assertEqual(request.method, "DELETE")
            self.assertEqual(request.headers["authorization"], "Bearer user-session")
            deletes.append(request.url.path)
            if request.url.path == "/rest/v1/resume_versions":
                # A concurrent worker inserted a referencing application after
                # the earlier GET checks. PostgreSQL rejects this DELETE at
                # the transaction boundary, before any bytes are touched.
                return httpx.Response(metadata_status, json=metadata_rows if metadata_rows is not None
                    else [{"id": RESUME_ID}])
            self.assertEqual(request.url.path, "/storage/v1/object/resumes")
            return httpx.Response(storage_status, json=[])

        settings = Settings(supabase_url="https://test.supabase.co", supabase_anon_key="public",
            supabase_service_role_key="server-secret")
        async with httpx.AsyncClient(transport=httpx.MockTransport(supabase)) as upstream:
            app = create_app(settings, upstream)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                    response = await client.delete(f"/api/resumes/{RESUME_ID}",
                        headers={"Authorization": "Bearer user-session"})
        return response, deletes

    async def test_concurrent_reference_rejection_never_deletes_storage_bytes(self):
        response, deletes = await self.remove(metadata_status=409)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(deletes, ["/rest/v1/resume_versions"])
        self.assertIn("archivo privado se conserva", response.json()["detail"])
        self.assertNotIn("deleted", response.json())

    async def test_unconfirmed_metadata_deletion_never_deletes_storage_bytes(self):
        response, deletes = await self.remove(metadata_rows=[])
        self.assertEqual(response.status_code, 409)
        self.assertEqual(deletes, ["/rest/v1/resume_versions"])
        self.assertNotIn("deleted", response.json())

    async def test_storage_failure_reports_incomplete_cleanup(self):
        response, deletes = await self.remove(storage_status=503)
        self.assertEqual(response.status_code, 502)
        self.assertEqual(deletes, ["/rest/v1/resume_versions", "/storage/v1/object/resumes"])
        self.assertIn("versión se quitó del perfil", response.json()["detail"])
        self.assertIn("limpieza quedó incompleta", response.json()["detail"])
        self.assertNotIn("deleted", response.json())
        self.assertNotIn(OBJECT_PATH, response.text)

    async def test_success_removes_metadata_before_guarded_private_storage(self):
        response, deletes = await self.remove()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(deletes, ["/rest/v1/resume_versions", "/storage/v1/object/resumes"])
        self.assertTrue(response.json()["deleted"])


if __name__ == "__main__":
    unittest.main()

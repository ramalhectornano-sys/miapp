"""Chat persistence exercises PostgREST's bulk-row contract and safe failures."""
import json
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from app.config import Settings
from app.main import create_app
from app.models import ChatResponse


USER_ID = "00000000-0000-4000-8000-000000000001"
SECRET = "sb_secret_PRIVATE-SERVER-KEY"


class ChatStorageTests(unittest.IsolatedAsyncioTestCase):
    async def post_chat(self, provider):
        settings = Settings(supabase_url="https://project.invalid", supabase_anon_key="sb_publishable_PUBLIC",
            supabase_service_role_key=SECRET, ai_provider="openai_compatible")
        response = ChatResponse(reply="¿En qué ciudad buscás trabajo?", mode="live")
        model = AsyncMock(return_value=response)
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as upstream:
            app = create_app(settings, upstream)
            async with app.router.lifespan_context(app):
                with patch("app.main.ai.chat", model):
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api") as client:
                        result = await client.post("/api/chat", json={"message": "Busco trabajo por esta zona"},
                            headers={"Authorization": "Bearer user-session"})
        model.assert_awaited_once()
        return result

    async def test_live_reply_and_both_messages_are_saved_with_uniform_bulk_keys(self):
        stored = []
        def provider(request):
            if request.url.path == "/auth/v1/user":
                return httpx.Response(200, json={"id": USER_ID})
            self.assertEqual(request.method, "POST")
            self.assertEqual(request.url.path, "/rest/v1/chat_messages")
            self.assertEqual(request.headers["apikey"], SECRET)
            rows = json.loads(request.content)
            # This is the actual PostgREST rule that rejected the old endpoint.
            if not rows or any(set(row) != set(rows[0]) for row in rows):
                return httpx.Response(400, json={"code": "PGRST102", "message": "All object keys must match"})
            stored.extend(rows)
            return httpx.Response(201, json=rows)
        result = await self.post_chat(provider)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["mode"], "live")
        self.assertEqual([row["role"] for row in stored], ["user", "assistant"])
        self.assertEqual([row["user_id"] for row in stored], [USER_ID, USER_ID])
        self.assertEqual(stored[0]["metadata"], {})
        self.assertEqual(stored[1]["metadata"]["reply"], result.json()["reply"])

    async def test_rejected_server_key_does_not_blame_the_valid_user_session(self):
        def provider(request):
            if request.url.path == "/auth/v1/user":
                return httpx.Response(200, json={"id": USER_ID})
            return httpx.Response(401, json={"message": f"PRIVATE invalid key {SECRET}"})
        result = await self.post_chat(provider)
        self.assertEqual(result.status_code, 503)
        self.assertIn("servidor", result.json()["detail"])
        self.assertNotIn("sesión", result.json()["detail"])
        self.assertNotIn("PRIVATE", result.text)
        self.assertNotIn(SECRET, result.text)


if __name__ == "__main__":
    unittest.main()

"""Authenticated chat persistence through mocked AI and PostgREST contracts."""
from contextlib import asynccontextmanager
import json
import unittest

import httpx

from app.config import Settings
from app.main import create_app


USER_ID = "11111111-1111-4111-8111-111111111111"
SESSION = "header.chat-session.signature"
PUBLIC_KEY = "sb_publishable_PUBLIC-TEST-KEY"
SERVICE_KEY = "sb_secret_PRIVATE-SERVER-KEY"
AI_KEY = "PRIVATE-PROVIDER-KEY"
MESSAGE = "Buscá empleos de chofer en Rincón de los Sauces todos los días a las 9."
PROPOSAL = {
    "title": "Chofer en Rincón de los Sauces", "role": "chofer",
    "city": "Rincón de los Sauces", "time": "09:00", "mode": "manual",
}


@asynccontextmanager
async def api_client(handler):
    settings = Settings(supabase_url="https://project.invalid", supabase_anon_key=PUBLIC_KEY,
        supabase_service_role_key=SERVICE_KEY, ai_provider="openai_compatible",
        ai_base_url="https://api.groq.com/openai/v1", ai_model="openai/gpt-oss-20b", ai_api_key=AI_KEY)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as upstream:
        app = create_app(settings, upstream)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api") as client:
                yield client


def model_reply():
    return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
        "content": json.dumps({"reply": "Preparé una propuesta.", "proposal": PROPOSAL})}}]})


class ChatPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_chat_saves_both_turns_in_one_uniform_bulk_and_reads_history(self):
        writes, stored = [], []

        def provider(request):
            if request.url.path == "/auth/v1/user":
                self.assertEqual(request.headers["apikey"], PUBLIC_KEY)
                self.assertEqual(request.headers["authorization"], f"Bearer {SESSION}")
                return httpx.Response(200, json={"id": USER_ID})
            if request.url.path == "/openai/v1/chat/completions":
                self.assertEqual(request.headers["authorization"], f"Bearer {AI_KEY}")
                return model_reply()
            if request.url.path == "/rest/v1/chat_messages" and request.method == "POST":
                self.assertEqual(request.headers["apikey"], SERVICE_KEY)
                self.assertNotIn("authorization", request.headers)
                self.assertEqual(request.headers["prefer"], "return=representation")
                rows = json.loads(request.content)
                writes.append(rows)
                # PostgREST rejects a bulk whose objects have different keys;
                # enforcing its contract reproduces the original PGRST102 bug.
                if any(set(row) != set(rows[0]) for row in rows):
                    return httpx.Response(400, json={"code": "PGRST102", "message": "All object keys must match"})
                self.assertEqual(len(rows), 2)
                self.assertEqual({row["user_id"] for row in rows}, {USER_ID})
                stored.extend({**row, "id": str(index)} for index, row in enumerate(rows))
                return httpx.Response(201, json=stored)
            if request.url.path == "/rest/v1/chat_messages" and request.method == "GET":
                self.assertEqual(request.headers["apikey"], PUBLIC_KEY)
                self.assertEqual(request.headers["authorization"], f"Bearer {SESSION}")
                self.assertEqual(request.url.params["order"], "created_at.desc")
                return httpx.Response(200, json=list(reversed(stored)))
            self.fail("Unexpected upstream operation")

        async with api_client(provider) as client:
            response = await client.post("/api/chat", headers={"Authorization": f"Bearer {SESSION}"},
                json={"message": MESSAGE, "history": [{"role": "user", "content": "Una conversación anterior"}]})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["mode"], "live")
            self.assertEqual(response.json()["proposal"]["role"], "chofer")
            history = await client.get("/api/chat/history", headers={"Authorization": f"Bearer {SESSION}"})

        self.assertEqual(len(writes), 1)
        self.assertEqual([row["role"] for row in stored], ["user", "assistant"])
        self.assertEqual(stored[0]["content"], MESSAGE)
        self.assertEqual(stored[0]["metadata"], {})
        self.assertEqual(stored[1]["metadata"], response.json())
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.json(), stored)
        self.assertNotIn(AI_KEY, response.text + history.text)
        self.assertNotIn(SERVICE_KEY, response.text + history.text)

    async def test_failed_bulk_write_returns_safe_error_without_partial_chat_or_retry(self):
        writes = []

        def provider(request):
            if request.url.path == "/auth/v1/user":
                return httpx.Response(200, json={"id": USER_ID})
            if request.url.path == "/openai/v1/chat/completions":
                return model_reply()
            if request.url.path == "/rest/v1/chat_messages" and request.method == "POST":
                writes.append(json.loads(request.content))
                return httpx.Response(403, json={"message": f"PRIVATE {MESSAGE} {SERVICE_KEY}",
                    "details": f"PRIVATE {AI_KEY}"})
            self.fail("Unexpected upstream operation")

        async with api_client(provider) as client:
            response = await client.post("/api/chat", headers={"Authorization": f"Bearer {SESSION}"},
                json={"message": MESSAGE})

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json(), {"detail": "No se pudo completar la operación de datos."})
        self.assertEqual(len(writes), 1)
        self.assertEqual([row["role"] for row in writes[0]], ["user", "assistant"])
        self.assertNotIn("PRIVATE", response.text)
        self.assertNotIn(MESSAGE, response.text)
        self.assertNotIn("proposal", response.json())

    async def test_invalid_session_cannot_call_model_or_persist_chat(self):
        paths = []

        def provider(request):
            paths.append(request.url.path)
            self.assertEqual(request.url.path, "/auth/v1/user")
            return httpx.Response(401, json={"message": "PRIVATE auth error"})

        async with api_client(provider) as client:
            response = await client.post("/api/chat", headers={"Authorization": f"Bearer {SESSION}"},
                json={"message": MESSAGE})

        self.assertEqual(response.status_code, 401)
        self.assertEqual(paths, ["/auth/v1/user"])
        self.assertNotIn("PRIVATE", response.text)

    async def test_provider_failure_does_not_persist_a_turn_or_expose_private_error(self):
        paths = []

        def provider(request):
            paths.append(request.url.path)
            if request.url.path == "/auth/v1/user":
                return httpx.Response(200, json={"id": USER_ID})
            if request.url.path == "/openai/v1/chat/completions":
                return httpx.Response(429, json={"error": f"PRIVATE quota {AI_KEY} {MESSAGE}"})
            self.fail("A failed provider must not write chat history")

        async with api_client(provider) as client:
            response = await client.post("/api/chat", headers={"Authorization": f"Bearer {SESSION}"},
                json={"message": MESSAGE})

        self.assertEqual(response.status_code, 502)
        self.assertEqual(paths, ["/auth/v1/user", "/openai/v1/chat/completions"])
        self.assertNotIn("PRIVATE", response.text)
        self.assertNotIn(MESSAGE, response.text)


if __name__ == "__main__":
    unittest.main()

"""Provider transport substitutes never contact Google or send mail."""
import json
import unittest
from datetime import datetime, timedelta, timezone

import httpx
from cryptography.fernet import Fernet
from fastapi import HTTPException

from app.config import Settings
from app.services.mail import SCOPES, access_token, oauth_callback


class OAuthDatabase:
    def __init__(self, client, *, existing=False):
        self.client = client
        self.key = Fernet.generate_key()
        self.settings = Settings(google_client_id="test-client", google_client_secret="test-secret",
            token_encryption_key=self.key.decode(), supabase_service_role_key="test-service")
        self.events = []
        self.connection = ({"id": "connection", "user_id": "user", "email": "persona@example.com",
            "provider": "google", "status": "connected"} if existing else None)
        self.secret = None
        self.fail_secret = False
        self.fail_final_patch = False

    def encrypt(self, tokens):
        return {"encrypted_payload": Fernet(self.key).encrypt(json.dumps(tokens).encode()).decode()}

    def stored_tokens(self):
        return json.loads(Fernet(self.key).decrypt(self.secret["encrypted_payload"].encode()))

    async def rpc(self, name, payload):
        if name == "consume_oauth_state":
            return {"user_id": "user", "encrypted_verifier": Fernet(self.key).encrypt(b"test-verifier").decode(),
                "redirect_uri": "https://backend.example/api/mail/google/callback"}
        if name == "get_email_secret":
            if self.connection:
                assert payload["p_connection_id"] == self.connection["id"]
                assert payload["p_user_id"] == self.connection["user_id"]
            return self.secret
        if name == "store_email_secret":
            self.events.append(("secret", self.connection["status"] if self.connection else None))
            if self.fail_secret:
                raise HTTPException(503, "No se confirmó la persistencia privada.")
            self.secret = {"encrypted_payload": payload["p_encrypted_payload"]}
            return None
        raise AssertionError(name)

    async def select(self, table, user, *, params):
        assert table == "email_connections" and params["user_id"] == "eq.user"
        assert params["email"] == "eq.persona@example.com"
        return [self.connection.copy()] if self.connection else []

    async def insert(self, table, data):
        assert table == "email_connections"
        self.connection = data.copy()
        self.events.append(("connection", data["status"]))
        return [data.copy()]

    async def patch(self, table, data, *, params):
        assert table == "email_connections" and params["user_id"] == "eq.user"
        self.events.append(("connection", data["status"]))
        if data["status"] == "connected" and self.fail_final_patch:
            return []
        self.connection.update(data)
        return [self.connection.copy()]


class GoogleOAuthTests(unittest.IsolatedAsyncioTestCase):
    def provider(self, tokens, *, identity=None):
        def handle(request):
            if request.url.host == "oauth2.googleapis.com":
                return httpx.Response(200, json=tokens)
            if request.url.host == "openidconnect.googleapis.com":
                self.assertEqual(request.headers["Authorization"], "Bearer fresh-access")
                return httpx.Response(200, json=identity if identity is not None else {
                    "email": "persona@example.com", "email_verified": True})
            self.fail(f"No se admite contactar otro servicio: {request.url.host}")
        return handle

    def tokens(self):
        return {"access_token": "fresh-access", "refresh_token": "offline-refresh",
            "expires_in": 3600, "token_type": "Bearer", "scope": " ".join(SCOPES)}

    async def test_connection_is_confirmed_only_after_private_credentials_are_saved(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(self.provider(self.tokens()))) as client:
            db = OAuthDatabase(client)
            result = await oauth_callback(db, "state", "code")
        self.assertTrue(result["connected"])
        self.assertEqual(db.events, [("connection", "disconnected"), ("secret", "disconnected"),
            ("connection", "connected")])
        self.assertEqual(db.stored_tokens()["refresh_token"], "offline-refresh")
        self.assertNotIn("offline-refresh", db.secret["encrypted_payload"])

    async def test_failed_secret_storage_leaves_connection_disconnected(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(self.provider(self.tokens()))) as client:
            for existing in (False, True):
                with self.subTest(existing=existing):
                    db = OAuthDatabase(client, existing=existing)
                    db.fail_secret = True
                    with self.assertRaises(HTTPException):
                        await oauth_callback(db, "state", "code")
                    self.assertEqual(db.connection["status"], "disconnected")
                    self.assertNotIn(("connection", "connected"), db.events)

    async def test_unconfirmed_final_state_is_not_success(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(self.provider(self.tokens()))) as client:
            db = OAuthDatabase(client)
            db.fail_final_patch = True
            with self.assertRaises(HTTPException) as error:
                await oauth_callback(db, "state", "code")
        self.assertEqual(error.exception.status_code, 502)
        self.assertEqual(db.connection["status"], "disconnected")

    async def test_reconnection_keeps_same_account_refresh_token_when_google_omits_it(self):
        tokens = self.tokens()
        del tokens["refresh_token"]
        async with httpx.AsyncClient(transport=httpx.MockTransport(self.provider(tokens))) as client:
            db = OAuthDatabase(client, existing=True)
            db.secret = db.encrypt({"refresh_token": "previous-offline-token"})
            self.assertTrue((await oauth_callback(db, "state", "code"))["connected"])
        self.assertEqual(db.stored_tokens()["refresh_token"], "previous-offline-token")
        self.assertEqual(db.stored_tokens()["access_token"], "fresh-access")

    async def test_malformed_provider_tokens_are_safe_errors_before_connection_writes(self):
        cases = [[], {}, {**self.tokens(), "expires_in": "invalid"}, {**self.tokens(), "expires_in": True},
            {**self.tokens(), "expires_in": -1}, {**self.tokens(), "expires_in": 1.5},
            {**self.tokens(), "access_token": "bad\r\naccess"}, {**self.tokens(), "token_type": "invalid"},
            {**self.tokens(), "scope": []}, {**self.tokens(), "refresh_token": None}]
        for tokens in cases:
            with self.subTest(tokens=tokens):
                async with httpx.AsyncClient(transport=httpx.MockTransport(self.provider(tokens))) as client:
                    db = OAuthDatabase(client)
                    with self.assertRaises(HTTPException) as error:
                        await oauth_callback(db, "state", "code")
                    self.assertEqual(error.exception.status_code, 502)
                    self.assertFalse(db.events)
                    self.assertNotIn("fresh-access", str(error.exception.detail))

    async def test_unverified_or_malformed_identity_never_records_connected(self):
        for identity in ([], {"email": "persona@example.com", "email_verified": False},
                {"email": 42, "email_verified": True}):
            with self.subTest(identity=identity):
                async with httpx.AsyncClient(transport=httpx.MockTransport(self.provider(self.tokens(), identity=identity))) as client:
                    db = OAuthDatabase(client)
                    with self.assertRaises(HTTPException) as error:
                        await oauth_callback(db, "state", "code")
                    self.assertEqual(error.exception.status_code, 502)
                    self.assertFalse(db.events)

    def expired_tokens(self):
        return {"access_token": "expired-access", "refresh_token": "previous-offline-token",
            "expires_at": (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(), "scope": " ".join(SCOPES)}

    async def test_refresh_requires_new_access_token_and_preserves_previous_credentials_on_failure(self):
        for response in ({"expires_in": 3600}, [], {"access_token": "fresh-access", "expires_in": "bad"},
                {"access_token": "fresh-access", "refresh_token": None},
                {"access_token": "fresh-access", "scope": "openid"}):
            with self.subTest(response=response):
                async with httpx.AsyncClient(transport=httpx.MockTransport(self.provider(response))) as client:
                    db = OAuthDatabase(client, existing=True)
                    db.secret = db.encrypt(self.expired_tokens())
                    original_secret = db.secret.copy()
                    with self.assertRaises(HTTPException) as error:
                        await access_token(db, db.connection, "user")
                    self.assertEqual(error.exception.status_code, 409)
                    self.assertEqual(db.secret, original_secret)
                    self.assertFalse(db.events)

    async def test_refresh_preserves_offline_credential_and_records_fresh_expiry(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(self.provider({
                "access_token": "fresh-access", "expires_in": 3600}))) as client:
            db = OAuthDatabase(client, existing=True)
            db.secret = db.encrypt(self.expired_tokens())
            self.assertEqual(await access_token(db, db.connection, "user"), "fresh-access")
        saved = db.stored_tokens()
        self.assertEqual(saved["refresh_token"], "previous-offline-token")
        self.assertEqual(saved["scope"], " ".join(SCOPES))
        self.assertGreater(datetime.fromisoformat(saved["expires_at"]), datetime.now(timezone.utc))

    async def test_malformed_private_payload_is_recoverable_without_provider_contact(self):
        def no_provider(request):
            self.fail("No debe contactarse Google con datos guardados inválidos")
        cases = [[], {"expires_at": "invalid"}, {**self.expired_tokens(), "expires_at": "2027-01-01T00:00:00"},
            {**self.expired_tokens(), "expires_at": None}, {**self.expired_tokens(), "access_token": "bad\nheader"}]
        for payload in cases:
            with self.subTest(payload=payload):
                async with httpx.AsyncClient(transport=httpx.MockTransport(no_provider)) as client:
                    db = OAuthDatabase(client, existing=True)
                    db.secret = db.encrypt(payload)
                    with self.assertRaises(HTTPException) as error:
                        await access_token(db, db.connection, "user")
                    self.assertEqual(error.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()

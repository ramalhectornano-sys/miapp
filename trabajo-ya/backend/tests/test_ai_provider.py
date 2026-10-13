"""Provider verification uses only synthetic input and never invokes app actions."""
import json
import unittest

import httpx
from fastapi import HTTPException

from app.config import Settings
from app.services.ai import MAX_OUTPUT_TOKENS, chat, verify_provider
from app.models import ChatRequest


def settings(**changes):
    return Settings(**{
        "ai_provider": "openai_compatible",
        "ai_base_url": "https://api.groq.com/openai/v1",
        "ai_model": "openai/gpt-oss-120b",
        "ai_api_key": "TEST-PRIVATE-KEY",
        **changes,
    })


def proposal(**changes):
    return {
        "title": "Chofer en Rincón de los Sauces",
        "role": "chofer", "city": "Rincón de los Sauces",
        "frequency": "daily", "time": "09:00",
        "timezone": "America/Argentina/Buenos_Aires",
        "weekdays": [1, 2, 3, 4, 5, 6, 7], "mode": "manual",
        **changes,
    }


def completion(data=None, *, finish_reason="stop"):
    payload = data if data is not None else {"reply": "Propuesta", "proposal": proposal()}
    return {"choices": [{"message": {"content": json.dumps(payload)}, "finish_reason": finish_reason}]}


class ProviderVerificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_verification_checks_provider_and_returns_only_metadata(self):
        captured = []

        def transport(request):
            captured.append(request)
            return httpx.Response(200, json=completion())

        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            result = await verify_provider(settings(), client)
        self.assertEqual(result, {
            "verified": True, "provider": "openai_compatible",
            "model": "openai/gpt-oss-120b", "proposal_valid": True,
        })
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].url.path, "/openai/v1/chat/completions")
        body = json.loads(captured[0].content)
        self.assertEqual(body["model"], "openai/gpt-oss-120b")
        self.assertEqual(body["max_completion_tokens"], MAX_OUTPUT_TOKENS)
        self.assertNotIn("tools", body)
        self.assertEqual([turn["role"] for turn in body["messages"]], ["system", "user"])
        self.assertIn("propuesta manual", body["messages"][-1]["content"])
        self.assertNotIn("TEST-PRIVATE-KEY", json.dumps(result))

    async def test_ollama_verification_has_bounded_generation_without_api_key(self):
        captured = []

        def transport(request):
            captured.append(request)
            return httpx.Response(200, json={"message": {"content": json.dumps({"proposal": proposal()})}, "done_reason": "stop"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            result = await verify_provider(settings(ai_provider="ollama", ai_base_url="http://ollama:11434", ai_api_key=""), client)
        self.assertTrue(result["verified"])
        self.assertEqual(captured[0].url.path, "/api/chat")
        self.assertEqual(json.loads(captured[0].content)["options"]["num_predict"], MAX_OUTPUT_TOKENS)
        self.assertNotIn("authorization", captured[0].headers)

    async def test_groq_gpt_oss_20b_uses_supported_reasoning_controls(self):
        def transport(request):
            body = json.loads(request.content)
            self.assertEqual(body["temperature"], 0.2)
            self.assertEqual(body["reasoning_effort"], "low")
            self.assertIs(body["include_reasoning"], False)
            self.assertNotIn("reasoning_format", body)
            return httpx.Response(200, json=completion())

        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            result = await verify_provider(settings(ai_model="openai/gpt-oss-20b"), client)
        self.assertEqual(result["model"], "openai/gpt-oss-20b")

    async def test_other_models_and_providers_do_not_receive_groq_specific_options(self):
        for config in (settings(), settings(ai_base_url="https://provider.example/v1", ai_model="openai/gpt-oss-20b")):
            with self.subTest(base_url=config.ai_base_url, model=config.ai_model):
                def transport(request):
                    body = json.loads(request.content)
                    self.assertEqual(body["temperature"], 0)
                    self.assertNotIn("reasoning_effort", body)
                    self.assertNotIn("include_reasoning", body)
                    return httpx.Response(200, json=completion())

                async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
                    result = await verify_provider(config, client)
                self.assertTrue(result["verified"])

    async def test_demo_does_not_count_as_real_verification(self):
        captured = []
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: captured.append(request))) as client:
            with self.assertRaises(HTTPException) as error:
                await verify_provider(Settings(), client)
        self.assertEqual(error.exception.status_code, 503)
        self.assertEqual(captured, [])

    async def test_missing_managed_provider_key_fails_before_request(self):
        captured = []
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: captured.append(request))) as client:
            with self.assertRaises(HTTPException) as error:
                await verify_provider(settings(ai_api_key="  "), client)
        self.assertEqual(error.exception.status_code, 503)
        self.assertEqual(captured, [])

    async def test_local_openai_compatible_server_can_omit_key(self):
        def transport(request):
            self.assertNotIn("authorization", request.headers)
            return httpx.Response(200, json=completion())

        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            result = await verify_provider(settings(ai_base_url="http://localhost:8080/v1", ai_api_key=""), client)
        self.assertTrue(result["verified"])

    async def test_invented_or_automatic_schedule_cannot_verify(self):
        for changes in (
            {"role": "electricista"}, {"city": "Neuquén"}, {"time": "21:00"},
            {"frequency": "weekly"}, {"weekdays": [1]}, {"timezone": "UTC"},
            {"mode": "automatic"}, {"resume_id": "11111111-1111-4111-8111-111111111111"},
        ):
            with self.subTest(changes=changes):
                async with httpx.AsyncClient(transport=httpx.MockTransport(
                    lambda request: httpx.Response(200, json=completion({"proposal": proposal(**changes)}))
                )) as client:
                    with self.assertRaises(HTTPException) as error:
                        await verify_provider(settings(), client)
                self.assertEqual(error.exception.status_code, 502)

    async def test_unknown_model_errors_are_not_secret_or_success(self):
        def transport(request):
            self.assertEqual(json.loads(request.content)["model"], "unknown-model")
            return httpx.Response(404, json={"error": "PRIVATE PROVIDER DETAIL TEST-PRIVATE-KEY"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            with self.assertRaises(HTTPException) as error:
                await verify_provider(settings(ai_model="unknown-model"), client)
        self.assertEqual(error.exception.status_code, 502)
        self.assertNotIn("PRIVATE", error.exception.detail)
        self.assertNotIn("unknown-model", error.exception.detail)

    async def test_auth_and_quota_failures_never_echo_private_provider_error(self):
        for status in (401, 403, 429, 500):
            with self.subTest(status=status):
                async with httpx.AsyncClient(transport=httpx.MockTransport(
                    lambda request: httpx.Response(status, text="TEST-PRIVATE-KEY PROVIDER-PRIVATE-DATA")
                )) as client:
                    with self.assertRaises(HTTPException) as error:
                        await verify_provider(settings(), client)
                self.assertEqual(error.exception.status_code, 502)
                self.assertNotIn("PRIVATE", error.exception.detail)

    async def test_timeout_cannot_be_reported_as_verified(self):
        def transport(request):
            raise httpx.ReadTimeout("PRIVATE request context", request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            with self.assertRaises(HTTPException) as error:
                await verify_provider(settings(), client)
        self.assertEqual(error.exception.status_code, 502)
        self.assertNotIn("PRIVATE", error.exception.detail)

    async def test_truncated_even_valid_json_is_rejected(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=completion(finish_reason="length"))
        )) as client:
            with self.assertRaises(HTTPException) as error:
                await verify_provider(settings(), client)
        self.assertEqual(error.exception.status_code, 502)

    async def test_ollama_truncated_json_is_rejected(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"message": {"content": json.dumps({"proposal": proposal()})}, "done_reason": "length"})
        )) as client:
            with self.assertRaises(HTTPException) as error:
                await verify_provider(settings(ai_provider="ollama"), client)
        self.assertEqual(error.exception.status_code, 502)

    async def test_invalid_envelopes_json_and_missing_proposal_are_rejected(self):
        for envelope in (
            {"choices": []}, {"choices": [{"message": {"content": "not JSON"}}]},
            {"choices": [{"message": {"content": "[]"}}]},
            {"choices": [{"message": {"content": None}}]},
            completion({"proposal": None}), completion({"reply": "Ya envié correos"}),
        ):
            with self.subTest(envelope=envelope):
                async with httpx.AsyncClient(transport=httpx.MockTransport(
                    lambda request: httpx.Response(200, json=envelope)
                )) as client:
                    with self.assertRaises(HTTPException) as error:
                        await verify_provider(settings(), client)
                self.assertEqual(error.exception.status_code, 502)

    async def test_model_action_claim_and_invalid_reply_never_reach_visible_reply(self):
        for unsafe_reply in ("Ya envié 100 correos", {"token": "PRIVATE-KEY", "action": "send"}):
            with self.subTest(reply=unsafe_reply):
                async with httpx.AsyncClient(transport=httpx.MockTransport(
                    lambda request: httpx.Response(200, json=completion({"reply": unsafe_reply, "proposal": proposal()}))
                )) as client:
                    result = await chat(settings(), client, ChatRequest(message="Buscá empleos de chofer en Rincón de los Sauces"))
                self.assertEqual(result.mode, "live")
                self.assertNotIn("100", result.reply)
                self.assertNotIn("PRIVATE", result.reply)
                self.assertIn("No se ejecutó", result.reply)


if __name__ == "__main__":
    unittest.main()

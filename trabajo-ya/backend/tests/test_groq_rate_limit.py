"""Bounded Groq retry fixtures; no live provider requests or credentials."""
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import UUID

import httpx
from fastapi import HTTPException

from app.config import Settings
from app.services.job_evidence import INVALID_RESPONSE, RATE_LIMIT_RESPONSE, extract_job_evidence

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
SEARCH = {"roles": ["chofer"], "cities": ["Neuquén"]}
PRIVATE = "PRIVATE-PROVIDER-BODY"


def settings(**changes):
    return Settings(**{"ai_provider": "openai_compatible", "ai_base_url": "https://api.groq.com/openai/v1",
        "ai_model": "openai/gpt-oss-20b", "ai_api_key": "SYNTHETIC-PRIVATE-KEY", **changes})


def limited(retry_after=None):
    headers = {"x-groq-request-id": "groq-rate-limit-receipt"}
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return httpx.Response(429, headers=headers, json={"error": PRIVATE})


def success():
    return httpx.Response(200, json={"id": "groq-success-receipt", "choices": [{
        "finish_reason": "stop", "message": {"content": '{"jobs": []}'}}]})


class GroqRateLimitTests(unittest.IsolatedAsyncioTestCase):
    async def extract(self, responses, *, count=1, config=None, audit=None):
        self.requests, self.events = [], []
        self.sleep = AsyncMock()

        async def record(event):
            self.events.append(dict(event))
            if audit is not None:
                await audit(event)

        def transport(request):
            self.requests.append(request)
            response = responses[len(self.requests) - 1]
            if isinstance(response, Exception):
                raise response
            return response

        sources = [{"url": f"https://empleos.example.org/vacantes/{index}",
            "content": "Empresa busca chofer en Neuquén."} for index in range(count)]
        with patch("app.services.job_evidence.asyncio.sleep", self.sleep):
            async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
                return await extract_job_evidence(config or settings(), client, SEARCH,
                    sources, now=NOW, audit=record)

    async def test_retry_after_then_success_has_two_distinct_audited_attempts(self):
        self.assertEqual(await self.extract([limited("2.5"), success()]), [])
        self.sleep.assert_awaited_once_with(2.5)
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.requests[0].content, self.requests[1].content)
        self.assertTrue(all(request.url.host == "api.groq.com" for request in self.requests))
        self.assertEqual([event["status"] for event in self.events],
            ["started", "failed", "started", "succeeded"])
        first, failed, second, succeeded = self.events
        self.assertEqual(first["event_id"], failed["event_id"])
        self.assertEqual(second["event_id"], succeeded["event_id"])
        self.assertNotEqual(UUID(first["event_id"]), UUID(second["event_id"]))
        self.assertEqual([event["attempt"] for event in self.events], [1, 1, 2, 2])
        self.assertEqual(failed["http_status"], 429)
        self.assertTrue(failed["provider_response_received"])
        self.assertEqual(failed["retry_after_seconds"], 2.5)
        self.assertEqual(failed["request_id"], "groq-rate-limit-receipt")
        self.assertEqual(succeeded["http_status"], 200)
        self.assertNotIn(PRIVATE, json.dumps(self.events))
        self.assertNotIn("SYNTHETIC-PRIVATE-KEY", json.dumps(self.events))

    async def test_second_429_fails_without_third_request_or_partial_success(self):
        with self.assertRaises(HTTPException) as error:
            await self.extract([success(), limited("3"), limited("4"), success()], count=17)
        self.assertEqual(error.exception.status_code, 502)
        self.assertEqual(error.exception.detail, RATE_LIMIT_RESPONSE)
        self.assertEqual(len(self.requests), 3)
        self.sleep.assert_awaited_once_with(3)
        terminal = [event for event in self.events if event["status"] != "started"]
        self.assertEqual([event["http_status"] for event in terminal], [200, 429, 429])
        self.assertEqual([event["batch_index"] for event in terminal], [1, 2, 2])
        self.assertNotIn(PRIVATE, str(error.exception.detail))

    async def test_total_wait_budget_is_shared_by_all_batches(self):
        with self.assertRaises(HTTPException):
            await self.extract([limited("60"), success(), limited("1"), success()], count=9)
        self.assertEqual(len(self.requests), 3)
        self.sleep.assert_awaited_once_with(60)
        terminal = [event for event in self.events if event["status"] != "started"]
        self.assertEqual([event["batch_index"] for event in terminal], [1, 1, 2])
        self.assertEqual([event["attempt"] for event in terminal], [1, 2, 1])

    async def test_separate_limited_batches_retry_once_each_within_shared_wait_budget(self):
        self.assertEqual(await self.extract([success(), limited("9"), success(), limited("20"), success()], count=24), [])
        self.assertEqual(len(self.requests), 5)
        self.assertEqual([call.args[0] for call in self.sleep.await_args_list], [9, 20])
        self.assertEqual(self.requests[1].content, self.requests[2].content)
        self.assertEqual(self.requests[3].content, self.requests[4].content)
        terminal = [event for event in self.events if event["status"] != "started"]
        self.assertEqual([event["batch_index"] for event in terminal], [1, 2, 2, 3, 3])

    async def test_all_three_batches_remain_bounded_to_six_requests_and_sixty_seconds(self):
        self.assertEqual(await self.extract([limited("20"), success()] * 3, count=24), [])
        self.assertEqual(len(self.requests), 6)
        self.assertEqual(sum(call.args[0] for call in self.sleep.await_args_list), 60)

    async def test_late_batch_retry_does_not_repeat_prior_batches(self):
        self.assertEqual(await self.extract([success(), success(), limited("0"), success()], count=24), [])
        self.sleep.assert_awaited_once_with(0)
        self.assertEqual(len(self.requests), 4)
        terminal = [event for event in self.events if event["status"] != "started"]
        self.assertEqual([event["batch_index"] for event in terminal], [1, 2, 3, 3])
        self.assertEqual(self.requests[2].content, self.requests[3].content)

    async def test_missing_or_unbounded_retry_after_fails_without_sleep(self):
        for value in (None, "", "61", "60.1", "-1", "NaN", "inf", "1e1", PRIVATE,
                "Thu, 15 Oct 2026 12:00:01 GMT", "1" * 100):
            with self.subTest(retry_after=value):
                with self.assertRaises(HTTPException) as error:
                    await self.extract([limited(value), success()])
                self.assertEqual(error.exception.detail, RATE_LIMIT_RESPONSE)
                self.assertEqual(len(self.requests), 1)
                self.sleep.assert_not_awaited()
                self.assertNotIn("retry_after_seconds", self.events[-1])
                self.assertNotIn(PRIVATE, json.dumps(self.events))

    async def test_other_providers_and_insecure_groq_addresses_never_retry(self):
        for base_url in ("https://api.openai.com/v1", "https://api.groq.com.example.org/openai/v1",
                "http://api.groq.com/openai/v1", "https://api.groq.com:8443/openai/v1"):
            with self.subTest(base_url=base_url):
                with self.assertRaises(HTTPException):
                    await self.extract([limited("1"), success()], config=settings(ai_base_url=base_url))
                self.assertEqual(len(self.requests), 1)
                self.sleep.assert_not_awaited()

    async def test_non_429_http_errors_do_not_retry_even_with_retry_after(self):
        for status in (400, 401, 403, 500, 503):
            with self.subTest(status=status):
                response = httpx.Response(status, headers={"Retry-After": "1"}, json={"error": PRIVATE})
                with self.assertRaises(HTTPException) as error:
                    await self.extract([response, success()])
                self.assertEqual(error.exception.detail, INVALID_RESPONSE)
                self.assertEqual(self.events[-1]["http_status"], status)
                self.assertEqual(len(self.requests), 1)
                self.sleep.assert_not_awaited()
                self.assertNotIn(PRIVATE, json.dumps(self.events))

    async def test_invalid_output_and_network_failure_do_not_retry(self):
        for response in (httpx.Response(200, headers={"Retry-After": "1"}, json={"error": PRIVATE}),
                httpx.ReadTimeout(PRIVATE)):
            with self.subTest(response=type(response).__name__):
                with self.assertRaises(HTTPException) as error:
                    await self.extract([response, success()])
                self.assertEqual(error.exception.detail, INVALID_RESPONSE)
                self.assertEqual(len(self.requests), 1)
                self.sleep.assert_not_awaited()
                self.assertNotIn(PRIVATE, json.dumps(self.events))

    async def test_failed_429_audit_stops_before_sleep_or_retry(self):
        async def fail_terminal(event):
            if event["status"] == "failed":
                raise RuntimeError(PRIVATE)

        with self.assertRaises(HTTPException) as error:
            await self.extract([limited("1"), success()], audit=fail_terminal)
        self.assertEqual(error.exception.status_code, 503)
        self.assertEqual(len(self.requests), 1)
        self.sleep.assert_not_awaited()
        self.assertNotIn(PRIVATE, str(error.exception.detail))


if __name__ == "__main__":
    unittest.main()

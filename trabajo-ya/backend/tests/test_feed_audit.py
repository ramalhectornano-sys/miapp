"""Authorized-feed HTTP audit fixtures; no real network or job applications."""
import hashlib
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID

import httpx
from fastapi import HTTPException

from app.config import Settings
from app.services.feeds import find_jobs, read_json_feed
from app.services.research_audit import ResearchAuditError


SOURCE = {"id": "partner:fixture", "authorized": True, "url": "https://partner.example.org/jobs.json"}
SEARCH = {"id": "11111111-1111-4111-8111-111111111111", "user_id": "owner",
    "run_id": "22222222-2222-4222-8222-222222222222", "claim_token": "fixture-lease",
    "roles": ["chofer"], "cities": ["Localidad de prueba"], "research_mode": "general"}


class FeedAuditTests(unittest.IsolatedAsyncioTestCase):
    async def read(self, envelope, *, audit=None, handler=None):
        requests, events = [], []

        async def record(event):
            events.append(event)
            if audit:
                await audit(event)

        def transport(request):
            requests.append(request)
            self.assertEqual(events[-1]["status"], "started")
            if handler:
                return handler(request)
            return envelope

        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            with patch("app.services.feeds.safe_feed_url", AsyncMock()):
                try:
                    rows = await read_json_feed(SimpleNamespace(client=client), SOURCE, audit=record)
                except Exception as caught:
                    return caught, events, requests
        return rows, events, requests

    async def test_actual_get_has_paired_uuid_hash_status_count_without_body(self):
        content = json.dumps({"jobs": [{"title": "chofer", "private_fixture_text": "PRIVATE BODY"}]}).encode()
        rows, events, requests = await self.read(httpx.Response(200, content=content))
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].method, "GET")
        self.assertEqual([event["status"] for event in events], ["started", "succeeded"])
        self.assertEqual(events[0]["event_id"], events[1]["event_id"])
        self.assertEqual(str(UUID(events[0]["event_id"])), events[0]["event_id"])
        self.assertEqual(events[1]["http_status"], 200)
        self.assertEqual(events[1]["result_count"], 1)
        self.assertEqual(events[1]["content_sha256"], hashlib.sha256(content).hexdigest())
        self.assertEqual(events[1]["source_id"], SOURCE["id"])
        self.assertEqual(events[1]["provider_method"], "GET")
        self.assertNotIn("PRIVATE BODY", json.dumps(events))

    async def test_denied_redirect_and_rate_limit_keep_real_status_without_body_or_followup(self):
        for status in (301, 403, 429, 500):
            with self.subTest(status=status):
                result, events, requests = await self.read(httpx.Response(status, text="PRIVATE UPSTREAM BODY",
                    headers={"Location": "https://127.0.0.1/private"}))
                self.assertIsInstance(result, httpx.HTTPStatusError)
                self.assertEqual(len(requests), 1)
                self.assertEqual([event["status"] for event in events], ["started", "failed"])
                self.assertEqual(events[-1]["http_status"], status)
                self.assertNotIn("PRIVATE", json.dumps(events))

    async def test_timeout_has_no_fabricated_http_status(self):
        def timeout(request):
            raise httpx.ReadTimeout("PRIVATE EXCEPTION", request=request)

        result, events, requests = await self.read(None, handler=timeout)
        self.assertIsInstance(result, httpx.ReadTimeout)
        self.assertEqual(len(requests), 1)
        self.assertEqual(events[-1]["status"], "failed")
        self.assertIsNone(events[-1]["http_status"])
        self.assertNotIn("PRIVATE", json.dumps(events))

    async def test_bad_json_is_failed_even_after_http_success(self):
        result, events, _ = await self.read(httpx.Response(200, text="PRIVATE MALFORMED JSON"))
        self.assertIsInstance(result, ValueError)
        self.assertEqual(events[-1]["status"], "failed")
        self.assertEqual(events[-1]["http_status"], 200)
        self.assertEqual(events[-1]["result_count"], 0)
        self.assertNotIn("PRIVATE", json.dumps(events))

    async def test_initial_audit_failure_prevents_get(self):
        async def fail(event):
            raise RuntimeError("PRIVATE DATABASE ERROR")

        result, events, requests = await self.read(httpx.Response(200, json=[]), audit=fail)
        self.assertIsInstance(result, ResearchAuditError)
        self.assertEqual(requests, [])
        self.assertEqual(len(events), 1)
        self.assertNotIn("PRIVATE", str(result.detail))

    async def test_terminal_audit_failure_does_not_return_completed_rows(self):
        async def fail_terminal(event):
            if event["status"] != "started":
                raise RuntimeError("PRIVATE DATABASE ERROR")

        result, events, requests = await self.read(httpx.Response(200, json=[{"title": "chofer"}]), audit=fail_terminal)
        self.assertIsInstance(result, ResearchAuditError)
        self.assertEqual(len(requests), 1)
        self.assertEqual(events[-1]["status"], "succeeded")  # proposed terminal fact was rejected by persistence
        self.assertNotIn("PRIVATE", str(result.detail))

    async def test_general_search_passes_durable_audit_and_does_not_swallow_write_failure(self):
        rpc, requests = AsyncMock(return_value=False), []
        config = Settings(authorized_feeds=[SOURCE], geocoder_provider="disabled")
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: requests.append(request) or httpx.Response(200, json=[]))) as client:
            db = SimpleNamespace(client=client, settings=config, rpc=rpc)
            with patch("app.services.feeds.safe_feed_url", AsyncMock()):
                with self.assertRaises(ResearchAuditError):
                    await find_jobs(db, SEARCH)
        self.assertEqual(requests, [])
        self.assertEqual(rpc.await_args.args[0], "record_web_research_event")
        payload = rpc.await_args.args[1]
        self.assertEqual(payload["p_event"]["provider"], "authorized_feed")
        self.assertEqual(payload["p_event"]["status"], "started")
        self.assertEqual(payload["p_claim_token"], SEARCH["claim_token"])

    async def test_unusable_feed_address_is_blocked_without_http_attempt(self):
        events = []
        record = AsyncMock(side_effect=lambda event: events.append(event))
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: self.fail("No blocked fetch"))) as client:
            with patch("app.services.feeds.safe_feed_url", AsyncMock(side_effect=HTTPException(503, "PRIVATE REASON"))):
                with self.assertRaises(HTTPException):
                    await read_json_feed(SimpleNamespace(client=client), SOURCE, audit=record)
        self.assertEqual([event["status"] for event in events], ["blocked"])
        self.assertNotIn("http_status", events[0])
        self.assertNotIn("PRIVATE", json.dumps(events))

    async def test_legacy_caller_without_audit_preserves_array_and_original_errors(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[]))) as client:
            with patch("app.services.feeds.safe_feed_url", AsyncMock()):
                self.assertEqual(await read_json_feed(SimpleNamespace(client=client), SOURCE), [])
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"jobs": {}}))) as client:
            with patch("app.services.feeds.safe_feed_url", AsyncMock()), self.assertRaises(ValueError):
                await read_json_feed(SimpleNamespace(client=client), SOURCE)


if __name__ == "__main__":
    unittest.main()

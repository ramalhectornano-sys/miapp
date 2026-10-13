"""Cloud job exit status, with mocked I/O and persistent send reservations."""
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException

from app.config import Settings
from app.worker import WorkerCycleFailure, main, tick


class WorkerOnceTests(unittest.IsolatedAsyncioTestCase):
    def database(self, claims=None):
        db = AsyncMock()
        db.settings = Settings(worker_batch_size=1)
        db.rpc = AsyncMock(return_value=[{"id": "search", "claim_token": "claim"}] if claims is None else claims)
        return db

    def result(self, status="completed", recorded=True):
        return {"run_id": "run", "status": status, "found_count": 0, "recorded": recorded}

    async def once(self, db):
        settings = Settings(supabase_url="https://project.invalid", supabase_service_role_key="PRIVATE-KEY")
        client = AsyncMock()
        client.__aenter__.return_value = client
        with patch("app.worker.Settings.from_env", return_value=settings), \
             patch("app.worker.httpx.AsyncClient", return_value=client), \
             patch("app.worker.Database", return_value=db), \
             patch("app.worker.asyncio.sleep", new_callable=AsyncMock) as sleep:
            try:
                return await main(once=True)
            finally:
                sleep.assert_not_awaited()

    async def test_empty_tick_does_not_execute_or_reserve_a_search(self):
        db = self.database([])
        with patch("app.worker.execute_claim", new_callable=AsyncMock) as execute:
            self.assertEqual(await tick(db, "cloud-job", fail_on_error=True), 0)
        execute.assert_not_awaited()
        db.rpc.assert_awaited_once_with("claim_due_searches", {
            "p_worker_id": "cloud-job", "p_limit_count": 1, "p_lease_seconds": 3600})

    async def test_default_tick_keeps_completed_count_on_recorded_search_error(self):
        db = self.database()
        with patch("app.worker.execute_claim", new_callable=AsyncMock, return_value=self.result("error")):
            self.assertEqual(await tick(db, "persistent-worker"), 1)

    async def test_strict_tick_rejects_unrecorded_completion(self):
        db = self.database()
        with patch("app.worker.execute_claim", new_callable=AsyncMock, return_value=self.result(recorded=False)):
            with self.assertRaises(WorkerCycleFailure):
                await tick(db, "cloud-job", fail_on_error=True)
        db.rpc.assert_awaited_once()

    async def test_successful_once_runs_exactly_one_claim_without_sleep(self):
        db = self.database()
        with patch("app.worker.execute_claim", new_callable=AsyncMock, return_value=self.result()) as execute:
            self.assertIsNone(await self.once(db))
        db.rpc.assert_awaited_once()
        execute.assert_awaited_once_with(db, {"id": "search", "claim_token": "claim"})

    async def test_empty_once_is_success_without_fake_execution(self):
        db = self.database([])
        with patch("app.worker.execute_claim", new_callable=AsyncMock) as execute:
            self.assertIsNone(await self.once(db))
        db.rpc.assert_awaited_once()
        execute.assert_not_awaited()

    async def assert_failed_result(self, result):
        db = self.database()
        with patch("app.worker.execute_claim", new_callable=AsyncMock, return_value=result) as execute:
            with self.assertLogs("app.worker", level="ERROR") as logs, self.assertRaises(SystemExit) as error:
                await self.once(db)
        self.assertEqual(error.exception.code, 1)
        db.rpc.assert_awaited_once()
        execute.assert_awaited_once()
        self.assertNotIn("PRIVATE", " ".join(logs.output))

    async def test_search_error_exits_one_without_repeating_claim(self):
        await self.assert_failed_result(self.result("error"))

    async def test_blocked_search_exits_one_without_repeating_claim(self):
        await self.assert_failed_result(self.result("blocked"))

    async def test_unrecorded_search_exits_one_without_repeating_claim(self):
        await self.assert_failed_result(self.result(recorded=False))

    async def assert_failed_query(self, exception):
        db = self.database()
        db.rpc.side_effect = exception
        with patch("app.worker.execute_claim", new_callable=AsyncMock) as execute:
            with self.assertLogs("app.worker", level="ERROR") as logs, self.assertRaises(SystemExit) as error:
                await self.once(db)
        self.assertEqual(error.exception.code, 1)
        db.rpc.assert_awaited_once()
        execute.assert_not_awaited()
        self.assertNotIn("PRIVATE", " ".join(logs.output))

    async def test_database_http_exception_exits_one_without_logging_details(self):
        await self.assert_failed_query(HTTPException(502, "PRIVATE database failure"))

    async def test_provider_request_error_exits_one_without_logging_url(self):
        await self.assert_failed_query(httpx.RequestError("PRIVATE network failure",
            request=httpx.Request("GET", "https://project.invalid/rest?key=PRIVATE")))

    async def test_invalid_query_result_exits_one_without_logging_details(self):
        await self.assert_failed_query(ValueError("PRIVATE malformed result"))


if __name__ == "__main__":
    unittest.main()

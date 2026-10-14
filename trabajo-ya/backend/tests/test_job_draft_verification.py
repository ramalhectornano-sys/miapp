"""New publisher proof can qualify a draft without changing its contents."""
import copy
import unittest

from app.db import User
from app.services.job_draft_verification import refresh_greenhouse_draft
from tests.test_daily_automation import DailyDatabase


class DraftVerificationTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self):
        db = DailyDatabase(None)
        draft = {"id": "draft", "user_id": "user-1", "job_id": "job", "search_id": "search-1",
            "status": "pending", "delivery_uncertain": False, "company": "Empresa",
            "job_title": "Chofer", "recipient_email": None, "recipient_verified_at": None,
            "body": "Mensaje personalizado conservado", "subject": "Asunto conservado",
            "resume_id": "resume-1", "email_connection_id": "connection-1"}
        db.tables["applications"].append(draft)
        job = {"id": "job", "user_id": "user-1", "source": "verified:greenhouse", "company": "Empresa", "title": "Chofer",
            "recipient_email": "jobs@empresa.example", "recipient_verified_at": db.now.isoformat(),
            "is_active": True, "source_authorized": True,
            "payload": {"verification_method": "publisher_api_explicit_email"}}
        return db, draft, job

    async def test_null_email_is_promoted_only_after_fresh_publisher_proof(self):
        db, draft, job = self.fixture()
        original = copy.deepcopy(draft)
        await refresh_greenhouse_draft(db, {"id": "search-1", "user_id": "user-1"}, User("user-1", ""), job)
        self.assertEqual(draft["recipient_email"], job["recipient_email"])
        self.assertEqual(draft["recipient_verified_at"], job["recipient_verified_at"])
        for key in original.keys() - {"recipient_email", "recipient_verified_at"}:
            self.assertEqual(draft[key], original[key])

    async def test_prior_attempt_uncertain_child_foreign_and_other_search_are_untouched(self):
        for change in ({"send_attempt_id": "attempt"}, {"delivery_uncertain": True}, {"status": "sent"},
                {"parent_application_id": "parent"}, {"user_id": "user-2"}, {"search_id": "search-2"},
                {"company": "Otra empresa"}, {"job_title": "Otro puesto"}, {"recipient_email": "other@empresa.example"}):
            db, draft, job = self.fixture()
            draft.update(change)
            original = draft.copy()
            await refresh_greenhouse_draft(db, {"id": "search-1", "user_id": "user-1"}, User("user-1", ""), job)
            self.assertEqual(draft, original, change)

    async def test_non_attested_or_withdrawn_job_cannot_promote_draft(self):
        for change in ({"source": "web:tavily"}, {"recipient_verified_at": None}, {"source_authorized": False},
                {"is_active": False}, {"payload": {}}, {"recipient_email": None}, {"user_id": "user-2"}):
            db, draft, job = self.fixture()
            job.update(change)
            original = draft.copy()
            await refresh_greenhouse_draft(db, {"id": "search-1", "user_id": "user-1"}, User("user-1", ""), job)
            self.assertEqual(draft, original)

    async def test_a_claim_between_select_and_patch_is_not_overwritten(self):
        db, draft, job = self.fixture()
        select = db.select
        async def claimed_after_read(table, user=None, params=None):
            selected = await select(table, user, params)
            draft["send_attempt_id"] = "concurrent-attempt"
            return selected
        db.select = claimed_after_read
        await refresh_greenhouse_draft(db, {"id": "search-1", "user_id": "user-1"}, User("user-1", ""), job)
        self.assertIsNone(draft["recipient_verified_at"])
        self.assertIsNone(draft["recipient_email"])
        self.assertEqual(draft["send_attempt_id"], "concurrent-attempt")

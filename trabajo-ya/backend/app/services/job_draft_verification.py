"""Promote only untouched drafts after a fresh publisher attestation.

This updates delivery evidence, not the message, sender, CV or authorization.
The existing atomic preparation/reservation RPCs still decide if sending is
allowed. Conditional PATCH prevents changing an already claimed delivery.
"""
from .ai import normalize
from .source_registry import GREENHOUSE_SOURCE_ID


async def refresh_greenhouse_draft(db, search, user, job):
    payload = job.get("payload")
    email = job.get("recipient_email")
    if (job.get("user_id") != user.id or search.get("user_id") != user.id
            or job.get("source") != GREENHOUSE_SOURCE_ID or not job.get("source_authorized")
            or not job.get("recipient_verified_at") or job.get("is_active") is not True
            or not isinstance(email, str) or not email.strip()
            or not isinstance(payload, dict) or payload.get("verification_method") != "publisher_api_explicit_email"):
        return
    params = {"user_id": f"eq.{user.id}", "job_id": f"eq.{job['id']}", "search_id": f"eq.{search['id']}",
        "status": "eq.pending", "send_attempt_id": "is.null", "delivery_uncertain": "eq.false",
        "parent_application_id": "is.null", "limit": "1"}
    drafts = await db.select("applications", None, params=params)
    for draft in drafts:
        # A changed employer/title must not inherit an old application body.
        if any(not isinstance(draft.get(saved), str) or not isinstance(job.get(current), str)
                or normalize(draft[saved]).strip() != normalize(job[current]).strip()
                for saved, current in (("company", "company"), ("job_title", "title"))):
            continue
        previous_email = draft.get("recipient_email")
        if previous_email is not None and (not isinstance(previous_email, str)
                or previous_email.strip().casefold() != email.strip().casefold()):
            continue
        if draft.get("recipient_verified_at") == job["recipient_verified_at"] and previous_email == email:
            continue
        await db.patch("applications", {"recipient_email": email, "recipient_verified_at": job["recipient_verified_at"]},
            params={key: value for key, value in {**params, "id": f"eq.{draft['id']}",
                "company": f"eq.{draft['company']}", "job_title": f"eq.{draft['job_title']}",
                "recipient_email": "is.null" if previous_email is None else f"eq.{previous_email}"}.items()
                if key != "limit"})

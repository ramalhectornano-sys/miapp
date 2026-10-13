from datetime import datetime, timedelta, timezone, time
from zoneinfo import ZoneInfo


def next_occurrence(search: dict, now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    zone = ZoneInfo(search["timezone"])
    local = now.astimezone(zone)
    clock = time.fromisoformat(search["schedule_time"])
    days = set(search["weekdays"]) if search["frequency"] == "weekly" else set(range(1, 8))
    for offset in range(9):
        day = local.date() + timedelta(days=offset)
        if day.isoweekday() not in days:
            continue
        candidate = datetime.combine(day, clock, zone)
        utc = candidate.astimezone(timezone.utc)
        # Spring-forward nonexistent local times are skipped, rather than running late silently.
        if utc.astimezone(zone).replace(tzinfo=None) != candidate.replace(tzinfo=None):
            continue
        if utc > now:
            return utc
    raise ValueError("No se pudo calcular la próxima ejecución.")


def proposal_row(proposal, user_id):
    row = {"user_id": user_id, "name": proposal.title, "roles": [proposal.role], "cities": [proposal.city],
        "frequency": proposal.frequency, "schedule_time": proposal.time, "timezone": proposal.timezone,
        "weekdays": proposal.weekdays, "status": "enabled", "auto_apply": False,
        "preferred_resume_id": str(proposal.resume_id) if proposal.resume_id else None}
    row["next_run_at"] = next_occurrence(row).isoformat()
    return row

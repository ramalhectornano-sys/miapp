"""Run independently of Android: python -m app.worker [--once]."""
import argparse
import asyncio
import logging
from uuid import uuid4
import httpx
from fastapi import HTTPException
from .config import Settings
from .db import Database
from .services.feeds import execute_claim

logger = logging.getLogger(__name__)


class WorkerCycleFailure(RuntimeError):
    """A one-shot job must not report unsuccessful searches as successful."""


async def tick(db: Database, worker_id: str, *, fail_on_error: bool = False):
    processed = 0
    failed = False
    # Claim just before each run: never hold a batch whose leases expire while queued.
    for _ in range(db.settings.worker_batch_size):
        claims = await db.rpc("claim_due_searches", {"p_worker_id": worker_id, "p_limit_count": 1, "p_lease_seconds": 3600})
        if not claims:
            break
        result = await execute_claim(db, claims[0])
        logger.info("Tarea %s: %s (%s resultados)", result["run_id"], result["status"], result["found_count"])
        processed += 1
        failed = failed or result.get("status") != "completed" or not result.get("recorded", False)
    if fail_on_error and failed:
        raise WorkerCycleFailure("El lote contiene ejecuciones no completadas o no confirmadas.")
    return processed


async def main(once=False):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    # Request URLs can contain personal identifiers and OAuth callback parameters.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = Settings.from_env()
    if not settings.supabase_service_role_key or not settings.supabase_url:
        raise SystemExit("Configurá Supabase y su clave de servicio antes de iniciar el worker.")
    worker_id = f"worker-{uuid4()}"
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        db = Database(settings, client)
        while True:
            try:
                await tick(db, worker_id, fail_on_error=once)
            except (HTTPException, httpx.HTTPError, ValueError, WorkerCycleFailure):
                logger.error("El ciclo del worker no se completó. Se reintentará la consulta, nunca un envío reservado.")
                if once:
                    # Cloud jobs need a failed execution signal. The scheduler
                    # can start a later query; it never clears send reservations.
                    raise SystemExit(1) from None
            if once:
                break
            await asyncio.sleep(30)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Procesar un lote y terminar")
    asyncio.run(main(parser.parse_args().once))

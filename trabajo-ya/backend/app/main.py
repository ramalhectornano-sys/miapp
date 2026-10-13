from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import UUID, uuid4

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Query
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .auth import require_user
from .config import Settings
from .db import Database, User
from .models import ApplicationPatch, ChatRequest, ChatResponse, ConsentRequest, SearchPatch, SearchProposal, SendRequest, StopFollowupsRequest
from .services import ai, mail
from .services.account import delete_account
from .services.feeds import execute_claim
from .services.resumes import extract_resume
from .services.schedule import next_occurrence, proposal_row


def create_app(settings: Settings | None = None, client: httpx.AsyncClient | None = None):
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app):
        owned_client = client is None
        app.state.http = client or httpx.AsyncClient(timeout=30, follow_redirects=False)
        app.state.db = Database(settings, app.state.http)
        yield
        if owned_client:
            await app.state.http.aclose()

    app = FastAPI(title="Trabajo YA", version="0.3.0", lifespan=lifespan,
        description="Asistente laboral. Ninguna integración se simula como una operación real.")
    app.state.settings = settings
    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type"])

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        # Pydantic input details can contain CV/chat/token data; return field paths only.
        return JSONResponse(status_code=422, content={"detail": "Revisá los datos de la solicitud.",
            "fields": [".".join(map(str, item["loc"])) for item in error.errors()]})

    @app.get("/health")
    async def health():
        return {"status": "ok", "version": "0.3.0", "integrations": {
            "supabase": "configured" if settings.auth_ready else "not_configured",
            "ai": "demo" if settings.ai_provider == "demo" else "configured_unverified",
            "job_sources": "configured_unverified" if settings.authorized_feeds else "not_configured",
            "mail_oauth": "configured_unverified" if settings.oauth_ready else "not_configured",
            "mail_sending": "enabled" if settings.mail_send_enabled else "disabled",
            "scheduler": "requires_separate_worker"}, "message": "El estado de configuración no confirma una búsqueda ni un envío."}

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(request: Request, body: ChatRequest, user: User = Depends(require_user)):
        response = await ai.chat(settings, request.app.state.http, body)
        # PostgREST bulk inserts require identical keys in every object. Keep
        # both turns in one insert so a failed write cannot save half a chat.
        await request.app.state.db.insert("chat_messages", [
            {"user_id": user.id, "role": "user", "content": body.message, "metadata": {}},
            {"user_id": user.id, "role": "assistant", "content": response.reply, "metadata": response.model_dump(mode="json")}])
        return response

    @app.get("/api/integrations")
    async def integrations(request: Request, user: User = Depends(require_user)):
        connections = await request.app.state.db.select("email_connections", user, params={
            "user_id": f"eq.{user.id}", "select": "id,provider,email,status,connected_at", "order": "connected_at.desc", "limit": "20"})
        sources = [{"id": feed["id"], "name": str(feed.get("name") or feed["id"])}
            for feed in settings.authorized_feeds if isinstance(feed, dict) and feed.get("authorized") and feed.get("id")]
        metadata = [{key: row.get(key) for key in ("id", "provider", "email", "status", "connected_at")} for row in connections]
        profiles = await request.app.state.db.select("profiles", user, params={
            "user_id": f"eq.{user.id}", "select": "sending_timezone", "limit": "1"})
        sending_timezone = (profiles[0].get("sending_timezone") if profiles else None) or "America/Argentina/Buenos_Aires"
        return {"sources": sources, "email_connections": metadata, "sending_enabled": settings.mail_send_enabled,
            "mail_policy": {"daily_limit": 10, "timezone": sending_timezone, "repeat_every_days": 3}}

    @app.get("/api/chat/history")
    async def chat_history(request: Request, user: User = Depends(require_user)):
        rows = await request.app.state.db.select("chat_messages", user, params={"order": "created_at.desc", "limit": "100"})
        return list(reversed(rows))

    @app.get("/api/searches")
    async def searches(request: Request, user: User = Depends(require_user)):
        db = request.app.state.db
        rows = await db.select("job_searches", user, params={"order": "created_at.desc", "limit": "100"})
        consents = await db.select("sending_consents", user, params={
            "user_id": f"eq.{user.id}", "order": "granted_at.desc", "limit": "200"})
        by_id = {row["id"]: row for row in consents}
        for row in rows:
            consent = by_id.get(row.get("consent_id"), {})
            row["consent_repeat_every_days"] = 3 if consent.get("repeat_enabled") and consent.get("policy_version") == "v3" else 0
            row["consent_daily_limit"] = 10
            row["consent_expires_at"] = consent.get("expires_at")
            row["consent_revoked_at"] = consent.get("revoked_at")
        return rows

    @app.post("/api/searches", status_code=201)
    async def create_search(request: Request, body: SearchProposal, user: User = Depends(require_user)):
        db = request.app.state.db
        if body.resume_id:
            await db.owned("resume_versions", body.resume_id, user)
        rows = await db.insert("job_searches", proposal_row(body, user.id))
        return {"search": rows[0], "automatic_authorization_required": body.mode == "automatic",
            "message": "Búsqueda guardada. Los envíos automáticos se habilitan únicamente con una autorización específica. Todavía no se ejecutó una búsqueda."}

    @app.patch("/api/searches/{search_id}")
    async def patch_search(search_id: UUID, request: Request, body: SearchPatch, user: User = Depends(require_user)):
        db = request.app.state.db
        old = await db.owned("job_searches", search_id, user)
        data = body.model_dump(exclude_none=True)
        if "resume_id" in data:
            await db.owned("resume_versions", data["resume_id"], user)
            data["preferred_resume_id"] = str(data.pop("resume_id"))
        if "time" in data:
            data["schedule_time"] = data.pop("time")
        merged = {**old, **data}
        SearchProposal(title=merged["name"], role=merged["roles"][0], city=merged["cities"][0], frequency=merged["frequency"],
            time=merged["schedule_time"][:5], timezone=merged["timezone"], weekdays=merged["weekdays"] or list(range(1, 8)))
        data["next_run_at"] = next_occurrence(merged).isoformat()
        rows = await db.patch("job_searches", data, params={"id": f"eq.{search_id}", "user_id": f"eq.{user.id}"})
        return rows[0]

    @app.post("/api/searches/{search_id}/run")
    async def run_search(search_id: UUID, request: Request, user: User = Depends(require_user)):
        db = request.app.state.db
        await db.owned("job_searches", search_id, user)
        if not settings.authorized_feeds:
            raise HTTPException(503, "No hay fuentes reales autorizadas configuradas. No se ejecutó ninguna búsqueda.")
        search = await db.rpc("claim_search_now", {"p_search_id": str(search_id), "p_user_id": user.id,
            "p_worker_id": f"manual-{uuid4()}", "p_lease_seconds": 3600})
        if not search:
            raise HTTPException(409, "La búsqueda ya está en ejecución.")
        return await execute_claim(db, search)

    @app.get("/api/searches/{search_id}/runs")
    async def search_runs(search_id: UUID, request: Request, user: User = Depends(require_user)):
        db = request.app.state.db
        await db.owned("job_searches", search_id, user)
        return await db.select("job_search_runs", user, params={"search_id": f"eq.{search_id}", "order": "started_at.desc", "limit": "50"})

    @app.post("/api/resumes/{resume_id}/extract")
    async def resume_extract(resume_id: UUID, request: Request, user: User = Depends(require_user)):
        return await extract_resume(request.app.state.db, user, str(resume_id))

    @app.delete("/api/resumes/{resume_id}")
    async def remove_resume(resume_id: UUID, request: Request, user: User = Depends(require_user)):
        db = request.app.state.db
        resume = await db.owned("resume_versions", resume_id, user)
        references = [
            ("applications", "resume_id"), ("job_searches", "preferred_resume_id"), ("sending_consents", "resume_id"),
        ]
        for table, field in references:
            linked = await db.select(table, None, params={"user_id": f"eq.{user.id}", field: f"eq.{resume_id}", "limit": "1"})
            if linked:
                raise HTTPException(409, "Esta versión está asociada a búsquedas, autorizaciones o postulaciones. Conservá el documento para que el historial sea verificable; podés cargar otra versión.")
        path = resume["object_path"]
        if not path.startswith(f"{user.id}/") or ".." in path.split("/"):
            raise HTTPException(409, "La ruta del documento no es válida.")
        # A worker can attach the CV after the advisory pre-check above. Delete
        # metadata first: PostgreSQL's foreign keys decide atomically whether
        # it is still unreferenced, while the actual private bytes remain safe.
        try:
            removed = await db.request("DELETE", "/rest/v1/resume_versions", user,
                params={"id": f"eq.{resume_id}", "user_id": f"eq.{user.id}"}, headers={"Prefer": "return=representation"})
            if not removed:
                raise HTTPException(409, "El registro cambió durante la eliminación.")
        except HTTPException:
            raise HTTPException(409, "No se eliminó el currículum: el registro pudo quedar asociado a una búsqueda o postulación. El archivo privado se conserva.")
        try:
            # Keep the user's bearer so Storage's historical-document guard
            # also applies if the same path was linked again concurrently.
            await db.request("DELETE", "/storage/v1/object/resumes", user, json={"prefixes": [path]})
        except HTTPException:
            raise HTTPException(502, "La versión se quitó del perfil, pero no se confirmó la eliminación de su archivo privado. La limpieza quedó incompleta; al eliminar la cuenta se volverá a intentar borrar todos sus documentos.")
        return {"deleted": True, "message": "Se eliminó esta versión del currículum y su archivo privado."}

    @app.get("/api/applications")
    async def applications(request: Request, user: User = Depends(require_user)):
        db = request.app.state.db
        rows = await db.select("applications", user, params={"order": "created_at.desc", "limit": "100"})
        suppressed = await db.select("recipient_suppressions", user, params={
            "user_id": f"eq.{user.id}", "select": "recipient_email,stopped_at,reason", "limit": "2000"})
        by_email = {row["recipient_email"].strip().casefold(): row for row in suppressed}
        for row in rows:
            suppression = by_email.get((row.get("recipient_email") or "").strip().casefold())
            row["followups_stopped"] = bool(suppression)
            if suppression:
                row["followups_stopped_at"] = suppression["stopped_at"]
                row["followups_stop_reason"] = suppression["reason"]
        return rows

    @app.post("/api/applications/{application_id}/send")
    async def application_send(application_id: UUID, request: Request, body: SendRequest, user: User = Depends(require_user)):
        return await mail.send_application(request.app.state.db, user, str(application_id), manual=True, acknowledgment=body.acknowledgment)

    @app.post("/api/applications/{application_id}/stop-followups")
    async def stop_followups(application_id: UUID, request: Request, body: StopFollowupsRequest, user: User = Depends(require_user)):
        db = request.app.state.db
        await db.owned("applications", application_id, user)
        result = await db.rpc("stop_recipient_followups", {"p_application_id": str(application_id),
            "p_user_id": user.id, "p_reason": body.reason})
        if not result:
            raise HTTPException(409, "No se pudieron detener los recordatorios de esta empresa.")
        return {**result, "stopped": True,
            "message": "Se detuvieron los próximos recordatorios a este correo en todas tus búsquedas. Un envío ya reservado puede estar en curso."}

    @app.patch("/api/applications/{application_id}")
    async def edit_application(application_id: UUID, request: Request, body: ApplicationPatch, user: User = Depends(require_user)):
        db = request.app.state.db
        current = await db.owned("applications", application_id, user)
        if current.get("send_attempt_id") or current["status"] not in ("pending", "error"):
            raise HTTPException(409, "Solo se pueden editar borradores sin intentos de envío.")
        data = body.model_dump(exclude_none=True, mode="json")
        if body.resume_id:
            await db.owned("resume_versions", body.resume_id, user)
        if body.email_connection_id:
            connection = await db.owned("email_connections", body.email_connection_id, user)
            if connection["status"] != "connected":
                raise HTTPException(409, "La cuenta de correo seleccionada no está conectada.")
        rows = await db.patch("applications", data, params={"id": f"eq.{application_id}", "user_id": f"eq.{user.id}", "send_attempt_id": "is.null"})
        if not rows:
            raise HTTPException(409, "El borrador cambió durante la edición. Volvé a revisar su estado.")
        return rows[0]

    @app.post("/api/mail/google/start")
    async def google_start(request: Request, user: User = Depends(require_user)):
        return await mail.oauth_start(request.app.state.db, user)

    @app.get("/api/mail/google/callback")
    async def google_callback(request: Request, state: str = Query(max_length=200), code: str = Query(max_length=4000)):
        return await mail.oauth_callback(request.app.state.db, state, code)

    @app.post("/api/mail/consents", status_code=201)
    async def grant_consent(request: Request, body: ConsentRequest, user: User = Depends(require_user)):
        db = request.app.state.db
        await db.owned("job_searches", body.search_id, user)
        await db.owned("resume_versions", body.resume_id, user)
        connection = await db.owned("email_connections", body.email_connection_id, user)
        if connection["status"] != "connected" or connection.get("revoked_at") or connection.get("provider") != "google":
            raise HTTPException(409, "Conectá tu correo antes de autorizar envíos.")
        if mail.SCOPES[0] not in connection.get("scopes", []):
            raise HTTPException(409, "Volvé a conectar Gmail y habilitá el permiso de envío.")
        allowed = {feed["id"] for feed in settings.authorized_feeds if feed.get("authorized")}
        if not set(body.allowed_sources).issubset(allowed):
            raise HTTPException(409, "Solo se pueden autorizar fuentes configuradas y permitidas.")
        result = await db.rpc("grant_sending_consent", {"p_user_id": user.id,
            "p_search_id": str(body.search_id), "p_resume_id": str(body.resume_id),
            "p_email_connection_id": str(body.email_connection_id), "p_authorized_sources": body.allowed_sources,
            "p_expires_at": body.expires_at.isoformat(), "p_authorization_text": body.acknowledgment,
            "p_repeat_enabled": body.repeat_every_days == 3})
        if not result or not result.get("consent") or not result.get("search"):
            raise HTTPException(409, "No se pudo autorizar el envío. Revisá la búsqueda, el CV y la conexión de correo.")
        granted = result["consent"]
        granted["repeat_every_days"] = 3 if granted.get("repeat_enabled") and granted.get("policy_version") == "v3" else 0
        result["search"].update({"consent_repeat_every_days": granted["repeat_every_days"],
            "consent_daily_limit": 10, "consent_expires_at": granted.get("expires_at"),
            "consent_revoked_at": granted.get("revoked_at")})
        repeat_message = (" Se autorizaron recordatorios cada 72 horas al mismo correo, mientras la fuente vuelva a verificar una vacante vigente compatible."
            if body.repeat_every_days == 3 else " No se autorizaron recordatorios.")
        return {**result, "message": "Se autorizó esta búsqueda con un máximo total de 10 correos por día por usuario, sumando todas las búsquedas, envíos manuales y recordatorios."
            + repeat_message + " La autorización vence en la fecha indicada. Los borradores se procesarán en la próxima ejecución programada."}

    @app.get("/api/mail/consents")
    async def list_consents(request: Request, user: User = Depends(require_user)):
        # Keep the user's bearer for RLS; tokens live only in the private schema.
        rows = await request.app.state.db.select("sending_consents", user, params={
            "user_id": f"eq.{user.id}", "order": "granted_at.desc", "limit": "200"})
        now = datetime.now(timezone.utc)
        for row in rows:
            expiry = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
            row["status"] = "revoked" if row.get("revoked_at") else "expired" if expiry <= now else "active"
            row["repeat_every_days"] = 3 if row.get("repeat_enabled") and row.get("policy_version") == "v3" else 0
        return rows

    @app.delete("/api/mail/consents/{consent_id}")
    async def revoke_consent(consent_id: UUID, request: Request, user: User = Depends(require_user)):
        result = await request.app.state.db.rpc("revoke_sending_consent", {"p_consent_id": str(consent_id)}, user)
        return {"revoked": bool(result)}

    @app.delete("/api/account")
    async def remove_account(request: Request, user: User = Depends(require_user)):
        return await delete_account(request.app.state.db, user)

    return app


app = create_app()

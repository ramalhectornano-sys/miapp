"""Small PostgREST client. User queries always keep the bearer token for RLS."""
from dataclasses import dataclass
import logging
from typing import Any
import httpx
from fastapi import HTTPException

from .config import Settings


logger = logging.getLogger(__name__)
SAFE_ERROR_CODES = frozenset({"PGRST102", "PGRST202", "PGRST204", "PGRST205", "PGRST301", "PGRST302",
    "42501", "42P01", "23503", "23505", "23514"})
SAFE_REST_PATHS = frozenset(f"/rest/v1/{name}" for name in (
    "profiles", "work_experiences", "professional_references", "credentials", "resume_versions",
    "email_connections", "job_searches", "sending_consents", "job_search_runs", "jobs", "applications",
    "chat_messages", "job_search_matches", "recipient_suppressions", "web_research_events")) | frozenset(f"/rest/v1/rpc/{name}" for name in (
    "claim_due_searches", "claim_search_now", "grant_sending_consent", "revoke_sending_consent",
    "stop_recipient_followups", "assert_search_claim", "complete_search_run", "create_initial_application",
    "prepare_automatic_application", "prepare_followup_application", "claim_application_send",
    "consume_oauth_state", "get_email_secret", "store_email_secret", "store_oauth_state", "record_web_research_event"))


def diagnostic_path(path: str) -> str:
    """Log resource types only, never object filenames, IDs or query strings."""
    if path in SAFE_REST_PATHS:
        return path
    if path.startswith("/storage/v1/"):
        return "/storage/v1/[resource]"
    if path.startswith("/auth/v1/"):
        return "/auth/v1/[resource]"
    return "[resource]"


def safe_error_code(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return "UNKNOWN"
    code = payload.get("code") if isinstance(payload, dict) else None
    return code if isinstance(code, str) and code in SAFE_ERROR_CODES else "UNKNOWN"


def database_failure(response: httpx.Response, user: "User | None") -> HTTPException:
    """Classify known failures without exposing upstream SQL or private data."""
    code = safe_error_code(response)
    if response.status_code == 401:
        return HTTPException(401, "Tu sesión venció o ya no es válida. Volvé a ingresar.") if user else HTTPException(
            503, "El servidor no tiene acceso autorizado a los datos. Revisá la configuración de Supabase en el servidor.")
    if code in {"PGRST202", "PGRST204", "PGRST205", "42P01"}:
        return HTTPException(503, "La base de datos necesita actualizarse para completar esta operación.")
    if code == "42501" or response.status_code == 403:
        return HTTPException(403, "No tenés permiso para completar esta operación.") if user else HTTPException(
            503, "El servidor no tiene permisos para completar esta operación. Revisá su acceso a Supabase.")
    if code == "PGRST102":
        return HTTPException(502, "El servicio necesita una actualización para guardar estos datos.")
    status = 404 if response.status_code == 404 else 409 if response.status_code == 409 else 502
    return HTTPException(status, "No se pudo completar la operación de datos.")


@dataclass(frozen=True)
class User:
    id: str
    token: str


class Database:
    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings, self.client = settings, client

    def headers(self, user: User | None):
        key = self.settings.supabase_anon_key if user else self.settings.supabase_service_role_key
        if not self.settings.supabase_url or not key:
            raise HTTPException(503, "Supabase todavía no está configurado.")
        headers = {"apikey": key}
        if user:
            headers["Authorization"] = f"Bearer {user.token}"
        elif not key.startswith(("sb_secret_", "sb_publishable_")):
            # Legacy anon/service_role keys are JWTs. Modern API keys are opaque
            # and belong only in apikey; using them as Bearer fails JWT checks.
            headers["Authorization"] = f"Bearer {key}"
        return headers

    async def request(self, method, path, user=None, *, params=None, json=None, headers=None):
        try:
            response = await self.client.request(method, f"{self.settings.supabase_url}{path}",
                headers={**self.headers(user), **(headers or {})}, params=params, json=json)
        except httpx.RequestError:
            logger.warning("Supabase request failed method=%s path=%s code=NETWORK",
                method if method in {"GET", "POST", "PATCH", "DELETE"} else "UNKNOWN", diagnostic_path(path))
            raise HTTPException(502, "No se pudo contactar al almacenamiento. Intentá nuevamente.")
        if response.status_code >= 400:
            logger.warning("Supabase request rejected method=%s path=%s status=%s code=%s",
                method if method in {"GET", "POST", "PATCH", "DELETE"} else "UNKNOWN",
                diagnostic_path(path), response.status_code, safe_error_code(response))
            raise database_failure(response, user)
        return response.json() if response.content else None

    async def select(self, table, user, *, params=None):
        return await self.request("GET", f"/rest/v1/{table}", user, params=params or {})

    async def owned(self, table, item_id, user: User, service=False):
        rows = await self.select(table, None if service else user,
            params={"id": f"eq.{item_id}", "user_id": f"eq.{user.id}", "limit": "1"})
        if not rows:
            raise HTTPException(404, "No se encontró el registro.")
        return rows[0]

    async def insert(self, table, data, user=None, *, conflict=None):
        return await self.request("POST", f"/rest/v1/{table}", user, json=data,
            params={"on_conflict": conflict} if conflict else None,
            headers={"Prefer": "return=representation,resolution=ignore-duplicates" if conflict else "return=representation"})

    async def patch(self, table, data, user=None, *, params):
        return await self.request("PATCH", f"/rest/v1/{table}", user, json=data, params=params,
            headers={"Prefer": "return=representation"})

    async def rpc(self, name, payload, user=None):
        return await self.request("POST", f"/rest/v1/rpc/{name}", user, json=payload)

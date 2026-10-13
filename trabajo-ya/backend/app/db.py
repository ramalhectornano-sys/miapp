"""Small PostgREST client. User queries always keep the bearer token for RLS."""
from dataclasses import dataclass
from typing import Any
import httpx
from fastapi import HTTPException

from .config import Settings


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
            raise HTTPException(502, "No se pudo contactar al almacenamiento. Intentá nuevamente.")
        if response.status_code >= 400:
            # Never forward PostgREST diagnostics or SQL details containing personal data.
            status = 404 if response.status_code == 404 else 409 if response.status_code == 409 else 502
            raise HTTPException(status, "No se pudo completar la operación de datos.")
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

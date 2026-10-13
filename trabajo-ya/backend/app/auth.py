from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import httpx
from .db import User

bearer = HTTPBearer(auto_error=False)


async def require_user(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(401, "Iniciá sesión para continuar.")
    settings = request.app.state.settings
    if not settings.auth_ready:
        raise HTTPException(503, "La autenticación todavía no está configurada.")
    try:
        response = await request.app.state.http.get(f"{settings.supabase_url}/auth/v1/user",
            headers={"apikey": settings.supabase_anon_key, "Authorization": f"Bearer {credentials.credentials}"})
    except httpx.RequestError:
        raise HTTPException(503, "No se pudo validar tu sesión.")
    if response.status_code != 200:
        raise HTTPException(401, "La sesión venció o no es válida.")
    try:
        data = response.json()
    except ValueError:
        raise HTTPException(503, "No se pudo validar tu sesión.")
    if not isinstance(data, dict) or not data.get("id"):
        raise HTTPException(401, "La sesión no es válida.")
    return User(id=str(data["id"]), token=credentials.credentials)

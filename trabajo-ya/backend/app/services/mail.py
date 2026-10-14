"""Gmail OAuth and one-attempt sending. No simulated mail delivery exists."""
import asyncio
import base64
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import hashlib
import json
import logging
import secrets
from urllib.parse import urlencode
from uuid import uuid4

import httpx
from fastapi import HTTPException
from cryptography.fernet import Fernet, InvalidToken

from ..db import Database, User
from .resumes import download_resume

SCOPES = ["https://www.googleapis.com/auth/gmail.send", "https://www.googleapis.com/auth/userinfo.email", "openid"]
logger = logging.getLogger(__name__)


def cipher(db: Database):
    try:
        return Fernet(db.settings.token_encryption_key.encode())
    except (ValueError, TypeError):
        raise HTTPException(503, "La clave de cifrado del correo no está configurada.")


async def oauth_start(db: Database, user: User):
    if not db.settings.oauth_ready:
        raise HTTPException(503, "La integración real de Google todavía no está configurada.")
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    await db.rpc("store_oauth_state", {"p_state_hash": hashlib.sha256(state.encode()).hexdigest(),
        "p_user_id": user.id, "p_provider": "google", "p_encrypted_verifier": cipher(db).encrypt(verifier.encode()).decode(),
        "p_redirect_uri": db.settings.google_redirect_uri, "p_scopes": SCOPES,
        "p_expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()})
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({"client_id": db.settings.google_client_id,
        "redirect_uri": db.settings.google_redirect_uri, "response_type": "code", "scope": " ".join(SCOPES),
        "access_type": "offline", "prompt": "consent", "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256"})
    return {"authorization_url": url, "message": "Conectar el correo no autoriza envíos automáticos."}


async def store_tokens(db, connection_id, user_id, tokens):
    encrypted = cipher(db).encrypt(json.dumps(tokens).encode()).decode()
    await db.rpc("store_email_secret", {"p_connection_id": connection_id, "p_user_id": user_id,
        "p_encrypted_payload": encrypted, "p_key_id": "v1"})


def provider_tokens(payload: object) -> dict:
    """Validate a fresh Google token before extending its usable lifetime."""
    if not isinstance(payload, dict):
        raise ValueError("Respuesta de credenciales inválida")
    token = payload.get("access_token")
    if not isinstance(token, str) or not token or any(character.isspace() for character in token):
        raise ValueError("Sin credencial de acceso válida")
    token_type = payload.get("token_type", "Bearer")
    if not isinstance(token_type, str) or token_type.casefold() != "bearer":
        raise ValueError("Tipo de credencial no admitido")
    lifetime = payload.get("expires_in", 3600)
    if isinstance(lifetime, bool) or not isinstance(lifetime, (int, str)):
        raise ValueError("Vigencia inválida")
    lifetime = int(lifetime)
    if not 0 < lifetime <= 86400:
        raise ValueError("Vigencia inválida")
    if "refresh_token" in payload and (not isinstance(payload["refresh_token"], str)
            or not payload["refresh_token"] or any(character.isspace() for character in payload["refresh_token"])):
        raise ValueError("Credencial de renovación inválida")
    if "scope" in payload and (not isinstance(payload["scope"], str) or SCOPES[0] not in payload["scope"].split()):
        raise ValueError("Falta permiso de envío")
    tokens = dict(payload)
    tokens["expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds=lifetime)).isoformat()
    return tokens


async def oauth_callback(db: Database, state: str, code: str):
    if not db.settings.oauth_ready:
        raise HTTPException(503, "La integración de correo no está configurada.")
    if not state or not code or len(state) > 200 or len(code) > 4000:
        raise HTTPException(400, "La respuesta de Google no es válida.")
    saved = await db.rpc("consume_oauth_state", {"p_state_hash": hashlib.sha256(state.encode()).hexdigest(), "p_provider": "google"})
    if not saved:
        raise HTTPException(400, "La autorización venció o ya fue utilizada. Volvé a conectar el correo.")
    try:
        verifier = cipher(db).decrypt(saved["encrypted_verifier"].encode()).decode()
        response = await db.client.post("https://oauth2.googleapis.com/token", data={"client_id": db.settings.google_client_id,
            "client_secret": db.settings.google_client_secret, "redirect_uri": saved["redirect_uri"], "code": code,
            "code_verifier": verifier, "grant_type": "authorization_code"})
        response.raise_for_status()
        tokens = provider_tokens(response.json())
        info = await db.client.get("https://openidconnect.googleapis.com/v1/userinfo", headers={"Authorization": f"Bearer {tokens['access_token']}"})
        info.raise_for_status()
        identity = info.json()
        if (not isinstance(identity, dict) or identity.get("email_verified") is not True
                or not isinstance(identity.get("email"), str) or not identity["email"].strip()):
            raise ValueError("Correo no verificado")
        scope = tokens.get("scope", "")
        if not isinstance(scope, str):
            raise ValueError("Permisos no válidos")
        granted = scope.split()
        if SCOPES[0] not in granted:
            raise ValueError("Falta permiso de envío")
    except (httpx.HTTPError, ValueError, KeyError, TypeError, InvalidToken):
        raise HTTPException(502, "Google no confirmó la conexión del correo. No se envió ningún mensaje.")
    existing = await db.select("email_connections", None, params={"user_id": f"eq.{saved['user_id']}", "provider": "eq.google", "email": f"eq.{identity['email']}", "limit": "1"})
    connection_id = existing[0]["id"] if existing else str(uuid4())
    if existing and not tokens.get("refresh_token"):
        # Google can omit a refresh token on a later authorization. Keep the
        # credential belonging to this exact user/account instead of replacing
        # a working offline connection with one that expires after an hour.
        previous = await db.rpc("get_email_secret", {"p_connection_id": connection_id,
            "p_user_id": saved["user_id"]})
        if previous:
            try:
                old = json.loads(cipher(db).decrypt(previous["encrypted_payload"].encode()))
                refresh = old.get("refresh_token") if isinstance(old, dict) else None
                if isinstance(refresh, str) and refresh and not any(character.isspace() for character in refresh):
                    tokens["refresh_token"] = refresh
            except (InvalidToken, ValueError, KeyError, TypeError):
                raise HTTPException(409, "No se pudo conservar la conexión anterior. Volvé a conectar tu correo.") from None
    data = {"id": connection_id, "user_id": saved["user_id"], "provider": "google", "email": identity["email"],
        "status": "disconnected", "scopes": granted}
    if existing:
        await db.patch("email_connections", data, params={"id": f"eq.{connection_id}", "user_id": f"eq.{saved['user_id']}"})
    else:
        await db.insert("email_connections", data)
    await store_tokens(db, connection_id, saved["user_id"], tokens)
    connected = await db.patch("email_connections", {"status": "connected",
        "connected_at": datetime.now(timezone.utc).isoformat(), "revoked_at": None},
        params={"id": f"eq.{connection_id}", "user_id": f"eq.{saved['user_id']}"})
    if not connected:
        raise HTTPException(502, "No se confirmó el registro de la conexión. Volvé a conectar tu correo.")
    return {"connected": True, "message": "Correo conectado. Volvé a Trabajo YA. Ningún envío fue autorizado por esta conexión."}


async def access_token(db: Database, connection: dict, user_id: str):
    saved = await db.rpc("get_email_secret", {"p_connection_id": connection["id"], "p_user_id": user_id})
    if not saved:
        raise HTTPException(409, "Volvé a conectar tu correo para enviar.")
    try:
        tokens = json.loads(cipher(db).decrypt(saved["encrypted_payload"].encode()))
        if (not isinstance(tokens, dict) or not isinstance(tokens.get("access_token"), str)
                or not tokens["access_token"] or any(character.isspace() for character in tokens["access_token"])):
            raise ValueError("Credenciales inválidas")
        expiry = datetime.fromisoformat(tokens["expires_at"])
        if expiry.tzinfo is None:
            raise ValueError("Vigencia sin zona horaria")
    except (InvalidToken, ValueError, KeyError, TypeError):
        raise HTTPException(409, "No se pudo recuperar la conexión. Volvé a conectar tu correo.")
    if expiry > datetime.now(timezone.utc) + timedelta(minutes=1):
        return tokens["access_token"]
    if not tokens.get("refresh_token"):
        raise HTTPException(409, "La conexión venció. Volvé a conectar el correo.")
    try:
        response = await db.client.post("https://oauth2.googleapis.com/token", data={"client_id": db.settings.google_client_id,
            "client_secret": db.settings.google_client_secret, "grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]})
        response.raise_for_status()
        update = provider_tokens(response.json())
        tokens.update(update)
        await store_tokens(db, connection["id"], user_id, tokens)
        return tokens["access_token"]
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        raise HTTPException(409, "Google no renovó la conexión. Volvé a conectar tu correo.")


def verified_recipient(application: dict, job: dict):
    recipient = application.get("recipient_email")
    if not recipient or recipient.strip().casefold() != (job.get("recipient_email") or "").strip().casefold() or not job.get("recipient_verified_at") or not job.get("source_authorized") or job.get("is_active") is False:
        raise HTTPException(409, "El destinatario no está verificado por una fuente autorizada. Prepará la postulación manualmente.")
    if any(c in recipient for c in "\r\n<>"):
        raise HTTPException(409, "El destinatario no es válido.")


async def record_cancelled_attempt(db: Database, attempt_params: dict, *, delivery_uncertain: bool):
    error = (
        "Se interrumpió la espera del proveedor. El resultado es incierto; no se reintentará automáticamente."
        if delivery_uncertain else
        "Se interrumpió la preparación. No se contactó al servicio de envío; no se reintentará automáticamente."
    )
    try:
        # The worker's deadline cancels the send task. Preserve this bounded
        # database write while cancellation propagates back to the worker.
        await asyncio.shield(db.patch("applications", {"status": "error", "delivery_uncertain": delivery_uncertain,
            "error": error}, params=attempt_params))
    except HTTPException:
        logger.error("No se registró interrupción del intento application=%s attempt=%s",
            attempt_params["id"], attempt_params["send_attempt_id"])


async def send_application(db: Database, user: User, application_id: str, *, manual: bool, acknowledgment=None):
    if not db.settings.mail_send_enabled:
        raise HTTPException(503, "Los envíos reales están desactivados. La postulación permanece pendiente; no se envió ningún correo.")
    if manual and acknowledgment != "Enviar esta postulación":
        raise HTTPException(403, "Hace falta autorizar esta postulación expresamente.")
    application = await db.owned("applications", application_id, user, service=True)
    if application.get("status") in ("sent", "responded"):
        return application
    if application.get("send_attempt_id"):
        raise HTTPException(409, "Esta postulación ya tiene un intento de envío. Revisá el historial; no se reintentará automáticamente.")
    if not application.get("email_connection_id") or not application.get("resume_id"):
        raise HTTPException(409, "Seleccioná un correo conectado y un currículum antes de enviar.")
    # Reserve before any asynchronous preparation. The conditional draft PATCH
    # rejects edits after this point, and the RPC returns the frozen row actually
    # authorized. Never compose from the earlier, potentially stale read.
    claimed = await db.rpc("claim_application_send", {"p_application_id": application_id, "p_user_id": user.id,
        "p_explicit_manual_consent": manual, "p_manual_approval_text": acknowledgment})
    if not claimed:
        raise HTTPException(409, "No se autorizó el envío: revisá consentimiento, límite diario o un intento previo.")
    attempt_params = {"id": f"eq.{application_id}", "user_id": f"eq.{user.id}",
        "send_attempt_id": f"eq.{claimed['send_attempt_id']}"}
    try:
        job = await db.owned("jobs", claimed["job_id"], user, service=True)
        verified_recipient(claimed, job)
        connection = await db.owned("email_connections", claimed["email_connection_id"], user, service=True)
        if connection.get("provider") != "google" or connection.get("status") != "connected":
            raise HTTPException(409, "Esta conexión de correo no puede enviar mensajes.")
        resume = await db.owned("resume_versions", claimed["resume_id"], user, service=True)
        attachment = await download_resume(db, user, resume, service=True)
        token = await access_token(db, connection, user.id)
        message = EmailMessage()
        sender = claimed.get("sender_email") or connection["email"]
        if sender.strip().casefold() != connection["email"].strip().casefold():
            raise HTTPException(409, "La conexión de correo cambió después de reservar el envío.")
        message["From"] = sender
        message["To"] = claimed["recipient_email"]
        message["Subject"] = claimed["subject"]
        message.set_content(claimed["body"])
        subtype = "pdf" if resume["mime_type"] == "application/pdf" else "vnd.openxmlformats-officedocument.wordprocessingml.document"
        message.add_attachment(attachment, maintype="application", subtype=subtype, filename=resume["original_filename"])
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    except asyncio.CancelledError:
        await record_cancelled_attempt(db, attempt_params, delivery_uncertain=False)
        raise
    except (HTTPException, ValueError, KeyError, TypeError):
        # Preparation failed before Gmail's send endpoint was contacted. Keep
        # the attempt reserved; a worker restart must not turn it into a retry.
        await db.patch("applications", {"status": "error", "delivery_uncertain": False,
            "error": "No se pudo preparar la postulación. No se contactó al servicio de envío y no se reintentará automáticamente."},
            params=attempt_params)
        raise HTTPException(409, "No se pudo preparar la postulación. No se contactó al servicio de envío; revisá el historial. No se reintentará automáticamente.")
    try:
        response = await db.client.post("https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            headers={"Authorization": f"Bearer {token}"}, json={"raw": raw}, timeout=45)
        response.raise_for_status()
        payload = response.json()
        provider_id = payload.get("id") if isinstance(payload, dict) else None
        if not isinstance(provider_id, str) or not provider_id.strip():
            raise ValueError("Sin comprobante")
    except asyncio.CancelledError:
        # Gmail may already have accepted the message even though the worker
        # deadline prevented receiving the receipt. The reservation survives.
        await record_cancelled_attempt(db, attempt_params, delivery_uncertain=True)
        raise
    except (httpx.HTTPError, ValueError):
        # A timeout or 5xx may have delivered mail. No retry, even on process restart.
        await db.patch("applications", {"status": "error", "delivery_uncertain": True,
            "error": "El proveedor no entregó una confirmación verificable. El resultado es incierto; no se reintentará automáticamente."},
            params=attempt_params)
        raise HTTPException(502, "No hay confirmación del proveedor. El resultado es incierto y no se reintentará automáticamente.")
    now = datetime.now(timezone.utc).isoformat()
    try:
        updated = await db.patch("applications", {"status": "sent", "provider_message_id": provider_id,
            "provider_confirmed_at": now, "sent_at": now, "error": None, "delivery_uncertain": False},
            params=attempt_params)
        if not updated:
            raise HTTPException(502, "No se pudo registrar la confirmación.")
        return updated[0]
    except HTTPException:
        logger.error("Proveedor confirmó envío; reconciliación necesaria application_id=%s provider_id=%s", application_id, provider_id)
        raise HTTPException(502, "El proveedor confirmó el envío, pero falló el registro del historial. No vuelvas a enviarlo; la confirmación requiere revisión.")

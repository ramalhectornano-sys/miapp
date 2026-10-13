from datetime import datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchProposal(StrictModel):
    title: str = Field(min_length=1, max_length=160)
    role: str = Field(min_length=1, max_length=120)
    city: str = Field(min_length=1, max_length=120)
    frequency: Literal["daily", "weekly"] = "daily"
    time: str = "09:00"
    timezone: str = "America/Argentina/Buenos_Aires"
    weekdays: list[int] = Field(default_factory=lambda: [1, 2, 3, 4, 5, 6, 7], min_length=1, max_length=7)
    mode: Literal["manual", "automatic"] = "manual"
    resume_id: UUID | None = None

    @field_validator("time")
    @classmethod
    def valid_time(cls, value):
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
            raise ValueError("Usá un horario válido HH:MM.")
        return value

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Zona horaria desconocida.")
        return value

    @field_validator("weekdays")
    @classmethod
    def valid_weekdays(cls, value):
        if any(day < 1 or day > 7 for day in value):
            raise ValueError("Los días usan ISO: lunes 1 a domingo 7.")
        return sorted(set(value))


class ChatTurn(StrictModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class ChatRequest(StrictModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=12)


class ChatResponse(StrictModel):
    reply: str
    proposal: SearchProposal | None = None
    mode: Literal["demo", "live"]


class SearchPatch(StrictModel):
    status: Literal["enabled", "paused"] | None = None
    time: str | None = None
    timezone: str | None = None
    frequency: Literal["daily", "weekly"] | None = None
    weekdays: list[int] | None = None
    resume_id: UUID | None = None

    @field_validator("time")
    @classmethod
    def valid_time(cls, value):
        return SearchProposal.valid_time(value) if value is not None else value

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        return SearchProposal.valid_timezone(value) if value is not None else value

    @field_validator("weekdays")
    @classmethod
    def valid_weekdays(cls, value):
        if value == []:
            raise ValueError("Seleccioná al menos un día.")
        return SearchProposal.valid_weekdays(value) if value is not None else value


class SendRequest(StrictModel):
    consent: Literal[True]
    acknowledgment: Literal["Enviar esta postulación"]


class ApplicationPatch(StrictModel):
    subject: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, min_length=1, max_length=10000)
    resume_id: UUID | None = None
    email_connection_id: UUID | None = None

    @field_validator("subject")
    @classmethod
    def no_header_injection(cls, value):
        if value and any(c in value for c in "\r\n"):
            raise ValueError("El asunto no puede contener saltos de línea.")
        return value


class ConsentRequest(StrictModel):
    search_id: UUID
    resume_id: UUID
    email_connection_id: UUID
    allowed_sources: list[str] = Field(min_length=1, max_length=20)
    expires_at: datetime
    # Old clients keep their original single-delivery authorization. Only the
    # separate, explicit repeat choice can grant the broader v3 policy.
    repeat_every_days: Literal[0, 3] = 0
    acknowledgment: Literal[
        "Autorizo los envíos automáticos de esta búsqueda",
        "Autorizo los envíos automáticos de esta búsqueda y los recordatorios cada 3 días, con un máximo total de 10 correos por día",
    ]

    @model_validator(mode="after")
    def future_expiry(self):
        from datetime import timezone, timedelta
        if self.expires_at.tzinfo is None:
            raise ValueError("La fecha debe incluir zona horaria.")
        now = datetime.now(timezone.utc)
        if not now < self.expires_at <= now + timedelta(days=90):
            raise ValueError("La autorización debe vencer dentro de los próximos 90 días.")
        expected = ("Autorizo los envíos automáticos de esta búsqueda y los recordatorios cada 3 días, con un máximo total de 10 correos por día"
            if self.repeat_every_days == 3 else "Autorizo los envíos automáticos de esta búsqueda")
        if self.acknowledgment != expected:
            raise ValueError("La autorización debe coincidir con la opción de recordatorios elegida.")
        return self


class StopFollowupsRequest(StrictModel):
    reason: Literal["user_request", "responded"] = "user_request"

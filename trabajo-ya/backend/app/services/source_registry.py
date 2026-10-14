"""Configured search integrations; a search result never attests an email."""

WEB_SOURCE_ID = "web:tavily"
GREENHOUSE_SOURCE_ID = "verified:greenhouse"
RESERVED_SOURCE_IDS = frozenset({WEB_SOURCE_ID, GREENHOUSE_SOURCE_ID})


def configured_sources(settings):
    sources = [dict(source) for source in settings.authorized_feeds
        if isinstance(source, dict) and source.get("id") and source.get("authorized")
        and source.get("id") not in RESERVED_SOURCE_IDS
        and source.get("kind") not in {"web_search", "greenhouse_verified"}]
    if settings.web_search_ready:
        sources = sources[:18]
        sources.append({"id": GREENHOUSE_SOURCE_ID, "name": "Ofertas verificadas de Greenhouse",
            "kind": "greenhouse_verified", "authorized": True,
            "recipient_verification": "source_attestation",
            "description": "Verifica ofertas descubiertas en Greenhouse mediante su API oficial. Solo admite correo cuando la oferta vigente publica expresamente una dirección para enviar el CV; los formularios y otros portales requieren revisión manual."})
        sources.append({"id": WEB_SOURCE_ID, "name": "Búsqueda en Internet",
            "kind": "web_search", "authorized": True,
            "recipient_verification": "manual_review",
            "description": "Busca vacantes en distintos sitios. Los enlaces y correos encontrados requieren revisión; el buscador no verifica destinatarios."})
    return sources[:20]


def public_source(source):
    automatic_email = (source.get("kind") != "web_search"
        and source.get("id") != WEB_SOURCE_ID
        and source.get("recipient_verification") == "source_attestation")
    if source.get("kind") == "greenhouse_verified" or source.get("id") == GREENHOUSE_SOURCE_ID:
        automatic_email = (automatic_email and source.get("kind") == "greenhouse_verified"
            and source.get("id") == GREENHOUSE_SOURCE_ID)
    return {"id": source["id"], "name": str(source.get("name") or source["id"]),
        "description": str(source.get("description") or "")[:500],
        "supports_automatic_email": automatic_email}

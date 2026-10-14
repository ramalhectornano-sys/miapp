"""Configured search integrations; a search result never attests an email."""

WEB_SOURCE_ID = "web:tavily"


def configured_sources(settings):
    sources = [dict(source) for source in settings.authorized_feeds
        if isinstance(source, dict) and source.get("id") and source.get("authorized")
        and source.get("id") != WEB_SOURCE_ID]
    if settings.web_search_ready:
        sources = sources[:19]
        sources.append({"id": WEB_SOURCE_ID, "name": "Búsqueda en Internet",
            "kind": "web_search", "authorized": True,
            "recipient_verification": "manual_review",
            "description": "Busca vacantes en distintos sitios. Los enlaces y correos encontrados requieren revisión; el buscador no verifica destinatarios."})
    return sources[:20]


def public_source(source):
    return {"id": source["id"], "name": str(source.get("name") or source["id"]),
        "description": str(source.get("description") or "")[:500],
        "supports_automatic_email": source.get("kind") != "web_search"
            and source.get("recipient_verification") == "source_attestation"}

"""Configuration is server-only; no secret belongs in the Expo bundle."""
from dataclasses import dataclass, field
import json
import os


@dataclass
class Settings:
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    ai_provider: str = "demo"
    ai_base_url: str = "http://localhost:11434"
    ai_model: str = "qwen2.5:7b"
    ai_api_key: str = ""
    default_timezone: str = "America/Argentina/Buenos_Aires"
    cors_origins: list[str] = field(default_factory=list)
    authorized_feeds: list[dict] = field(default_factory=list)
    web_search_provider: str = ""
    web_search_api_key: str = ""
    web_search_max_queries: int = 2
    geocoder_provider: str = "georef_ar"
    public_page_reads_enabled: bool = True
    public_page_max_reads: int = 6
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/mail/google/callback"
    token_encryption_key: str = ""
    mail_send_enabled: bool = False
    max_resume_bytes: int = 10 * 1024 * 1024
    worker_batch_size: int = 10

    @classmethod
    def from_env(cls):
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
        def json_env(name, default):
            return json.loads(os.getenv(name, json.dumps(default)))
        return cls(
            supabase_url=os.getenv("SUPABASE_URL", "").rstrip("/"),
            supabase_anon_key=os.getenv("SUPABASE_ANON_KEY", ""),
            supabase_service_role_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""),
            ai_provider=os.getenv("AI_PROVIDER", "demo"),
            ai_base_url=os.getenv("AI_BASE_URL", "http://localhost:11434").rstrip("/"),
            ai_model=os.getenv("AI_MODEL", "qwen2.5:7b"),
            ai_api_key=os.getenv("AI_API_KEY", ""),
            default_timezone=os.getenv("DEFAULT_TIMEZONE", "America/Argentina/Buenos_Aires"),
            cors_origins=json_env("CORS_ORIGINS", []),
            authorized_feeds=json_env("AUTHORIZED_JOB_FEEDS", []),
            web_search_provider=os.getenv("WEB_SEARCH_PROVIDER", "").strip().lower(),
            web_search_api_key=os.getenv("WEB_SEARCH_API_KEY", "").strip(),
            web_search_max_queries=min(max(int(os.getenv("WEB_SEARCH_MAX_QUERIES", "6")), 1), 12),
            geocoder_provider=os.getenv("GEOCODER_PROVIDER", "georef_ar").strip().lower(),
            public_page_reads_enabled=os.getenv("PUBLIC_PAGE_READS_ENABLED", "true").lower() == "true",
            public_page_max_reads=min(max(int(os.getenv("PUBLIC_PAGE_MAX_READS", "6")), 1), 6),
            google_client_id=os.getenv("GOOGLE_CLIENT_ID", ""),
            google_client_secret=os.getenv("GOOGLE_CLIENT_SECRET", ""),
            google_redirect_uri=os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/mail/google/callback"),
            token_encryption_key=os.getenv("TOKEN_ENCRYPTION_KEY", ""),
            mail_send_enabled=os.getenv("MAIL_SEND_ENABLED", "false").lower() == "true",
            worker_batch_size=min(max(int(os.getenv("WORKER_BATCH_SIZE", "10")), 1), 50),
        )

    @property
    def auth_ready(self):
        return bool(self.supabase_url and self.supabase_anon_key)

    @property
    def oauth_ready(self):
        return bool(self.google_client_id and self.google_client_secret and self.token_encryption_key and self.supabase_service_role_key)

    @property
    def web_search_ready(self):
        return self.web_search_provider == "tavily" and bool(self.web_search_api_key)

    @property
    def job_sources(self):
        from .services.source_registry import configured_sources
        return configured_sources(self)

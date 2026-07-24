"""Application settings.

All values have dev defaults so the app imports (and unit tests run) without a
real environment. Production deploys set the env vars listed in CONTRACTS.md.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: str = "dev"
    log_level: str = "INFO"

    supabase_url: str = "http://127.0.0.1:54321"
    database_url: str = "postgresql+asyncpg://postgres:postgres@127.0.0.1:54322/postgres"

    anthropic_api_key: str = ""
    chat_model: str = "claude-sonnet-5"
    safety_model: str = "claude-haiku-4-5-20251001"

    allowed_origins: str = "http://localhost:3000"

    # Phase 2 (Vapi custom-LLM endpoint). Empty means the endpoint is disabled
    # outside dev. TODO(Phase 2): provision per-environment secret for Vapi.
    vapi_shared_secret: str = ""

    @property
    def is_dev(self) -> bool:
        return self.env == "dev"

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def jwks_url(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()

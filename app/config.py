"""Application configuration.

All settings are read from environment variables (or a local .env file) via
pydantic-settings, so no secrets ever live in the source tree. Field names map
to env vars case-insensitively, e.g. `google_api_key` <- `GOOGLE_API_KEY`.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # LLM provider: Google Gemini (free cloud tier) via LangChain.
    google_api_key: str = ""
    llm_model: str = "gemini-2.5-flash"

    # API security: value required in the X-API-Key header for write operations.
    api_key: str = "dev-secret-key"

    # Database (defaults match the docker-compose "db" service).
    database_url: str = "postgresql+psycopg2://asm:asm@db:5432/asm"

    # Behaviour tuning.
    expiring_soon_days: int = 30
    default_org_id: str = "default"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


# Single shared settings instance imported across the app.
settings = Settings()

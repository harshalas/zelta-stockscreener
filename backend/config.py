from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_url: str = Field(alias="POSTGRES_URL")
    redis_url: str = Field("redis://localhost:6379/0", alias="REDIS_URL")
    finnhub_api_key: str | None = Field(None, alias="FINNHUB_API_KEY")
    openai_api_key: str | None = Field(None, alias="OPENAI_API_KEY")
    supabase_url: str | None = Field(None, alias="SUPABASE_URL")
    supabase_jwt_audience: str = Field("authenticated", alias="SUPABASE_JWT_AUDIENCE")
    # Deliberately a plain str, not list[str]. pydantic-settings tries to
    # JSON-decode any env/dotenv value bound to a list-typed field *before*
    # a field_validator ever sees it -- a `mode="before"` validator here
    # cannot intercept that. A bare comma-separated value (exactly what
    # .env.example documents: CORS_ORIGINS=http://localhost:3000) is not
    # valid JSON, so the old list[str] field raised SettingsError on every
    # startup and took the whole API down with it. Parsing it ourselves in
    # the `cors_origins` property below sidesteps pydantic-settings' decoder
    # entirely.
    cors_origins_raw: str = Field("http://localhost:3000", alias="CORS_ORIGINS")
    market_data_timeout_seconds: float = Field(15, alias="MARKET_DATA_TIMEOUT_SECONDS", gt=0)
    news_timeout_seconds: float = Field(10, alias="NEWS_TIMEOUT_SECONDS", gt=0)

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins_raw.split(",") if origin.strip()]

    @property
    def supabase_jwks_url(self) -> str | None:
        if not self.supabase_url:
            return None
        return f"{self.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()

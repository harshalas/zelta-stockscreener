"""Regression test for a real startup bug: Settings() used to crash on the
exact CORS_ORIGINS value backend/.env.example tells every new developer to
use, because pydantic-settings tries to JSON-decode any env value bound to
a list[str] field before a field_validator can intervene. See config.py's
comment on `cors_origins_raw` for the full story.
"""

from config import Settings


def _settings(**env_overrides) -> Settings:
    # Bypass the real .env file/lru_cache entirely so this test only
    # depends on the env vars it explicitly sets.
    defaults = {"POSTGRES_URL": "postgresql://user:pass@localhost:5432/db"}
    return Settings(_env_file=None, **{**defaults, **env_overrides})


def test_settings_load_with_the_exact_value_env_example_documents():
    settings = _settings(CORS_ORIGINS="http://localhost:3000")
    assert settings.cors_origins == ["http://localhost:3000"]


def test_settings_parse_multiple_comma_separated_origins():
    settings = _settings(CORS_ORIGINS="https://app.example.com, https://admin.example.com")
    assert settings.cors_origins == ["https://app.example.com", "https://admin.example.com"]


def test_settings_default_cors_origin_when_unset():
    settings = _settings()
    assert settings.cors_origins == ["http://localhost:3000"]

"""Конфигурация приложения. Значения читаются из переменных окружения и файла .env."""
from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # SecretStr не попадёт в логи / repr случайно.
    anthropic_api_key: SecretStr
    anthropic_model: str = "claude-sonnet-5-5"
    anthropic_max_tokens: int = 8000
    anthropic_timeout_s: float = 90.0
    anthropic_max_retries: int = 2  # ретраи сети / 429 / 5xx внутри самого SDK

    max_requirements_chars: int = 10_000


@lru_cache
def get_settings() -> Settings:
    return Settings()

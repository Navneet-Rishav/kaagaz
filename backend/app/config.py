"""All configuration comes from environment variables, validated once at startup (pydantic-settings)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+psycopg://postgres@localhost:5432/kaagaz"
    jwt_secret: str = Field(min_length=32)
    jwt_expires_minutes: int = 8 * 60
    cors_origins: str = "http://localhost:5173"

    # "demo" runs everything offline with a rule-based provider (tests, CI, no API key); "sarvam" calls the real APIs.
    ai_provider: Literal["demo", "sarvam"] = "demo"
    sarvam_api_key: str | None = None
    sarvam_chat_model: str = "sarvam-105b"
    sarvam_reasoning_effort: Literal["none", "low", "medium", "high", "max"] | None = None

    # Upload limits
    max_upload_mb: int = 10
    max_pages: int = 30
    # A PDF page with at least this many characters of text layer is used as-is (no OCR).
    min_text_chars_per_page: int = 80

    # Per-user rate limits on endpoints that call paid APIs (requests per hour).
    ask_per_hour: int = 30
    upload_per_hour: int = 10
    voice_per_hour: int = 30

    worker_poll_seconds: float = 2.0
    run_worker: bool = True

    @field_validator("sarvam_reasoning_effort", mode="before")
    @classmethod
    def _empty_is_none(cls, v: object) -> object:
        return v or None

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def check(self) -> "Settings":
        if self.ai_provider == "sarvam" and not self.sarvam_api_key:
            raise ValueError("AI_PROVIDER=sarvam requires SARVAM_API_KEY")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings().check()  # type: ignore[call-arg]

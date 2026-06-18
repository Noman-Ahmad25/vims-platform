from __future__ import annotations

import secrets
from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import AnyUrl, BeforeValidator, PostgresDsn, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _parse_cors(v: Any) -> list[str]:
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        return [origin.strip() for origin in v.split(",") if origin.strip()]
    raise ValueError(f"Invalid CORS origins value: {v!r}")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        case_sensitive=False,
    )

    # ── Application ───────────────────────────────────────────────────────────
    APP_NAME: str = "Volunteer Information Management System"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"

    # ── Security ──────────────────────────────────────────────────────────────
    SECRET_KEY: str = secrets.token_urlsafe(64)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ── Database ──────────────────────────────────────────────────────────────
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "volunteer_db"

    SQLALCHEMY_POOL_SIZE: int = 10
    SQLALCHEMY_MAX_OVERFLOW: int = 20
    SQLALCHEMY_POOL_TIMEOUT: int = 30
    SQLALCHEMY_POOL_RECYCLE: int = 1800
    SQLALCHEMY_ECHO: bool = False

    # ── CORS ──────────────────────────────────────────────────────────────────
    BACKEND_CORS_ORIGINS: Annotated[list[str], BeforeValidator(_parse_cors)] = [
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:8080",
    ]

    # ── Email (optional) ──────────────────────────────────────────────────────
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    EMAILS_FROM_NAME: str = "VIMS Platform"
    EMAILS_FROM_EMAIL: str = "noreply@vims.example.com"

    # ── Pagination ────────────────────────────────────────────────────────────
    DEFAULT_PAGE_SIZE: int = 20
    MAX_PAGE_SIZE: int = 100

    # ── Computed ──────────────────────────────────────────────────────────────
    @computed_field
    @property
    def ASYNC_DATABASE_URL(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @computed_field
    @property
    def SYNC_DATABASE_URL(self) -> str:
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @model_validator(mode="after")
    def _production_checks(self) -> "Settings":
        if self.ENVIRONMENT == "production":
            if self.SECRET_KEY == secrets.token_urlsafe(64):
                raise ValueError("SECRET_KEY must be explicitly set in production.")
            if self.DEBUG:
                raise ValueError("DEBUG must be False in production.")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
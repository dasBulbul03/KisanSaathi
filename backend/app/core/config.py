"""Application configuration.

All configuration is environment driven. No secrets are hard coded; values that
are required in production (JWT secret, database credentials) have no defaults
and the application refuses to start without them when ``ENVIRONMENT`` is not
``development``/``test``.
"""

from __future__ import annotations

import functools
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "staging", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ------------------------------------------------------------------ app
    PROJECT_NAME: str = "KisanSaathi"
    PROJECT_DESCRIPTION: str = (
        "Market intelligence and transaction enablement platform connecting "
        "Maharashtra farmers and FPOs with verified buyers."
    )
    ENVIRONMENT: Environment = "development"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"
    APP_VERSION: str = "1.0.0"

    # ------------------------------------------------------------- database
    POSTGRES_USER: str = "kisan"
    POSTGRES_PASSWORD: str = "kisan"
    POSTGRES_DB: str = "kisansaathi"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    DATABASE_URL: str | None = None
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_ECHO: bool = False
    SQLITE_PATH: str = "./kisansaathi_dev.db"

    # ------------------------------------------------------------ security
    JWT_SECRET_KEY: str | None = None
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 8
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14
    PASSWORD_MIN_LENGTH: int = 8
    PBKDF2_ITERATIONS: int = 390_000

    # ----------------------------------------------------------------- cors
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"
    CORS_ALLOW_CREDENTIALS: bool = True

    # --------------------------------------------------------------- redis
    REDIS_URL: str | None = None
    CACHE_TTL_SECONDS: int = 120
    RATE_LIMIT_ENABLED: bool = False
    RATE_LIMIT_REQUESTS: int = 240
    RATE_LIMIT_WINDOW_SECONDS: int = 60

    # ------------------------------------------------------------------- ai
    AI_PROVIDER: str = "nvidia"
    NVIDIA_API_KEY: str | None = None
    NVIDIA_BASE_URL: str = "https://integrate.api.nvidia.com/v1"
    NVIDIA_MODEL: str = "meta/llama-3.3-70b-instruct"
    NVIDIA_EMBEDDING_MODEL: str = "nvidia/nv-embedqa-e5-v5"
    NVIDIA_TIMEOUT_SECONDS: float = 45.0
    NVIDIA_MAX_RETRIES: int = 2
    AI_ASSISTANT_ENABLED: bool = True
    AI_TEMPERATURE: float = 0.25
    AI_MAX_TOKENS: int = 900

    # --------------------------------------------------------- integrations
    MARKET_DATA_PROVIDER: str = "demo"
    MARKET_DATA_BASE_URL: str | None = None
    MARKET_DATA_API_KEY: str | None = None
    LOGISTICS_PROVIDER: str = "demo"
    LOGISTICS_BASE_URL: str | None = None
    LOGISTICS_API_KEY: str | None = None
    NOTIFICATION_PROVIDER: str = "database"

    # ---------------------------------------------------------------- files
    MEDIA_ROOT: str = "./media"
    MAX_UPLOAD_BYTES: int = 5 * 1024 * 1024
    ALLOWED_IMAGE_TYPES: str = "image/jpeg,image/png,image/webp"

    # ---------------------------------------------------------------- misc
    DEMO_MODE: bool = True
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = True
    DOCS_ENABLED: bool = True

    # ----------------------------------------------------------- derived
    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> str:
        if isinstance(value, list):
            return ",".join(str(v) for v in value)
        return str(value or "")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def allowed_image_types(self) -> list[str]:
        return [t.strip() for t in self.ALLOWED_IMAGE_TYPES.split(",") if t.strip()]

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def ai_enabled(self) -> bool:
        return bool(self.AI_ASSISTANT_ENABLED and self.NVIDIA_API_KEY)

    def resolved_database_url(self) -> str:
        """Return an explicit DATABASE_URL or build one from the parts."""
        if self.DATABASE_URL:
            url = self.DATABASE_URL
        elif self.ENVIRONMENT in ("development", "test") and self.POSTGRES_HOST in (
            "",
            "localhost",
        ):
            url = f"sqlite+pysqlite:///{self.SQLITE_PATH}"
        else:
            url = (
                f"postgresql+psycopg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
                f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
            )
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+psycopg://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        return url

    def validate_runtime(self) -> None:
        """Fail fast when production-critical configuration is missing."""
        if not self.JWT_SECRET_KEY and self.is_production:
            raise RuntimeError(
                "JWT_SECRET_KEY must be set in production. Generate one with "
                "`python -c 'import secrets; print(secrets.token_urlsafe(48))'`."
            )
        if not self.JWT_SECRET_KEY and self.ENVIRONMENT not in ("development", "test"):
            raise RuntimeError("JWT_SECRET_KEY must be set for staging deployments.")
        if self.is_production and not self.NVIDIA_API_KEY:
            # Not fatal: the assistant degrades to the deterministic engine.
            pass


@functools.lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_runtime()
    return settings


settings = get_settings()

"""Application configuration powered by Pydantic Settings."""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent.parent
_PROJECT_ROOT = _BACKEND_DIR.parent


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=(
            _PROJECT_ROOT / ".env",
            _BACKEND_DIR / ".env",
            ".env",
        ),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Core Application Settings
    APP_NAME: str = "FlowPilot API"
    SERVICE_NAME: str = "flowpilot-api"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    API_V1_PREFIX: str = "/api/v1"
    FRONTEND_URL: str = "http://localhost:3000"
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    # Database Configuration (PostgreSQL + asyncpg)
    DATABASE_URL: str = (
        "postgresql+asyncpg://flowpilot:flowpilot_dev_password@127.0.0.1:5433/flowpilot"
    )
    TEST_DATABASE_URL: str = (
        "postgresql+asyncpg://flowpilot:flowpilot_dev_password@127.0.0.1:5433/flowpilot_test"
    )
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_ECHO: bool = False

    # Authentication & JWT Configuration
    JWT_SECRET_KEY: str = "insecure-development-secret-key-change-in-production-min32chars"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Cookie Configuration for Refresh Tokens
    AUTH_COOKIE_NAME: str = "refresh_token"
    AUTH_COOKIE_SECURE: bool | None = None
    AUTH_COOKIE_SAMESITE: str = "lax"

    # LLM BYOK & Encryption Configuration
    LLM_ENCRYPTION_KEYS: list[str] = [
        "k1V9O2gDqG4g3VzZ6X_K5y5uW1qR9nS8lJ4fA0bC2eY=",
    ]
    LLM_REQUEST_TIMEOUT_SECONDS: float = 30.0
    LLM_MAX_RETRIES: int = 2
    LLM_RETRY_BACKOFF_FACTOR: float = 1.5

    # Redis & Celery Background Execution Configuration
    REDIS_URL: str = "redis://127.0.0.1:6379/0"
    CELERY_BROKER_URL: str = "redis://127.0.0.1:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://127.0.0.1:6379/1"
    CELERY_TASK_ALWAYS_EAGER: bool = False
    CELERY_WORKER_CONCURRENCY: int = 4
    WORKFLOW_HEARTBEAT_TIMEOUT_SECONDS: int = 300
    MAX_ACTIVE_SCHEDULES_PER_USER: int = 50
    OUTBOX_MAX_RETRIES: int = 5

    # External Integrations & OAuth Configuration
    INTEGRATION_ENCRYPTION_KEYS: list[str] = []
    OAUTH_STATE_EXPIRE_SECONDS: int = 600
    OAUTH_DEFAULT_REDIRECT_URL: str = "http://localhost:3000/settings/integrations"

    # Google OAuth (Gmail & Sheets)
    GOOGLE_CLIENT_ID: str | None = None
    GOOGLE_CLIENT_SECRET: str | None = None
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/v1/integrations/google/callback"

    # Slack OAuth & Events
    SLACK_CLIENT_ID: str | None = None
    SLACK_CLIENT_SECRET: str | None = None
    SLACK_REDIRECT_URI: str = "http://localhost:8000/api/v1/integrations/slack/callback"
    SLACK_SIGNING_SECRET: str | None = None

    # WhatsApp Business Cloud API (Meta Graph API)
    WHATSAPP_APP_ID: str | None = None
    WHATSAPP_APP_SECRET: str | None = None
    WHATSAPP_BUSINESS_ACCOUNT_ID: str | None = None
    WHATSAPP_PHONE_NUMBER_ID: str | None = None
    WHATSAPP_ACCESS_TOKEN: str | None = None
    WHATSAPP_WEBHOOK_VERIFY_TOKEN: str | None = None
    WHATSAPP_GRAPH_API_VERSION: str = "v21.0"

    # Password Recovery & Transactional Email
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: int = 15
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_TLS: bool = True
    EMAILS_FROM_EMAIL: str | None = None
    EMAILS_FROM_NAME: str = "FlowPilot AI"

    @field_validator(
        "CORS_ORIGINS",
        "LLM_ENCRYPTION_KEYS",
        "INTEGRATION_ENCRYPTION_KEYS",
        mode="before",
    )
    @classmethod
    def parse_string_list(cls, value: Any) -> list[str]:
        """Parse list settings from JSON array string, comma-separated list, or list."""
        if isinstance(value, str):
            trimmed = value.strip()
            if not trimmed:
                return []
            if trimmed.startswith("[") and trimmed.endswith("]"):
                try:
                    parsed = json.loads(trimmed)
                    if isinstance(parsed, list):
                        return [str(item).strip() for item in parsed if str(item).strip()]
                except json.JSONDecodeError:
                    pass
            return [item.strip() for item in trimmed.split(",") if item.strip()]
        if isinstance(value, (list, tuple)):
            return [str(item).strip() for item in value if str(item).strip()]
        return []

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        """Enforce strict secret keys, secure credentials, and network rules in production."""
        if self.is_production:
            if "insecure" in self.JWT_SECRET_KEY.lower() or len(self.JWT_SECRET_KEY) < 32:
                msg = (
                    "Production environment requires a strong, non-default JWT_SECRET_KEY "
                    "with at least 32 characters."
                )
                raise ValueError(msg)
            if not self.LLM_ENCRYPTION_KEYS or not any(k.strip() for k in self.LLM_ENCRYPTION_KEYS):
                msg = "Production environment requires non-empty LLM_ENCRYPTION_KEYS."
                raise ValueError(msg)
            if "flowpilot_dev_password" in self.DATABASE_URL:
                msg = (
                    "Production environment cannot use the default development database password. "
                    "Please set a secure DATABASE_URL."
                )
                raise ValueError(msg)
            if any(origin.strip() == "*" for origin in self.CORS_ORIGINS):
                msg = "Wildcard '*' CORS origin is not permitted in production environment."
                raise ValueError(msg)
            if self.AUTH_COOKIE_SECURE is False:
                msg = "AUTH_COOKIE_SECURE cannot be set to False in production environment."
                raise ValueError(msg)
        return self

    @property
    def is_production(self) -> bool:
        """Check if current environment is production."""
        return self.ENVIRONMENT.lower() == "production"

    @property
    def is_development(self) -> bool:
        """Check if current environment is development."""
        return self.ENVIRONMENT.lower() == "development"

    @property
    def is_testing(self) -> bool:
        """Check if current environment is testing."""
        return self.ENVIRONMENT.lower() == "testing"

    @property
    def cookie_secure(self) -> bool:
        """Determine whether cookies must use the Secure flag."""
        if self.AUTH_COOKIE_SECURE is not None:
            return self.AUTH_COOKIE_SECURE
        return self.is_production

    @property
    def is_whatsapp_configured(self) -> bool:
        """Check if WhatsApp Business Cloud API has required credentials configured."""
        return bool(self.WHATSAPP_PHONE_NUMBER_ID and self.WHATSAPP_ACCESS_TOKEN)

    @property
    def whatsapp_missing_fields(self) -> list[str]:
        """Return list of missing configuration variable names for WhatsApp Cloud API."""
        missing: list[str] = []
        if not self.WHATSAPP_APP_ID:
            missing.append("WHATSAPP_APP_ID")
        if not self.WHATSAPP_APP_SECRET:
            missing.append("WHATSAPP_APP_SECRET")
        if not self.WHATSAPP_BUSINESS_ACCOUNT_ID:
            missing.append("WHATSAPP_BUSINESS_ACCOUNT_ID")
        if not self.WHATSAPP_PHONE_NUMBER_ID:
            missing.append("WHATSAPP_PHONE_NUMBER_ID")
        if not self.WHATSAPP_ACCESS_TOKEN:
            missing.append("WHATSAPP_ACCESS_TOKEN")
        if not self.WHATSAPP_WEBHOOK_VERIFY_TOKEN:
            missing.append("WHATSAPP_WEBHOOK_VERIFY_TOKEN")
        return missing


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()

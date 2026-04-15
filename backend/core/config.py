import os
from typing import Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application settings
    APP_NAME: str = "Spinr API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # Database settings
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    USE_SUPABASE: bool = True  # Supabase is now the default database

    # Firebase settings
    FIREBASE_SERVICE_ACCOUNT_JSON: Optional[str] = None

    # Security settings
    JWT_SECRET: str = "your-strong-secret-key"  # Default for development only
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # CORS settings
    # Comma-separated list of origins. Defaults to localhost dev ports so a
    # fresh deploy is not wide-open. Override in .env for staging/prod.
    # Set to "*" ONLY for local development — wildcard is rejected in production
    # (see core/middleware.init_middleware).
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:8081,http://localhost:19006"

    # Admin credentials
    # ADMIN_PASSWORD has no default — set it via the ADMIN_PASSWORD environment variable.
    # The application will refuse to start in production/staging if it is unset.
    ADMIN_EMAIL: str = "admin@spinr.ca"
    ADMIN_PASSWORD: Optional[str] = None

    @model_validator(mode="after")
    def _require_admin_password_in_prod(self) -> "Settings":
        if self.ENV.lower() not in ("development", "test") and not self.ADMIN_PASSWORD:
            raise ValueError(
                "ADMIN_PASSWORD must be set via environment variable in non-development environments. "
                "Set ADMIN_PASSWORD to a strong secret before deploying."
            )
        return self

    # Rate limiting
    RATE_LIMIT: str = "10/minute"

    # File storage
    STORAGE_BUCKET: str = "driver-documents"

    # Environment
    ENV: str = "development"

    @property
    def SECRET_KEY(self) -> str:
        return self.JWT_SECRET

    @property
    def debug(self) -> bool:
        return self.ENV.lower() == "development"


settings = Settings()

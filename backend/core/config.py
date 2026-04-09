from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator, model_validator
from typing import Optional
import os

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'),
        env_file_encoding='utf-8',
        extra='ignore'
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
    # JWT_SECRET has NO default — validation enforced in dependencies.py at startup.
    # In development, dependencies.py falls back to a named dev key.
    # In production, dependencies.py raises RuntimeError if this is absent or weak.
    JWT_SECRET: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # CORS settings
    # Leave blank — explicit origins are managed in core/middleware.py.
    # Set ALLOWED_ORIGINS to a comma-separated list of origins in production.
    ALLOWED_ORIGINS: str = ""

    # Admin credentials — NO defaults. Must be set via environment variables.
    # Leaving these empty in production will trigger a startup warning.
    ADMIN_EMAIL: str = ""
    ADMIN_PASSWORD: str = ""

    # Rate limiting
    RATE_LIMIT: str = "10/minute"

    # File storage
    STORAGE_BUCKET: str = "driver-documents"

    # Environment
    ENV: str = "development"

    @model_validator(mode='after')
    def validate_production_secrets(self) -> 'Settings':
        """Warn loudly if admin credentials are missing in production."""
        if self.ENV == 'production':
            import logging
            _log = logging.getLogger(__name__)
            if not self.ADMIN_EMAIL:
                _log.warning(
                    "SECURITY WARNING: ADMIN_EMAIL is not set. "
                    "Admin login will be unavailable until this env var is configured."
                )
            if not self.ADMIN_PASSWORD:
                _log.warning(
                    "SECURITY WARNING: ADMIN_PASSWORD is not set. "
                    "Admin login will be unavailable until this env var is configured."
                )
        return self

    @property
    def SECRET_KEY(self) -> str:
        return self.JWT_SECRET

    @property
    def debug(self) -> bool:
        return self.ENV.lower() == 'development'

settings = Settings()

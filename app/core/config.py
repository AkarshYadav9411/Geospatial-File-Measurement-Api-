"""
Application configuration loaded from environment variables.

Uses pydantic-settings for validated, typed configuration with sensible defaults.
All sensitive or deployment-specific values are read from .env or environment variables.
"""

from pathlib import Path
from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings with environment variable loading."""

    # Application
    app_name: str = "GeoMeasure API"
    app_version: str = "1.0.0"
    app_env: str = "development"
    debug: bool = False

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Database
    database_url: str = "sqlite:///./storage/geomeasure.db"

    # File Upload
    upload_dir: str = "./storage/uploads"
    max_upload_size_mb: int = 50
    allowed_extensions: str = ".zip,.kml"

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"

    @property
    def max_upload_size_bytes(self) -> int:
        """Maximum upload size in bytes."""
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def allowed_extensions_list(self) -> list[str]:
        """List of allowed file extensions."""
        return [ext.strip().lower() for ext in self.allowed_extensions.split(",")]

    @property
    def upload_path(self) -> Path:
        """Resolved upload directory path."""
        path = Path(self.upload_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings singleton."""
    return Settings()

"""
API dependencies for dependency injection.

Provides database session and settings via FastAPI's Depends mechanism.
"""

from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.core.config import Settings, get_settings


def get_database() -> Session:
    """Database session dependency — alias for get_db generator."""
    return get_db()


def get_app_settings() -> Settings:
    """Settings dependency."""
    return get_settings()

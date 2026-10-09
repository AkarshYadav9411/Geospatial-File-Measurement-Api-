"""
Health check endpoint.

Provides a simple application health check for monitoring and Docker health checks.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database.connection import get_db
from app.core.config import get_settings

router = APIRouter(prefix="/api/health", tags=["Health"])


@router.get(
    "/",
    summary="Application health check",
    description="Returns application status, version, and database connectivity.",
)
def health_check(db: Session = Depends(get_db)):
    """Check application health including database connectivity."""
    settings = get_settings()

    # Check database connectivity
    db_status = "healthy"
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_status = "unhealthy"

    return {
        "status": "healthy" if db_status == "healthy" else "degraded",
        "application": settings.app_name,
        "version": settings.app_version,
        "environment": settings.app_env,
        "database": db_status,
    }

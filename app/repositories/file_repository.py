"""
File repository — database access layer for file and feature records.

Provides CRUD operations and queries for UploadedFile and FeatureMeasurement models.
All database access is encapsulated here to keep business logic separate from
persistence concerns.
"""

import math

from sqlalchemy.orm import Session
from sqlalchemy import func, distinct

from app.database.models import UploadedFile, FeatureMeasurement


def get_file_by_id(db: Session, file_id: str) -> UploadedFile | None:
    """Get a file record by its unique ID."""
    return db.query(UploadedFile).filter(UploadedFile.id == file_id).first()


def list_files(
    db: Session,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[UploadedFile], int]:
    """
    List uploaded files with pagination.

    Returns (files, total_count).
    """
    total = db.query(func.count(UploadedFile.id)).scalar() or 0
    offset = (page - 1) * page_size

    files = (
        db.query(UploadedFile)
        .order_by(UploadedFile.upload_timestamp.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    return files, total


def get_features_by_file_id(
    db: Session,
    file_id: str,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[FeatureMeasurement], int]:
    """
    Get feature measurements for a file with pagination.

    Returns (features, total_count).
    """
    total = (
        db.query(func.count(FeatureMeasurement.id))
        .filter(FeatureMeasurement.file_id == file_id)
        .scalar()
    ) or 0

    offset = (page - 1) * page_size

    features = (
        db.query(FeatureMeasurement)
        .filter(FeatureMeasurement.file_id == file_id)
        .order_by(FeatureMeasurement.feature_index)
        .offset(offset)
        .limit(page_size)
        .all()
    )

    return features, total


def get_geometry_type_counts(
    db: Session,
    file_id: str,
) -> list[dict]:
    """
    Get feature counts grouped by geometry type for a file.

    Returns a list of {"geometry_type": str, "count": int} dicts.
    """
    results = (
        db.query(
            FeatureMeasurement.geometry_type,
            func.count(FeatureMeasurement.id).label("count"),
        )
        .filter(FeatureMeasurement.file_id == file_id)
        .group_by(FeatureMeasurement.geometry_type)
        .all()
    )

    return [
        {"geometry_type": r.geometry_type or "None", "count": r.count}
        for r in results
    ]


def get_measurement_status_counts(
    db: Session,
    file_id: str,
) -> dict[str, int]:
    """
    Get counts of measurement statuses for a file.

    Returns {"success": N, "not_required": N, "error": N, ...}
    """
    results = (
        db.query(
            FeatureMeasurement.measurement_status,
            func.count(FeatureMeasurement.id).label("count"),
        )
        .filter(FeatureMeasurement.file_id == file_id)
        .group_by(FeatureMeasurement.measurement_status)
        .all()
    )

    return {r.measurement_status: r.count for r in results}


def calculate_total_pages(total: int, page_size: int) -> int:
    """Calculate the total number of pages."""
    if total == 0:
        return 1
    return math.ceil(total / page_size)

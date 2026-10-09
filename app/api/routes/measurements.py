"""
Measurement endpoints.

Provides feature measurement results with summary statistics and pagination.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.repositories.file_repository import (
    get_file_by_id,
    get_features_by_file_id,
    get_geometry_type_counts,
    get_measurement_status_counts,
    calculate_total_pages,
)
from app.schemas.measurement import (
    MeasurementsResponse,
    MeasurementSummary,
    FeatureMeasurementResponse,
    MeasurementValue,
    GeometryTypeCounts,
    AreaTotal,
    LengthTotal,
)
from app.schemas.file import ErrorResponse
from app.core.exceptions import FileNotFoundError_
from app.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/files", tags=["Measurements"])


@router.get(
    "/{file_id}/measurements/",
    response_model=MeasurementsResponse,
    summary="Get feature measurements",
    description=(
        "Retrieve measurement results for all features in a processed file. "
        "Includes summary statistics with polygon area totals and line length totals "
        "(kept separate), geometry type counts, and paginated individual feature results."
    ),
    responses={
        404: {"model": ErrorResponse, "description": "File not found"},
    },
)
def get_measurements(
    file_id: str,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=200, description="Features per page"),
    db: Session = Depends(get_db),
):
    """
    Get feature measurements for a processed file.

    Returns summary statistics and paginated feature-level results.
    Area totals and length totals are reported separately — never combined.
    """
    # Verify file exists
    file_record = get_file_by_id(db, file_id)
    if file_record is None:
        raise FileNotFoundError_(f"File with ID '{file_id}' not found")

    # Get paginated features
    features, total_features = get_features_by_file_id(
        db, file_id, page=page, page_size=page_size
    )
    total_pages = calculate_total_pages(total_features, page_size)

    # Get summary statistics
    geom_type_counts = get_geometry_type_counts(db, file_id)
    status_counts = get_measurement_status_counts(db, file_id)

    # Build summary
    successfully_measured = status_counts.get("success", 0)
    measurement_not_required = status_counts.get("not_required", 0)
    unsupported_or_failed = sum(
        status_counts.get(s, 0)
        for s in ("unsupported_geometry", "error", "invalid_geometry", "no_crs", "null_geometry")
    )

    # Area totals
    area_totals = None
    if file_record.total_area_sq_m is not None and file_record.total_area_sq_m > 0:
        area_totals = AreaTotal(
            total_sq_m=round(file_record.total_area_sq_m, 4),
            total_sq_km=round(file_record.total_area_sq_km or 0, 10),
        )

    # Length totals
    length_totals = None
    if file_record.total_length_m is not None and file_record.total_length_m > 0:
        length_totals = LengthTotal(
            total_m=round(file_record.total_length_m, 4),
            total_km=round(file_record.total_length_km or 0, 10),
        )

    summary = MeasurementSummary(
        file_id=file_record.id,
        original_filename=file_record.original_filename,
        file_format=file_record.file_format,
        original_crs=file_record.original_crs,
        measurement_crs=file_record.measurement_crs,
        measurement_strategy=file_record.measurement_strategy,
        processing_status=file_record.processing_status,
        total_features=total_features,
        geometry_type_counts=[
            GeometryTypeCounts(**gc) for gc in geom_type_counts
        ],
        successfully_measured=successfully_measured,
        measurement_not_required=measurement_not_required,
        unsupported_or_failed=unsupported_or_failed,
        area_totals=area_totals,
        length_totals=length_totals,
    )

    # Build feature responses
    feature_responses = []
    for f in features:
        measurement = None
        if f.measurement_type is not None:
            measurement = MeasurementValue(
                measurement_type=f.measurement_type,
                value_primary=round(f.measurement_value_m, 4) if f.measurement_value_m is not None else None,
                value_secondary=round(f.measurement_value_km, 10) if f.measurement_value_km is not None else None,
                unit_primary=f.measurement_unit_primary,
                unit_secondary=f.measurement_unit_secondary,
                measurement_crs=f.measurement_crs,
                measurement_method=f.measurement_method,
            )

        feature_responses.append(
            FeatureMeasurementResponse(
                feature_index=f.feature_index,
                geometry_type=f.geometry_type,
                is_valid=f.is_valid,
                was_repaired=f.was_repaired,
                properties=f.properties,
                measurement=measurement,
                measurement_status=f.measurement_status,
                measurement_warning=f.measurement_warning,
            )
        )

    return MeasurementsResponse(
        summary=summary,
        features=feature_responses,
        page=page,
        page_size=page_size,
        total_features=total_features,
        total_pages=total_pages,
    )

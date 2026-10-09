"""
File service — orchestrates the full file upload, processing, and persistence workflow.

This is the main business logic coordinator that ties together:
- File validation and storage
- Geospatial parsing (Shapefile/KML)
- CRS detection and measurement strategy selection
- Feature measurement calculations
- Database persistence

All operations are wrapped in proper error handling with cleanup on failure.
"""

import uuid
import shutil
import time
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.exceptions import (
    GeoMeasureError,
    GeospatialProcessingError,
)
from app.database.models import UploadedFile, FeatureMeasurement
from app.utils.file_validation import (
    validate_file_extension,
    validate_file_size,
    validate_zip_archive,
    validate_kml_content,
    get_file_format,
)
from app.services.geospatial_service import read_shapefile, read_kml
from app.services.crs_service import detect_crs, select_measurement_strategy
from app.services.measurement_service import measure_features

logger = get_logger(__name__)


async def process_upload(
    file: UploadFile,
    db: Session,
) -> UploadedFile:
    """
    Process an uploaded geospatial file end-to-end.

    Steps:
    1. Validate file extension and size
    2. Save file to disk with a safe generated name
    3. Validate file content (ZIP integrity / KML structure)
    4. Parse geospatial dataset
    5. Detect CRS and select measurement strategy
    6. Calculate measurements for all features
    7. Persist results to database
    8. Return the file record

    On failure, cleans up stored files and partial database records.
    """
    settings = get_settings()
    file_id = str(uuid.uuid4())
    stored_path: Path | None = None
    start_time = time.time()

    try:
        # 1. Validate extension
        original_filename = file.filename or "unknown"
        extension = validate_file_extension(original_filename)
        file_format = get_file_format(extension)

        # 2. Read and validate size
        content = await file.read()
        file_size = validate_file_size(content)

        # 3. Save with safe generated filename
        safe_filename = f"{file_id}{extension}"
        stored_path = settings.upload_path / safe_filename
        stored_path.write_bytes(content)

        logger.info(
            f"File saved: {safe_filename} ({file_size} bytes)",
            extra={"file_id": file_id, "upload_filename": original_filename},
        )

        # 4. Validate content and parse dataset
        warnings = []

        if file_format == "shapefile":
            validate_zip_archive(stored_path)
            dataset = read_shapefile(stored_path)
        elif file_format == "kml":
            dataset = read_kml(stored_path)
        else:
            raise GeospatialProcessingError(f"Unsupported format: {file_format}")

        warnings.extend(dataset.warnings)

        # 5. CRS detection and strategy selection
        crs_info = detect_crs(dataset.crs)
        crs_info = select_measurement_strategy(crs_info, dataset.bounds)
        warnings.extend(crs_info.warnings)

        # 6. Calculate measurements
        measurement_results = measure_features(dataset.features, crs_info)

        # 7. Calculate summary statistics
        total_area_m = 0.0
        total_area_km = 0.0
        total_length_m = 0.0
        total_length_km = 0.0

        for result in measurement_results:
            if result.status == "success":
                if result.measurement_type == "area" and result.value_m is not None:
                    total_area_m += result.value_m
                    total_area_km += result.value_km
                elif result.measurement_type == "length" and result.value_m is not None:
                    total_length_m += result.value_m
                    total_length_km += result.value_km

        # Determine processing status
        has_errors = any(
            r.status in ("error", "invalid_geometry", "no_crs")
            for r in measurement_results
        )
        has_successes = any(r.status == "success" for r in measurement_results)

        if has_errors and has_successes:
            processing_status = "partial"
        elif has_errors and not has_successes:
            if any(r.status in ("not_required", "null_geometry") for r in measurement_results):
                processing_status = "completed"
            else:
                processing_status = "partial"
        else:
            processing_status = "completed"

        # 8. Persist to database
        file_record = UploadedFile(
            id=file_id,
            original_filename=original_filename,
            stored_filename=safe_filename,
            file_format=file_format,
            file_size_bytes=file_size,
            original_crs=crs_info.source_crs_string,
            original_crs_name=crs_info.source_crs_name,
            measurement_crs=crs_info.measurement_crs_string,
            measurement_strategy=crs_info.measurement_strategy,
            feature_count=len(dataset.features),
            processing_status=processing_status,
            processing_warnings=warnings if warnings else None,
            total_area_sq_m=total_area_m if total_area_m > 0 else None,
            total_area_sq_km=total_area_km if total_area_km > 0 else None,
            total_length_m=total_length_m if total_length_m > 0 else None,
            total_length_km=total_length_km if total_length_km > 0 else None,
        )

        db.add(file_record)

        # Persist feature measurements
        for result in measurement_results:
            feature_record = FeatureMeasurement(
                file_id=file_id,
                feature_index=result.feature.feature_index,
                geometry_type=result.feature.geometry_type,
                geometry_geojson=result.feature.geometry_geojson,
                is_valid=result.feature.is_valid,
                was_repaired="yes" if result.was_repaired else "no",
                properties=result.feature.properties,
                measurement_type=result.measurement_type,
                measurement_value_m=result.value_m,
                measurement_value_km=result.value_km,
                measurement_unit_primary=result.unit_primary,
                measurement_unit_secondary=result.unit_secondary,
                measurement_crs=result.measurement_crs,
                measurement_method=result.measurement_method,
                measurement_status=result.status,
                measurement_warning=result.warning,
            )
            db.add(feature_record)

        db.commit()
        db.refresh(file_record)

        duration = int((time.time() - start_time) * 1000)
        logger.info(
            f"File processed successfully in {duration}ms",
            extra={
                "file_id": file_id,
                "upload_filename": original_filename,
                "operation": "process_upload",
                "duration_ms": duration,
            },
        )

        return file_record

    except GeoMeasureError:
        # Clean up stored file on known errors
        if stored_path and stored_path.exists():
            stored_path.unlink(missing_ok=True)
        db.rollback()
        raise

    except Exception as e:
        # Clean up on unexpected errors
        if stored_path and stored_path.exists():
            stored_path.unlink(missing_ok=True)
        db.rollback()
        logger.error(f"Unexpected error processing upload: {e}", exc_info=True)
        raise GeospatialProcessingError(
            f"An unexpected error occurred while processing the file"
        )


def delete_file(file_id: str, db: Session) -> None:
    """
    Delete a file record, its features, and the stored file.

    Uses cascade delete for feature measurements.
    """
    from app.repositories.file_repository import get_file_by_id

    file_record = get_file_by_id(db, file_id)
    if file_record is None:
        from app.core.exceptions import FileNotFoundError_
        raise FileNotFoundError_(f"File with ID '{file_id}' not found")

    # Delete stored file
    settings = get_settings()
    stored_file = settings.upload_path / file_record.stored_filename
    if stored_file.exists():
        stored_file.unlink()
        logger.info(f"Deleted stored file: {file_record.stored_filename}")

    # Delete database records (cascade handles features)
    db.delete(file_record)
    db.commit()

    logger.info(
        f"File record deleted",
        extra={"file_id": file_id, "operation": "delete_file"},
    )

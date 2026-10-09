"""
File management endpoints.

Handles file upload, listing, information retrieval, and deletion.
"""

from fastapi import APIRouter, Depends, UploadFile, File, Query, HTTPException
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.services.file_service import process_upload, delete_file
from app.repositories.file_repository import (
    get_file_by_id,
    list_files,
    calculate_total_pages,
)
from app.schemas.file import (
    FileUploadResponse,
    FileInfoResponse,
    FileListResponse,
    FileListItem,
    DeleteResponse,
    ErrorResponse,
)
from app.core.exceptions import FileNotFoundError_
from app.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/files", tags=["Files"])


@router.post(
    "/",
    response_model=FileUploadResponse,
    status_code=201,
    summary="Upload and process a geospatial file",
    description=(
        "Upload a Shapefile (as .zip) or KML file for processing. "
        "The API validates the file, extracts features, detects CRS, "
        "calculates measurements, and persists the results."
    ),
    responses={
        400: {"model": ErrorResponse, "description": "Invalid file content"},
        413: {"model": ErrorResponse, "description": "File too large"},
        415: {"model": ErrorResponse, "description": "Unsupported format"},
        422: {"model": ErrorResponse, "description": "Validation error"},
        500: {"model": ErrorResponse, "description": "Internal processing error"},
    },
)
async def upload_file(
    file: UploadFile = File(
        ...,
        description="Geospatial file: .zip (Shapefile) or .kml",
    ),
    db: Session = Depends(get_db),
):
    """
    Upload and process a geospatial file.

    Supports:
    - **Shapefile (.zip)**: ZIP archive containing .shp, .shx, .dbf (and optionally .prj)
    - **KML (.kml)**: KML file with geographic features

    The response includes file metadata, CRS information, and processing status.
    Feature measurements are available via the measurements endpoint.
    """
    file_record = await process_upload(file, db)

    return FileUploadResponse(
        file_id=file_record.id,
        filename=file_record.original_filename,
        file_format=file_record.file_format,
        file_size_bytes=file_record.file_size_bytes,
        feature_count=file_record.feature_count,
        original_crs=file_record.original_crs,
        measurement_crs=file_record.measurement_crs,
        measurement_strategy=file_record.measurement_strategy,
        processing_status=file_record.processing_status,
        warnings=file_record.processing_warnings or [],
    )


@router.get(
    "/",
    response_model=FileListResponse,
    summary="List uploaded files",
    description="List all uploaded file records with pagination.",
)
def list_uploaded_files(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db),
):
    """List uploaded files with pagination."""
    files, total = list_files(db, page=page, page_size=page_size)
    total_pages = calculate_total_pages(total, page_size)

    return FileListResponse(
        files=[
            FileListItem(
                file_id=f.id,
                original_filename=f.original_filename,
                upload_timestamp=f.upload_timestamp,
                file_format=f.file_format,
                feature_count=f.feature_count,
                processing_status=f.processing_status,
            )
            for f in files
        ],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get(
    "/{file_id}/",
    response_model=FileInfoResponse,
    summary="Get file information",
    description="Retrieve detailed information about a specific uploaded file.",
    responses={
        404: {"model": ErrorResponse, "description": "File not found"},
    },
)
def get_file_info(
    file_id: str,
    db: Session = Depends(get_db),
):
    """Get detailed information about an uploaded file."""
    file_record = get_file_by_id(db, file_id)
    if file_record is None:
        raise FileNotFoundError_(f"File with ID '{file_id}' not found")

    return FileInfoResponse(
        file_id=file_record.id,
        original_filename=file_record.original_filename,
        upload_timestamp=file_record.upload_timestamp,
        file_format=file_record.file_format,
        file_size_bytes=file_record.file_size_bytes,
        feature_count=file_record.feature_count,
        original_crs=file_record.original_crs,
        original_crs_name=file_record.original_crs_name,
        measurement_crs=file_record.measurement_crs,
        measurement_strategy=file_record.measurement_strategy,
        processing_status=file_record.processing_status,
        processing_warnings=file_record.processing_warnings or [],
    )


@router.delete(
    "/{file_id}/",
    response_model=DeleteResponse,
    summary="Delete a file",
    description="Delete a file record, its stored file, and all associated measurements.",
    responses={
        404: {"model": ErrorResponse, "description": "File not found"},
    },
)
def delete_uploaded_file(
    file_id: str,
    db: Session = Depends(get_db),
):
    """Delete a file and all associated data."""
    delete_file(file_id, db)
    return DeleteResponse(
        message="File deleted successfully",
        file_id=file_id,
    )

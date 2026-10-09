"""
Pydantic schemas for file-related API responses.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class FileUploadResponse(BaseModel):
    """Response returned after successfully uploading and processing a file."""

    file_id: str = Field(..., description="Unique identifier for the uploaded file")
    filename: str = Field(..., description="Original filename as uploaded")
    file_format: str = Field(..., description="Detected file format (shapefile or kml)")
    file_size_bytes: int = Field(..., description="File size in bytes")
    feature_count: int = Field(..., description="Number of features extracted")
    original_crs: str | None = Field(None, description="Original CRS of the dataset")
    measurement_crs: str | None = Field(
        None, description="CRS or method used for measurements"
    )
    measurement_strategy: str | None = Field(
        None, description="Strategy used for measurement CRS selection"
    )
    processing_status: str = Field(
        ..., description="Processing status: completed, partial, or failed"
    )
    warnings: list[str] = Field(
        default_factory=list, description="Processing warnings"
    )

    model_config = {"from_attributes": True}


class FileInfoResponse(BaseModel):
    """Response for file information endpoint."""

    file_id: str
    original_filename: str
    upload_timestamp: datetime
    file_format: str
    file_size_bytes: int
    feature_count: int
    original_crs: str | None = None
    original_crs_name: str | None = None
    measurement_crs: str | None = None
    measurement_strategy: str | None = None
    processing_status: str
    processing_warnings: list[str] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class FileListItem(BaseModel):
    """Abbreviated file info for list endpoints."""

    file_id: str
    original_filename: str
    upload_timestamp: datetime
    file_format: str
    feature_count: int
    processing_status: str

    model_config = {"from_attributes": True}


class FileListResponse(BaseModel):
    """Paginated list of uploaded files."""

    files: list[FileListItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class DeleteResponse(BaseModel):
    """Response for file deletion."""

    message: str
    file_id: str


class ErrorResponse(BaseModel):
    """Standard error response schema."""

    error: str = Field(..., description="Error type")
    message: str = Field(..., description="Human-readable error message")
    details: dict[str, Any] = Field(
        default_factory=dict, description="Additional error details"
    )

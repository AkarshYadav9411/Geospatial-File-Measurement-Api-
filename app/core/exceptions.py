"""
Application-specific exceptions.

Custom exception classes for structured error handling across the application.
These exceptions are caught by the global exception handlers in main.py and
translated to appropriate HTTP responses.
"""

from typing import Any


class GeoMeasureError(Exception):
    """Base exception for all GeoMeasure application errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        self.message = message
        self.details = details or {}
        super().__init__(message)


class FileValidationError(GeoMeasureError):
    """Raised when an uploaded file fails validation checks."""

    pass


class UnsupportedFormatError(GeoMeasureError):
    """Raised when the uploaded file format is not supported."""

    pass


class FileSizeExceededError(GeoMeasureError):
    """Raised when the uploaded file exceeds the size limit."""

    pass


class CorruptFileError(GeoMeasureError):
    """Raised when the uploaded file is corrupt or unreadable."""

    pass


class ShapefileValidationError(FileValidationError):
    """Raised when a ZIP archive does not contain a valid Shapefile dataset."""

    pass


class KMLValidationError(FileValidationError):
    """Raised when a KML file is invalid or malformed."""

    pass


class CRSError(GeoMeasureError):
    """Raised when CRS detection or transformation fails."""

    pass


class MeasurementError(GeoMeasureError):
    """Raised when geometry measurement calculation fails."""

    pass


class GeospatialProcessingError(GeoMeasureError):
    """Raised when geospatial file parsing or feature extraction fails."""

    pass


class FileNotFoundError_(GeoMeasureError):
    """Raised when a requested file record does not exist."""

    pass


class AmbiguousDatasetError(FileValidationError):
    """Raised when a ZIP archive contains multiple candidate Shapefile datasets."""

    pass

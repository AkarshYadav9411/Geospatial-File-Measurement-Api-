"""
Pydantic schemas for measurement-related API responses.
"""

from typing import Any

from pydantic import BaseModel, Field


class MeasurementValue(BaseModel):
    """A single measurement result with type, value, and unit."""

    measurement_type: str | None = Field(
        None, description="Type of measurement: area or length"
    )
    value_primary: float | None = Field(
        None, description="Measurement value in primary unit (m² or m)"
    )
    value_secondary: float | None = Field(
        None, description="Measurement value in secondary unit (km² or km)"
    )
    unit_primary: str | None = Field(
        None, description="Primary unit (m² or m)"
    )
    unit_secondary: str | None = Field(
        None, description="Secondary unit (km² or km)"
    )
    measurement_crs: str | None = Field(
        None, description="CRS or method used for this measurement"
    )
    measurement_method: str | None = Field(
        None, description="Method used for calculation"
    )


class FeatureMeasurementResponse(BaseModel):
    """Measurement result for a single feature."""

    feature_index: int
    geometry_type: str | None = None
    is_valid: str | None = None
    was_repaired: str = "no"
    properties: dict[str, Any] | None = None
    measurement: MeasurementValue | None = None
    measurement_status: str = Field(
        ..., description="Status: success, not_required, unsupported_geometry, "
                         "error, no_crs, invalid_geometry"
    )
    measurement_warning: str | None = None

    model_config = {"from_attributes": True}


class GeometryTypeCounts(BaseModel):
    """Count of features grouped by geometry type."""

    geometry_type: str
    count: int


class AreaTotal(BaseModel):
    """Total polygon area across all features."""

    total_sq_m: float = Field(..., description="Total area in square meters")
    total_sq_km: float = Field(..., description="Total area in square kilometers")
    unit_primary: str = "m²"
    unit_secondary: str = "km²"


class LengthTotal(BaseModel):
    """Total line length across all features."""

    total_m: float = Field(..., description="Total length in meters")
    total_km: float = Field(..., description="Total length in kilometers")
    unit_primary: str = "m"
    unit_secondary: str = "km"


class MeasurementSummary(BaseModel):
    """Summary statistics for a processed file's measurements."""

    file_id: str
    original_filename: str
    file_format: str
    original_crs: str | None = None
    measurement_crs: str | None = None
    measurement_strategy: str | None = None
    processing_status: str

    total_features: int
    geometry_type_counts: list[GeometryTypeCounts]
    successfully_measured: int
    measurement_not_required: int
    unsupported_or_failed: int

    area_totals: AreaTotal | None = None
    length_totals: LengthTotal | None = None


class MeasurementsResponse(BaseModel):
    """Full measurement response with summary and paginated feature results."""

    summary: MeasurementSummary
    features: list[FeatureMeasurementResponse]
    page: int
    page_size: int
    total_features: int
    total_pages: int

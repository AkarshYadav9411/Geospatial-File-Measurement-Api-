"""
Pydantic schemas for feature data in API responses.
"""

from typing import Any

from pydantic import BaseModel, Field


class FeatureResponse(BaseModel):
    """Individual feature extracted from a geospatial file."""

    feature_index: int = Field(..., description="Zero-based feature index")
    geometry_type: str | None = Field(None, description="Geometry type name")
    geometry: dict | None = Field(
        None, description="GeoJSON-compatible geometry representation"
    )
    is_valid: str | None = Field(
        None, description="Geometry validity: valid, invalid, empty, or null"
    )
    was_repaired: str = Field("no", description="Whether the geometry was repaired")
    properties: dict[str, Any] | None = Field(
        None, description="Feature properties/attributes"
    )

    model_config = {"from_attributes": True}

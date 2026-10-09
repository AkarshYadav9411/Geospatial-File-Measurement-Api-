"""
Geometry utility functions.

Provides helpers for geometry inspection, GeoJSON conversion, validity checking,
and safe geometry operations. Handles edge cases like empty geometries,
null geometries, and geometry collections.
"""

import json
from typing import Any

from shapely.geometry import mapping, shape
from shapely import Geometry
import shapely

from app.core.logging import get_logger

logger = get_logger(__name__)

# Geometry types that support area measurement
AREA_GEOMETRY_TYPES = {"Polygon", "MultiPolygon"}

# Geometry types that support length measurement
LENGTH_GEOMETRY_TYPES = {"LineString", "MultiLineString"}

# Geometry types with no measurement required
NO_MEASUREMENT_TYPES = {"Point", "MultiPoint"}

# All supported geometry types
SUPPORTED_GEOMETRY_TYPES = AREA_GEOMETRY_TYPES | LENGTH_GEOMETRY_TYPES | NO_MEASUREMENT_TYPES

# Types that can be handled but have special behavior
COLLECTION_TYPES = {"GeometryCollection"}


def geometry_to_geojson(geom: Geometry | None) -> dict | None:
    """
    Convert a Shapely geometry to a GeoJSON-compatible dictionary.

    Returns None for null geometries.
    """
    if geom is None or geom.is_empty:
        if geom is not None and geom.is_empty:
            return {"type": geom.geom_type, "coordinates": []}
        return None

    try:
        return mapping(geom)
    except Exception as e:
        logger.warning(f"Failed to convert geometry to GeoJSON: {e}")
        return None


def check_geometry_validity(geom: Geometry | None) -> str:
    """
    Check the validity status of a geometry.

    Returns:
        "null" - geometry is None
        "empty" - geometry is empty
        "valid" - geometry is valid
        "invalid" - geometry is invalid
    """
    if geom is None:
        return "null"
    if geom.is_empty:
        return "empty"
    if geom.is_valid:
        return "valid"
    return "invalid"


def get_geometry_type(geom: Geometry | None) -> str | None:
    """Get the geometry type name, or None for null geometries."""
    if geom is None:
        return None
    return geom.geom_type


def get_measurement_type(geometry_type: str | None) -> str | None:
    """
    Determine the measurement type for a geometry type.

    Returns "area", "length", or None.
    """
    if geometry_type is None:
        return None
    if geometry_type in AREA_GEOMETRY_TYPES:
        return "area"
    if geometry_type in LENGTH_GEOMETRY_TYPES:
        return "length"
    return None


def get_measurement_status(
    geometry_type: str | None,
    validity: str,
    has_crs: bool,
) -> str:
    """
    Determine the measurement status based on geometry type, validity, and CRS availability.

    Returns one of:
    - "success" (placeholder, actual success set after measurement)
    - "not_required" (points)
    - "unsupported_geometry" (geometry collections, unknown types)
    - "invalid_geometry" (invalid geometries)
    - "no_crs" (no CRS available)
    - "null_geometry" (null/empty geometry)
    """
    if geometry_type is None or validity == "null":
        return "null_geometry"

    if validity == "empty":
        return "null_geometry"

    if geometry_type in NO_MEASUREMENT_TYPES:
        return "not_required"

    if geometry_type not in SUPPORTED_GEOMETRY_TYPES:
        return "unsupported_geometry"

    if validity == "invalid":
        return "invalid_geometry"

    if not has_crs and geometry_type in (AREA_GEOMETRY_TYPES | LENGTH_GEOMETRY_TYPES):
        return "no_crs"

    return "pending"


def try_make_valid(geom: Geometry | None) -> tuple[Geometry | None, bool]:
    """
    Attempt to repair an invalid geometry using Shapely's make_valid.

    Returns a tuple of (geometry, was_repaired).
    The repair is explicit — callers must track and report repairs.
    """
    if geom is None or geom.is_empty:
        return geom, False

    if geom.is_valid:
        return geom, False

    try:
        repaired = shapely.make_valid(geom)
        if repaired is not None and not repaired.is_empty and repaired.is_valid:
            logger.info(
                f"Geometry repaired: {geom.geom_type} -> {repaired.geom_type}"
            )
            return repaired, True
        return geom, False
    except Exception as e:
        logger.warning(f"Geometry repair failed: {e}")
        return geom, False


def safe_properties_dict(properties: dict | None) -> dict[str, Any] | None:
    """
    Sanitize feature properties for JSON serialization.

    Converts non-serializable values to strings and handles None values.
    """
    if properties is None:
        return None

    clean = {}
    for key, value in properties.items():
        if value is None:
            clean[key] = None
        elif isinstance(value, (str, int, float, bool)):
            clean[key] = value
        elif isinstance(value, (list, dict)):
            try:
                json.dumps(value)
                clean[key] = value
            except (TypeError, ValueError):
                clean[key] = str(value)
        else:
            clean[key] = str(value)

    return clean

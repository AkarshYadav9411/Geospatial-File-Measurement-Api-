"""
Measurement service.

Calculates area and length measurements for geospatial features using
CRS-aware strategies. Supports:
- UTM projection for small-extent datasets
- Geodesic (ellipsoidal) measurement for large-extent datasets
- Pass-through for already-projected datasets
"""

from shapely import Geometry

from app.core.logging import get_logger
from app.core.exceptions import MeasurementError
from app.services.crs_service import (
    CRSInfo,
    transform_geometry,
    geodesic_area,
    geodesic_length,
)
from app.services.geospatial_service import ExtractedFeature
from app.utils.geometry_utils import (
    AREA_GEOMETRY_TYPES,
    LENGTH_GEOMETRY_TYPES,
    NO_MEASUREMENT_TYPES,
    SUPPORTED_GEOMETRY_TYPES,
    get_measurement_status,
    try_make_valid,
)

logger = get_logger(__name__)


class FeatureMeasurementResult:
    """Result of measuring a single feature."""

    def __init__(
        self,
        feature: ExtractedFeature,
        measurement_type: str | None,
        value_m: float | None,
        value_km: float | None,
        unit_primary: str | None,
        unit_secondary: str | None,
        measurement_crs: str | None,
        measurement_method: str | None,
        status: str,
        warning: str | None,
        was_repaired: bool,
    ):
        self.feature = feature
        self.measurement_type = measurement_type
        self.value_m = value_m
        self.value_km = value_km
        self.unit_primary = unit_primary
        self.unit_secondary = unit_secondary
        self.measurement_crs = measurement_crs
        self.measurement_method = measurement_method
        self.status = status
        self.warning = warning
        self.was_repaired = was_repaired


def measure_features(
    features: list[ExtractedFeature],
    crs_info: CRSInfo,
) -> list[FeatureMeasurementResult]:
    """
    Calculate measurements for all features using the selected CRS strategy.

    Args:
        features: List of extracted features.
        crs_info: CRS information with measurement strategy.

    Returns:
        List of measurement results, one per feature.
    """
    results = []
    has_crs = crs_info.source_crs is not None

    for feature in features:
        result = _measure_single_feature(feature, crs_info, has_crs)
        results.append(result)

    return results


def _measure_single_feature(
    feature: ExtractedFeature,
    crs_info: CRSInfo,
    has_crs: bool,
) -> FeatureMeasurementResult:
    """Measure a single feature based on its geometry type and the CRS strategy."""
    geom_type = feature.geometry_type
    validity = feature.is_valid

    # Handle null/empty geometry
    if geom_type is None or validity in ("null", "empty"):
        return FeatureMeasurementResult(
            feature=feature,
            measurement_type=None,
            value_m=None,
            value_km=None,
            unit_primary=None,
            unit_secondary=None,
            measurement_crs=None,
            measurement_method=None,
            status="null_geometry",
            warning="Feature has no geometry or geometry is empty",
            was_repaired=False,
        )

    # Handle Point/MultiPoint — no measurement needed
    if geom_type in NO_MEASUREMENT_TYPES:
        return FeatureMeasurementResult(
            feature=feature,
            measurement_type=None,
            value_m=None,
            value_km=None,
            unit_primary=None,
            unit_secondary=None,
            measurement_crs=None,
            measurement_method=None,
            status="not_required",
            warning=None,
            was_repaired=False,
        )

    # Handle unsupported geometry types
    if geom_type not in SUPPORTED_GEOMETRY_TYPES:
        return FeatureMeasurementResult(
            feature=feature,
            measurement_type=None,
            value_m=None,
            value_km=None,
            unit_primary=None,
            unit_secondary=None,
            measurement_crs=None,
            measurement_method=None,
            status="unsupported_geometry",
            warning=f"Geometry type '{geom_type}' is not supported for measurement",
            was_repaired=False,
        )

    # Handle missing CRS
    if not has_crs:
        return FeatureMeasurementResult(
            feature=feature,
            measurement_type="area" if geom_type in AREA_GEOMETRY_TYPES else "length",
            value_m=None,
            value_km=None,
            unit_primary=None,
            unit_secondary=None,
            measurement_crs=None,
            measurement_method=None,
            status="no_crs",
            warning="Cannot calculate measurement: dataset has no CRS information",
            was_repaired=False,
        )

    # Handle invalid geometry — try repair
    geom = feature.geometry
    was_repaired = False

    if validity == "invalid":
        repaired_geom, did_repair = try_make_valid(geom)
        if did_repair and repaired_geom is not None and repaired_geom.is_valid:
            geom = repaired_geom
            was_repaired = True
            logger.info(
                f"Feature {feature.feature_index}: geometry repaired for measurement "
                f"({feature.geometry_type} -> {geom.geom_type})"
            )
        else:
            return FeatureMeasurementResult(
                feature=feature,
                measurement_type="area" if geom_type in AREA_GEOMETRY_TYPES else "length",
                value_m=None,
                value_km=None,
                unit_primary=None,
                unit_secondary=None,
                measurement_crs=crs_info.measurement_crs_string,
                measurement_method=None,
                status="invalid_geometry",
                warning="Geometry is invalid and could not be repaired for measurement",
                was_repaired=False,
            )

    # Perform measurement
    try:
        if geom_type in AREA_GEOMETRY_TYPES:
            return _calculate_area(feature, geom, crs_info, was_repaired)
        elif geom_type in LENGTH_GEOMETRY_TYPES:
            return _calculate_length(feature, geom, crs_info, was_repaired)
        else:
            return FeatureMeasurementResult(
                feature=feature,
                measurement_type=None,
                value_m=None,
                value_km=None,
                unit_primary=None,
                unit_secondary=None,
                measurement_crs=None,
                measurement_method=None,
                status="unsupported_geometry",
                warning=f"No measurement strategy for geometry type '{geom_type}'",
                was_repaired=was_repaired,
            )

    except Exception as e:
        logger.error(
            f"Measurement failed for feature {feature.feature_index}: {e}",
            exc_info=True,
        )
        return FeatureMeasurementResult(
            feature=feature,
            measurement_type="area" if geom_type in AREA_GEOMETRY_TYPES else "length",
            value_m=None,
            value_km=None,
            unit_primary=None,
            unit_secondary=None,
            measurement_crs=crs_info.measurement_crs_string,
            measurement_method=crs_info.measurement_strategy,
            status="error",
            warning=f"Measurement calculation failed: {str(e)[:200]}",
            was_repaired=was_repaired,
        )


def _calculate_area(
    feature: ExtractedFeature,
    geom: Geometry,
    crs_info: CRSInfo,
    was_repaired: bool,
) -> FeatureMeasurementResult:
    """Calculate area for a polygon/multipolygon geometry."""
    strategy = crs_info.measurement_strategy

    if strategy == "geodesic":
        # Use geodesic calculation
        area_sq_m = geodesic_area(geom, crs_info.source_crs)
        method = "geodesic_ellipsoidal"
    elif strategy == "utm_projection":
        # Transform to UTM and calculate planar area
        projected_geom = transform_geometry(
            geom, crs_info.source_crs, crs_info.measurement_crs
        )
        area_sq_m = projected_geom.area
        method = "projected_planar"
    elif strategy == "source_projected":
        # Already projected — use directly
        area_sq_m = geom.area
        method = "source_projected_planar"
    else:
        return FeatureMeasurementResult(
            feature=feature,
            measurement_type="area",
            value_m=None,
            value_km=None,
            unit_primary="m²",
            unit_secondary="km²",
            measurement_crs=crs_info.measurement_crs_string,
            measurement_method=None,
            status="error",
            warning=f"Unknown measurement strategy: {strategy}",
            was_repaired=was_repaired,
        )

    area_sq_km = area_sq_m / 1_000_000.0

    warning = None
    if was_repaired:
        warning = (
            "Geometry was repaired before measurement. "
            "The reported area is based on the repaired geometry."
        )

    return FeatureMeasurementResult(
        feature=feature,
        measurement_type="area",
        value_m=area_sq_m,
        value_km=area_sq_km,
        unit_primary="m²",
        unit_secondary="km²",
        measurement_crs=crs_info.measurement_crs_string,
        measurement_method=method,
        status="success",
        warning=warning,
        was_repaired=was_repaired,
    )


def _calculate_length(
    feature: ExtractedFeature,
    geom: Geometry,
    crs_info: CRSInfo,
    was_repaired: bool,
) -> FeatureMeasurementResult:
    """Calculate length for a linestring/multilinestring geometry."""
    strategy = crs_info.measurement_strategy

    if strategy == "geodesic":
        length_m = geodesic_length(geom, crs_info.source_crs)
        method = "geodesic_ellipsoidal"
    elif strategy == "utm_projection":
        projected_geom = transform_geometry(
            geom, crs_info.source_crs, crs_info.measurement_crs
        )
        length_m = projected_geom.length
        method = "projected_planar"
    elif strategy == "source_projected":
        length_m = geom.length
        method = "source_projected_planar"
    else:
        return FeatureMeasurementResult(
            feature=feature,
            measurement_type="length",
            value_m=None,
            value_km=None,
            unit_primary="m",
            unit_secondary="km",
            measurement_crs=crs_info.measurement_crs_string,
            measurement_method=None,
            status="error",
            warning=f"Unknown measurement strategy: {strategy}",
            was_repaired=was_repaired,
        )

    length_km = length_m / 1000.0

    warning = None
    if was_repaired:
        warning = (
            "Geometry was repaired before measurement. "
            "The reported length is based on the repaired geometry."
        )

    return FeatureMeasurementResult(
        feature=feature,
        measurement_type="length",
        value_m=length_m,
        value_km=length_km,
        unit_primary="m",
        unit_secondary="km",
        measurement_crs=crs_info.measurement_crs_string,
        measurement_method=method,
        status="success",
        warning=warning,
        was_repaired=was_repaired,
    )

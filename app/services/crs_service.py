"""
CRS (Coordinate Reference System) service.

Responsible for:
- Detecting and validating CRS from geospatial datasets
- Selecting appropriate measurement CRS or geodesic strategy
- Transforming geometries for measurement purposes
- Handling missing or invalid CRS information

Design decisions:
- For datasets in geographic CRS (e.g., EPSG:4326), we select a projected CRS
  suitable for accurate measurement rather than treating degrees as meters.
- For small extents: UTM zone selection based on the dataset's centroid.
- For large extents or cross-zone datasets: geodesic measurement via PyProj.
- Missing CRS: features are preserved but measurements are marked unavailable.
"""

import math
from typing import Any

import pyproj
from pyproj import CRS, Transformer
from shapely.geometry import box
from shapely import Geometry
from shapely.ops import transform

from app.core.logging import get_logger
from app.core.exceptions import CRSError

logger = get_logger(__name__)

# Maximum extent (in degrees) for which UTM projection is considered reliable
# UTM zones are 6° wide; datasets spanning more than ~6° may lose accuracy
MAX_UTM_EXTENT_DEGREES = 6.0

# Maximum latitude extent for UTM (UTM is designed for -80° to 84°)
UTM_LAT_MIN = -80.0
UTM_LAT_MAX = 84.0


class CRSInfo:
    """Holds CRS detection and measurement strategy results."""

    def __init__(
        self,
        source_crs: CRS | None,
        source_crs_string: str | None,
        source_crs_name: str | None,
        is_geographic: bool,
        is_projected: bool,
        measurement_crs: CRS | None,
        measurement_crs_string: str | None,
        measurement_strategy: str,
        warnings: list[str],
    ):
        self.source_crs = source_crs
        self.source_crs_string = source_crs_string
        self.source_crs_name = source_crs_name
        self.is_geographic = is_geographic
        self.is_projected = is_projected
        self.measurement_crs = measurement_crs
        self.measurement_crs_string = measurement_crs_string
        self.measurement_strategy = measurement_strategy
        self.warnings = warnings


def detect_crs(crs_input: Any) -> CRSInfo:
    """
    Detect and validate the CRS from a geospatial dataset.

    Args:
        crs_input: CRS object, EPSG code, WKT string, or None.

    Returns:
        CRSInfo with source CRS details. Measurement CRS is NOT selected here.
    """
    warnings = []

    if crs_input is None:
        logger.warning("Dataset has no CRS information")
        return CRSInfo(
            source_crs=None,
            source_crs_string=None,
            source_crs_name=None,
            is_geographic=False,
            is_projected=False,
            measurement_crs=None,
            measurement_crs_string=None,
            measurement_strategy="none",
            warnings=["No CRS information found in the dataset. "
                       "Measurements cannot be calculated without a known CRS."],
        )

    try:
        crs = CRS(crs_input)
    except Exception as e:
        logger.warning(f"Failed to parse CRS: {e}")
        return CRSInfo(
            source_crs=None,
            source_crs_string=str(crs_input),
            source_crs_name=None,
            is_geographic=False,
            is_projected=False,
            measurement_crs=None,
            measurement_crs_string=None,
            measurement_strategy="none",
            warnings=[f"Invalid or unrecognized CRS: {str(crs_input)[:100]}. "
                       "Measurements cannot be calculated."],
        )

    # Extract CRS details
    try:
        epsg = crs.to_epsg()
        crs_string = f"EPSG:{epsg}" if epsg else crs.to_wkt()[:200]
    except Exception:
        crs_string = str(crs_input)[:200]

    try:
        crs_name = crs.name
    except Exception:
        crs_name = None

    is_geographic = crs.is_geographic
    is_projected = crs.is_projected

    return CRSInfo(
        source_crs=crs,
        source_crs_string=crs_string,
        source_crs_name=crs_name,
        is_geographic=is_geographic,
        is_projected=is_projected,
        measurement_crs=None,
        measurement_crs_string=None,
        measurement_strategy="pending",
        warnings=warnings,
    )


def select_measurement_strategy(
    crs_info: CRSInfo,
    bounds: tuple[float, float, float, float] | None,
) -> CRSInfo:
    """
    Select an appropriate measurement CRS or strategy based on the source CRS
    and the dataset's geographic extent.

    Strategy selection:
    1. No CRS → measurements unavailable
    2. Already projected → use existing CRS (it's already in meters/feet)
    3. Geographic CRS + small extent → UTM zone projection
    4. Geographic CRS + large extent → geodesic measurement (PyProj Geod)

    Args:
        crs_info: CRS detection result.
        bounds: Dataset bounds as (minx, miny, maxx, maxy) in the source CRS.

    Returns:
        Updated CRSInfo with measurement strategy selected.
    """
    if crs_info.source_crs is None:
        return crs_info  # No CRS, already marked

    # If already projected, use the source CRS for measurement
    if crs_info.is_projected:
        crs_info.measurement_crs = crs_info.source_crs
        crs_info.measurement_crs_string = crs_info.source_crs_string
        crs_info.measurement_strategy = "source_projected"
        logger.info(
            f"Using source projected CRS for measurement: {crs_info.source_crs_string}"
        )
        return crs_info

    # Geographic CRS — need to select a projected CRS or use geodesic
    if crs_info.is_geographic and bounds is not None:
        minx, miny, maxx, maxy = bounds
        lon_extent = abs(maxx - minx)
        lat_extent = abs(maxy - miny)

        # Check if extent is suitable for UTM
        center_lon = (minx + maxx) / 2.0
        center_lat = (miny + maxy) / 2.0

        if (
            lon_extent <= MAX_UTM_EXTENT_DEGREES
            and UTM_LAT_MIN <= center_lat <= UTM_LAT_MAX
            and lat_extent <= MAX_UTM_EXTENT_DEGREES * 2
        ):
            # Use UTM zone
            utm_crs = _select_utm_zone(center_lon, center_lat)
            if utm_crs is not None:
                epsg = utm_crs.to_epsg()
                crs_info.measurement_crs = utm_crs
                crs_info.measurement_crs_string = (
                    f"EPSG:{epsg}" if epsg else utm_crs.name
                )
                crs_info.measurement_strategy = "utm_projection"
                logger.info(
                    f"Selected UTM zone for measurement: {crs_info.measurement_crs_string}"
                )
                return crs_info

        # Large extent or UTM not suitable — use geodesic measurement
        crs_info.measurement_crs = None
        crs_info.measurement_crs_string = "geodesic (WGS84 ellipsoid)"
        crs_info.measurement_strategy = "geodesic"

        if lon_extent > MAX_UTM_EXTENT_DEGREES:
            crs_info.warnings.append(
                f"Dataset spans {lon_extent:.1f}° of longitude, which exceeds "
                f"the {MAX_UTM_EXTENT_DEGREES}° UTM zone width. "
                "Using geodesic measurement for accuracy."
            )

        logger.info("Using geodesic measurement for large-extent geographic dataset")
        return crs_info

    # Geographic CRS without bounds — use geodesic as fallback
    if crs_info.is_geographic:
        crs_info.measurement_crs = None
        crs_info.measurement_crs_string = "geodesic (WGS84 ellipsoid)"
        crs_info.measurement_strategy = "geodesic"
        crs_info.warnings.append(
            "Dataset bounds unavailable; using geodesic measurement."
        )
        return crs_info

    # Unknown CRS type
    crs_info.measurement_strategy = "none"
    crs_info.warnings.append(
        "CRS is neither geographic nor projected. Measurements may be unreliable."
    )
    return crs_info


def _select_utm_zone(longitude: float, latitude: float) -> CRS | None:
    """
    Select the appropriate UTM zone CRS for a given longitude/latitude.

    UTM zones are numbered 1-60, each covering 6° of longitude.
    Northern hemisphere uses EPSG:326xx, Southern uses EPSG:327xx.
    """
    try:
        # Calculate UTM zone number
        zone_number = int((longitude + 180) / 6) + 1
        zone_number = max(1, min(60, zone_number))

        # Select EPSG code based on hemisphere
        if latitude >= 0:
            epsg_code = 32600 + zone_number  # Northern hemisphere
        else:
            epsg_code = 32700 + zone_number  # Southern hemisphere

        return CRS.from_epsg(epsg_code)
    except Exception as e:
        logger.warning(f"Failed to create UTM CRS for lon={longitude}, lat={latitude}: {e}")
        return None


def transform_geometry(
    geom: Geometry,
    source_crs: CRS,
    target_crs: CRS,
) -> Geometry:
    """
    Transform a Shapely geometry from source CRS to target CRS.

    Uses PyProj transformer for accurate coordinate transformation.
    """
    try:
        transformer = Transformer.from_crs(
            source_crs, target_crs, always_xy=True
        )
        return transform(transformer.transform, geom)
    except Exception as e:
        raise CRSError(
            f"Failed to transform geometry from {source_crs} to {target_crs}: {e}"
        )


def geodesic_area(geom: Geometry, source_crs: CRS | None = None) -> float:
    """
    Calculate the geodesic area of a geometry in square meters.

    Uses PyProj Geod for ellipsoidal area calculation on the WGS84 ellipsoid.
    Expects coordinates in geographic CRS (longitude, latitude).

    For polygons with holes, the interior rings are subtracted.
    """
    if source_crs is None:
        source_crs = CRS.from_epsg(4326)

    # If source CRS is projected, transform to geographic first
    if source_crs.is_projected:
        geom = transform_geometry(geom, source_crs, CRS.from_epsg(4326))

    geod = pyproj.Geod(ellps="WGS84")

    if geom.geom_type == "Polygon":
        return abs(_polygon_geodesic_area(geod, geom))
    elif geom.geom_type == "MultiPolygon":
        total = 0.0
        for polygon in geom.geoms:
            total += abs(_polygon_geodesic_area(geod, polygon))
        return total
    else:
        return 0.0


def _polygon_geodesic_area(geod: pyproj.Geod, polygon) -> float:
    """Calculate geodesic area for a single polygon, accounting for holes."""
    # Exterior ring
    coords = list(polygon.exterior.coords)
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    area, _ = geod.polygon_area_perimeter(lons, lats)
    total_area = abs(area)

    # Subtract interior rings (holes)
    for interior in polygon.interiors:
        coords = list(interior.coords)
        lons = [c[0] for c in coords]
        lats = [c[1] for c in coords]
        hole_area, _ = geod.polygon_area_perimeter(lons, lats)
        total_area -= abs(hole_area)

    return total_area


def geodesic_length(geom: Geometry, source_crs: CRS | None = None) -> float:
    """
    Calculate the geodesic length of a geometry in meters.

    Uses PyProj Geod for ellipsoidal distance calculation on the WGS84 ellipsoid.
    """
    if source_crs is None:
        source_crs = CRS.from_epsg(4326)

    if source_crs.is_projected:
        geom = transform_geometry(geom, source_crs, CRS.from_epsg(4326))

    geod = pyproj.Geod(ellps="WGS84")

    if geom.geom_type == "LineString":
        return _linestring_geodesic_length(geod, geom)
    elif geom.geom_type == "MultiLineString":
        total = 0.0
        for line in geom.geoms:
            total += _linestring_geodesic_length(geod, line)
        return total
    else:
        return 0.0


def _linestring_geodesic_length(geod: pyproj.Geod, linestring) -> float:
    """Calculate geodesic length for a single LineString."""
    coords = list(linestring.coords)
    total_length = 0.0

    for i in range(len(coords) - 1):
        lon1, lat1 = coords[i][0], coords[i][1]
        lon2, lat2 = coords[i + 1][0], coords[i + 1][1]
        _, _, dist = geod.inv(lon1, lat1, lon2, lat2)
        total_length += dist

    return total_length

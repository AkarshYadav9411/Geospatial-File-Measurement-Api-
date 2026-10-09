"""
Geospatial service for reading and parsing geospatial files.

Handles reading Shapefiles (from ZIP) and KML files using GeoPandas/Fiona,
extracting features, and preparing them for measurement.
"""

import tempfile
import shutil
from pathlib import Path
from typing import Any

import geopandas as gpd
import fiona
from shapely import Geometry

from app.core.logging import get_logger
from app.core.exceptions import (
    GeospatialProcessingError,
    ShapefileValidationError,
    KMLValidationError,
)
from app.utils.file_validation import extract_zip_safely, validate_kml_content
from app.utils.geometry_utils import (
    geometry_to_geojson,
    check_geometry_validity,
    get_geometry_type,
    safe_properties_dict,
)

logger = get_logger(__name__)


class ExtractedFeature:
    """Represents a single extracted feature from a geospatial dataset."""

    def __init__(
        self,
        feature_index: int,
        geometry: Geometry | None,
        geometry_type: str | None,
        geometry_geojson: dict | None,
        is_valid: str,
        properties: dict[str, Any] | None,
    ):
        self.feature_index = feature_index
        self.geometry = geometry
        self.geometry_type = geometry_type
        self.geometry_geojson = geometry_geojson
        self.is_valid = is_valid
        self.properties = properties


class DatasetInfo:
    """Holds parsed dataset information including CRS and features."""

    def __init__(
        self,
        crs: Any,
        bounds: tuple[float, float, float, float] | None,
        features: list[ExtractedFeature],
        warnings: list[str],
    ):
        self.crs = crs
        self.bounds = bounds
        self.features = features
        self.warnings = warnings


def read_shapefile(file_path: Path) -> DatasetInfo:
    """
    Read a Shapefile from a ZIP archive.

    Extracts the ZIP to a temporary directory, reads the Shapefile with GeoPandas,
    and extracts all features.

    Args:
        file_path: Path to the uploaded ZIP file.

    Returns:
        DatasetInfo with CRS, bounds, and extracted features.
    """
    temp_dir = None
    warnings = []

    try:
        temp_dir = Path(tempfile.mkdtemp(prefix="geomeasure_shp_"))
        shp_path = extract_zip_safely(file_path, temp_dir)

        logger.info(f"Reading Shapefile: {shp_path.name}")

        try:
            gdf = gpd.read_file(shp_path, engine="fiona")
        except Exception as e:
            raise GeospatialProcessingError(
                f"Failed to read Shapefile dataset: {str(e)[:200]}"
            )

        # Check for empty dataset
        if len(gdf) == 0:
            warnings.append("Dataset contains no features")

        # Extract CRS
        crs = gdf.crs
        if crs is None:
            warnings.append(
                "No CRS (.prj) found in Shapefile. "
                "Measurements cannot be calculated without CRS information."
            )

        # Extract bounds
        bounds = None
        if len(gdf) > 0 and crs is not None:
            try:
                total_bounds = gdf.total_bounds
                bounds = tuple(total_bounds)
            except Exception:
                warnings.append("Could not determine dataset bounds")

        # Extract features
        features = _extract_features(gdf)

        return DatasetInfo(
            crs=crs,
            bounds=bounds,
            features=features,
            warnings=warnings,
        )

    finally:
        # Clean up temporary directory
        if temp_dir and temp_dir.exists():
            try:
                shutil.rmtree(temp_dir)
                logger.debug("Cleaned up temporary Shapefile extraction directory")
            except Exception as e:
                logger.warning(f"Failed to clean up temp directory: {e}")


def read_kml(file_path: Path) -> DatasetInfo:
    """
    Read a KML file using GeoPandas with the KML driver.

    Args:
        file_path: Path to the KML file.

    Returns:
        DatasetInfo with CRS, bounds, and extracted features.
    """
    warnings = []

    # Validate KML structure first
    validate_kml_content(file_path)

    try:
        # Enable KML driver in Fiona
        fiona.drvsupport.supported_drivers["KML"] = "r"
        fiona.drvsupport.supported_drivers["LIBKML"] = "r"
    except Exception:
        pass  # Drivers may already be registered

    try:
        try:
            gdf = gpd.read_file(file_path, driver="KML")
        except Exception:
            try:
                gdf = gpd.read_file(file_path, driver="LIBKML")
            except Exception as e:
                raise GeospatialProcessingError(
                    f"Failed to read KML file. Ensure GDAL KML/LIBKML driver is available. "
                    f"Error: {str(e)[:200]}"
                )

        if len(gdf) == 0:
            warnings.append("KML file contains no features")

        # KML is always in EPSG:4326
        crs = gdf.crs
        if crs is None:
            from pyproj import CRS as ProjCRS
            crs = ProjCRS.from_epsg(4326)
            warnings.append(
                "KML CRS not detected by reader; assuming EPSG:4326 "
                "(KML specification requires WGS84 geographic coordinates)."
            )

        # Extract bounds
        bounds = None
        if len(gdf) > 0:
            try:
                total_bounds = gdf.total_bounds
                bounds = tuple(total_bounds)
            except Exception:
                warnings.append("Could not determine dataset bounds")

        features = _extract_features(gdf)

        return DatasetInfo(
            crs=crs,
            bounds=bounds,
            features=features,
            warnings=warnings,
        )

    except GeospatialProcessingError:
        raise
    except Exception as e:
        raise GeospatialProcessingError(
            f"Unexpected error reading KML file: {str(e)[:200]}"
        )


def _extract_features(gdf: gpd.GeoDataFrame) -> list[ExtractedFeature]:
    """
    Extract features from a GeoDataFrame.

    Handles null geometries, empty geometries, and non-serializable properties.
    """
    features = []

    # Get non-geometry columns for properties
    prop_columns = [col for col in gdf.columns if col != "geometry"]

    for idx, row in gdf.iterrows():
        try:
            geom = row.geometry
            geom_type = get_geometry_type(geom)
            validity = check_geometry_validity(geom)
            geojson = geometry_to_geojson(geom)

            # Extract properties
            props = {}
            for col in prop_columns:
                val = row[col]
                # Handle pandas NA/NaN
                if hasattr(val, "__class__") and val.__class__.__name__ in (
                    "NaTType", "NAType"
                ):
                    props[col] = None
                elif isinstance(val, float) and (val != val):  # NaN check
                    props[col] = None
                else:
                    props[col] = val

            props = safe_properties_dict(props)

            feature = ExtractedFeature(
                feature_index=len(features),
                geometry=geom,
                geometry_type=geom_type,
                geometry_geojson=geojson,
                is_valid=validity,
                properties=props,
            )
            features.append(feature)

        except Exception as e:
            logger.warning(f"Failed to extract feature at index {idx}: {e}")
            # Create a placeholder feature so we don't silently discard it
            features.append(
                ExtractedFeature(
                    feature_index=len(features),
                    geometry=None,
                    geometry_type=None,
                    geometry_geojson=None,
                    is_valid="null",
                    properties={"_extraction_error": str(e)[:200]},
                )
            )

    return features

"""
Tests for CRS (Coordinate Reference System) detection and strategy selection.

Covers:
- EPSG:4326 detection (geographic)
- Projected CRS detection (e.g., UTM, Web Mercator)
- UTM zone calculation for various longitudes/latitudes
- Fallback to geodesic measurement for large-extent datasets
- Missing CRS detection and warning handling
- Geometry transformation accuracy
- Geodesic area and length calculations
"""

import pytest
from pyproj import CRS
from shapely.geometry import Polygon, LineString, Point

from app.services.crs_service import (
    detect_crs,
    select_measurement_strategy,
    _select_utm_zone,
    transform_geometry,
    geodesic_area,
    geodesic_length,
)


class TestCRSDetect:
    """Tests for detect_crs function."""

    def test_detect_epsg_4326(self):
        """Test detection of standard WGS84 geographic CRS."""
        crs_info = detect_crs("EPSG:4326")
        assert crs_info.source_crs is not None
        assert crs_info.is_geographic is True
        assert crs_info.is_projected is False
        assert crs_info.source_crs_string == "EPSG:4326"
        assert len(crs_info.warnings) == 0

    def test_detect_projected_utm(self):
        """Test detection of projected UTM CRS (EPSG:32618)."""
        crs_info = detect_crs("EPSG:32618")
        assert crs_info.source_crs is not None
        assert crs_info.is_geographic is False
        assert crs_info.is_projected is True
        assert crs_info.source_crs_string == "EPSG:32618"

    def test_detect_none_crs(self):
        """Test handling of None/missing CRS."""
        crs_info = detect_crs(None)
        assert crs_info.source_crs is None
        assert crs_info.source_crs_string is None
        assert crs_info.is_geographic is False
        assert crs_info.is_projected is False
        assert crs_info.measurement_strategy == "none"
        assert len(crs_info.warnings) > 0
        assert "No CRS information found" in crs_info.warnings[0]

    def test_detect_invalid_crs(self):
        """Test handling of invalid CRS string."""
        crs_info = detect_crs("INVALID_CRS_NOT_REAL_99999")
        assert crs_info.source_crs is None
        assert crs_info.measurement_strategy == "none"
        assert len(crs_info.warnings) > 0


class TestUTMZoneSelection:
    """Tests for _select_utm_zone helper."""

    def test_new_york_utm_zone(self):
        """New York (-74.0, 40.7) should be in UTM Zone 18N (EPSG:32618)."""
        utm = _select_utm_zone(-74.0, 40.7)
        assert utm is not None
        assert utm.to_epsg() == 32618

    def test_london_utm_zone(self):
        """London (-0.1, 51.5) should be in UTM Zone 30N (EPSG:32630)."""
        utm = _select_utm_zone(-0.1, 51.5)
        assert utm is not None
        assert utm.to_epsg() == 32630

    def test_sydney_utm_zone(self):
        """Sydney (151.2, -33.8) should be in UTM Zone 56S (EPSG:32756)."""
        utm = _select_utm_zone(151.2, -33.8)
        assert utm is not None
        assert utm.to_epsg() == 32756

    def test_tokyo_utm_zone(self):
        """Tokyo (139.7, 35.7) should be in UTM Zone 54N (EPSG:32654)."""
        utm = _select_utm_zone(139.7, 35.7)
        assert utm is not None
        assert utm.to_epsg() == 32654


class TestMeasurementStrategySelection:
    """Tests for select_measurement_strategy."""

    def test_projected_source_uses_source_crs(self):
        """Already projected datasets keep their source CRS."""
        crs_info = detect_crs("EPSG:32618")
        result = select_measurement_strategy(crs_info, (580000, 4500000, 590000, 4510000))
        assert result.measurement_strategy == "source_projected"
        assert result.measurement_crs_string == "EPSG:32618"

    def test_small_extent_geographic_uses_utm(self):
        """Small geographic dataset (< 6 degrees) uses UTM projection."""
        crs_info = detect_crs("EPSG:4326")
        # NYC extent (~0.1 degree)
        bounds = (-74.05, 40.70, -73.95, 40.80)
        result = select_measurement_strategy(crs_info, bounds)
        assert result.measurement_strategy == "utm_projection"
        assert result.measurement_crs_string == "EPSG:32618"

    def test_large_extent_geographic_uses_geodesic(self):
        """Large geographic dataset (> 6 degrees) falls back to geodesic."""
        crs_info = detect_crs("EPSG:4326")
        # Entire continental US bounds
        bounds = (-125.0, 24.0, -66.0, 49.0)
        result = select_measurement_strategy(crs_info, bounds)
        assert result.measurement_strategy == "geodesic"
        assert "geodesic" in result.measurement_crs_string.lower()
        assert any("exceeds" in w for w in result.warnings)

    def test_missing_crs_strategy(self):
        """Missing CRS results in 'none' strategy and no measurement CRS."""
        crs_info = detect_crs(None)
        result = select_measurement_strategy(crs_info, (-74.0, 40.0, -73.0, 41.0))
        assert result.measurement_strategy == "none"
        assert result.measurement_crs is None


class TestGeodesicCalculations:
    """Tests for geodesic area and length calculations."""

    def test_geodesic_polygon_area_equator(self):
        """
        A 1-degree by 1-degree square at the equator:
        ~111.32 km per degree -> ~111,320 m * 111,320 m ≈ 1.23e10 m².
        """
        poly = Polygon([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0)])
        area = geodesic_area(poly)
        # Should be roughly 12,308 km² (1.23e10 m²)
        assert 1.2e10 < area < 1.25e10

    def test_geodesic_polygon_with_hole(self):
        """Area of polygon with hole should be exterior minus interior."""
        outer = [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0), (0.0, 0.0)]
        hole = [(0.5, 0.5), (1.5, 0.5), (1.5, 1.5), (0.5, 1.5), (0.5, 0.5)]
        poly_with_hole = Polygon(shell=outer, holes=[hole])
        poly_solid = Polygon(shell=outer)

        area_with_hole = geodesic_area(poly_with_hole)
        area_solid = geodesic_area(poly_solid)
        assert area_with_hole < area_solid

    def test_geodesic_linestring_length_equator(self):
        """
        1 degree along the equator is approximately 111,319 meters.
        """
        line = LineString([(0.0, 0.0), (1.0, 0.0)])
        length = geodesic_length(line)
        assert 111_000 < length < 112_000

    def test_transform_geometry(self):
        """Test transforming geometry between EPSG:4326 and EPSG:3857."""
        pt = Point(-74.0060, 40.7128)
        transformed = transform_geometry(pt, CRS.from_epsg(4326), CRS.from_epsg(3857))
        # Longitude in Web Mercator is around -8.2e6, Lat around 4.9e6
        assert -8.3e6 < transformed.x < -8.1e6
        assert 4.8e6 < transformed.y < 5.1e6

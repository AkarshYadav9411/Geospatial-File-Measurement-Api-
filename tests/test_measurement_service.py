"""
Tests for measurement service.

Covers:
- Polygon area calculation (m² and km²)
- MultiPolygon area calculation
- LineString length calculation (m and km)
- MultiLineString length calculation
- Point / MultiPoint (status="not_required", values None)
- Self-intersecting polygon repair (was_repaired)
- Null and empty geometry handling
- Missing CRS (status="no_crs", values None)
- Crucial assertion: degree coordinates are NEVER directly measured as meters
"""

import pytest
from shapely.geometry import (
    Polygon,
    MultiPolygon,
    LineString,
    MultiLineString,
    Point,
    MultiPoint,
)

from app.services.crs_service import detect_crs, select_measurement_strategy
from app.services.geospatial_service import ExtractedFeature
from app.services.measurement_service import (
    measure_features,
    _measure_single_feature,
)
from app.utils.geometry_utils import geometry_to_geojson


def _make_feature(geom, index=0, is_valid="valid", properties=None):
    geom_type = geom.geom_type if geom else None
    geojson = geometry_to_geojson(geom) if geom else None
    return ExtractedFeature(
        feature_index=index,
        geometry=geom,
        geometry_type=geom_type,
        geometry_geojson=geojson,
        is_valid=is_valid,
        properties=properties or {"name": f"Feature_{index}"},
    )


class TestPolygonMeasurements:
    """Tests for Polygon and MultiPolygon area measurements."""

    def test_polygon_area_in_wgs84(self):
        """
        A polygon in WGS84 should be measured via UTM or geodesic in square meters.
        Central Park roughly: -73.973, 40.764 to -73.958, 40.800
        Area should be roughly ~3.4 million m² (3.4 km²).
        """
        # ~1km x 1km polygon in NYC
        # 0.01 deg lat ~ 1.11 km, 0.01 deg lon ~ 0.84 km
        poly = Polygon([
            (-74.00, 40.70),
            (-73.99, 40.70),
            (-73.99, 40.71),
            (-74.00, 40.71),
            (-74.00, 40.70),
        ])
        feature = _make_feature(poly)
        crs_info = select_measurement_strategy(
            detect_crs("EPSG:4326"),
            poly.bounds,
        )

        results = measure_features([feature], crs_info)
        assert len(results) == 1
        res = results[0]

        assert res.measurement_type == "area"
        assert res.status == "success"
        assert res.unit_primary == "m²"
        assert res.unit_secondary == "km²"
        assert res.value_m is not None
        assert res.value_km is not None
        # Approx 0.01 deg x 0.01 deg at lat 40.7 is ~840m x 1110m ≈ 930,000 m²
        assert 800_000 < res.value_m < 1_100_000
        assert 0.8 < res.value_km < 1.1
        # CRITICAL: Verify geographic degrees are NOT measured as meters!
        # If degrees were treated as meters, area would be 0.01 * 0.01 = 0.0001
        assert res.value_m > 100_000

    def test_multipolygon_area(self):
        """Test MultiPolygon area measurement combines parts."""
        p1 = Polygon([
            (-74.00, 40.70),
            (-73.99, 40.70),
            (-73.99, 40.71),
            (-74.00, 40.71),
            (-74.00, 40.70),
        ])
        p2 = Polygon([
            (-73.98, 40.70),
            (-73.97, 40.70),
            (-73.97, 40.71),
            (-73.98, 40.71),
            (-73.98, 40.70),
        ])
        mp = MultiPolygon([p1, p2])
        feature = _make_feature(mp)
        crs_info = select_measurement_strategy(detect_crs("EPSG:4326"), mp.bounds)

        results = measure_features([feature], crs_info)
        assert len(results) == 1
        res = results[0]

        assert res.measurement_type == "area"
        assert res.status == "success"
        # Total area should be roughly double p1
        assert 1_600_000 < res.value_m < 2_200_000

    def test_self_intersecting_polygon_repair(self):
        """Bowtie polygon is invalid; should be repaired and measured."""
        # Bowtie polygon (self-intersecting)
        bowtie = Polygon([(0, 0), (2, 2), (2, 0), (0, 2), (0, 0)])
        feature = _make_feature(bowtie, is_valid="invalid")
        crs_info = select_measurement_strategy(detect_crs("EPSG:32618"), bowtie.bounds)

        results = measure_features([feature], crs_info)
        assert len(results) == 1
        res = results[0]

        assert res.was_repaired is True
        assert res.status == "success"
        assert res.value_m is not None
        assert res.value_m > 0


class TestLineMeasurements:
    """Tests for LineString and MultiLineString length measurements."""

    def test_linestring_length_in_wgs84(self):
        """
        LineString in WGS84 should be converted to meters.
        0.01 degrees of latitude is ~1,113 meters.
        """
        line = LineString([(-74.00, 40.70), (-74.00, 40.71)])
        feature = _make_feature(line)
        crs_info = select_measurement_strategy(detect_crs("EPSG:4326"), line.bounds)

        results = measure_features([feature], crs_info)
        assert len(results) == 1
        res = results[0]

        assert res.measurement_type == "length"
        assert res.status == "success"
        assert res.unit_primary == "m"
        assert res.unit_secondary == "km"
        # Length should be ~1,110 m
        assert 1100 < res.value_m < 1125
        assert 1.10 < res.value_km < 1.13
        # CRITICAL: Verify degree length (0.01) was not treated as 0.01 meters!
        assert res.value_m > 500

    def test_multilinestring_length(self):
        """Test MultiLineString length combines all sub-lines."""
        l1 = LineString([(-74.00, 40.70), (-74.00, 40.71)])
        l2 = LineString([(-74.00, 40.71), (-74.00, 40.72)])
        mls = MultiLineString([l1, l2])
        feature = _make_feature(mls)
        crs_info = select_measurement_strategy(detect_crs("EPSG:4326"), mls.bounds)

        results = measure_features([feature], crs_info)
        assert len(results) == 1
        res = results[0]

        assert res.measurement_type == "length"
        assert res.status == "success"
        assert 2200 < res.value_m < 2250


class TestPointAndEdgeCases:
    """Tests for Point, empty geometries, and missing CRS."""

    def test_point_measurement_not_required(self):
        """Point features should have status 'not_required' and null values."""
        pt = Point(-74.00, 40.70)
        feature = _make_feature(pt)
        crs_info = select_measurement_strategy(detect_crs("EPSG:4326"), pt.bounds)

        results = measure_features([feature], crs_info)
        assert len(results) == 1
        res = results[0]

        assert res.status == "not_required"
        assert res.measurement_type is None
        assert res.value_m is None
        assert res.value_km is None

    def test_multipoint_measurement_not_required(self):
        """MultiPoint features should also have status 'not_required'."""
        mpt = MultiPoint([(-74.00, 40.70), (-74.01, 40.71)])
        feature = _make_feature(mpt)
        crs_info = select_measurement_strategy(detect_crs("EPSG:4326"), mpt.bounds)

        results = measure_features([feature], crs_info)
        assert results[0].status == "not_required"
        assert results[0].value_m is None

    def test_empty_geometry(self):
        """Empty geometry feature should have null_geometry status and no measurement."""
        # Empty Polygon
        empty_poly = Polygon()
        feature_empty = _make_feature(empty_poly, is_valid="empty")
        crs_info = select_measurement_strategy(detect_crs("EPSG:4326"), None)

        results_empty = measure_features([feature_empty], crs_info)
        assert results_empty[0].status == "null_geometry"
        assert results_empty[0].value_m is None

        # Null geometry
        feature_null = _make_feature(None, is_valid="null")
        results_null = measure_features([feature_null], crs_info)
        assert results_null[0].status == "null_geometry"
        assert results_null[0].value_m is None

    def test_no_crs_polygon_marked_no_crs(self):
        """When CRS is missing, polygon measurement status should be 'no_crs'."""
        poly = Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])
        feature = _make_feature(poly)
        crs_info = select_measurement_strategy(detect_crs(None), poly.bounds)

        results = measure_features([feature], crs_info)
        assert results[0].status == "no_crs"
        assert results[0].value_m is None
        assert "CRS" in results[0].warning

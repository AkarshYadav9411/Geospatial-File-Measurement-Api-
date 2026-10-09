"""
Integration tests for the GeoMeasure REST API endpoints.

Covers:
- GET /api/health/ (Health check)
- POST /api/files/ (Shapefile ZIP and KML uploads)
- GET /api/files/{file_id}/ (File metadata retrieval)
- GET /api/files/{file_id}/measurements/ (Feature measurements and summary statistics)
- Pagination on measurements and file lists
- DELETE /api/files/{file_id}/ (File deletion and cascade cleanup)
- Error handling: 404 (not found), 415 (unsupported format), 400 (corrupt/invalid archive)
"""

import io
import pytest
from tests.conftest import (
    create_shapefile_zip,
    create_kml_file,
    create_corrupt_zip,
    create_empty_zip,
    create_polygon_geometry,
    create_linestring_geometry,
    create_point_geometry,
)


class TestHealthCheck:
    """Tests for health endpoint."""

    def test_health_check_returns_ok(self, client):
        """GET /api/health/ should return status healthy."""
        response = client.get("/api/health/")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data


class TestUploadEndpoints:
    """Tests for POST /api/files/ endpoint."""

    def test_upload_valid_shapefile_zip(self, client):
        """Upload valid shapefile ZIP containing a polygon feature."""
        poly = create_polygon_geometry()
        zip_bytes = create_shapefile_zip([poly], [{"id": 1, "name": "Park"}])

        response = client.post(
            "/api/files/",
            files={"file": ("test_polygon.zip", io.BytesIO(zip_bytes), "application/zip")},
        )
        assert response.status_code == 201
        data = response.json()

        assert "file_id" in data
        assert data["filename"] == "test_polygon.zip"
        assert data["file_format"] == "shapefile"
        assert data["feature_count"] == 1
        assert data["processing_status"] in ("completed", "partial")
        assert data["original_crs"] == "EPSG:4326"
        assert data["measurement_strategy"] in ("utm_projection", "geodesic")

    def test_upload_valid_kml(self, client):
        """Upload valid KML file containing a linestring feature."""
        kml_bytes = create_kml_file([
            {
                "name": "River",
                "geometry_type": "LineString",
                "coordinates": "-74.00,40.70,0 -74.00,40.75,0",
            }
        ])

        response = client.post(
            "/api/files/",
            files={"file": ("test_river.kml", io.BytesIO(kml_bytes), "application/vnd.google-earth.kml+xml")},
        )
        assert response.status_code == 201
        data = response.json()

        assert "file_id" in data
        assert data["filename"] == "test_river.kml"
        assert data["file_format"] == "kml"
        assert data["feature_count"] == 1
        assert data["processing_status"] == "completed"

    def test_upload_unsupported_format(self, client):
        """Upload unsupported extension (.csv) returns 415."""
        response = client.post(
            "/api/files/",
            files={"file": ("test.csv", io.BytesIO(b"a,b,c\n1,2,3"), "text/csv")},
        )
        assert response.status_code == 415
        data = response.json()
        assert data["error"] == "unsupported_format"

    def test_upload_corrupt_zip(self, client):
        """Upload corrupt zip returns 400."""
        corrupt = create_corrupt_zip()
        response = client.post(
            "/api/files/",
            files={"file": ("broken.zip", io.BytesIO(corrupt), "application/zip")},
        )
        assert response.status_code == 400
        data = response.json()
        assert data["error"] in ("corrupt_file", "invalid_shapefile")


class TestFileInfoAndMeasurementsEndpoints:
    """Tests for GET /api/files/{id}/ and GET /api/files/{id}/measurements/."""

    def test_get_file_info_and_measurements(self, client):
        """Upload a file, check its info and measurement results."""
        kml_bytes = create_kml_file([
            {
                "name": "Zone A",
                "geometry_type": "Polygon",
                "coordinates": "-74.00,40.70,0 -73.99,40.70,0 -73.99,40.71,0 -74.00,40.71,0 -74.00,40.70,0",
            },
            {
                "name": "Road B",
                "geometry_type": "LineString",
                "coordinates": "-74.00,40.70,0 -73.99,40.71,0",
            },
            {
                "name": "Point C",
                "geometry_type": "Point",
                "coordinates": "-74.00,40.70,0",
            },
        ])

        # Upload
        up_res = client.post(
            "/api/files/",
            files={"file": ("mixed.kml", io.BytesIO(kml_bytes), "application/vnd.google-earth.kml+xml")},
        )
        assert up_res.status_code == 201
        file_id = up_res.json()["file_id"]

        # Get file info
        info_res = client.get(f"/api/files/{file_id}/")
        assert info_res.status_code == 200
        info_data = info_res.json()
        assert info_data["file_id"] == file_id
        assert info_data["feature_count"] == 3

        # Get measurements
        meas_res = client.get(f"/api/files/{file_id}/measurements/")
        assert meas_res.status_code == 200
        meas_data = meas_res.json()

        # Check summary
        summary = meas_data["summary"]
        assert summary["total_features"] == 3
        assert summary["successfully_measured"] == 2  # Polygon and Line
        assert summary["measurement_not_required"] == 1  # Point

        # Area and length totals must be separate
        assert summary["area_totals"]["total_sq_m"] is not None
        assert summary["area_totals"]["total_sq_m"] > 0
        assert summary["length_totals"]["total_m"] is not None
        assert summary["length_totals"]["total_m"] > 0

        # Check features list
        features = meas_data["features"]
        assert len(features) == 3

        # First feature is Polygon
        assert features[0]["geometry_type"] == "Polygon"
        assert features[0]["measurement"]["measurement_type"] == "area"
        assert features[0]["measurement_status"] == "success"

        # Second feature is LineString
        assert features[1]["geometry_type"] == "LineString"
        assert features[1]["measurement"]["measurement_type"] == "length"
        assert features[1]["measurement_status"] == "success"

        # Third feature is Point
        assert features[2]["geometry_type"] == "Point"
        assert features[2]["measurement_status"] == "not_required"

    def test_file_not_found(self, client):
        """GET with non-existent file ID returns 404."""
        response = client.get("/api/files/non-existent-uuid-12345/")
        assert response.status_code == 404
        assert response.json()["error"] == "not_found"

    def test_measurements_not_found(self, client):
        """GET measurements with non-existent file ID returns 404."""
        response = client.get("/api/files/non-existent-uuid-12345/measurements/")
        assert response.status_code == 404

    def test_pagination(self, client):
        """Test pagination parameter on measurements."""
        geoms = [create_polygon_geometry() for _ in range(5)]
        props = [{"id": i, "name": f"P{i}"} for i in range(5)]
        zip_bytes = create_shapefile_zip(geoms, props)

        up = client.post(
            "/api/files/",
            files={"file": ("page_test.zip", io.BytesIO(zip_bytes), "application/zip")},
        )
        file_id = up.json()["file_id"]

        # Page 1, size 2
        p1 = client.get(f"/api/files/{file_id}/measurements/?page=1&page_size=2")
        assert p1.status_code == 200
        p1_data = p1.json()
        assert len(p1_data["features"]) == 2
        assert p1_data["page"] == 1
        assert p1_data["page_size"] == 2
        assert p1_data["total_pages"] == 3

        # Page 3, size 2
        p3 = client.get(f"/api/files/{file_id}/measurements/?page=3&page_size=2")
        p3_data = p3.json()
        assert len(p3_data["features"]) == 1


class TestDeleteAndListEndpoints:
    """Tests for file listing and deletion."""

    def test_list_and_delete_file(self, client):
        """Test listing files and deleting a file."""
        poly = create_polygon_geometry()
        zip_bytes = create_shapefile_zip([poly])

        up = client.post(
            "/api/files/",
            files={"file": ("to_delete.zip", io.BytesIO(zip_bytes), "application/zip")},
        )
        file_id = up.json()["file_id"]

        # List files
        list_res = client.get("/api/files/")
        assert list_res.status_code == 200
        assert any(f["file_id"] == file_id for f in list_res.json()["files"])

        # Delete file
        del_res = client.delete(f"/api/files/{file_id}/")
        assert del_res.status_code == 200
        assert del_res.json()["file_id"] == file_id

        # Verify 404 after deletion
        get_res = client.get(f"/api/files/{file_id}/")
        assert get_res.status_code == 404

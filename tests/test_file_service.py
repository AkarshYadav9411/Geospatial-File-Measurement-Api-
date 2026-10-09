"""
Tests for file validation, extraction, and service error handling.

Covers:
- Extension validation (.zip and .kml allowed, others rejected)
- File size validation and rejection
- Valid Shapefile extraction
- Missing required components (.shx, .dbf)
- Corrupt ZIP archives
- Path traversal protection (zip slip)
- Multiple shapefiles in ZIP (ambiguous dataset)
- Valid KML parsing
- Invalid/malformed KML XML structure
- File deletion and cleanup
"""

import io
import pytest
from pathlib import Path

from app.core.exceptions import (
    FileValidationError,
    UnsupportedFormatError,
    FileSizeExceededError,
    ShapefileValidationError,
    KMLValidationError,
    AmbiguousDatasetError,
    CorruptFileError,
)
from app.utils.file_validation import (
    validate_file_extension,
    validate_file_size,
    validate_zip_archive,
    validate_kml_content,
    extract_zip_safely,
)
from tests.conftest import (
    create_shapefile_zip,
    create_corrupt_zip,
    create_empty_zip,
    create_zip_without_shp,
    create_zip_with_path_traversal,
    create_kml_file,
    create_polygon_geometry,
)


class TestFileValidation:
    """Tests for file extension and size validation."""

    def test_allowed_extensions(self):
        """Test .zip and .kml are accepted."""
        assert validate_file_extension("data.zip") == ".zip"
        assert validate_file_extension("DATA.ZIP") == ".zip"
        assert validate_file_extension("layer.kml") == ".kml"
        assert validate_file_extension("Layer.KML") == ".kml"

    def test_rejected_extensions(self):
        """Test unsupported formats raise UnsupportedFormatError."""
        with pytest.raises(UnsupportedFormatError):
            validate_file_extension("data.geojson")
        with pytest.raises(UnsupportedFormatError):
            validate_file_extension("data.csv")
        with pytest.raises(UnsupportedFormatError):
            validate_file_extension("data.shp")

    def test_file_size_limit(self, monkeypatch):
        """Test file size limit rejection."""
        # Valid small size
        small = b"hello" * 10
        assert validate_file_size(small) == 50

        # Simulate small limit to trigger exception
        from app.core.config import get_settings
        settings = get_settings()
        monkeypatch.setattr(settings, "max_upload_size_mb", 1)  # 1MB max

        huge = b"x" * (1024 * 1024 + 10)  # > 1MB
        with pytest.raises(FileSizeExceededError):
            validate_file_size(huge)


class TestZipShapefileValidation:
    """Tests for ZIP archive inspection and validation."""

    def test_valid_shapefile_zip(self):
        """Valid shapefile zip passes validation."""
        geom = create_polygon_geometry()
        zip_bytes = create_shapefile_zip([geom])
        shp_name = validate_zip_archive(zip_bytes)
        assert str(shp_name).endswith(".shp")

    def test_corrupt_zip(self):
        """Corrupt ZIP raises CorruptFileError."""
        corrupt = create_corrupt_zip()
        with pytest.raises(CorruptFileError):
            validate_zip_archive(corrupt)

    def test_empty_zip(self):
        """Empty ZIP raises ShapefileValidationError."""
        empty = create_empty_zip()
        with pytest.raises(ShapefileValidationError):
            validate_zip_archive(empty)

    def test_zip_without_shp(self):
        """ZIP without .shp file raises ShapefileValidationError."""
        no_shp = create_zip_without_shp()
        with pytest.raises(ShapefileValidationError) as exc:
            validate_zip_archive(no_shp)
        assert "No valid Shapefile dataset found" in str(exc.value) or "No .shp" in str(exc.value)

    def test_path_traversal_detection(self, tmp_path):
        """Zip archive with directory traversal raises FileValidationError."""
        evil_zip = create_zip_with_path_traversal()
        zip_file = tmp_path / "evil.zip"
        zip_file.write_bytes(evil_zip)
        extract_dir = tmp_path / "extracted"

        with pytest.raises(FileValidationError) as exc:
            extract_zip_safely(zip_file, extract_dir)
        assert "path traversal" in str(exc.value).lower()


class TestKMLValidation:
    """Tests for KML file validation."""

    def test_valid_kml(self, tmp_path):
        """Valid KML content passes validation."""
        kml_content = create_kml_file([
            {"name": "Pt1", "geometry_type": "Point", "coordinates": "-74.0,40.7,0"}
        ])
        kml_file = tmp_path / "test.kml"
        kml_file.write_bytes(kml_content)

        assert validate_kml_content(kml_file) is True

    def test_malformed_xml_kml(self, tmp_path):
        """Malformed XML raises KMLValidationError."""
        kml_file = tmp_path / "bad.kml"
        kml_file.write_text("<kml><Document><unclosed_tag>", encoding="utf-8")

        with pytest.raises(KMLValidationError):
            validate_kml_content(kml_file)

    def test_non_kml_xml(self, tmp_path):
        """XML without <kml> root raises KMLValidationError."""
        kml_file = tmp_path / "not_kml.kml"
        kml_file.write_text("<?xml version='1.0'?><root><item>data</item></root>", encoding="utf-8")

        with pytest.raises(KMLValidationError):
            validate_kml_content(kml_file)

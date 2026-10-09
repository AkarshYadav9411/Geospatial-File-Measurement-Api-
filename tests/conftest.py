"""
Test configuration and fixtures.

Provides:
- Isolated test database (SQLite in-memory or temp file)
- FastAPI test client via HTTPX
- Synthetic geospatial test data generators
- Cleanup utilities
"""

import os
import io
import json
import shutil
import struct
import tempfile
import zipfile
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session

from app.database.connection import Base, get_db
from app.core.config import get_settings, Settings
from app.main import app


# --- Test Database Setup ---

TEST_DB_PATH = None


@pytest.fixture(scope="session")
def test_db_path():
    """Create a temporary database file for the test session."""
    global TEST_DB_PATH
    tmp = tempfile.mkdtemp(prefix="geomeasure_test_")
    db_path = os.path.join(tmp, "test.db")
    TEST_DB_PATH = db_path
    yield db_path
    # Cleanup
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture(scope="session")
def test_engine(test_db_path):
    """Create a test database engine."""
    engine = create_engine(
        f"sqlite:///{test_db_path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def test_session_factory(test_engine):
    """Create a session factory bound to the test engine."""
    return sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture
def db_session(test_session_factory) -> Generator[Session, None, None]:
    """Provide a clean database session per test."""
    session = test_session_factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def client(test_session_factory, tmp_path) -> Generator[TestClient, None, None]:
    """
    FastAPI test client with isolated database and upload directory.

    Overrides the database dependency and upload directory for each test.
    """
    def override_get_db():
        session = test_session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db

    # Override upload directory to temp path
    settings = get_settings()
    original_upload_dir = settings.upload_dir
    settings.upload_dir = str(tmp_path / "uploads")
    os.makedirs(settings.upload_dir, exist_ok=True)

    with TestClient(app) as c:
        yield c

    # Restore
    settings.upload_dir = original_upload_dir
    app.dependency_overrides.clear()


# --- Synthetic Test Data Generators ---


def create_shapefile_zip(
    geometries: list[dict],
    properties_list: list[dict] | None = None,
    crs_wkt: str | None = None,
    include_prj: bool = True,
) -> bytes:
    """
    Create a minimal Shapefile ZIP archive from GeoJSON-like geometry dicts.

    Uses Fiona to write a proper Shapefile into a ZIP archive.

    Args:
        geometries: List of GeoJSON geometry dicts.
        properties_list: List of property dicts per feature.
        crs_wkt: WKT string for the .prj file. If None and include_prj is True,
                 uses WGS84 (EPSG:4326).
        include_prj: Whether to include a .prj file.

    Returns:
        ZIP file content as bytes.
    """
    import fiona
    from fiona.crs import from_epsg
    import geopandas as gpd
    from shapely.geometry import shape

    if properties_list is None:
        properties_list = [{"id": i, "name": f"Feature {i}"} for i in range(len(geometries))]

    # Build GeoDataFrame
    shapes = []
    for g in geometries:
        if g is not None:
            shapes.append(shape(g))
        else:
            shapes.append(None)

    gdf = gpd.GeoDataFrame(
        properties_list,
        geometry=shapes,
        crs="EPSG:4326" if include_prj else None,
    )

    # Write to temp directory
    tmp_dir = Path(tempfile.mkdtemp(prefix="geomeasure_fixture_"))
    try:
        shp_path = tmp_dir / "test_data.shp"
        gdf.to_file(shp_path, driver="ESRI Shapefile")

        # Remove .prj if not wanted
        if not include_prj:
            prj_file = shp_path.with_suffix(".prj")
            if prj_file.exists():
                prj_file.unlink()

        # Package into ZIP
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in tmp_dir.iterdir():
                if file_path.is_file():
                    zf.write(file_path, file_path.name)

        return zip_buffer.getvalue()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def create_kml_file(
    placemarks: list[dict],
) -> bytes:
    """
    Create a KML file with the given placemarks.

    Args:
        placemarks: List of dicts with "name", "geometry_type", and "coordinates".
            geometry_type: "Point", "LineString", "Polygon"
            coordinates: For Point: "lon,lat,alt"
                        For LineString: "lon1,lat1,alt1 lon2,lat2,alt2 ..."
                        For Polygon: "lon1,lat1,alt1 lon2,lat2,alt2 ..."

    Returns:
        KML file content as bytes.
    """
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2">',
        "  <Document>",
        "    <name>Test KML</name>",
    ]

    for pm in placemarks:
        name = pm.get("name", "Feature")
        geom_type = pm.get("geometry_type", "Point")
        coords = pm.get("coordinates", "0,0,0")

        parts.append("    <Placemark>")
        parts.append(f"      <name>{name}</name>")

        if pm.get("description"):
            parts.append(f"      <description>{pm['description']}</description>")

        if geom_type == "Point":
            parts.append("      <Point>")
            parts.append(f"        <coordinates>{coords}</coordinates>")
            parts.append("      </Point>")
        elif geom_type == "LineString":
            parts.append("      <LineString>")
            parts.append(f"        <coordinates>{coords}</coordinates>")
            parts.append("      </LineString>")
        elif geom_type == "Polygon":
            parts.append("      <Polygon>")
            parts.append("        <outerBoundaryIs>")
            parts.append("          <LinearRing>")
            parts.append(f"            <coordinates>{coords}</coordinates>")
            parts.append("          </LinearRing>")
            parts.append("        </outerBoundaryIs>")
            parts.append("      </Polygon>")

        parts.append("    </Placemark>")

    parts.append("  </Document>")
    parts.append("</kml>")

    return "\n".join(parts).encode("utf-8")


def create_corrupt_zip() -> bytes:
    """Create a corrupt ZIP file."""
    return b"PK\x03\x04" + b"\x00" * 100 + b"corrupt data here"


def create_empty_zip() -> bytes:
    """Create a valid but empty ZIP archive."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w"):
        pass
    return buf.getvalue()


def create_zip_without_shp() -> bytes:
    """Create a ZIP with files but no Shapefile components."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("readme.txt", "No shapefile here")
        zf.writestr("data.csv", "a,b,c\n1,2,3")
    return buf.getvalue()


def create_zip_with_path_traversal() -> bytes:
    """Create a ZIP with path traversal entries."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../../../etc/passwd", "evil content")
    return buf.getvalue()


def create_polygon_geometry(
    lon_min: float = -73.99,
    lat_min: float = 40.74,
    lon_max: float = -73.98,
    lat_max: float = 40.75,
) -> dict:
    """Create a simple polygon GeoJSON geometry dict."""
    return {
        "type": "Polygon",
        "coordinates": [[
            [lon_min, lat_min],
            [lon_max, lat_min],
            [lon_max, lat_max],
            [lon_min, lat_max],
            [lon_min, lat_min],
        ]],
    }


def create_polygon_with_hole() -> dict:
    """Create a polygon with an interior hole."""
    return {
        "type": "Polygon",
        "coordinates": [
            # Exterior ring
            [
                [-74.0, 40.7],
                [-73.9, 40.7],
                [-73.9, 40.8],
                [-74.0, 40.8],
                [-74.0, 40.7],
            ],
            # Interior hole
            [
                [-73.98, 40.72],
                [-73.92, 40.72],
                [-73.92, 40.78],
                [-73.98, 40.78],
                [-73.98, 40.72],
            ],
        ],
    }


def create_multipolygon_geometry() -> dict:
    """Create a MultiPolygon geometry."""
    return {
        "type": "MultiPolygon",
        "coordinates": [
            [[
                [-73.99, 40.74],
                [-73.98, 40.74],
                [-73.98, 40.75],
                [-73.99, 40.75],
                [-73.99, 40.74],
            ]],
            [[
                [-73.97, 40.74],
                [-73.96, 40.74],
                [-73.96, 40.75],
                [-73.97, 40.75],
                [-73.97, 40.74],
            ]],
        ],
    }


def create_linestring_geometry() -> dict:
    """Create a LineString geometry."""
    return {
        "type": "LineString",
        "coordinates": [
            [-73.99, 40.74],
            [-73.98, 40.75],
            [-73.97, 40.76],
        ],
    }


def create_multilinestring_geometry() -> dict:
    """Create a MultiLineString geometry."""
    return {
        "type": "MultiLineString",
        "coordinates": [
            [[-73.99, 40.74], [-73.98, 40.75]],
            [[-73.97, 40.76], [-73.96, 40.77]],
        ],
    }


def create_point_geometry() -> dict:
    """Create a Point geometry."""
    return {
        "type": "Point",
        "coordinates": [-73.9857, 40.7484],
    }


def create_multipoint_geometry() -> dict:
    """Create a MultiPoint geometry."""
    return {
        "type": "MultiPoint",
        "coordinates": [
            [-73.9857, 40.7484],
            [-73.9700, 40.7600],
        ],
    }

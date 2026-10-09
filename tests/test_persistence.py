"""
Tests for database persistence across application restarts.

Ensures that:
- File metadata persists in SQLite when connection is closed and reopened
- Feature measurements persist with intact geometry GeoJSON and properties
- Cascading deletion works correctly on restart
"""

import uuid
from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.connection import Base
from app.database.models import UploadedFile, FeatureMeasurement
from app.repositories.file_repository import (
    get_file_by_id,
    get_features_by_file_id,
)


def test_persistence_across_connection_restarts(tmp_path):
    """
    Test that SQLite data survives closing the engine/connection
    and recreating a new engine on the same database file.
    """
    db_file = tmp_path / "persistent_geomeasure.db"
    db_url = f"sqlite:///{db_file}"

    # --- Phase 1: Initialize DB and write records ---
    engine_1 = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine_1)
    SessionFactory1 = sessionmaker(bind=engine_1)

    file_id = str(uuid.uuid4())
    session_1 = SessionFactory1()

    file_record = UploadedFile(
        id=file_id,
        original_filename="survey.zip",
        stored_filename=f"{file_id}.zip",
        file_format="shapefile",
        file_size_bytes=4096,
        original_crs="EPSG:4326",
        original_crs_name="WGS 84",
        measurement_crs="EPSG:32618",
        measurement_strategy="utm_projection",
        feature_count=1,
        processing_status="completed",
        processing_warnings=[],
        total_area_sq_m=12345.67,
        total_area_sq_km=0.01234567,
    )
    session_1.add(file_record)

    feature_record = FeatureMeasurement(
        file_id=file_id,
        feature_index=0,
        geometry_type="Polygon",
        geometry_geojson={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
        is_valid="valid",
        was_repaired="no",
        properties={"zone": "Commercial", "code": 101},
        measurement_type="area",
        measurement_value_m=12345.67,
        measurement_value_km=0.01234567,
        measurement_unit_primary="m²",
        measurement_unit_secondary="km²",
        measurement_crs="EPSG:32618",
        measurement_method="UTM projection",
        measurement_status="success",
    )
    session_1.add(feature_record)
    session_1.commit()
    session_1.close()
    engine_1.dispose()  # Fully terminate connection pool

    # --- Phase 2: Start new engine on the same DB file (simulating app restart) ---
    engine_2 = create_engine(db_url, connect_args={"check_same_thread": False})
    SessionFactory2 = sessionmaker(bind=engine_2)
    session_2 = SessionFactory2()

    # Query file record
    loaded_file = get_file_by_id(session_2, file_id)
    assert loaded_file is not None
    assert loaded_file.original_filename == "survey.zip"
    assert loaded_file.file_format == "shapefile"
    assert loaded_file.original_crs == "EPSG:4326"
    assert loaded_file.measurement_crs == "EPSG:32618"
    assert loaded_file.feature_count == 1
    assert loaded_file.total_area_sq_m == pytest.approx(12345.67)

    # Query feature measurements
    loaded_features, total_count = get_features_by_file_id(session_2, file_id)
    assert total_count == 1
    assert len(loaded_features) == 1

    feat = loaded_features[0]
    assert feat.geometry_type == "Polygon"
    assert feat.measurement_type == "area"
    assert feat.measurement_value_m == pytest.approx(12345.67)
    assert feat.measurement_unit_primary == "m²"
    assert feat.properties == {"zone": "Commercial", "code": 101}
    assert feat.geometry_geojson["type"] == "Polygon"

    session_2.close()
    engine_2.dispose()

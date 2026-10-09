"""
SQLAlchemy ORM models for persisting file metadata and feature measurements.

Two main tables:
- uploaded_files: Stores metadata about each uploaded geospatial file.
- feature_measurements: Stores per-feature extraction results and measurements.

JSON columns store complex nested data (geometry, properties, warnings) that
doesn't need relational querying.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Column, Integer, String, Float, Text, DateTime, ForeignKey, JSON
)
from sqlalchemy.orm import relationship

from app.database.connection import Base


class UploadedFile(Base):
    """Represents an uploaded geospatial file and its processing results."""

    __tablename__ = "uploaded_files"

    id = Column(String(36), primary_key=True, index=True)
    original_filename = Column(String(255), nullable=False)
    stored_filename = Column(String(255), nullable=False)
    file_format = Column(String(20), nullable=False)  # "shapefile" or "kml"
    file_size_bytes = Column(Integer, nullable=False)
    upload_timestamp = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    # CRS information
    original_crs = Column(String(255), nullable=True)
    original_crs_name = Column(String(255), nullable=True)
    measurement_crs = Column(String(500), nullable=True)
    measurement_strategy = Column(String(100), nullable=True)

    # Processing status
    feature_count = Column(Integer, nullable=True, default=0)
    processing_status = Column(
        String(50), nullable=False, default="pending"
    )  # pending, completed, failed, partial
    processing_warnings = Column(JSON, nullable=True)
    processing_error = Column(Text, nullable=True)

    # Summary statistics
    total_area_sq_m = Column(Float, nullable=True)
    total_area_sq_km = Column(Float, nullable=True)
    total_length_m = Column(Float, nullable=True)
    total_length_km = Column(Float, nullable=True)

    # Relationships
    features = relationship(
        "FeatureMeasurement",
        back_populates="file",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )


class FeatureMeasurement(Base):
    """Stores extracted feature data and measurement results for each feature."""

    __tablename__ = "feature_measurements"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_id = Column(
        String(36), ForeignKey("uploaded_files.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    feature_index = Column(Integer, nullable=False)

    # Geometry
    geometry_type = Column(String(50), nullable=True)
    geometry_geojson = Column(JSON, nullable=True)
    is_valid = Column(String(10), nullable=True)  # "valid", "invalid", "empty", "null"
    was_repaired = Column(String(10), nullable=False, default="no")

    # Properties
    properties = Column(JSON, nullable=True)

    # Measurement
    measurement_type = Column(String(20), nullable=True)  # "area", "length", null
    measurement_value_m = Column(Float, nullable=True)  # m² or m
    measurement_value_km = Column(Float, nullable=True)  # km² or km
    measurement_unit_primary = Column(String(10), nullable=True)  # "m²" or "m"
    measurement_unit_secondary = Column(String(10), nullable=True)  # "km²" or "km"
    measurement_crs = Column(String(500), nullable=True)
    measurement_method = Column(String(100), nullable=True)

    # Status
    measurement_status = Column(
        String(30), nullable=False, default="pending"
    )  # success, not_required, unsupported_geometry, error, no_crs, invalid_geometry
    measurement_warning = Column(Text, nullable=True)

    # Relationships
    file = relationship("UploadedFile", back_populates="features")

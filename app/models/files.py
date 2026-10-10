"""SQLAlchemy models for uploaded_files and features."""

import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class UploadedFile(Base):
    """Represents an uploaded geospatial file record."""

    __tablename__ = "uploaded_files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_type: Mapped[str] = mapped_column(String(32), nullable=False)  # 'shp_zip' or 'kml'
    sha256: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="PENDING", nullable=False
    )  # PENDING, PROCESSING, COMPLETED, FAILED
    crs: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    crs_assumed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    feature_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    warnings: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        nullable=False,
    )
    completed_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationship to extracted features
    features: Mapped[List["Feature"]] = relationship(
        "Feature", back_populates="file", cascade="all, delete-orphan", order_by="Feature.feature_index"
    )


class Feature(Base):
    """Represents an individual extracted geospatial feature and its computed measurements."""

    __tablename__ = "features"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("uploaded_files.id", ondelete="CASCADE"), index=True, nullable=False
    )
    feature_index: Mapped[int] = mapped_column(Integer, nullable=False)
    layer_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    geometry_type: Mapped[str] = mapped_column(String(64), nullable=False)
    geometry: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)  # GeoJSON dict
    crs: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    properties: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Measurement details (SI units: sq_m or m)
    measurement_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # 'area', 'length', or None
    measurement_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    measurement_unit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # 'sq_m' or 'm'
    method: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # 'utm_projection' or 'geodesic'
    projected_crs: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    geodesic_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    difference_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    warnings: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)

    # Extra spatial metrics
    perimeter: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    vertex_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    centroid: Mapped[Optional[List[float]]] = mapped_column(JSON, nullable=True)
    bbox: Mapped[Optional[List[float]]] = mapped_column(JSON, nullable=True)  # [minx, miny, maxx, maxy]

    # Relationship back to uploaded file
    file: Mapped["UploadedFile"] = relationship("UploadedFile", back_populates="features")

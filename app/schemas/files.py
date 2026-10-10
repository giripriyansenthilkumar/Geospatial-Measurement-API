"""Pydantic schemas for request validation and response shaping."""

import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


class FileUploadResponse(BaseModel):
    id: str
    filename: str
    feature_count: int
    crs: Optional[str]
    status: str
    warnings: List[str] = Field(default_factory=list)


class FileDetailResponse(BaseModel):
    id: str
    filename: str
    file_type: str
    feature_count: int
    crs: Optional[str]
    crs_assumed: bool
    status: str
    created_at: datetime.datetime
    warnings: List[str] = Field(default_factory=list)


class MeasurementDetail(BaseModel):
    type: str
    value: float
    unit: str
    method: Optional[str] = None
    projected_crs: Optional[str] = None
    geodesic_value: Optional[float] = None
    difference_pct: Optional[float] = None


class FeatureResultItem(BaseModel):
    feature_index: int
    geometry_type: str
    crs: Optional[str] = None
    properties: Dict[str, Any] = Field(default_factory=dict)
    geometry: Optional[Dict[str, Any]] = None
    measurement: Optional[MeasurementDetail] = None
    note: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)


class MeasurementsResponse(BaseModel):
    file_id: str
    total: int
    page: int
    page_size: int
    results: List[FeatureResultItem]


class FileSummaryResponse(BaseModel):
    file_id: str
    filename: str
    status: str
    crs: Optional[str]
    feature_count: int
    total_area_sq_m: float
    total_length_m: float
    geometry_counts: Dict[str, int]
    bounding_box: Optional[List[float]] = None
    largest_feature_by_area: Optional[Dict[str, Any]] = None
    longest_feature_by_length: Optional[Dict[str, Any]] = None
    warnings: List[str] = Field(default_factory=list)

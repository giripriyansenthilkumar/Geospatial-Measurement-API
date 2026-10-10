"""Measurement engine using Strategy pattern, UTM reprojection, and Geodesic cross-checks."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol, Tuple

from pyproj import Geod
from shapely.geometry.base import BaseGeometry

from app.config import settings
from app.services.crs_service import CrsService
from app.services.geometry_utils import get_bbox, get_centroid_coords, get_vertex_count

# WGS84 Geod instance for ellipsoidal cross-checks
geod = Geod(ellps="WGS84")


@dataclass
class MeasurementResult:
    """Encapsulates the measurement outcome for an individual geometry."""

    measurement_type: Optional[str] = None
    measurement_value: Optional[float] = None
    measurement_unit: Optional[str] = None
    method: Optional[str] = None
    projected_crs: Optional[str] = None
    geodesic_value: Optional[float] = None
    difference_pct: Optional[float] = None
    note: Optional[str] = None
    warnings: List[str] = field(default_factory=list)

    # Extra spatial metrics
    perimeter: Optional[float] = None
    vertex_count: Optional[int] = None
    centroid: Optional[List[float]] = None
    bbox: Optional[List[float]] = None


class Calculator(Protocol):
    """Protocol for geometry measurement strategies."""

    def measure(
        self,
        geom: BaseGeometry,
        src_crs: str,
        custom_target_crs: Optional[str] = None,
    ) -> MeasurementResult: ...


class AreaCalculator:
    """Computes area for Polygon and MultiPolygon geometries in metric CRS with geodesic cross-check."""

    def measure(
        self,
        geom: BaseGeometry,
        src_crs: str,
        custom_target_crs: Optional[str] = None,
    ) -> MeasurementResult:
        warnings: List[str] = []

        if geom is None or geom.is_empty:
            return MeasurementResult(
                measurement_type="area",
                measurement_value=0.0,
                measurement_unit="sq_m",
                note="Empty geometry",
            )

        # 1. Projected calculation
        projected_crs, proj_geom, wgs84_geom = CrsService.get_measurement_crs_and_projected_geom(
            geom, src_crs, custom_target_crs=custom_target_crs
        )
        proj_area = float(proj_geom.area)
        proj_perimeter = float(proj_geom.length)

        # 2. Geodesic calculation on WGS84 ellipsoid
        geo_area, geo_perim = geod.geometry_area_perimeter(wgs84_geom)
        geodesic_area = abs(float(geo_area))
        geodesic_perim = abs(float(geo_perim))

        # 3. Accuracy comparison
        if geodesic_area > 0:
            diff_pct = abs(proj_area - geodesic_area) / geodesic_area * 100.0
        else:
            diff_pct = 0.0

        # 4. Decision: use geodesic if distortion exceeds threshold
        if diff_pct > settings.DIFF_THRESHOLD_PCT:
            final_value = geodesic_area
            method = "geodesic"
            warnings.append(
                f"Projection distortion ({diff_pct:.4f}%) exceeded threshold ({settings.DIFF_THRESHOLD_PCT}%); used geodesic value."
            )
        else:
            final_value = proj_area
            method = "utm_projection"

        return MeasurementResult(
            measurement_type="area",
            measurement_value=round(final_value, 4),
            measurement_unit="sq_m",
            method=method,
            projected_crs=projected_crs,
            geodesic_value=round(geodesic_area, 4),
            difference_pct=round(diff_pct, 6),
            perimeter=round(proj_perimeter or geodesic_perim, 4),
            vertex_count=get_vertex_count(geom),
            centroid=get_centroid_coords(wgs84_geom),
            bbox=get_bbox(wgs84_geom),
            warnings=warnings,
        )


class LengthCalculator:
    """Computes length for LineString and MultiLineString geometries with geodesic cross-check."""

    def measure(
        self,
        geom: BaseGeometry,
        src_crs: str,
        custom_target_crs: Optional[str] = None,
    ) -> MeasurementResult:
        warnings: List[str] = []

        if geom is None or geom.is_empty:
            return MeasurementResult(
                measurement_type="length",
                measurement_value=0.0,
                measurement_unit="m",
                note="Empty geometry",
            )

        # 1. Projected calculation
        projected_crs, proj_geom, wgs84_geom = CrsService.get_measurement_crs_and_projected_geom(
            geom, src_crs, custom_target_crs=custom_target_crs
        )
        proj_length = float(proj_geom.length)

        # 2. Geodesic calculation on WGS84 ellipsoid
        geodesic_length = abs(float(geod.geometry_length(wgs84_geom)))

        # 3. Accuracy comparison
        if geodesic_length > 0:
            diff_pct = abs(proj_length - geodesic_length) / geodesic_length * 100.0
        else:
            diff_pct = 0.0

        # 4. Decision
        if diff_pct > settings.DIFF_THRESHOLD_PCT:
            final_value = geodesic_length
            method = "geodesic"
            warnings.append(
                f"Projection distortion ({diff_pct:.4f}%) exceeded threshold ({settings.DIFF_THRESHOLD_PCT}%); used geodesic value."
            )
        else:
            final_value = proj_length
            method = "utm_projection"

        return MeasurementResult(
            measurement_type="length",
            measurement_value=round(final_value, 4),
            measurement_unit="m",
            method=method,
            projected_crs=projected_crs,
            geodesic_value=round(geodesic_length, 4),
            difference_pct=round(diff_pct, 6),
            vertex_count=get_vertex_count(geom),
            centroid=get_centroid_coords(wgs84_geom),
            bbox=get_bbox(wgs84_geom),
            warnings=warnings,
        )


class NoMeasurement:
    """Strategy for geometries where measurement is not applicable (Point, MultiPoint)."""

    def measure(
        self,
        geom: BaseGeometry,
        src_crs: str,
        custom_target_crs: Optional[str] = None,
    ) -> MeasurementResult:
        geom_wgs84 = CrsService.to_wgs84(geom, src_crs) if geom else None
        geom_type = geom.geom_type if geom else "Point"
        return MeasurementResult(
            measurement_type=None,
            measurement_value=None,
            measurement_unit=None,
            note=f"No measurement required for {geom_type}",
            vertex_count=get_vertex_count(geom),
            centroid=get_centroid_coords(geom_wgs84),
            bbox=get_bbox(geom_wgs84),
            warnings=[],
        )


class UnsupportedCalculator:
    """Strategy fallback for unsupported geometry types (GeometryCollection, etc)."""

    def measure(
        self,
        geom: BaseGeometry,
        src_crs: str,
        custom_target_crs: Optional[str] = None,
    ) -> MeasurementResult:
        geom_type = geom.geom_type if geom else "Unknown"
        return MeasurementResult(
            measurement_type=None,
            measurement_value=None,
            measurement_unit=None,
            note=f"Measurement not supported for geometry type '{geom_type}'",
            vertex_count=get_vertex_count(geom),
            warnings=[f"Unsupported geometry type: {geom_type}"],
        )


CALCULATORS: Dict[str, Calculator] = {
    "Polygon": AreaCalculator(),
    "MultiPolygon": AreaCalculator(),
    "LineString": LengthCalculator(),
    "MultiLineString": LengthCalculator(),
    "Point": NoMeasurement(),
    "MultiPoint": NoMeasurement(),
}


def measure_geometry(
    geom: Optional[BaseGeometry],
    src_crs: str,
    custom_target_crs: Optional[str] = None,
) -> MeasurementResult:
    """Dispatch geometry to appropriate calculator strategy."""
    if geom is None or geom.is_empty:
        return MeasurementResult(note="Empty or null geometry", warnings=["Empty geometry"])

    calculator = CALCULATORS.get(geom.geom_type, UnsupportedCalculator())
    return calculator.measure(geom, src_crs, custom_target_crs=custom_target_crs)


# Unit conversion factors
AREA_CONVERSIONS = {
    "sq_m": 1.0,
    "sq_km": 1e-6,
    "hectare": 1e-4,
    "acre": 0.000247105381,
}

LENGTH_CONVERSIONS = {
    "m": 1.0,
    "km": 1e-3,
    "mile": 0.000621371192,
}


def convert_measurement(
    val: Optional[float],
    measure_type: Optional[str],
    target_unit: Optional[str],
) -> Tuple[Optional[float], Optional[str]]:
    """
    Convert an SI measurement value to a requested target unit.
    Returns:
        (converted_value, unit_string)
    """
    if val is None or measure_type is None or target_unit is None:
        return val, "sq_m" if measure_type == "area" else ("m" if measure_type == "length" else None)

    target_norm = target_unit.strip().lower()

    if measure_type == "area":
        if target_norm in AREA_CONVERSIONS:
            factor = AREA_CONVERSIONS[target_norm]
            return round(val * factor, 4), target_norm
    elif measure_type == "length":
        if target_norm in LENGTH_CONVERSIONS:
            factor = LENGTH_CONVERSIONS[target_norm]
            return round(val * factor, 4), target_norm

    # If unrecognized or already SI unit
    default_unit = "sq_m" if measure_type == "area" else "m"
    return round(val, 4), default_unit

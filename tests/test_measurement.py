"""Unit tests for the measurement engine, strategy calculators, and geodesic cross-checks."""

import math

import shapely.geometry as sg

from app.services.geometry_utils import validate_and_repair
from app.services.measurement import (
    convert_measurement,
    measure_geometry,
)


def test_known_1km_square_area():
    """A known 1000m x 1000m square in UTM coordinates should measure 1,000,000 sq_m."""
    square_1km = sg.box(500000, 1000000, 501000, 1001000)
    result = measure_geometry(square_1km, "EPSG:32643")

    assert result.measurement_type == "area"
    assert result.measurement_unit == "sq_m"
    # Should be 1,000,000 m² with high precision
    assert math.isclose(result.measurement_value, 1_000_000.0, rel_tol=1e-3)


def test_guard_against_degree_squared_trap():
    """
    CRITICAL GUARD TEST:
    Degrees are NOT a unit of area. A 0.01 x 0.01 degree box has raw degree² area of 0.0001.
    The measurement engine MUST reproject to metric CRS, yielding ~1.2 million m², NOT 0.0001!
    """
    box_degrees = sg.box(77.59, 12.97, 77.60, 12.98)
    raw_degree_sq = box_degrees.area
    assert math.isclose(raw_degree_sq, 0.0001, rel_tol=1e-5)

    result = measure_geometry(box_degrees, "EPSG:4326")
    assert result.measurement_type == "area"
    # Measurement must NEVER equal 0.0001
    assert result.measurement_value > 1_000_000
    assert result.measurement_value != raw_degree_sq


def test_polygon_with_hole():
    """Area of outer polygon minus inner hole."""
    outer = sg.box(500000, 1000000, 501000, 1001000)
    inner = sg.box(500200, 1000200, 500400, 1000400)
    donut = outer.difference(inner)

    result = measure_geometry(donut, "EPSG:32643")
    expected_area = 1_000_000.0 - 40_000.0  # 960,000 m²
    assert math.isclose(result.measurement_value, expected_area, rel_tol=1e-3)


def test_multipolygon_sum():
    """Area of MultiPolygon is the sum of disjoint constituent polygons."""
    poly1 = sg.box(500000, 1000000, 500500, 1000500)       # 250,000 m²
    poly2 = sg.box(501000, 1001000, 501500, 1001500)       # 250,000 m²
    mp = sg.MultiPolygon([poly1, poly2])

    result = measure_geometry(mp, "EPSG:32643")
    assert math.isclose(result.measurement_value, 500_000.0, rel_tol=1e-3)


def test_linestring_length():
    """1000m line in projected CRS."""
    line = sg.LineString([(0, 0), (1000, 0)])
    result = measure_geometry(line, "EPSG:32643")

    assert result.measurement_type == "length"
    assert result.measurement_unit == "m"
    assert math.isclose(result.measurement_value, 1000.0, rel_tol=1e-3)


def test_multilinestring_length():
    """MultiLineString with two segments of 500m each."""
    mls = sg.MultiLineString([
        sg.LineString([(0, 0), (500, 0)]),
        sg.LineString([(500, 0), (500, 500)]),
    ])
    result = measure_geometry(mls, "EPSG:32643")

    assert result.measurement_type == "length"
    assert math.isclose(result.measurement_value, 1000.0, rel_tol=1e-3)


def test_point_no_measurement():
    """Point geometries return measurement: None and note."""
    pt = sg.Point(77.59, 12.97)
    result = measure_geometry(pt, "EPSG:4326")

    assert result.measurement_type is None
    assert result.measurement_value is None
    assert "No measurement required for Point" in result.note


def test_unsupported_geometry():
    """GeometryCollection returns measurement: None with reason note."""
    gc = sg.GeometryCollection([sg.Point(0, 0), sg.LineString([(0, 0), (1, 1)])])
    result = measure_geometry(gc, "EPSG:4326")

    assert result.measurement_type is None
    assert result.measurement_value is None
    assert "Measurement not supported" in result.note


def test_bowtie_polygon_repair():
    """Self-intersecting bow-tie polygon is repaired via make_valid and measured."""
    # Bow-tie polygon has self-intersection at (1, 1)
    bowtie = sg.Polygon([(0, 0), (2, 2), (2, 0), (0, 2), (0, 0)])
    assert not bowtie.is_valid

    repaired, is_valid_orig, note = validate_and_repair(bowtie)
    assert not is_valid_orig
    assert repaired.is_valid
    assert note is not None

    result = measure_geometry(repaired, "EPSG:32643")
    assert result.measurement_type == "area"
    assert result.measurement_value > 0


def test_projected_vs_geodesic_accuracy():
    """Projected UTM and geodesic cross-check for localized area should agree within threshold."""
    poly = sg.box(77.590, 12.970, 77.595, 12.975)
    result = measure_geometry(poly, "EPSG:4326")

    assert result.geodesic_value is not None
    assert result.difference_pct is not None
    # For a small feature (~500m), UTM distortion is very small (< 0.1%)
    assert result.difference_pct < 0.5
    assert result.method == "utm_projection"


def test_unit_conversion():
    # Area: 10,000 m² = 1 hectare = 0.01 km² = 2.47105 acres
    val_m2 = 10000.0
    val_ha, unit_ha = convert_measurement(val_m2, "area", "hectare")
    assert unit_ha == "hectare"
    assert math.isclose(val_ha, 1.0, rel_tol=1e-3)

    val_km2, unit_km2 = convert_measurement(val_m2, "area", "sq_km")
    assert unit_km2 == "sq_km"
    assert math.isclose(val_km2, 0.01, rel_tol=1e-3)

    val_acre, unit_acre = convert_measurement(val_m2, "area", "acre")
    assert unit_acre == "acre"
    assert math.isclose(val_acre, 2.471, rel_tol=1e-2)

    # Length: 1000m = 1km = 0.621371 mile
    val_m = 1000.0
    val_km, unit_km = convert_measurement(val_m, "length", "km")
    assert unit_km == "km"
    assert math.isclose(val_km, 1.0, rel_tol=1e-3)

    val_mi, unit_mi = convert_measurement(val_m, "length", "mile")
    assert unit_mi == "mile"
    assert math.isclose(val_mi, 0.6214, rel_tol=1e-2)

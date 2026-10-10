"""Unit tests for CRS service, UTM zone selection, and coordinate reprojection."""

import shapely.geometry as sg

from app.services.crs_service import CrsService, utm_epsg


def test_utm_epsg_northern_hemisphere():
    # Bangalore: lon=77.59, lat=12.97 -> zone 43 North (EPSG:32643)
    assert utm_epsg(77.59, 12.97) == 32643


def test_utm_epsg_southern_hemisphere():
    # Sydney: lon=151.2, lat=-33.86 -> zone 56 South (EPSG:32756)
    assert utm_epsg(151.2, -33.86) == 32756


def test_utm_epsg_boundaries():
    # Greenwich meridian (lon=0.0, lat=51.5) -> zone 31 North
    assert utm_epsg(0.0, 51.5) == 32631

    # International date line
    assert utm_epsg(179.9, 10.0) == 32660
    assert utm_epsg(-179.9, 10.0) == 32601


def test_geographic_crs_reprojection():
    # Simple polygon in Bangalore (EPSG:4326)
    poly = sg.box(77.59, 12.97, 77.60, 12.98)
    target_crs, proj_geom, wgs84_geom = CrsService.get_measurement_crs_and_projected_geom(
        poly, "EPSG:4326"
    )

    assert target_crs == "EPSG:32643"
    assert proj_geom.is_valid
    # In UTM, coordinates should be in thousands/millions of metres
    assert proj_geom.bounds[0] > 100000


def test_already_projected_metric_crs_retained():
    # Already in UTM 43N
    poly_utm = sg.box(780000, 1435000, 781000, 1436000)
    target_crs, proj_geom, wgs84_geom = CrsService.get_measurement_crs_and_projected_geom(
        poly_utm, "EPSG:32643"
    )

    assert target_crs == "EPSG:32643"
    # Should use the source geometry directly
    assert proj_geom.bounds == poly_utm.bounds


def test_projected_non_metric_crs_reprojected_to_utm():
    # California State Plane Zone 5 (EPSG:2227) in US Survey Feet
    # Around San Francisco: ~6000000 ft, ~2100000 ft
    poly_feet = sg.box(6000000, 2100000, 6001000, 2101000)
    target_crs, proj_geom, wgs84_geom = CrsService.get_measurement_crs_and_projected_geom(
        poly_feet, "EPSG:2227"
    )

    # Should NOT use EPSG:2227 since units are feet, but rather UTM
    assert target_crs != "EPSG:2227"
    assert "EPSG:326" in target_crs


def test_custom_target_crs_override():
    poly = sg.box(77.59, 12.97, 77.60, 12.98)
    custom_crs = "EPSG:3857"  # Web Mercator
    target_crs, proj_geom, wgs84_geom = CrsService.get_measurement_crs_and_projected_geom(
        poly, "EPSG:4326", custom_target_crs=custom_crs
    )

    assert target_crs == custom_crs

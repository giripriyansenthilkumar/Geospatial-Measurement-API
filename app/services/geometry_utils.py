"""Geometry normalization, validation, repair, and utility helpers."""

from typing import List, Optional, Tuple

import shapely
from shapely.geometry.base import BaseGeometry


def ensure_2d(geom: Optional[BaseGeometry]) -> Optional[BaseGeometry]:
    """Drop Z/M coordinates to enforce 2D planar geometries."""
    if geom is None or geom.is_empty:
        return geom
    return shapely.force_2d(geom)


def validate_and_repair(
    geom: Optional[BaseGeometry],
) -> Tuple[Optional[BaseGeometry], bool, Optional[str]]:
    """
    Check if a geometry is valid. If invalid, repair it with shapely.make_valid.

    Returns:
        (repaired_geom, is_valid_original, repair_note)
    """
    if geom is None or geom.is_empty:
        return geom, True, None

    if geom.is_valid:
        return geom, True, None

    # Geometry is invalid, attempt repair
    try:
        repaired = shapely.make_valid(geom)
        repaired_2d = shapely.force_2d(repaired)
        return repaired_2d, False, "Geometry was invalid; repaired using make_valid"
    except Exception as e:
        return geom, False, f"Geometry invalid and repair failed: {str(e)}"


def get_vertex_count(geom: Optional[BaseGeometry]) -> int:
    """Return total number of vertices in a geometry."""
    if geom is None or geom.is_empty:
        return 0
    try:
        return shapely.get_num_coordinates(geom)
    except Exception:
        return 0


def get_bbox(geom: Optional[BaseGeometry]) -> Optional[List[float]]:
    """Return [minx, miny, maxx, maxy] bounding box."""
    if geom is None or geom.is_empty:
        return None
    try:
        bounds = geom.bounds
        return [round(c, 6) for c in bounds]
    except Exception:
        return None


def get_centroid_coords(geom: Optional[BaseGeometry]) -> Optional[List[float]]:
    """Return [lon/x, lat/y] centroid coordinates."""
    if geom is None or geom.is_empty:
        return None
    try:
        c = geom.centroid
        return [round(c.x, 6), round(c.y, 6)]
    except Exception:
        return None

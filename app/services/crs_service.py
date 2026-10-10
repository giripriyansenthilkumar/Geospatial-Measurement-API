"""CRS detection, local UTM selection, and coordinate reprojection service."""

from typing import Optional, Tuple

import pyproj
import shapely.ops
from pyproj import Transformer
from shapely.geometry.base import BaseGeometry


def utm_epsg(lon: float, lat: float) -> int:
    """
    Compute EPSG code for the appropriate UTM zone for a (lon, lat) coordinate.
    lon in [-180, 180], lat in [-90, 90].
    """
    # Wrap lon between -180 and 180
    norm_lon = ((lon + 180.0) % 360.0) - 180.0
    zone = min(int((norm_lon + 180.0) // 6) + 1, 60)
    base = 32600 if lat >= 0 else 32700
    return base + zone


class CrsService:
    """Provides CRS analysis, reprojection transformers, and UTM zone selection."""

    WGS84_CRS_STR = "EPSG:4326"

    @classmethod
    def to_wgs84(
        cls, geom: BaseGeometry, src_crs_str: str
    ) -> BaseGeometry:
        """Reproject geometry from src_crs to WGS84 (EPSG:4326) with always_xy=True."""
        if geom is None or geom.is_empty:
            return geom

        # Check if already WGS84
        try:
            crs_obj = pyproj.CRS.from_user_input(src_crs_str)
            epsg = crs_obj.to_epsg()
            if epsg == 4326:
                return geom
        except Exception:
            pass

        transformer = Transformer.from_crs(src_crs_str, cls.WGS84_CRS_STR, always_xy=True)
        return shapely.ops.transform(transformer.transform, geom)

    @classmethod
    def get_measurement_crs_and_projected_geom(
        cls, geom: BaseGeometry, src_crs_str: str, custom_target_crs: Optional[str] = None
    ) -> Tuple[str, BaseGeometry, BaseGeometry]:
        """
        Determine appropriate metric CRS and reproject geometry.
        Also returns the geometry in WGS84 for geodesic cross-checking.

        Returns:
            (projected_crs_str, projected_geom, wgs84_geom)
        """
        geom_wgs84 = cls.to_wgs84(geom, src_crs_str)

        # If user explicitly supplied a target CRS
        if custom_target_crs:
            transformer = Transformer.from_crs(src_crs_str, custom_target_crs, always_xy=True)
            projected_geom = shapely.ops.transform(transformer.transform, geom)
            return custom_target_crs, projected_geom, geom_wgs84

        try:
            crs_obj = pyproj.CRS.from_user_input(src_crs_str)
        except Exception:
            crs_obj = pyproj.CRS.from_user_input(cls.WGS84_CRS_STR)

        # Case 1: Already projected with metre units
        if crs_obj.is_projected:
            unit_name = crs_obj.axis_info[0].unit_name.lower()
            if unit_name in ("metre", "meter", "m"):
                # Use source CRS directly
                return src_crs_str, geom, geom_wgs84

        # Case 2: Geographic or non-metre projected CRS -> pick per-feature local UTM
        rep_pt = geom_wgs84.representative_point()
        epsg_code = utm_epsg(rep_pt.x, rep_pt.y)
        utm_crs_str = f"EPSG:{epsg_code}"

        transformer = Transformer.from_crs(src_crs_str, utm_crs_str, always_xy=True)
        projected_geom = shapely.ops.transform(transformer.transform, geom)

        return utm_crs_str, projected_geom, geom_wgs84

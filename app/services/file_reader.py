"""Reader service for Shapefile (.zip) and KML geospatial datasets."""

import math
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import pyogrio
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry

from app.core.errors import IncompleteShapefileError, InvalidFileError
from app.services.geometry_utils import ensure_2d, validate_and_repair


def clean_properties(props: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure properties dictionary is clean and JSON serializable."""
    cleaned: Dict[str, Any] = {}
    for k, v in props.items():
        if k in ("geometry", "shape", "geom"):
            continue
        if v is None:
            cleaned[k] = None
        elif isinstance(v, (float, int)):
            if math.isnan(v) or math.isinf(v):
                cleaned[k] = None
            else:
                cleaned[k] = v
        elif isinstance(v, (pd.Timestamp, pd.Timedelta)):
            cleaned[k] = str(v)
        elif pd.isna(v):
            cleaned[k] = None
        else:
            cleaned[k] = v
    return cleaned


class ExtractedFeature:
    """In-memory representation of an extracted feature before measurement and persistence."""

    def __init__(
        self,
        feature_index: int,
        layer_name: Optional[str],
        geom: Optional[BaseGeometry],
        is_valid: bool,
        crs: str,
        properties: Dict[str, Any],
        warnings: List[str],
    ) -> None:
        self.feature_index = feature_index
        self.layer_name = layer_name
        self.geom = geom
        self.is_valid = is_valid
        self.crs = crs
        self.properties = properties
        self.warnings = warnings
        self.geometry_type = geom.geom_type if geom is not None and not geom.is_empty else "None"
        self.geojson = mapping(geom) if geom is not None and not geom.is_empty else None


class ReadResult:
    """Result of reading a geospatial file."""

    def __init__(
        self,
        crs: str,
        crs_assumed: bool,
        features: List[ExtractedFeature],
        file_warnings: List[str],
    ) -> None:
        self.crs = crs
        self.crs_assumed = crs_assumed
        self.features = features
        self.file_warnings = file_warnings


def read_shapefile(shp_path: Path) -> ReadResult:
    """Read an extracted Shapefile using pyogrio."""
    file_warnings: List[str] = []
    try:
        gdf = pyogrio.read_dataframe(shp_path)
    except Exception as e:
        raise InvalidFileError(f"Failed to read Shapefile: {str(e)}")

    if len(gdf) == 0:
        raise IncompleteShapefileError("Shapefile contains zero features.")

    # Determine CRS
    crs_assumed = False
    if gdf.crs is None:
        crs_str = "EPSG:4326"
        crs_assumed = True
        file_warnings.append("Missing .prj file; assumed CRS EPSG:4326.")
    else:
        epsg = gdf.crs.to_epsg()
        crs_str = f"EPSG:{epsg}" if epsg else gdf.crs.to_string()

    features: List[ExtractedFeature] = []
    layer_name = shp_path.stem

    for idx, row in enumerate(gdf.iterfeatures()):
        feat_warnings: List[str] = []
        raw_geom = None
        if row.get("geometry"):
            try:
                import shapely.geometry
                raw_geom = shapely.geometry.shape(row["geometry"])
            except Exception as e:
                feat_warnings.append(f"Geometry parsing error: {str(e)}")

        # Normalise geometry
        geom_2d = ensure_2d(raw_geom)
        repaired_geom, is_valid_orig, repair_note = validate_and_repair(geom_2d)

        if repair_note:
            feat_warnings.append(repair_note)

        if repaired_geom is None or repaired_geom.is_empty:
            feat_warnings.append("Geometry is empty or null.")

        props = clean_properties(row.get("properties") or {})

        features.append(
            ExtractedFeature(
                feature_index=idx,
                layer_name=layer_name,
                geom=repaired_geom,
                is_valid=is_valid_orig,
                crs=crs_str,
                properties=props,
                warnings=feat_warnings,
            )
        )

    return ReadResult(
        crs=crs_str,
        crs_assumed=crs_assumed,
        features=features,
        file_warnings=file_warnings,
    )


def read_kml(kml_path: Path) -> ReadResult:
    """Read a KML file, enumerating layers and reading each."""
    file_warnings: List[str] = []
    crs_str = "EPSG:4326"  # KML is always WGS84 by specification
    crs_assumed = False

    try:
        layer_list = pyogrio.list_layers(kml_path)
    except Exception as e:
        raise InvalidFileError(f"Failed to inspect KML layers: {str(e)}")

    if len(layer_list) == 0:
        raise IncompleteShapefileError("KML file contains zero layers or features.")

    all_features: List[ExtractedFeature] = []
    feature_counter = 0

    for layer_entry in layer_list:
        layer_name = layer_entry[0]
        try:
            gdf = pyogrio.read_dataframe(kml_path, layer=layer_name)
        except Exception:
            continue

        for _, row in enumerate(gdf.iterfeatures()):
            feat_warnings: List[str] = []
            raw_geom = None
            if row.get("geometry"):
                try:
                    import shapely.geometry
                    raw_geom = shapely.geometry.shape(row["geometry"])
                except Exception as e:
                    feat_warnings.append(f"Geometry parsing error: {str(e)}")

            geom_2d = ensure_2d(raw_geom)
            repaired_geom, is_valid_orig, repair_note = validate_and_repair(geom_2d)

            if repair_note:
                feat_warnings.append(repair_note)

            if repaired_geom is None or repaired_geom.is_empty:
                feat_warnings.append("Geometry is empty or null.")

            props = clean_properties(row.get("properties") or {})

            all_features.append(
                ExtractedFeature(
                    feature_index=feature_counter,
                    layer_name=layer_name,
                    geom=repaired_geom,
                    is_valid=is_valid_orig,
                    crs=crs_str,
                    properties=props,
                    warnings=feat_warnings,
                )
            )
            feature_counter += 1

    if not all_features:
        raise IncompleteShapefileError("KML file contains zero features.")

    return ReadResult(
        crs=crs_str,
        crs_assumed=crs_assumed,
        features=all_features,
        file_warnings=file_warnings,
    )

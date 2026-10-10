"""Unit tests for Shapefile and KML reading and geometry normalization."""

from pathlib import Path

import pytest

from app.core.errors import IncompleteShapefileError, InvalidFileError
from app.services.file_reader import read_kml, read_shapefile
from app.services.file_validator import validate_and_extract_shapefile_zip
from tests.conftest import create_shapefile_zip


def test_read_kml_valid(tmp_path: Path, valid_kml_bytes: bytes):
    kml_file = tmp_path / "survey.kml"
    kml_file.write_bytes(valid_kml_bytes)

    result = read_kml(kml_file)
    assert result.crs == "EPSG:4326"
    assert result.crs_assumed is False
    assert len(result.features) == 3

    geom_types = [f.geometry_type for f in result.features]
    assert "Polygon" in geom_types
    assert "LineString" in geom_types
    assert "Point" in geom_types


def test_read_kml_multi_layer(tmp_path: Path, multi_layer_kml_bytes: bytes):
    kml_file = tmp_path / "multi.kml"
    kml_file.write_bytes(multi_layer_kml_bytes)

    result = read_kml(kml_file)
    assert len(result.features) == 2
    layers = {f.layer_name for f in result.features}
    assert "Zoning" in layers
    assert "Infrastructure" in layers


def test_read_kml_corrupt(tmp_path: Path):
    corrupt_file = tmp_path / "corrupt.kml"
    corrupt_file.write_bytes(b"<kml>Corrupt unmatched XML")

    with pytest.raises(InvalidFileError):
        read_kml(corrupt_file)


def test_read_kml_empty(tmp_path: Path):
    empty_kml = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document></Document>
</kml>"""
    kml_file = tmp_path / "empty.kml"
    kml_file.write_text(empty_kml)

    with pytest.raises(IncompleteShapefileError):
        read_kml(kml_file)


def test_read_shapefile_with_prj(tmp_path: Path):
    zip_bytes = create_shapefile_zip(include_prj=True)
    zip_file = tmp_path / "with_prj.zip"
    zip_file.write_bytes(zip_bytes)

    target_dir = tmp_path / "extracted_with_prj"
    shp_path, _ = validate_and_extract_shapefile_zip(zip_file, target_dir)

    result = read_shapefile(shp_path)
    assert result.crs == "EPSG:4326"
    assert result.crs_assumed is False
    assert len(result.features) == 3


def test_read_shapefile_missing_prj(tmp_path: Path):
    zip_bytes = create_shapefile_zip(include_prj=False)
    zip_file = tmp_path / "no_prj.zip"
    zip_file.write_bytes(zip_bytes)

    target_dir = tmp_path / "extracted_no_prj"
    shp_path, _ = validate_and_extract_shapefile_zip(zip_file, target_dir)

    result = read_shapefile(shp_path)
    assert result.crs == "EPSG:4326"
    assert result.crs_assumed is True
    assert any("assumed CRS" in w for w in result.file_warnings)


def test_read_shapefile_empty_dataset(tmp_path: Path):
    # Shapefile with 0 features
    zip_bytes = create_shapefile_zip(is_empty=True)
    zip_file = tmp_path / "empty.zip"
    zip_file.write_bytes(zip_bytes)

    target_dir = tmp_path / "extracted_empty"
    shp_path, _ = validate_and_extract_shapefile_zip(zip_file, target_dir)

    with pytest.raises(IncompleteShapefileError) as exc:
        read_shapefile(shp_path)
    assert "zero features" in str(exc.value)

"""Unit tests for file validator (extensions, magic bytes, zip security)."""

import io
import zipfile
from pathlib import Path

import pytest

from app.core.errors import (
    IncompleteShapefileError,
    InvalidFileError,
    UnsupportedTypeError,
)
from app.services.file_validator import (
    validate_and_extract_shapefile_zip,
    validate_file_extension,
    validate_magic_bytes,
)
from tests.conftest import create_shapefile_zip


def test_validate_file_extension_supported():
    assert validate_file_extension("survey.zip") == "shp_zip"
    assert validate_file_extension("BOUNDARY.KML") == "kml"
    assert validate_file_extension("test.ZIP") == "shp_zip"


def test_validate_file_extension_unsupported():
    with pytest.raises(UnsupportedTypeError) as exc:
        validate_file_extension("data.geojson")
    assert exc.value.status_code == 415

    with pytest.raises(UnsupportedTypeError):
        validate_file_extension("archive.tar.gz")

    with pytest.raises(UnsupportedTypeError):
        validate_file_extension("sample.csv")


def test_validate_magic_bytes_zip_valid(tmp_path: Path):
    zip_bytes = create_shapefile_zip()
    file_path = tmp_path / "valid.zip"
    file_path.write_bytes(zip_bytes)

    # Should not raise
    validate_magic_bytes(file_path, "shp_zip")


def test_validate_magic_bytes_zip_corrupt(tmp_path: Path):
    file_path = tmp_path / "corrupt.zip"
    file_path.write_bytes(b"NOT_A_ZIP_HEADER_DATA_12345")

    with pytest.raises(InvalidFileError) as exc:
        validate_magic_bytes(file_path, "shp_zip")
    assert exc.value.status_code == 400


def test_validate_magic_bytes_kml_valid(tmp_path: Path, valid_kml_bytes: bytes):
    file_path = tmp_path / "valid.kml"
    file_path.write_bytes(valid_kml_bytes)

    validate_magic_bytes(file_path, "kml")


def test_validate_magic_bytes_kml_corrupt(tmp_path: Path):
    file_path = tmp_path / "corrupt.kml"
    file_path.write_bytes(b"THIS IS RAW TEXT NOT XML AT ALL")

    with pytest.raises(InvalidFileError) as exc:
        validate_magic_bytes(file_path, "kml")
    assert exc.value.status_code == 400


def test_extract_shapefile_complete(tmp_path: Path):
    zip_bytes = create_shapefile_zip(include_prj=True)
    zip_path = tmp_path / "complete.zip"
    zip_path.write_bytes(zip_bytes)

    target_dir = tmp_path / "extracted"
    shp_path, warnings = validate_and_extract_shapefile_zip(zip_path, target_dir)

    assert shp_path.exists()
    assert shp_path.suffix == ".shp"
    assert len(warnings) == 0


def test_extract_shapefile_missing_prj_warning(tmp_path: Path):
    zip_bytes = create_shapefile_zip(include_prj=False)
    zip_path = tmp_path / "no_prj.zip"
    zip_path.write_bytes(zip_bytes)

    target_dir = tmp_path / "extracted_no_prj"
    shp_path, warnings = validate_and_extract_shapefile_zip(zip_path, target_dir)

    assert shp_path.exists()
    assert any("No .prj file found" in w for w in warnings)


def test_extract_shapefile_missing_shx_fails(tmp_path: Path):
    zip_bytes = create_shapefile_zip(missing_companion=".shx")
    zip_path = tmp_path / "missing_shx.zip"
    zip_path.write_bytes(zip_bytes)

    target_dir = tmp_path / "extracted_missing"
    with pytest.raises(IncompleteShapefileError) as exc:
        validate_and_extract_shapefile_zip(zip_path, target_dir)
    assert exc.value.status_code == 422
    assert ".shx" in str(exc.value)


def test_extract_shapefile_missing_dbf_fails(tmp_path: Path):
    zip_bytes = create_shapefile_zip(missing_companion=".dbf")
    zip_path = tmp_path / "missing_dbf.zip"
    zip_path.write_bytes(zip_bytes)

    target_dir = tmp_path / "extracted_missing"
    with pytest.raises(IncompleteShapefileError) as exc:
        validate_and_extract_shapefile_zip(zip_path, target_dir)
    assert exc.value.status_code == 422
    assert ".dbf" in str(exc.value)


def test_extract_shapefile_zip_slip_protection(tmp_path: Path):
    # Construct an archive with malicious traversal filename
    slip_buf = io.BytesIO()
    with zipfile.ZipFile(slip_buf, "w") as zf:
        zf.writestr("../../etc/passwd", "malicious_content")
        zf.writestr("test.shp", "shp_content")
        zf.writestr("test.shx", "shx_content")
        zf.writestr("test.dbf", "dbf_content")

    slip_path = tmp_path / "slip.zip"
    slip_path.write_bytes(slip_buf.getvalue())

    target_dir = tmp_path / "extracted_slip"
    with pytest.raises(InvalidFileError) as exc:
        validate_and_extract_shapefile_zip(slip_path, target_dir)
    assert "Zip-slip" in str(exc.value)


def test_extract_shapefile_zip_bomb_entry_cap(tmp_path: Path):
    # Construct an archive exceeding MAX_ZIP_ENTRIES (default 500)
    bomb_buf = io.BytesIO()
    with zipfile.ZipFile(bomb_buf, "w") as zf:
        for i in range(505):
            zf.writestr(f"file_{i}.txt", "data")

    bomb_path = tmp_path / "bomb.zip"
    bomb_path.write_bytes(bomb_buf.getvalue())

    target_dir = tmp_path / "extracted_bomb"
    with pytest.raises(InvalidFileError) as exc:
        validate_and_extract_shapefile_zip(bomb_path, target_dir)
    assert "too many entries" in str(exc.value)

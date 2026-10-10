"""File validation for extensions, streaming size, magic bytes, and zip security."""

import zipfile
from pathlib import Path
from typing import List, Tuple

import defusedxml.ElementTree as ET

from app.config import settings
from app.core.errors import (
    FileTooLargeError,
    IncompleteShapefileError,
    InvalidFileError,
    UnsupportedTypeError,
)


def validate_file_extension(filename: str) -> str:
    """
    Validate extension and return normalized file type ('shp_zip' or 'kml').
    Raises UnsupportedTypeError (415) if not .zip or .kml.
    """
    if not filename:
        raise UnsupportedTypeError("Filename is missing or empty.")

    lower_name = filename.lower()
    if lower_name.endswith(".zip"):
        return "shp_zip"
    elif lower_name.endswith(".kml"):
        return "kml"
    else:
        raise UnsupportedTypeError(
            f"Unsupported file format for '{filename}'. Only .zip (Shapefile) and .kml are supported."
        )


def validate_magic_bytes(file_path: Path, file_type: str) -> None:
    """
    Verify magic bytes/content structure of the uploaded file.
    Raises InvalidFileError (400) if header signature does not match.
    """
    if not file_path.exists() or file_path.stat().st_size == 0:
        raise InvalidFileError("Uploaded file is empty or does not exist.")

    with file_path.open("rb") as f:
        header = f.read(512)

    if file_type == "shp_zip":
        # Standard PK zip headers: PK\x03\x04 or PK\x05\x06 (empty) or PK\x07\x08 (spanned)
        if not header.startswith(b"PK"):
            raise InvalidFileError("Invalid zip archive: file header does not match zip format.")
    elif file_type == "kml":
        # Check XML declaration or <kml tag in head of file
        header_text = header.decode("utf-8", errors="ignore").lower()
        if "<kml" not in header_text and "<?xml" not in header_text:
            raise InvalidFileError("Invalid KML file: file does not contain valid XML/KML markup.")
        # Verify XML parses safely without entity expansion attacks
        try:
            with file_path.open("rb") as f:
                # Parse with defusedxml to guard against XXE
                ET.parse(f)
        except Exception as e:
            raise InvalidFileError(f"Corrupted or invalid KML file: {str(e)}")


def validate_and_extract_shapefile_zip(
    zip_path: Path, target_dir: Path
) -> Tuple[Path, List[str]]:
    """
    Inspect zip for zip-slip, zip-bomb, and shapefile required members (.shp, .shx, .dbf).
    Extracts only shapefile components into target_dir.

    Returns:
        (extracted_shp_path, warnings_list)
    """
    warnings: List[str] = []

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            members = zf.infolist()

            # Zip bomb check 1: entry count cap
            if len(members) > settings.MAX_ZIP_ENTRIES:
                raise InvalidFileError(
                    f"Zip archive contains too many entries ({len(members)} > {settings.MAX_ZIP_ENTRIES})."
                )

            # Zip bomb check 2: uncompressed size cap
            total_uncompressed = sum(m.file_size for m in members)
            if total_uncompressed > settings.max_uncompressed_bytes:
                raise FileTooLargeError(
                    f"Uncompressed archive size ({total_uncompressed // (1024*1024)}MB) exceeds limit of {settings.MAX_UNCOMPRESSED_MB}MB."
                )

            # Zip slip check: test all paths
            for m in members:
                norm_name = m.filename.replace("\\", "/")
                p = Path(norm_name)
                if p.is_absolute() or ".." in p.parts:
                    raise InvalidFileError(
                        f"Zip-slip path traversal attempt detected in archive entry: {m.filename}"
                    )

            # Identify shapefile sets (.shp, .shx, .dbf, .prj)
            shp_members = [
                m for m in members if not m.is_dir() and m.filename.lower().endswith(".shp")
            ]
            if not shp_members:
                raise IncompleteShapefileError(
                    "No .shp file found inside the zip archive."
                )

            # Pick the primary shapefile (first one found)
            primary_shp = shp_members[0]
            shp_stem = Path(primary_shp.filename).stem.lower()
            shp_parent = Path(primary_shp.filename).parent

            # Companion extensions required and optional
            companion_exts = {".shx", ".dbf"}
            found_exts = set()
            has_prj = False

            for m in members:
                if m.is_dir():
                    continue
                mp = Path(m.filename)
                if mp.parent == shp_parent and mp.stem.lower() == shp_stem:
                    ext = mp.suffix.lower()
                    if ext in companion_exts:
                        found_exts.add(ext)
                    if ext == ".prj":
                        has_prj = True

            missing = companion_exts - found_exts
            if missing:
                missing_str = ", ".join(missing)
                raise IncompleteShapefileError(
                    f"Incomplete Shapefile '{primary_shp.filename}': missing required companion file(s): {missing_str}"
                )

            if not has_prj:
                warnings.append("No .prj file found in Shapefile archive. Assuming EPSG:4326.")

            # Safe extraction of only relevant shapefile files
            allowed_suffixes = {".shp", ".shx", ".dbf", ".prj", ".cpg", ".qpj", ".sbn", ".sbx"}
            target_dir.mkdir(parents=True, exist_ok=True)

            extracted_shp_path: Path | None = None
            for m in members:
                if m.is_dir():
                    continue
                mp = Path(m.filename)
                if mp.suffix.lower() in allowed_suffixes:
                    # Flatten filename into target_dir to avoid nested directory traversal issues
                    flat_filename = mp.name
                    dest_file = target_dir / flat_filename
                    with zf.open(m) as src, open(dest_file, "wb") as dst:
                        dst.write(src.read())

                    if mp.suffix.lower() == ".shp" and (
                        extracted_shp_path is None or mp.stem.lower() == shp_stem
                    ):
                        extracted_shp_path = dest_file

            if not extracted_shp_path or not extracted_shp_path.exists():
                raise IncompleteShapefileError("Failed to extract valid .shp file from archive.")

            return extracted_shp_path, warnings

    except zipfile.BadZipFile as e:
        raise InvalidFileError(f"Corrupt or unreadable zip archive: {str(e)}")

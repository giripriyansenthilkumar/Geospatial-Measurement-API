"""Pipeline orchestrator for reading, measuring, and persisting geospatial files."""

import shutil
import tempfile
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.core.errors import GeoMeasureException, InvalidFileError
from app.core.logging import logger
from app.models.files import UploadedFile
from app.repositories.feature_repo import FeatureRepository
from app.repositories.file_repo import FileRepository
from app.services.file_reader import read_kml, read_shapefile
from app.services.file_validator import validate_and_extract_shapefile_zip
from app.services.measurement import measure_geometry


class FileProcessor:
    """Orchestrates end-to-end ingestion, reprojection, measurement, and persistence."""

    @classmethod
    def process_file(
        cls,
        db: Session,
        file_record: UploadedFile,
        custom_target_crs: Optional[str] = None,
    ) -> UploadedFile:
        """Execute the measurement pipeline on an uploaded file."""
        file_id = file_record.id
        stored_path = Path(file_record.stored_path)
        file_type = file_record.file_type

        logger.info(f"Beginning processing for file {file_id} ({file_record.filename})")
        FileRepository.update_status(db, file_id, status="PROCESSING")

        temp_extract_dir: Optional[Path] = None
        try:
            file_warnings = list(file_record.warnings or [])

            if file_type == "shp_zip":
                # Create a secure temporary directory for extraction
                temp_extract_dir = Path(tempfile.mkdtemp(prefix=f"extract_{file_id}_"))
                shp_path, zip_warnings = validate_and_extract_shapefile_zip(
                    stored_path, temp_extract_dir
                )
                file_warnings.extend(zip_warnings)
                read_result = read_shapefile(shp_path)
            elif file_type == "kml":
                read_result = read_kml(stored_path)
            else:
                raise InvalidFileError(f"Unsupported internal file type: {file_type}")

            file_warnings.extend(read_result.file_warnings)

            # Process each feature
            feature_dicts = []
            for feat in read_result.features:
                measurement = measure_geometry(
                    feat.geom,
                    src_crs=read_result.crs,
                    custom_target_crs=custom_target_crs,
                )

                combined_warnings = list(feat.warnings)
                for w in measurement.warnings:
                    if w not in combined_warnings:
                        combined_warnings.append(w)

                f_dict = {
                    "file_id": file_id,
                    "feature_index": feat.feature_index,
                    "layer_name": feat.layer_name,
                    "geometry_type": feat.geometry_type,
                    "geometry": feat.geojson or {},
                    "crs": feat.crs,
                    "properties": feat.properties,
                    "is_valid": feat.is_valid,
                    "measurement_type": measurement.measurement_type,
                    "measurement_value": measurement.measurement_value,
                    "measurement_unit": measurement.measurement_unit,
                    "method": measurement.method,
                    "projected_crs": measurement.projected_crs,
                    "geodesic_value": measurement.geodesic_value,
                    "difference_pct": measurement.difference_pct,
                    "note": measurement.note,
                    "warnings": combined_warnings,
                    "perimeter": measurement.perimeter,
                    "vertex_count": measurement.vertex_count,
                    "centroid": measurement.centroid,
                    "bbox": measurement.bbox,
                }
                feature_dicts.append(f_dict)

            # Persist features in bulk
            FeatureRepository.bulk_create(db, feature_dicts)

            # Mark file COMPLETED
            updated_file = FileRepository.update_status(
                db,
                file_id=file_id,
                status="COMPLETED",
                feature_count=len(feature_dicts),
                crs=read_result.crs,
                crs_assumed=read_result.crs_assumed,
                warnings=file_warnings,
            )
            logger.info(
                f"Successfully processed file {file_id}: {len(feature_dicts)} features measured."
            )
            return updated_file or file_record

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Processing failed for file {file_id}: {error_msg}", exc_info=True)
            FileRepository.update_status(
                db,
                file_id=file_id,
                status="FAILED",
                error_message=error_msg,
            )
            if isinstance(e, GeoMeasureException):
                raise
            raise InvalidFileError(f"Error processing file: {error_msg}") from e

        finally:
            # Cleanup temporary extracted files
            if temp_extract_dir and temp_extract_dir.exists():
                try:
                    shutil.rmtree(temp_extract_dir)
                except Exception as cleanup_err:
                    logger.warning(f"Failed to remove temp extract directory: {cleanup_err}")

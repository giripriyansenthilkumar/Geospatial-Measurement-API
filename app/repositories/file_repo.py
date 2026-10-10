"""Repository for UploadedFile database operations."""

import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.files import UploadedFile


class FileRepository:
    """Handles CRUD operations for UploadedFile records."""

    @staticmethod
    def create(db: Session, file_obj: UploadedFile) -> UploadedFile:
        db.add(file_obj)
        db.commit()
        db.refresh(file_obj)
        return file_obj

    @staticmethod
    def get_by_id(db: Session, file_id: str) -> Optional[UploadedFile]:
        return db.query(UploadedFile).filter(UploadedFile.id == file_id).first()

    @staticmethod
    def get_by_sha256(db: Session, sha256_hash: str) -> Optional[UploadedFile]:
        """Find an existing successfully completed file with identical hash for deduplication."""
        return (
            db.query(UploadedFile)
            .filter(UploadedFile.sha256 == sha256_hash, UploadedFile.status == "COMPLETED")
            .first()
        )

    @staticmethod
    def update_status(
        db: Session,
        file_id: str,
        status: str,
        error_message: Optional[str] = None,
        feature_count: Optional[int] = None,
        crs: Optional[str] = None,
        crs_assumed: Optional[bool] = None,
        warnings: Optional[List[str]] = None,
    ) -> Optional[UploadedFile]:
        file_record = db.query(UploadedFile).filter(UploadedFile.id == file_id).first()
        if not file_record:
            return None

        file_record.status = status
        if error_message is not None:
            file_record.error_message = error_message
        if feature_count is not None:
            file_record.feature_count = feature_count
        if crs is not None:
            file_record.crs = crs
        if crs_assumed is not None:
            file_record.crs_assumed = crs_assumed
        if warnings is not None:
            current_warnings = list(file_record.warnings or [])
            for w in warnings:
                if w not in current_warnings:
                    current_warnings.append(w)
            file_record.warnings = current_warnings

        if status in ("COMPLETED", "FAILED"):
            file_record.completed_at = datetime.datetime.now(datetime.timezone.utc)

        db.commit()
        db.refresh(file_record)
        return file_record

"""Repository for Feature database operations."""

from typing import List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.files import Feature


class FeatureRepository:
    """Handles CRUD operations for Feature records."""

    @staticmethod
    def bulk_create(db: Session, features_data: List[dict]) -> None:
        """Insert features efficiently in a single batch."""
        if not features_data:
            return
        feature_objs = [Feature(**item) for item in features_data]
        db.add_all(feature_objs)
        db.commit()

    @staticmethod
    def get_paginated(
        db: Session,
        file_id: str,
        page: int = 1,
        page_size: int = 50,
        geometry_type: Optional[str] = None,
    ) -> Tuple[List[Feature], int]:
        """Fetch paginated features for a given file with optional geometry_type filtering."""
        query = db.query(Feature).filter(Feature.file_id == file_id)

        if geometry_type:
            query = query.filter(
                func.lower(Feature.geometry_type) == geometry_type.strip().lower()
            )

        total = query.count()
        offset = (page - 1) * page_size
        results = (
            query.order_by(Feature.feature_index.asc())
            .offset(offset)
            .limit(page_size)
            .all()
        )
        return results, total

    @staticmethod
    def get_all_for_file(db: Session, file_id: str) -> List[Feature]:
        """Fetch all features for a file (useful for summary stats and GeoJSON/CSV export)."""
        return (
            db.query(Feature)
            .filter(Feature.file_id == file_id)
            .order_by(Feature.feature_index.asc())
            .all()
        )

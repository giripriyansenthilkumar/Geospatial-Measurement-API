"""Shared test configuration, fixtures, and geospatial test data generators."""

import io
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Generator

import geopandas as gpd
import pandas as pd
import pytest
import shapely.geometry as sg
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from starlette.testclient import TestClient

import app.api.deps as deps
from app.api.deps import get_db
from app.config import settings
from app.main import app
from app.models.base import Base


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment() -> Generator[None, None, None]:
    """Configure test database and temporary upload directory."""
    test_db_path = Path(tempfile.gettempdir()) / "test_geo_measure.db"
    if test_db_path.exists():
        test_db_path.unlink()

    test_engine = create_engine(
        f"sqlite:///{test_db_path}",
        connect_args={"check_same_thread": False},
    )
    deps.engine = test_engine
    deps.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    Base.metadata.create_all(bind=test_engine)

    test_storage = Path(tempfile.gettempdir()) / "test_uploads"
    test_storage.mkdir(parents=True, exist_ok=True)
    settings.STORAGE_DIR = str(test_storage)

    yield

    Base.metadata.drop_all(bind=test_engine)
    if test_db_path.exists():
        test_db_path.unlink()
    if test_storage.exists():
        shutil.rmtree(test_storage, ignore_errors=True)


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """Provide a transactional database session for a test."""
    session = deps.SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """Test client configured with test database session."""
    def override_get_db():
        session = deps.SessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def valid_kml_bytes() -> bytes:
    """Sample valid KML containing Polygon, LineString, and Point features."""
    kml_str = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Survey Dataset</name>
    <Placemark>
      <name>Plot Alpha</name>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>
              77.5900,12.9700,0
              77.5910,12.9700,0
              77.5910,12.9710,0
              77.5900,12.9710,0
              77.5900,12.9700,0
            </coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
    <Placemark>
      <name>Boundary Line</name>
      <LineString>
        <coordinates>
          77.5900,12.9700,0
          77.5920,12.9700,0
        </coordinates>
      </LineString>
    </Placemark>
    <Placemark>
      <name>Benchmark Point</name>
      <Point>
        <coordinates>77.5905,12.9705,0</coordinates>
      </Point>
    </Placemark>
  </Document>
</kml>
"""
    return kml_str.encode("utf-8")


@pytest.fixture
def multi_layer_kml_bytes() -> bytes:
    """Sample multi-layer KML containing multiple folders."""
    kml_str = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Multi-Layer Survey</name>
    <Folder>
      <name>Zoning</name>
      <Placemark>
        <name>Zone 1</name>
        <Polygon>
          <outerBoundaryIs>
            <LinearRing>
              <coordinates>
                78.000,10.000,0 78.005,10.000,0 78.005,10.005,0 78.000,10.005,0 78.000,10.000,0
              </coordinates>
            </LinearRing>
          </outerBoundaryIs>
        </Polygon>
      </Placemark>
    </Folder>
    <Folder>
      <name>Infrastructure</name>
      <Placemark>
        <name>Transmission Line</name>
        <LineString>
          <coordinates>
            78.000,10.000,0 78.010,10.010,0
          </coordinates>
        </LineString>
      </Placemark>
    </Folder>
  </Document>
</kml>
"""
    return kml_str.encode("utf-8")


def create_shapefile_zip(
    features=None,
    crs="EPSG:4326",
    include_prj=True,
    missing_companion=None,
    is_empty=False,
) -> bytes:
    """Helper to create an in-memory Shapefile zip archive with valid homogenous geometries."""
    if is_empty:
        gdf = gpd.GeoDataFrame(
            {"name": pd.Series(dtype="str"), "geometry": gpd.GeoSeries(dtype="geometry")},
            crs=crs if include_prj else None,
        )
    elif features is not None:
        gdf = gpd.GeoDataFrame(features, crs=crs if include_prj else None)
    else:
        # Standard polygon parcels
        default_features = [
            {"name": "Parcel 1", "geometry": sg.box(77.590, 12.970, 77.595, 12.975)},
            {"name": "Parcel 2", "geometry": sg.box(77.595, 12.970, 77.600, 12.975)},
            {"name": "Parcel 3", "geometry": sg.box(77.600, 12.970, 77.605, 12.975)},
        ]
        gdf = gpd.GeoDataFrame(default_features, crs=crs if include_prj else None)

    temp_dir = tempfile.mkdtemp()
    shp_path = Path(temp_dir) / "parcels.shp"
    gdf.to_file(shp_path)

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in Path(temp_dir).iterdir():
            if missing_companion and file.suffix.lower() == missing_companion:
                continue
            if not include_prj and file.suffix.lower() == ".prj":
                continue
            zf.write(file, arcname=file.name)

    shutil.rmtree(temp_dir, ignore_errors=True)
    return zip_buffer.getvalue()

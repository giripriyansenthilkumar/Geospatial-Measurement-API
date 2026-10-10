"""API route handlers for geospatial file management, measurements, summary, export, and preview."""

import csv
import hashlib
import io
import json
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.config import settings
from app.core.errors import (
    FileNotFoundError,
    FileNotReadyError,
    FileTooLargeError,
    InvalidFileError,
)
from app.core.logging import logger
from app.models.files import UploadedFile
from app.repositories.feature_repo import FeatureRepository
from app.repositories.file_repo import FileRepository
from app.schemas.files import (
    FeatureResultItem,
    FileDetailResponse,
    FileSummaryResponse,
    FileUploadResponse,
    MeasurementDetail,
    MeasurementsResponse,
)
from app.services.file_validator import (
    validate_file_extension,
    validate_magic_bytes,
)
from app.services.measurement import convert_measurement
from app.services.processor import FileProcessor

router = APIRouter(prefix="/api/files", tags=["Geospatial Files"])


@router.post(
    "/",
    response_model=FileUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and process a geospatial file",
)
async def upload_file(
    file: UploadFile = File(..., description="Shapefile archive (.zip) or KML file (.kml)"),
    db: Session = Depends(get_db),
) -> FileUploadResponse:
    """
    Upload a Shapefile (.zip) or .kml file.
    Streams upload with size checks, performs security validation, deduplicates by SHA256,
    and calculates projected and geodesic measurements.
    """
    raw_filename = file.filename or "unknown"
    file_type = validate_file_extension(raw_filename)

    file_id = str(uuid.uuid4())
    upload_dir = settings.storage_path / file_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    dest_path = upload_dir / f"original_{raw_filename}"
    sha256_hasher = hashlib.sha256()
    total_bytes = 0

    # Stream the file to disk with strict size enforcement
    try:
        with dest_path.open("wb") as buffer:
            while True:
                chunk = await file.read(64 * 1024)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > settings.max_upload_bytes:
                    raise FileTooLargeError(
                        f"File size exceeds maximum allowed upload limit of {settings.MAX_UPLOAD_MB}MB."
                    )
                sha256_hasher.update(chunk)
                buffer.write(chunk)
    except Exception:
        # Clean up partial upload on failure
        if dest_path.exists():
            dest_path.unlink()
        if upload_dir.exists():
            upload_dir.rmdir()
        raise
    finally:
        await file.close()

    sha256_hex = sha256_hasher.hexdigest()

    # Validate file magic bytes
    validate_magic_bytes(dest_path, file_type)

    # Check for duplicate file (Deduplication)
    existing_record = FileRepository.get_by_sha256(db, sha256_hex)
    if existing_record:
        logger.info(
            f"File duplicate detected with SHA256 {sha256_hex}. Reusing existing file {existing_record.id}."
        )
        # Clean up duplicate upload on disk
        if dest_path.exists():
            dest_path.unlink()
        if upload_dir.exists():
            upload_dir.rmdir()

        warnings = list(existing_record.warnings or [])
        warnings.append(f"Identical file already processed under ID {existing_record.id} (SHA256 deduplicated).")

        return FileUploadResponse(
            id=existing_record.id,
            filename=raw_filename,
            feature_count=existing_record.feature_count,
            crs=existing_record.crs,
            status=existing_record.status,
            warnings=warnings,
        )

    # Persist pending file entry
    file_record = UploadedFile(
        id=file_id,
        filename=raw_filename,
        stored_path=str(dest_path),
        file_type=file_type,
        sha256=sha256_hex,
        status="PENDING",
        feature_count=0,
        warnings=[],
    )
    FileRepository.create(db, file_record)

    # Process file synchronously (reproject and measure)
    processed = FileProcessor.process_file(db, file_record)

    return FileUploadResponse(
        id=processed.id,
        filename=processed.filename,
        feature_count=processed.feature_count,
        crs=processed.crs,
        status=processed.status,
        warnings=processed.warnings or [],
    )


@router.get(
    "/{id}/",
    response_model=FileDetailResponse,
    summary="Get geospatial file metadata and status",
)
def get_file_info(
    id: str,
    db: Session = Depends(get_db),
) -> FileDetailResponse:
    """Retrieve file metadata, processing status, detected CRS, and any file-level warnings."""
    file_record = FileRepository.get_by_id(db, id)
    if not file_record:
        raise FileNotFoundError(f"File with ID '{id}' was not found.")

    return FileDetailResponse(
        id=file_record.id,
        filename=file_record.filename,
        file_type=file_record.file_type,
        feature_count=file_record.feature_count,
        crs=file_record.crs,
        crs_assumed=file_record.crs_assumed,
        status=file_record.status,
        created_at=file_record.created_at,
        warnings=file_record.warnings or [],
    )


@router.get(
    "/{id}/measurements/",
    response_model=MeasurementsResponse,
    summary="Get paginated feature measurements with unit conversion",
)
def get_file_measurements(
    id: str,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=500, description="Items per page"),
    geometry_type: Optional[str] = Query(None, description="Filter by geometry type (e.g. Polygon, LineString, Point)"),
    unit: Optional[str] = Query(None, description="Optional unit conversion (sq_m, sq_km, hectare, acre, m, km, mile)"),
    db: Session = Depends(get_db),
) -> MeasurementsResponse:
    """Retrieve measured features with pagination, geometry filtering, and unit conversion."""
    file_record = FileRepository.get_by_id(db, id)
    if not file_record:
        raise FileNotFoundError(f"File with ID '{id}' was not found.")

    if file_record.status == "PROCESSING" or file_record.status == "PENDING":
        raise FileNotReadyError(
            f"File '{id}' is currently in status '{file_record.status}'. Measurements not ready yet."
        )

    if file_record.status == "FAILED":
        raise InvalidFileError(
            f"File '{id}' processing failed: {file_record.error_message or 'Unknown error'}"
        )

    features, total = FeatureRepository.get_paginated(
        db,
        file_id=id,
        page=page,
        page_size=page_size,
        geometry_type=geometry_type,
    )

    results: List[FeatureResultItem] = []
    for feat in features:
        measurement_payload = None
        if feat.measurement_type and feat.measurement_value is not None:
            val, out_unit = convert_measurement(
                feat.measurement_value, feat.measurement_type, target_unit=unit
            )
            # Also convert geodesic cross-check value if requested
            geo_val, _ = convert_measurement(
                feat.geodesic_value, feat.measurement_type, target_unit=unit
            )

            measurement_payload = MeasurementDetail(
                type=feat.measurement_type,
                value=val if val is not None else 0.0,
                unit=out_unit or feat.measurement_unit or "sq_m",
                method=feat.method,
                projected_crs=feat.projected_crs,
                geodesic_value=geo_val,
                difference_pct=feat.difference_pct,
            )

        results.append(
            FeatureResultItem(
                feature_index=feat.feature_index,
                geometry_type=feat.geometry_type,
                crs=feat.crs,
                properties=feat.properties or {},
                geometry=feat.geometry,
                measurement=measurement_payload,
                note=feat.note,
                warnings=feat.warnings or [],
            )
        )

    return MeasurementsResponse(
        file_id=id,
        total=total,
        page=page,
        page_size=page_size,
        results=results,
    )


@router.get(
    "/{id}/summary/",
    response_model=FileSummaryResponse,
    summary="Get aggregated geospatial summary statistics",
)
def get_file_summary(
    id: str,
    db: Session = Depends(get_db),
) -> FileSummaryResponse:
    """
    Returns aggregated metrics: total area, total length, counts by geometry type,
    overall bounding box, and largest/longest features.
    """
    file_record = FileRepository.get_by_id(db, id)
    if not file_record:
        raise FileNotFoundError(f"File with ID '{id}' was not found.")

    if file_record.status != "COMPLETED":
        raise FileNotReadyError(f"File '{id}' is not yet COMPLETED (current status: {file_record.status}).")

    all_features = FeatureRepository.get_all_for_file(db, id)

    total_area = 0.0
    total_length = 0.0
    geometry_counts: Dict[str, int] = {}
    largest_area_feature: Optional[Dict[str, Any]] = None
    longest_line_feature: Optional[Dict[str, Any]] = None

    min_x, min_y, max_x, max_y = float("inf"), float("inf"), float("-inf"), float("-inf")

    for f in all_features:
        gtype = f.geometry_type
        geometry_counts[gtype] = geometry_counts.get(gtype, 0) + 1

        if f.measurement_type == "area" and f.measurement_value is not None:
            total_area += f.measurement_value
            if (
                largest_area_feature is None
                or f.measurement_value > largest_area_feature["area_sq_m"]
            ):
                largest_area_feature = {
                    "feature_index": f.feature_index,
                    "layer_name": f.layer_name,
                    "area_sq_m": f.measurement_value,
                    "properties": f.properties,
                }

        if f.measurement_type == "length" and f.measurement_value is not None:
            total_length += f.measurement_value
            if (
                longest_line_feature is None
                or f.measurement_value > longest_line_feature["length_m"]
            ):
                longest_line_feature = {
                    "feature_index": f.feature_index,
                    "layer_name": f.layer_name,
                    "length_m": f.measurement_value,
                    "properties": f.properties,
                }

        if f.bbox and len(f.bbox) == 4:
            min_x = min(min_x, f.bbox[0])
            min_y = min(min_y, f.bbox[1])
            max_x = max(max_x, f.bbox[2])
            max_y = max(max_y, f.bbox[3])

    bbox_result = (
        [round(min_x, 6), round(min_y, 6), round(max_x, 6), round(max_y, 6)]
        if min_x != float("inf")
        else None
    )

    return FileSummaryResponse(
        file_id=id,
        filename=file_record.filename,
        status=file_record.status,
        crs=file_record.crs,
        feature_count=file_record.feature_count,
        total_area_sq_m=round(total_area, 4),
        total_length_m=round(total_length, 4),
        geometry_counts=geometry_counts,
        bounding_box=bbox_result,
        largest_feature_by_area=largest_area_feature,
        longest_feature_by_length=longest_line_feature,
        warnings=file_record.warnings or [],
    )


@router.get(
    "/{id}/export/",
    summary="Export features with measurements to GeoJSON or CSV",
)
def export_file(
    id: str,
    format: str = Query("geojson", description="Export format: geojson or csv"),
    db: Session = Depends(get_db),
) -> Response:
    """Export features and calculated measurements in standard GeoJSON or tabular CSV."""
    file_record = FileRepository.get_by_id(db, id)
    if not file_record:
        raise FileNotFoundError(f"File with ID '{id}' was not found.")

    if file_record.status != "COMPLETED":
        raise FileNotReadyError(f"File '{id}' is not ready for export (status: {file_record.status}).")

    all_features = FeatureRepository.get_all_for_file(db, id)
    clean_stem = Path(file_record.filename).stem

    if format.lower() == "geojson":
        geojson_features = []
        for f in all_features:
            props = dict(f.properties or {})
            props.update(
                {
                    "feature_index": f.feature_index,
                    "layer_name": f.layer_name,
                    "measurement_type": f.measurement_type,
                    "measurement_value": f.measurement_value,
                    "measurement_unit": f.measurement_unit,
                    "method": f.method,
                    "projected_crs": f.projected_crs,
                    "geodesic_value": f.geodesic_value,
                    "difference_pct": f.difference_pct,
                    "warnings": f.warnings,
                }
            )
            geojson_features.append(
                {
                    "type": "Feature",
                    "geometry": f.geometry,
                    "properties": props,
                }
            )

        collection = {
            "type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": file_record.crs or "EPSG:4326"}},
            "features": geojson_features,
        }

        return Response(
            content=json.dumps(collection, indent=2),
            media_type="application/geo+json",
            headers={"Content-Disposition": f'attachment; filename="{clean_stem}_measurements.geojson"'},
        )

    elif format.lower() == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "feature_index",
                "layer_name",
                "geometry_type",
                "measurement_type",
                "measurement_value",
                "measurement_unit",
                "method",
                "projected_crs",
                "geodesic_value",
                "difference_pct",
                "properties_json",
            ]
        )

        for f in all_features:
            writer.writerow(
                [
                    f.feature_index,
                    f.layer_name or "",
                    f.geometry_type,
                    f.measurement_type or "",
                    f.measurement_value if f.measurement_value is not None else "",
                    f.measurement_unit or "",
                    f.method or "",
                    f.projected_crs or "",
                    f.geodesic_value if f.geodesic_value is not None else "",
                    f.difference_pct if f.difference_pct is not None else "",
                    json.dumps(f.properties or {}),
                ]
            )

        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{clean_stem}_measurements.csv"'},
        )
    else:
        raise InvalidFileError(f"Unsupported export format '{format}'. Supported formats: geojson, csv.")


@router.get(
    "/{id}/preview/",
    response_class=HTMLResponse,
    summary="Interactive Leaflet map preview",
)
def preview_map(
    id: str,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Serves an interactive Leaflet map rendering all features and measurements."""
    file_record = FileRepository.get_by_id(db, id)
    if not file_record:
        raise FileNotFoundError(f"File with ID '{id}' was not found.")

    if file_record.status != "COMPLETED":
        raise FileNotReadyError(f"File '{id}' is not completed yet (status: {file_record.status}).")

    all_features = FeatureRepository.get_all_for_file(db, id)

    features_json_list = []
    for f in all_features:
        if not f.geometry:
            continue
        props = dict(f.properties or {})
        props.update(
            {
                "feature_index": f.feature_index,
                "layer_name": f.layer_name,
                "geometry_type": f.geometry_type,
                "measurement_type": f.measurement_type,
                "measurement_value": f.measurement_value,
                "measurement_unit": f.measurement_unit,
                "method": f.method,
                "projected_crs": f.projected_crs,
                "geodesic_value": f.geodesic_value,
                "difference_pct": f.difference_pct,
                "warnings": f.warnings,
            }
        )
        features_json_list.append(
            {
                "type": "Feature",
                "geometry": f.geometry,
                "properties": props,
            }
        )

    geojson_data = {
        "type": "FeatureCollection",
        "features": features_json_list,
    }

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Map Preview - {file_record.filename}</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'Plus Jakarta Sans', sans-serif;
      background: #0f172a;
      color: #f8fafc;
      height: 100vh;
      display: flex;
      flex-direction: column;
    }}
    header {{
      background: #1e293b;
      padding: 14px 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1px solid #334155;
      box-shadow: 0 4px 12px rgba(0,0,0,0.3);
      z-index: 1000;
    }}
    .brand {{ display: flex; align-items: center; gap: 12px; }}
    .badge {{
      background: #3b82f6;
      color: #fff;
      font-size: 11px;
      font-weight: 700;
      padding: 3px 8px;
      border-radius: 6px;
      letter-spacing: 0.5px;
    }}
    h1 {{ font-size: 18px; font-weight: 600; color: #f1f5f9; }}
    .meta {{ font-size: 13px; color: #94a3b8; display: flex; gap: 16px; }}
    .meta span strong {{ color: #cbd5e1; }}
    #map {{ flex: 1; width: 100%; }}
    .leaflet-popup-content-wrapper {{
      background: #1e293b;
      color: #f8fafc;
      border-radius: 8px;
      border: 1px solid #475569;
      box-shadow: 0 10px 25px rgba(0,0,0,0.5);
    }}
    .leaflet-popup-tip {{ background: #1e293b; }}
    .popup-title {{
      font-size: 14px;
      font-weight: 700;
      color: #38bdf8;
      margin-bottom: 6px;
      border-bottom: 1px solid #334155;
      padding-bottom: 4px;
    }}
    .popup-row {{ font-size: 12px; margin: 4px 0; color: #cbd5e1; display: flex; justify-content: space-between; gap: 10px; }}
    .popup-val {{ font-weight: 600; color: #10b981; }}
    .warning-tag {{
      display: inline-block;
      background: rgba(245, 158, 11, 0.2);
      color: #fbbf24;
      padding: 2px 6px;
      border-radius: 4px;
      font-size: 10px;
      margin-top: 4px;
    }}
  </style>
</head>
<body>
  <header>
    <div class="brand">
      <span class="badge">AEREO GEO-MEASURE</span>
      <h1>{file_record.filename}</h1>
    </div>
    <div class="meta">
      <span>CRS: <strong>{file_record.crs}</strong></span>
      <span>Features: <strong>{file_record.feature_count}</strong></span>
      <span>Status: <strong style="color: #10b981;">{file_record.status}</strong></span>
    </div>
  </header>
  <div id="map"></div>

  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
    const geojsonData = {json.dumps(geojson_data)};
    const map = L.map('map').setView([0, 0], 2);

    L.tileLayer('https://{{s}}.basemaps.cartocdn.com/rastertiles/voyager/{{z}}/{{x}}/{{y}}{{r}}.png', {{
      maxZoom: 19,
      attribution: '&copy; CartoDB &copy; OpenStreetMap'
    }}).addTo(map);

    function onEachFeature(feature, layer) {{
      const p = feature.properties || {{}};
      let content = '<div class="popup-title">Feature #' + p.feature_index + ' (' + p.geometry_type + ')</div>';
      if (p.measurement_type) {{
        content += '<div class="popup-row"><span>Measurement:</span><span class="popup-val">' + p.measurement_value.toLocaleString() + ' ' + p.measurement_unit + '</span></div>';
        content += '<div class="popup-row"><span>Method:</span><span>' + (p.method || 'N/A') + '</span></div>';
        if (p.projected_crs) {{
          content += '<div class="popup-row"><span>Projected CRS:</span><span>' + p.projected_crs + '</span></div>';
        }}
        if (p.geodesic_value) {{
          content += '<div class="popup-row"><span>Geodesic Cross-Check:</span><span>' + p.geodesic_value.toLocaleString() + '</span></div>';
          content += '<div class="popup-row"><span>Difference:</span><span>' + (p.difference_pct || 0) + '%</span></div>';
        }}
      }}
      if (p.warnings && p.warnings.length > 0) {{
        p.warnings.forEach(w => {{
          content += '<div class="warning-tag">⚠️ ' + w + '</div>';
        }});
      }}
      layer.bindPopup(content);
    }}

    const geoLayer = L.geoJSON(geojsonData, {{
      style: function(feat) {{
        return {{
          color: '#38bdf8',
          weight: 3,
          opacity: 0.8,
          fillColor: '#0284c7',
          fillOpacity: 0.35
        }};
      }},
      pointToLayer: function(feat, latlng) {{
        return L.circleMarker(latlng, {{
          radius: 7,
          fillColor: '#38bdf8',
          color: '#ffffff',
          weight: 2,
          opacity: 1,
          fillOpacity: 0.9
        }});
      }},
      onEachFeature: onEachFeature
    }}).addTo(map);

    if (geojsonData.features.length > 0) {{
      map.fitBounds(geoLayer.getBounds(), {{ padding: [30, 30] }});
    }}
  </script>
</body>
</html>"""
    return HTMLResponse(content=html_content)

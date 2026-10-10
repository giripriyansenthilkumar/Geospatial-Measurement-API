# Geospatial File Measurement API

> High-precision geospatial measurement service for ESRI Shapefiles (`.zip`) and OGC KML datasets (`.kml`). Enforces strict reprojection to metric Coordinate Reference Systems (UTM), ellipsoidal geodesic cross-checks, geometry validation and auto-repair, and rich interactive map previews.

[![CI](https://github.com/aereo/geo-measure-api/actions/workflows/ci.yml/badge.svg)](https://github.com/aereo/geo-measure-api/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12-blue)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## 1. Quickstart

### Option A: Local Installation (Recommended for Development)

Prerequisites: Python 3.11+ installed.

```bash
# 1. Clone repository and navigate to root
git clone <repo-url>
cd Aereo

# 2. Set up virtual environment and install dependencies
make install
# or manually:
# python3 -m venv .venv
# source .venv/bin/activate
# pip install -e ".[dev]"

# 3. Start the FastAPI development server
make run
```

The service is now running at `http://localhost:8000`.
- **Interactive Swagger Documentation**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Health Check Probe**: [http://localhost:8000/health](http://localhost:8000/health)

### Option B: Docker & Docker Compose

```bash
# Build and run containerized application
make docker-up
# or manually:
# docker compose up --build -d

# Inspect health status
curl http://localhost:8000/health
```

---

## 2. API Endpoints & Real `curl` Examples

Sample datasets are included in `sample_data/` (`sample_data/survey.kml` and `sample_data/cadastre.zip`).

### 1. Upload Geospatial File (`POST /api/files/`)
Upload a Shapefile `.zip` archive or `.kml` file:

```bash
curl -X POST "http://localhost:8000/api/files/" \
  -H "accept: application/json" \
  -F "file=@sample_data/survey.kml"
```

**Response (`201 Created`):**
```json
{
  "id": "e0e29b1e-7b71-4171-87a2-f8303f26de6d",
  "filename": "survey.kml",
  "feature_count": 3,
  "crs": "EPSG:4326",
  "status": "COMPLETED",
  "warnings": []
}
```

---

### 2. Get File Information (`GET /api/files/{id}/`)
Retrieve processing state, metadata, and detected CRS:

```bash
curl -X GET "http://localhost:8000/api/files/e0e29b1e-7b71-4171-87a2-f8303f26de6d/"
```

**Response (`200 OK`):**
```json
{
  "id": "e0e29b1e-7b71-4171-87a2-f8303f26de6d",
  "filename": "survey.kml",
  "file_type": "kml",
  "feature_count": 3,
  "crs": "EPSG:4326",
  "crs_assumed": false,
  "status": "COMPLETED",
  "created_at": "2026-10-10T14:32:00Z",
  "warnings": []
}
```

---

### 3. Get Feature Measurements (`GET /api/files/{id}/measurements/`)
Query paginated measurements with optional geometry type filtering and unit conversion:

```bash
# Query in default SI units (m² and m)
curl -X GET "http://localhost:8000/api/files/e0e29b1e-7b71-4171-87a2-f8303f26de6d/measurements/?page=1&page_size=10"

# Query with unit conversion (e.g., hectare for areas, km for lines)
curl -X GET "http://localhost:8000/api/files/e0e29b1e-7b71-4171-87a2-f8303f26de6d/measurements/?unit=hectare"
```

**Response (`200 OK`):**
```json
{
  "file_id": "e0e29b1e-7b71-4171-87a2-f8303f26de6d",
  "total": 3,
  "page": 1,
  "page_size": 10,
  "results": [
    {
      "feature_index": 0,
      "geometry_type": "Polygon",
      "crs": "EPSG:4326",
      "properties": {
        "Name": "Runway Enclosure (Polygon)"
      },
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[77.59, 12.97], [77.595, 12.97], [77.595, 12.975], [77.59, 12.975], [77.59, 12.97]]]
      },
      "measurement": {
        "type": "area",
        "value": 30.6472,
        "unit": "hectare",
        "method": "utm_projection",
        "projected_crs": "EPSG:32643",
        "geodesic_value": 30.6717,
        "difference_pct": 0.0799
      },
      "warnings": []
    },
    {
      "feature_index": 1,
      "geometry_type": "LineString",
      "measurement": {
        "type": "length",
        "value": 1912.43,
        "unit": "m",
        "method": "utm_projection",
        "projected_crs": "EPSG:32643",
        "geodesic_value": 1912.82,
        "difference_pct": 0.0204
      },
      "warnings": []
    },
    {
      "feature_index": 2,
      "geometry_type": "Point",
      "measurement": null,
      "note": "No measurement required for Point",
      "warnings": []
    }
  ]
}
```

---

### 4. Summary Statistics (`GET /api/files/{id}/summary/`)
Aggregated spatial metrics, total area/length, geometry counts, and bounding box:

```bash
curl -X GET "http://localhost:8000/api/files/e0e29b1e-7b71-4171-87a2-f8303f26de6d/summary/"
```

**Response (`200 OK`):**
```json
{
  "file_id": "e0e29b1e-7b71-4171-87a2-f8303f26de6d",
  "filename": "survey.kml",
  "status": "COMPLETED",
  "crs": "EPSG:4326",
  "feature_count": 3,
  "total_area_sq_m": 306472.0,
  "total_length_m": 1912.43,
  "geometry_counts": {
    "Polygon": 1,
    "LineString": 1,
    "Point": 1
  },
  "bounding_box": [77.58, 12.96, 77.595, 12.975],
  "largest_feature_by_area": {
    "feature_index": 0,
    "layer_name": null,
    "area_sq_m": 306472.0,
    "properties": {"Name": "Runway Enclosure (Polygon)"}
  },
  "longest_feature_by_length": {
    "feature_index": 1,
    "layer_name": null,
    "length_m": 1912.43,
    "properties": {"Name": "Approach Flight Path (LineString)"}
  },
  "warnings": []
}
```

---

### 5. Export GeoJSON or CSV (`GET /api/files/{id}/export/`)
Export features with computed measurements embedded:

```bash
# Export as GeoJSON FeatureCollection
curl -X GET "http://localhost:8000/api/files/e0e29b1e-7b71-4171-87a2-f8303f26de6d/export/?format=geojson" -o survey_results.geojson

# Export as CSV table
curl -X GET "http://localhost:8000/api/files/e0e29b1e-7b71-4171-87a2-f8303f26de6d/export/?format=csv" -o survey_results.csv
```

---

### 6. Interactive Leaflet Map Preview (`GET /api/files/{id}/preview/`)
Open the interactive map preview in your web browser:
`http://localhost:8000/api/files/e0e29b1e-7b71-4171-87a2-f8303f26de6d/preview/`

- Styled dark slate interface with CartoDB Voyager tiles.
- Vector geometries rendered with dynamic popups.
- Shows real-time measurement numbers, methods, projected CRS, and cross-check discrepancies.

---

## 3. Uniform Error Model

All error responses strictly adhere to the unified format:
```json
{
  "error": {
    "code": "INVALID_FILE",
    "message": "Corrupted or invalid KML file: syntax error"
  }
}
```

| HTTP Status | Error Code | Scenario |
|---|---|---|
| `400` | `INVALID_FILE` | Corrupt header, malformed XML, unreadable archive |
| `404` | `FILE_NOT_FOUND` | File ID not found in database |
| `409` | `NOT_READY` | Measurements requested before processing completes |
| `413` | `FILE_TOO_LARGE` | Upload size or uncompressed zip size exceeds limit |
| `415` | `UNSUPPORTED_TYPE` | Extension is not `.zip` or `.kml` |
| `422` | `INCOMPLETE_SHAPEFILE` | Archive is missing `.shp`, `.shx`, `.dbf`, or dataset contains 0 features |
| `500` | `INTERNAL_ERROR` | Unhandled error (logged with request correlation ID) |

---

## 4. Architectural Decisions

| Decision | Chosen Solution | Considered Alternative | Rationale |
|---|---|---|---|
| **Measurement CRS** | Local UTM zone chosen per-feature from representative point | Single global CRS (e.g. EPSG:3857) | EPSG:3857 introduces extreme area distortion away from equator. Local UTM zones preserve conformal metric properties. |
| **Accuracy Verification** | WGS84 Geodesic cross-check via `pyproj.Geod` | Trusting projection blindly | Flags projection scale distortion when features cross UTM boundaries. Automatic fallback if discrepancy exceeds threshold. |
| **I/O Engine** | GeoPandas + `pyogrio` (GDAL) | Fiona / pure-python parsers | Fast C-accelerated vector reading for both Shapefile and multi-layer KML datasets. |
| **Geometry Representation** | Shapely 2.0 | GEOS C-API bindings | Shapely 2.0 uses vectorized C geometry arrays and built-in `shapely.make_valid` and `shapely.force_2d`. |
| **Persistence** | SQLAlchemy 2.0 with SQLite default | PostGIS mandatory from day 1 | Zero-setup review experience; zero native DB prerequisites; PostgreSQL supported seamlessly via `DATABASE_URL`. |
| **Single Feature Failure** | Warn and preserve row | Fail entire upload | Real-world surveys frequently contain 1 broken parcel among thousands of valid features. |

---

## 5. Engineering Learnings & Gotchas

1. **The Degrees Squared Trap**:
   A polygon defined in `EPSG:4326` with $0.01^\circ \times 0.01^\circ$ dimensions has a raw planar area of $0.0001\text{ deg}^2$. Calculating area directly on raw degrees produces nonsense numbers. Proper reprojection to local UTM or ellipsoidal geodesic integration produces $\approx 1,220,000\text{ m}^2$.
2. **Axis Ordering (`always_xy=True`)**:
   Standard EPSG definitions for geographic CRS designate (Latitude, Longitude) as $(y, x)$. Passing `always_xy=True` to `pyproj.Transformer` guarantees $(x, y) = (\text{lon}, \text{lat})$ ordering, eliminating swapped-coordinate bugs.
3. **KML Specification**:
   OGC KML strictly mandates `EPSG:4326` coordinates regardless of whether a CRS definition is present in the file.
4. **Archive Security**:
   Zip archives represent a significant attack surface. Ingestion safely verifies magic bytes, enforces uncompressed size and entry caps against zip bombs, and inspects relative path traversal (`..`) against zip-slip vulnerabilities.

---

## 6. Testing

Run the full automated test suite:

```bash
make test
# or:
# .venv/bin/pytest -v
```

Run linting and formatting checks:

```bash
make lint
```

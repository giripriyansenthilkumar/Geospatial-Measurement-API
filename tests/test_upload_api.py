"""End-to-end API tests for upload, measurements, summary, export, and preview."""

import io

from starlette.testclient import TestClient

from tests.conftest import create_shapefile_zip


def test_upload_kml_happy_path(client: TestClient, valid_kml_bytes: bytes):
    files = {"file": ("survey.kml", io.BytesIO(valid_kml_bytes), "application/vnd.google-earth.kml+xml")}
    response = client.post("/api/files/", files=files)

    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    assert data["filename"] == "survey.kml"
    assert data["status"] == "COMPLETED"
    assert data["feature_count"] == 3
    assert data["crs"] == "EPSG:4326"

    file_id = data["id"]

    # Test GET /api/files/{id}/
    info_resp = client.get(f"/api/files/{file_id}/")
    assert info_resp.status_code == 200
    info_data = info_resp.json()
    assert info_data["id"] == file_id
    assert info_data["file_type"] == "kml"
    assert info_data["feature_count"] == 3

    # Test GET /api/files/{id}/measurements/
    meas_resp = client.get(f"/api/files/{file_id}/measurements/")
    assert meas_resp.status_code == 200
    meas_data = meas_resp.json()
    assert meas_data["total"] == 3
    assert len(meas_data["results"]) == 3

    # Check polygon measurement
    poly_feature = next(f for f in meas_data["results"] if f["geometry_type"] == "Polygon")
    assert poly_feature["measurement"]["type"] == "area"
    assert poly_feature["measurement"]["value"] > 0
    assert poly_feature["measurement"]["unit"] == "sq_m"

    # Check point feature
    point_feature = next(f for f in meas_data["results"] if f["geometry_type"] == "Point")
    assert point_feature["measurement"] is None
    assert "No measurement required" in point_feature["note"]


def test_upload_shapefile_happy_path(client: TestClient):
    shp_bytes = create_shapefile_zip()
    files = {"file": ("parcels.zip", io.BytesIO(shp_bytes), "application/zip")}
    response = client.post("/api/files/", files=files)

    assert response.status_code == 201
    data = response.json()
    assert data["filename"] == "parcels.zip"
    assert data["status"] == "COMPLETED"
    assert data["feature_count"] == 3

    file_id = data["id"]

    # Test geometry filtering
    filter_resp = client.get(f"/api/files/{file_id}/measurements/?geometry_type=Polygon")
    assert filter_resp.status_code == 200
    filter_data = filter_resp.json()
    assert filter_data["total"] == 3
    assert all(r["geometry_type"] == "Polygon" for r in filter_data["results"])


def test_measurement_unit_conversion(client: TestClient, valid_kml_bytes: bytes):
    files = {"file": ("survey_units.kml", io.BytesIO(valid_kml_bytes), "application/vnd.google-earth.kml+xml")}
    res = client.post("/api/files/", files=files)
    file_id = res.json()["id"]

    # Convert area to hectare
    meas_resp = client.get(f"/api/files/{file_id}/measurements/?unit=hectare")
    assert meas_resp.status_code == 200
    meas_data = meas_resp.json()

    poly = next(f for f in meas_data["results"] if f["geometry_type"] == "Polygon")
    assert poly["measurement"]["unit"] == "hectare"


def test_file_summary_endpoint(client: TestClient, valid_kml_bytes: bytes):
    files = {"file": ("summary_test.kml", io.BytesIO(valid_kml_bytes), "application/vnd.google-earth.kml+xml")}
    res = client.post("/api/files/", files=files)
    file_id = res.json()["id"]

    summary_resp = client.get(f"/api/files/{file_id}/summary/")
    assert summary_resp.status_code == 200
    summary_data = summary_resp.json()

    assert summary_data["file_id"] == file_id
    assert summary_data["total_area_sq_m"] > 0
    assert summary_data["total_length_m"] > 0
    assert "Polygon" in summary_data["geometry_counts"]
    assert "LineString" in summary_data["geometry_counts"]
    assert "Point" in summary_data["geometry_counts"]
    assert summary_data["bounding_box"] is not None
    assert summary_data["largest_feature_by_area"] is not None


def test_export_geojson_and_csv(client: TestClient, valid_kml_bytes: bytes):
    files = {"file": ("export_test.kml", io.BytesIO(valid_kml_bytes), "application/vnd.google-earth.kml+xml")}
    res = client.post("/api/files/", files=files)
    file_id = res.json()["id"]

    # Export GeoJSON
    geojson_resp = client.get(f"/api/files/{file_id}/export/?format=geojson")
    assert geojson_resp.status_code == 200
    assert "geo+json" in geojson_resp.headers["content-type"]
    geojson_data = geojson_resp.json()
    assert geojson_data["type"] == "FeatureCollection"
    assert len(geojson_data["features"]) == 3

    # Export CSV
    csv_resp = client.get(f"/api/files/{file_id}/export/?format=csv")
    assert csv_resp.status_code == 200
    assert "text/csv" in csv_resp.headers["content-type"]
    csv_text = csv_resp.text
    assert "feature_index,layer_name,geometry_type" in csv_text


def test_map_preview_endpoint(client: TestClient, valid_kml_bytes: bytes):
    files = {"file": ("preview_test.kml", io.BytesIO(valid_kml_bytes), "application/vnd.google-earth.kml+xml")}
    res = client.post("/api/files/", files=files)
    file_id = res.json()["id"]

    preview_resp = client.get(f"/api/files/{file_id}/preview/")
    assert preview_resp.status_code == 200
    assert "text/html" in preview_resp.headers["content-type"]
    assert "<title>Map Preview" in preview_resp.text
    assert "leaflet" in preview_resp.text


def test_deduplication(client: TestClient, valid_kml_bytes: bytes):
    files1 = {"file": ("file1.kml", io.BytesIO(valid_kml_bytes), "application/vnd.google-earth.kml+xml")}
    res1 = client.post("/api/files/", files=files1)
    assert res1.status_code == 201
    id1 = res1.json()["id"]

    # Upload exact same bytes
    files2 = {"file": ("file2.kml", io.BytesIO(valid_kml_bytes), "application/vnd.google-earth.kml+xml")}
    res2 = client.post("/api/files/", files=files2)
    assert res2.status_code == 201
    assert res2.json()["id"] == id1
    assert any("deduplicated" in w.lower() for w in res2.json()["warnings"])


def test_error_file_not_found(client: TestClient):
    resp = client.get("/api/files/nonexistent-uuid-12345/")
    assert resp.status_code == 404
    err = resp.json()["error"]
    assert err["code"] == "FILE_NOT_FOUND"


def test_error_unsupported_extension(client: TestClient):
    files = {"file": ("data.geojson", io.BytesIO(b'{"type": "Point"}'), "application/json")}
    resp = client.post("/api/files/", files=files)
    assert resp.status_code == 415
    err = resp.json()["error"]
    assert err["code"] == "UNSUPPORTED_TYPE"


def test_error_corrupt_zip(client: TestClient):
    files = {"file": ("corrupt.zip", io.BytesIO(b"NOT_A_ZIP_HEADER"), "application/zip")}
    resp = client.post("/api/files/", files=files)
    assert resp.status_code == 400
    err = resp.json()["error"]
    assert err["code"] == "INVALID_FILE"


def test_error_incomplete_shapefile(client: TestClient):
    shp_missing_shx = create_shapefile_zip(missing_companion=".shx")
    files = {"file": ("broken.zip", io.BytesIO(shp_missing_shx), "application/zip")}
    resp = client.post("/api/files/", files=files)
    assert resp.status_code == 422
    err = resp.json()["error"]
    assert err["code"] == "INCOMPLETE_SHAPEFILE"

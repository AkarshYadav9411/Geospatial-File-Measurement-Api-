# Sample Geospatial Datasets

This directory contains pre-generated sample geospatial datasets for testing, demonstrations, and manual verification of the **GeoMeasure API**.

## Available Sample Datasets

| File | Format | Geometry Type | CRS | Notes / Test Purpose |
|------|--------|---------------|-----|----------------------|
| `sample_parcels.zip` | Shapefile ZIP | `Polygon` | EPSG:4326 | 3 land parcels in Manhattan; tests UTM Zone 18N projection and polygon area calculation in m² & km². |
| `sample_trails.zip` | Shapefile ZIP | `LineString` | EPSG:4326 | 2 recreational trails (Hudson Greenway, High Line); tests UTM Zone 18N line length calculation. |
| `sample_landmarks.kml` | KML | Mixed (`Polygon`, `LineString`, `Point`) | EPSG:4326 (WGS84) | Tests KML reader, mixed geometry handling, and point features (measurement marked `not_required`). |
| `sample_continental.zip` | Shapefile ZIP | `Polygon` | EPSG:4326 | Large-extent polygon spanning 10° of longitude (>6° UTM limit); verifies automatic fallback to geodesic ellipsoidal measurement. |
| `sample_no_crs.zip` | Shapefile ZIP | `Polygon` | None (missing `.prj`) | Tests missing CRS policy: features are parsed, but measurements are marked `no_crs` with warning. |

## Regenerating Sample Data

To regenerate all sample files programmatically:

```bash
python sample_data/create_sample_files.py
```

## Quick Verification with cURL

Upload sample parcels:
```bash
curl -X POST "http://localhost:8000/api/files/" \
  -H "accept: application/json" \
  -F "file=@sample_data/sample_parcels.zip"
```

Upload sample KML:
```bash
curl -X POST "http://localhost:8000/api/files/" \
  -H "accept: application/json" \
  -F "file=@sample_data/sample_landmarks.kml"
```

"""
Sample data generator for GeoMeasure API.

Generates sample geospatial files for manual testing and demonstration:
1. sample_parcels.zip — ESRI Shapefile with Polygon features (parcels in NYC)
2. sample_trails.zip — ESRI Shapefile with LineString features (hiking trails)
3. sample_landmarks.kml — KML file with Polygon, LineString, and Point placemarks
4. sample_continental.zip — Large-extent Shapefile spanning >6° longitude (triggers geodesic)
5. sample_no_crs.zip — Shapefile without .prj (tests missing CRS policy)
"""

import os
import io
import shutil
import zipfile
import tempfile
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Polygon, LineString, Point


def generate_all_samples(output_dir: Path | None = None):
    if output_dir is None:
        output_dir = Path(__file__).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Generating sample datasets in: {output_dir}")

    # 1. sample_parcels.zip (Polygons in NYC, EPSG:4326)
    parcels_gdf = gpd.GeoDataFrame(
        [
            {"parcel_id": "P-101", "name": "Central Park South Section", "zoning": "Park"},
            {"parcel_id": "P-102", "name": "Midtown Commercial Block", "zoning": "Commercial"},
            {"parcel_id": "P-103", "name": "Residential Quad A", "zoning": "Residential"},
        ],
        geometry=[
            Polygon([(-73.974, 40.764), (-73.965, 40.764), (-73.965, 40.771), (-73.974, 40.771), (-73.974, 40.764)]),
            Polygon([(-73.988, 40.751), (-73.982, 40.751), (-73.982, 40.756), (-73.988, 40.756), (-73.988, 40.751)]),
            Polygon([(-73.995, 40.730), (-73.990, 40.730), (-73.990, 40.735), (-73.995, 40.735), (-73.995, 40.730)]),
        ],
        crs="EPSG:4326",
    )
    _save_as_shp_zip(parcels_gdf, output_dir / "sample_parcels.zip")
    print("  Created sample_parcels.zip")

    # 2. sample_trails.zip (LineStrings, EPSG:4326)
    trails_gdf = gpd.GeoDataFrame(
        [
            {"trail_id": "T-1", "name": "Hudson River Greenway", "difficulty": "Easy"},
            {"trail_id": "T-2", "name": "High Line Walkway", "difficulty": "Easy"},
        ],
        geometry=[
            LineString([(-74.015, 40.705), (-74.012, 40.720), (-74.009, 40.740), (-74.005, 40.760)]),
            LineString([(-74.008, 40.738), (-74.005, 40.745), (-74.002, 40.752)]),
        ],
        crs="EPSG:4326",
    )
    _save_as_shp_zip(trails_gdf, output_dir / "sample_trails.zip")
    print("  Created sample_trails.zip")

    # 3. sample_landmarks.kml (Mixed Placemarks)
    kml_content = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>New York Highlights</name>
    <description>Demonstration KML with polygons, lines, and points</description>
    <Placemark>
      <name>Bryant Park</name>
      <description>Public park in Manhattan</description>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>
              -73.9845,40.7535,0 -73.9825,40.7535,0 -73.9825,40.7548,0 -73.9845,40.7548,0 -73.9845,40.7535,0
            </coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
    <Placemark>
      <name>Broadway Segment</name>
      <description>Historic boulevard route</description>
      <LineString>
        <coordinates>
          -73.9875,40.7510,0 -73.9860,40.7550,0 -73.9840,40.7590,0
        </coordinates>
      </LineString>
    </Placemark>
    <Placemark>
      <name>Empire State Building</name>
      <description>Iconic skyscraper observation point</description>
      <Point>
        <coordinates>-73.9857,40.7484,0</coordinates>
      </Point>
    </Placemark>
  </Document>
</kml>"""
    (output_dir / "sample_landmarks.kml").write_text(kml_content, encoding="utf-8")
    print("  Created sample_landmarks.kml")

    # 4. sample_continental.zip (Spans across >6 degrees longitude)
    cont_gdf = gpd.GeoDataFrame(
        [
            {"name": "Cross-State Corridor", "type": "Corridor"},
        ],
        geometry=[
            Polygon([(-80.0, 35.0), (-70.0, 35.0), (-70.0, 40.0), (-80.0, 40.0), (-80.0, 35.0)]),
        ],
        crs="EPSG:4326",
    )
    _save_as_shp_zip(cont_gdf, output_dir / "sample_continental.zip")
    print("  Created sample_continental.zip")

    # 5. sample_no_crs.zip (No .prj file)
    no_crs_gdf = gpd.GeoDataFrame(
        [
            {"name": "Local Survey Grid", "unit": "Local"},
        ],
        geometry=[
            Polygon([(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)]),
        ],
    )
    _save_as_shp_zip(no_crs_gdf, output_dir / "sample_no_crs.zip", include_prj=False)
    print("  Created sample_no_crs.zip")

    print("All sample datasets successfully generated!")


def _save_as_shp_zip(gdf: gpd.GeoDataFrame, target_zip: Path, include_prj: bool = True):
    tmp_dir = Path(tempfile.mkdtemp(prefix="shp_sample_"))
    try:
        shp_name = target_zip.stem
        shp_file = tmp_dir / f"{shp_name}.shp"
        gdf.to_file(shp_file, driver="ESRI Shapefile")

        if not include_prj:
            prj_file = shp_file.with_suffix(".prj")
            if prj_file.exists():
                prj_file.unlink()

        with zipfile.ZipFile(target_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in tmp_dir.iterdir():
                if file_path.is_file():
                    zf.write(file_path, file_path.name)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    generate_all_samples()

# ========================= IMPORTS =========================
import json
import math
from datetime import datetime

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

from shapely.geometry import MultiPoint, MultiPolygon, Point
from shapely.geometry import Polygon as ShapelyPolygon
from shapely.geometry import mapping   # ✅ ONLY ADDITION
from shapely.ops import transform, unary_union
from shapely.validation import make_valid

from pyproj import CRS, Transformer
import alphashape
import hdbscan

from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.responses import HTMLResponse

app = FastAPI()

# ========================= FRONTEND =========================
@app.get("/")
def map_page():
    return HTMLResponse("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Geofence Viewer</title>
        <link rel="stylesheet" href="https://unpkg.com/leaflet/dist/leaflet.css"/>
        <script src="https://unpkg.com/leaflet/dist/leaflet.js"></script>
    </head>
    <body>
        <div style="padding:10px">
            <input id="vehicleInput" placeholder="Vehicle ID"/>
            <button onclick="loadGeofence()">Load</button>
        </div>
        <div id="map" style="height:90vh;"></div>

        <script>
        const map = L.map('map').setView([15.14, 76.62], 13);

        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);

        let layers = [];

        function clearLayers(){
            layers.forEach(l => map.removeLayer(l));
            layers = [];
        }

        async function loadGeofence(){
            const vehicleId = document.getElementById("vehicleInput").value;

            const res = await fetch('/geofence', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ vehicleId })
            });

            const data = await res.json();
            console.log(data);

            clearLayers();

            if(data.error){
                alert(data.error);
                return;
            }

            // 🔴 Polygon (MAIN)
            if(data.polygon_geojson){
                const poly = L.geoJSON(data.polygon_geojson,{
                    style:{color:'red', weight:3, fillOpacity:0.2}
                }).addTo(map);

                layers.push(poly);
                map.fitBounds(poly.getBounds());
            }

            // 🔵 Raw points (optional debug)
            if(data.raw_points){
                data.raw_points.forEach(pt=>{
                    layers.push(
                        L.circleMarker([pt[1], pt[0]], {radius:2,color:'blue'}).addTo(map)
                    );
                });
            }
        }
        </script>
    </body>
    </html>
    """)

# ========================= CONFIG =========================
DB_URI = "mysql+pymysql://readonly_user:StrongPassword123%21@yl-prod-fleet.cuj2psst95uv.ap-south-1.rds.amazonaws.com:3306/yantralive_fleet"
INPUT_TABLE = "track_aggregate_data"

BUFFER_M = 15.0
SIMPLIFY_TOL_M = 5.0
COVERAGE_MIN_RATIO = 0.92

engine = create_engine(DB_URI, pool_pre_ping=True)

# ========================= CRS =========================
def utm_crs_for(lat, lon):
    zone = int(math.floor((lon + 180) / 6) + 1)
    hemi = "north" if lat >= 0 else "south"
    return CRS.from_dict({"proj": "utm", "zone": zone, "south": hemi == "south", "datum": "WGS84"})

def project_points(lats, lons, to_crs):
    transformer = Transformer.from_crs(CRS.from_epsg(4326), to_crs, always_xy=True)
    xs, ys = transformer.transform(lons, lats)
    return np.column_stack([xs, ys])

def reproject_geom(geom, transformer):
    return transform(lambda x, y, z=None: transformer.transform(x, y), geom)

# ========================= HELPERS =========================
def polygon_ensure_valid(poly):
    if poly is None or poly.is_empty:
        return poly

    fixed = make_valid(poly.buffer(0))

    if isinstance(fixed, ShapelyPolygon):
        return fixed
    if isinstance(fixed, MultiPolygon):
        return MultiPolygon([g for g in fixed.geoms])

    return fixed

def auto_alpha_percentile(cluster_pts):
    spread = np.std(cluster_pts, axis=0).mean()
    if spread < 15: return 0.70
    if spread < 40: return 0.80
    return 0.90

def concave_hull_auto(cluster_pts):
    if len(cluster_pts) < 3:
        return None

    alpha_percentile = auto_alpha_percentile(cluster_pts)

    nn = np.linalg.norm(cluster_pts[:, None, :] - cluster_pts[None, :, :], axis=2)
    nn_sorted = np.sort(nn, axis=1)[:, 1:]
    L = np.quantile(nn_sorted[:, 0], alpha_percentile)

    if L <= 0:
        return None

    alpha = 1.0 / L

    try:
        return alphashape.alphashape(cluster_pts, alpha)
    except:
        return None

def coverage_ratio(poly, pts_xy):
    if poly is None or poly.is_empty:
        return 0.0
    inside = sum(1 for x, y in pts_xy if poly.contains(Point(x, y)))
    return inside / len(pts_xy)

# ========================= MAIN LOGIC (UNCHANGED) =========================
def build_geofence(df_vehicle):
    lats = df_vehicle["Latitude"].to_numpy()
    lons = df_vehicle["Longtitude"].to_numpy()

    crs_utm = utm_crs_for(lats[0], lons[0])
    pts_xy = project_points(lats, lons, crs_utm)

    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=max(10, int(len(pts_xy) * 0.01)),
        min_samples=5
    )

    labels = clusterer.fit_predict(pts_xy)

    cluster_ids = [c for c in set(labels) if c != -1]

    inv_transformer = Transformer.from_crs(crs_utm, CRS.from_epsg(4326), always_xy=True)

    hulls = []
    total_points = 0

    for cid in cluster_ids:
        cluster_pts = pts_xy[labels == cid]

        if len(cluster_pts) < 3:
            continue

        hull = concave_hull_auto(cluster_pts) or MultiPoint(cluster_pts).convex_hull

        if coverage_ratio(hull, cluster_pts) < COVERAGE_MIN_RATIO:
            hull = MultiPoint(cluster_pts).convex_hull

        hull = polygon_ensure_valid(
            hull.buffer(BUFFER_M).simplify(SIMPLIFY_TOL_M, preserve_topology=True)
        )

        if hull and not hull.is_empty:
            hulls.append(hull)
            total_points += len(cluster_pts)

    if not hulls:
        return {"error": "No geofence"}

    merged_hull = polygon_ensure_valid(unary_union(hulls))

    if isinstance(merged_hull, MultiPolygon):
        merged_hull = merged_hull.convex_hull

    hull_4326 = reproject_geom(merged_hull, inv_transformer)

    # ✅ ONLY CHANGE HERE
    raw_points = [
        list(inv_transformer.transform(x, y))
        for x, y in pts_xy
    ]

    return {
        "polygon_geojson": mapping(hull_4326),
        "raw_points": raw_points
    }

# ========================= FETCH =========================
def fetch_points(vehicle_id):
    query = f"""
        SELECT vehicleId, Latitude, Longtitude, EventUnixTimestamp
        FROM {INPUT_TABLE}
        WHERE Latitude IS NOT NULL
          AND Longtitude IS NOT NULL
          AND vehicleId = :vehicleId
          AND Ignition_Indicator = 1
          AND EventUnixTimestamp >= DATE_SUB(NOW(), INTERVAL 30 DAY)
        ORDER BY EventUnixTimestamp
    """

    df = pd.read_sql(text(query), engine, params={"vehicleId": str(vehicle_id)})
    return df.dropna(subset=["vehicleId", "Latitude", "Longtitude"])

# ========================= API =========================
class RequestModel(BaseModel):
    vehicleId: str

@app.post("/geofence")
def generate_geofence(req: RequestModel):
    df = fetch_points(req.vehicleId)

    if df.empty:
        return {"error": "No data"}

    if len(df) > 150000:
        return {"error": "Too much data"}

    return build_geofence(df)
# geofence-clustering-engine
🚀 Geofence Clustering Engine

A geospatial backend that automatically generates geofences from raw vehicle GPS data using clustering and computational geometry.

🔍 Overview

This project builds geofences by analyzing GPS trajectory data and converting it into optimized polygon boundaries.

It combines:

Density-based clustering using HDBSCAN
Concave hull generation via Alpha Shapes
Geometric processing using Shapely
Coordinate transformations with PyProj

The system exposes a FastAPI service and provides a built-in Leaflet map UI for visualization.

🧠 Key Features
📍 Automatic geofence generation from GPS data
🧩 Unsupervised clustering of movement patterns
🔺 Adaptive polygon generation (concave + convex fallback)
🛠 Geometry validation, buffering, and simplification
🌍 CRS transformation (WGS84 ↔ UTM)
⚡ FastAPI backend with REST endpoint
🗺 Interactive map visualization (Leaflet.js)
🏗 How It Works
GPS Data (MySQL)
        ↓
Fetch & Clean Data
        ↓
Coordinate Projection (WGS84 → UTM)
        ↓
Clustering (HDBSCAN)
        ↓
Hull Generation (Alpha Shape)
        ↓
Fallback (Convex Hull if needed)
        ↓
Polygon Optimization (Buffer + Simplify)
        ↓
Merge Clusters
        ↓
Convert to GeoJSON
        ↓
Visualize on Map (Leaflet)
⚙️ Tech Stack
Backend: FastAPI (Python)
Database: MySQL (via SQLAlchemy)
Geospatial: Shapely, PyProj, AlphaShape
Clustering: HDBSCAN, NumPy
Data Processing: Pandas
Frontend: Leaflet.js

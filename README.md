# Gativa — Smart Traffic Analysis, Infrastructure Optimization & SUMO Simulation

> **Gativa** is a full-stack, AI/ML-powered geospatial and microscopic simulation platform designed for municipal civil engineers, urban transport planners, and GIS analysts to analyze traffic conditions, diagnose road network bottlenecks, evaluate evidence-backed infrastructure interventions, and simulate traffic-control strategies using Eclipse SUMO and TraCI.

Built in strict accordance with the approved **Stitch UI Design System** (Gativa Urban Infrastructure theme featuring saffron, white, India green, and brand navy) and technical PRD requirements.

---

## 🚦 End-to-End Workflow

1. **Map Selection (`/`)**: Opens directly on an interactive vector map powered by **OpenStreetMap** (CartoDB Voyager vector streets and Esri World Imagery satellite basemaps via Leaflet). No proprietary Google Maps API key or billing required. The user sketches an urban corridor or selects a 1-click preset.
2. **Analysis Trigger**: The user verifies the calculated geodesic area (in km²) and clicks **Analyze Area**.
3. **Data Ingestion & Processing**:
   - Road network topology retrieved from OpenStreetMap via OSMnx.
   - Live traffic telemetry (speeds, free-flow comparisons, incidents) fetched from TomTom.
   - Microclimate weather context retrieved from OpenWeather.
   - Network centrality and graph bottlenecks computed via NetworkX.
4. **Analysis Dashboard (`/analysis/:analysisId`)**: Strictly four core sections in order:
   - **1. Analysis Overview**: 6 metric cards, GIS topology map with road names and problem markers, road class distribution chart, and structural bottleneck priorities.
   - **2. Traffic Flow & LOS**: Level of Service (HCM 6th Ed) flow map (Green/Amber/Crimson), telemetry stream, detector speed matrix, and incident feed.
   - **3. Recommendations**: Filterable matrix of prioritized engineering interventions (Signal Optimization, Geometry Improvement, Road Widening), accompanied by impact scores, geometric schematics, supporting evidence, and engineering review notices.
   - **4. SUMO Simulation**: Native Eclipse SUMO microscopic traffic simulation driven via TraCI. Features live vehicle movement canvas, playback controls (Play/Pause/Reset/1x-5x Speed), 4 core metrics (Average Speed, Waiting Time, Queue Length, Completed Vehicles), and side-by-side scenario comparison (Baseline Fixed-Time vs. Actuated Adaptive Signal Control).
5. **Persistence & Export**: Analyses persist in MongoDB (with automatic in-memory fallback), allowing users to reload results by ID or download GIS GeoJSON FeatureCollections.

---

## 🔑 Required API Configuration Guide

Gativa requires configuration of two external API services for live telemetry. **Secrets are never committed to GitHub or exposed in frontend bundles.**

### 1. OpenStreetMap & Tile Services (No Key Required)

- **Used For**: Interactive map rendering, polygon drawing, pan/zoom, coordinate visualization, and road network graph extraction.
- **Providers**: CartoDB Voyager, Esri World Imagery, and OpenStreetMap contributors (all with compliant attribution enabled).
- **Billing / Key**: **None required**. Zero credit cards or Google Cloud billing accounts required.

### 2. TomTom Developer Portal

- **Used For**: Real-time traffic flow speed, free-flow velocity comparisons, congestion ratios, and traffic incident feeds.
- **Where to configure**: `backend/.env`
- **Variable**:
  ```dotenv
  TOMTOM_API_KEY=your_tomtom_api_key_here
  ```
- **How to obtain**:
  1. Register at [developer.tomtom.com](https://developer.tomtom.com/).
  2. Create an application to obtain your free API key.
  3. Ensure **Traffic Flow API** and **Traffic Incidents API** are enabled.

### 3. OpenWeather API

- **Used For**: Current temperature, precipitation rate, and wind speed to contextualize observed traffic conditions.
- **Where to configure**: `backend/.env`
- **Variable**:
  ```dotenv
  OPENWEATHER_API_KEY=your_openweather_api_key_here
  ```
- **How to obtain**:
  1. Register at [home.openweathermap.org](https://home.openweathermap.org/api_keys).
  2. Generate a standard API key under the free tier (Current Weather Data).

---

## 💻 Environment Files Setup

### Frontend `.env` (`frontend/.env`)

Copy `frontend/.env.example` to `frontend/.env`:

```dotenv
VITE_API_BASE_URL=http://localhost:8000
```

### Backend `.env` (`backend/.env`)

Copy `backend/.env.example` to `backend/.env`:

```dotenv
TOMTOM_API_KEY=your_tomtom_key
OPENWEATHER_API_KEY=your_openweather_key

MONGODB_URI=mongodb://localhost:27017
DATABASE_NAME=gativa

CORS_ORIGINS=http://localhost:5173,http://localhost:3000
MAX_AREA_KM2=50.0
ENVIRONMENT=development
```

> **Resilience Feature**: If MongoDB is not running locally, Gativa automatically caches session analyses in memory so you can test end-to-end without database configuration blockers. When MongoDB is started, it automatically persists to the database.

---

## 🚗 SUMO & TraCI Simulation Subsystem

Gativa provides a microscopic traffic simulation engine powered by **Eclipse SUMO** (Simulation of Urban MObility) and **TraCI** (Traffic Control Interface) with transparent execution modes and honest scenario comparison:

### 1. Dual Independent Simulation Architecture
- Rather than synthesizing comparison numbers through scalar multipliers, `SimulationService` coordinates two paired, independent simulation runs built on identical network topology and random seed (`42`):
  - **Baseline Run**: Pre-timed uncoordinated fixed-time signal control.
  - **Optimized Run**: Dynamic actuated adaptive signal control responding to real-time detector queue lengths.
- Stepping advances both sessions simultaneously, gathering empirical telemetry side-by-side.

### 2. Explicit Engine Modes & Transparency
- **`native_sumo`**: Discovers native `sumo.exe` and `netconvert.exe` from `SUMO_HOME` (`C:\Program Files (x86)\SUMO`), PATH, or default installations. Connects via TraCI on dynamic ephemeral ports with labeled connections (`gativa_<sim_id>`).
- **`fallback`**: When native SUMO or TraCI is unavailable, executes a deterministic physics and kinematics engine interpolating vehicle trajectories along the actual OSM road segment polylines of the selected corridor. Clearly flagged with a diagnostic badge in the UI explaining the exact fallback reason.
- **`unavailable`**: Explicit error state when network compilation or runtime fails.

### 3. Spatial Coordinate Systems & Geometry
- **Network Compiler**: `SumoNetworkBuilder` compiles nodes (`.nod.xml`), edges (`.edg.xml`), and trips (`.rou.xml`) with `netconvert --proj.plain-geo true`, ensuring node and edge coordinates match WGS84 degrees ($x = lon, y = lat$).
- **Coordinate Transformation**: TraCI `convertGeo(x, y, fromGeo=False)` converts internal coordinates back to WGS84, strictly validated ($[-90, 90]$ latitude, $[-180, 180]$ longitude, non-NaN).
- **Corridor Mapping**: In fallback kinematics, vehicles are placed along the real polyline vertices of the selected corridor, eliminating hardcoded geographic offsets.

### 4. Honest Scenario Comparison Methodology
- **Zero Synthetic Multipliers**: Eliminates artificial scaling factors. All variances represent empirical differences calculated directly from runtime metric samples:
  $$\Delta \% = \frac{\text{Optimized} - \text{Baseline}}{\text{Baseline}} \times 100$$
- **Comparison States**:
  - `pending`: Both scenarios have not stepped yet (0 elapsed seconds). Displays pending indicators instead of fabricated constants.
  - `insufficient_data`: Triggered when metric samples are insufficient.
  - `completed`: Computed after simulation execution, reporting honest improvements and regressions alike (no inverted or suppressed negative results).
  - Division by zero is protected, ensuring no `NaN` or `Infinity` values.

---

## 🚀 Quickstart Commands

### 1. Backend (FastAPI + Python 3.12)

```bash
# Navigate to backend directory
cd backend

# Activate Python virtual environment
# Windows (PowerShell):
.\venv\Scripts\Activate.ps1
# macOS / Linux:
source venv/bin/activate

# Start the FastAPI server on port 8000
uvicorn main:app --reload --port 8000
```

API documentation available at:
- **Interactive Swagger UI**: `http://localhost:8000/docs`
- **Health Check**: `http://localhost:8000/api/health`

### 2. Frontend (React + TypeScript + Vite + Tailwind CSS v4)

```bash
# In a new terminal, navigate to frontend
cd frontend

# Start Vite dev server on port 5173
npm run dev
```

Open your browser to:
- **Application URL**: `http://localhost:5173`

---

## 🧪 Testing & Verification

### Running Automated Backend Unit & Integration Tests

```bash
cd backend
.\venv\Scripts\python.exe -m pytest tests -v
```

**Test Coverage (18 Test Cases)**:
- ✅ GeoJSON polygon coordinate validation & spherical area computation.
- ✅ Feature engineering pipeline & tabular transformations.
- ✅ Machine Learning congestion risk scoring and data-leakage prevention.
- ✅ Evidence-backed recommendation engine with uncertainty notices.
- ✅ SUMO binary discovery (`sumo`, `netconvert`).
- ✅ SUMO network builder XML compilation.
- ✅ TraCI simulation session lifecycle (`ready`, `start`, `step`, `pause`, `reset`, `stop`).
- ✅ Scenario comparison variance calculations.
- ✅ Simulation API endpoints (`prepare`, `start`, `step`, `comparison`, `stop`).
- ✅ FastAPI endpoints: `/api/health`, `/api/analyses`, 404/422 validation handlers.

### Running ML Calibration & Evaluation Report

```bash
cd backend
.\venv\Scripts\python.exe -m app.ml.train_evaluate
```

Reports classification accuracy, F1-score, ROC-AUC, and feature importances comparing baseline Logistic Regression against candidate Random Forest estimators on an independent held-out validation set.

### Frontend Production Build & Linting

```bash
cd frontend
npm run lint
npm run build
```

---

## 🏛️ Project Directory Structure

```
Gativa/
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   │   └── client.ts                     # Typed axios API client with error mapping & simulation endpoints
│   │   ├── components/
│   │   │   ├── Header.tsx                    # Top fixed header matching Stitch design
│   │   │   ├── selection/
│   │   │   │   └── LeafletDrawingMap.tsx     # OpenStreetMap polygon drawing canvas with CartoDB & Esri
│   │   │   └── dashboard/
│   │   │       ├── AnalysisMap.tsx           # Leaflet GIS analysis map with road names & problem markers
│   │   │       ├── AnalysisOverviewTab.tsx   # 6 metric cards, GIS map, Recharts distribution
│   │   │       ├── TrafficFlowTab.tsx        # LOS speed gradient map, telemetry feed
│   │   │       ├── RecommendationsTab.tsx    # 3-column priority cards & schematics
│   │   │       └── SumoSimulationTab.tsx     # 4th dashboard tab: SUMO simulation, TraCI controls, scenario results
│   │   ├── pages/
│   │   │   ├── MapSelectionPage.tsx          # OpenStreetMap polygon drawing & area validation
│   │   │   └── AnalysisDashboardPage.tsx     # 4-tab dashboard coordinator
│   │   ├── types/
│   │   │   └── api.ts                        # Shared TypeScript API schemas
│   │   ├── App.tsx                           # React Router routes
│   │   ├── index.css                         # Gativa Tailwind v4 design tokens
│   │   └── main.tsx                          # React DOM bootstrap
│   ├── .env.example                          # Frontend environment blueprint
│   ├── package.json
│   └── vite.config.ts                        # Vite configuration
│
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── health.py                     # API status & provider validation
│   │   │   ├── analyses.py                   # Analyses CRUD & GeoJSON export
│   │   │   └── simulations.py                # SUMO simulation & TraCI playback endpoints
│   │   ├── core/
│   │   │   ├── config.py                     # Pydantic Settings with validation
│   │   │   └── database.py                   # Async Motor MongoDB connection with memory fallback
│   │   ├── data_ingestion/
│   │   │   ├── tomtom.py                     # TomTom Traffic Flow & Incidents adapter
│   │   │   └── openweather.py                # OpenWeather Current Weather adapter
│   │   ├── features/
│   │   │   └── pipeline.py                   # Feature extraction for road segments
│   │   ├── geospatial/
│   │   │   └── road_network.py               # OSMnx OpenStreetMap road network & betweenness
│   │   ├── ml/
│   │   │   ├── classifier.py                 # Congestion classification model with held-out validation
│   │   │   └── train_evaluate.py             # Reproducible training & evaluation report
│   │   ├── models/
│   │   │   └── schemas.py                    # Complete Pydantic request/response models
│   │   ├── recommendations/
│   │   │   └── engine.py                     # Evidence-backed recommendation generator
│   │   ├── services/
│   │   │   └── analysis.py                   # Pipeline orchestration & persistence
│   │   └── simulation/
│   │       ├── network_builder.py            # SUMO network & demand XML compiler
│   │       ├── traci_manager.py              # TraCI socket connection & adaptive signal controller
│   │       ├── scenario_comparator.py        # Baseline vs Optimized metric variance evaluator
│   │       └── service.py                    # Simulation orchestrator
│   ├── tests/                                # 18 pytest unit & integration tests
│   ├── .env.example                          # Backend environment blueprint
│   ├── main.py                               # FastAPI application entry point
│   └── requirements.txt                      # Python dependencies
│
└── README.md
```

---

## 🎨 Stitch Design Token Alignment

| Token | Color Code | Purpose in Gativa |
| :--- | :--- | :--- |
| **Saffron** | `#FF9933` | Primary action button, active selection highlights, highway markers |
| **Brand Navy** | `#0A1145` / `#0B1C30` | Structural headers, typography, card titles, navigation chrome |
| **India Green** | `#138808` / `#006E05` | Free-Flow Level of Service (LOS A-B), validated status badges |
| **Congestion Crimson** | `#DC2626` / `#BA1A1A` | Severe bottlenecks (LOS E-F), active hazard indicators |
| **Delay Amber** | `#F59E0B` | Moderate traffic delay (LOS C-D), capacity warnings |
| **Surface Canvas** | `#F8F9FF` / `#FFFFFF` | Analytical daylight municipal workspace canvas |

---

## 🔒 Security & Privacy

- **Zero authentication / registration**: Users immediately access the platform without providing personal accounts.
- **Zero secret leakage**: Secrets remain exclusively in backend `.env`. No API keys are required in the frontend.
- **Honest data provenance**: Telemetry failures or missing API credentials are never substituted with fabricated metrics; status indicators explicitly state data availability.
- **Civil engineering disclaimer**: All recommendations highlight uncertainties and mandate professional on-site engineering review before construction or capital commitments.

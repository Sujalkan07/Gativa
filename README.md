# Gativa — Smart Traffic Analysis & Infrastructure Recommendation System

> **Gativa** is a full-stack, AI/ML-powered geospatial platform designed for municipal civil engineers, urban transport planners, and GIS analysts to analyze traffic conditions, diagnose road network bottlenecks, and evaluate evidence-backed infrastructure interventions.

Built in strict accordance with the approved **Stitch UI Design System** (Gativa Urban Infrastructure theme featuring saffron, white, India green, and brand navy) and technical PRD requirements.

---

## 🚦 End-to-End Workflow

1. **Map Selection (`/`)**: Opens directly on an interactive vector map. The user draws or edits a polygon boundary to designate an urban corridor or district.
2. **Analysis Trigger**: The user verifies the calculated area (in km²) and clicks **Analyze Area**.
3. **Data Ingestion & Processing**:
   - Road network topology retrieved from OpenStreetMap via OSMnx.
   - Live traffic telemetry (speeds, free-flow comparisons, incidents) fetched from TomTom.
   - Microclimate weather context retrieved from OpenWeather.
   - Network centrality and graph bottlenecks computed via NetworkX.
4. **Analysis Dashboard (`/analysis/:analysisId`)**: Exactly three core tabs:
   - **Analysis Overview**: 6 metric cards, GIS topology map, road class distribution chart, and structural bottleneck priorities.
   - **Traffic Flow & LOS**: Level of Service (HCM 6th Ed) flow map (Green/Amber/Crimson), telemetry stream, detector speed matrix, and incident feed.
   - **Recommendations**: Filterable matrix of prioritized engineering interventions (Signal Optimization, Geometry Improvement, Road Widening), accompanied by impact scores, geometric schematics, supporting evidence, and engineering review notices.
5. **Persistence & Export**: Analyses persist in MongoDB (with automatic in-memory fallback), allowing users to reload results by ID or download GIS GeoJSON FeatureCollections.

---

## 🔑 Required API Configuration Guide

Gativa requires configuration of three external API services. **Secrets are never committed to GitHub or exposed in frontend bundles.**

### 1. Google Maps Platform

- **Used For**: Interactive map rendering, polygon drawing, pan/zoom, coordinate visualization.
- **Where to configure**: `frontend/.env`
- **Variable**:
  ```dotenv
  VITE_GOOGLE_MAPS_API_KEY=your_google_maps_api_key_here
  ```
- **Required Google Cloud Console APIs to Enable**:
  1. [Maps JavaScript API](https://console.cloud.google.com/marketplace/product/google/maps-backend.googleapis.com)
  2. [Geocoding API](https://console.cloud.google.com/marketplace/product/google/geocoding-backend.googleapis.com) (optional)
- **Security Best Practice**: In the Google Cloud Console, restrict this key by **HTTP referrer** to `http://localhost:*` for local development and your production domain for deployment.

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
  3. *Note*: New OpenWeather API keys may take up to 1–2 hours to activate globally.

---

## 💻 Environment Files Setup

### Frontend `.env` (`frontend/.env`)

Copy `frontend/.env.example` to `frontend/.env`:

```dotenv
VITE_GOOGLE_MAPS_API_KEY=your_google_maps_key
VITE_API_BASE_URL=http://localhost:8000
```

### Backend `.env` (`backend/.env`)

Copy `backend/.env.example` to `backend/.env`:

```dotenv
GOOGLE_MAPS_API_KEY=your_google_maps_key
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

# Install dependencies (already prepared)
pip install -r requirements.txt

# Start the FastAPI server on port 8000
uvicorn main:app --reload --port 8000
```

API documentation will be available at:
- **Interactive Swagger UI**: `http://localhost:8000/docs`
- **Health Check**: `http://localhost:8000/api/health`

### 2. Frontend (React + TypeScript + Vite + Tailwind CSS v4)

```bash
# In a new terminal, navigate to frontend
cd frontend

# Install packages (already installed)
npm install

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

**Test Coverage Includes**:
- ✅ GeoJSON polygon coordinate validation & spherical area computation.
- ✅ Feature engineering pipeline & tabular transformations.
- ✅ Machine Learning congestion risk scoring.
- ✅ Evidence-backed recommendation engine with uncertainty notices.
- ✅ FastAPI endpoints: `/api/health`, `/api/analyses`, 404/422 validation handlers.

### Running ML Calibration & Evaluation Report

```bash
cd backend
.\venv\Scripts\python.exe -m app.ml.train_evaluate
```

Reports classification accuracy, F1-score, ROC-AUC, and feature importances comparing the baseline Logistic Regression against candidate Random Forest estimators.

### Frontend Production Build

```bash
cd frontend
npm run build
```

Generates a minified, type-checked bundle inside `frontend/dist/`.

---

## 🏛️ Project Directory Structure

```
Gativa/
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   │   └── client.ts                     # Typed axios API client with error mapping
│   │   ├── components/
│   │   │   ├── Header.tsx                    # Top fixed header matching Stitch design
│   │   │   └── dashboard/
│   │   │       ├── AnalysisOverviewTab.tsx   # 6 metric cards, GIS map, Recharts distribution
│   │   │       ├── TrafficFlowTab.tsx        # LOS speed gradient map, telemetry feed
│   │   │       └── RecommendationsTab.tsx    # 3-column priority cards & schematics
│   │   ├── pages/
│   │   │   ├── MapSelectionPage.tsx          # Google Maps polygon drawing & area validation
│   │   │   └── AnalysisDashboardPage.tsx     # 3-tab dashboard coordinator
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
│   │   │   └── analyses.py                   # Analyses CRUD & GeoJSON export
│   │   ├── core/
│   │   │   ├── config.py                     # Pydantic Settings with validation
│   │   │   └── database.py                   # Async Motor MongoDB connection
│   │   ├── data_ingestion/
│   │   │   ├── tomtom.py                     # TomTom Traffic Flow & Incidents adapter
│   │   │   └── openweather.py                # OpenWeather Current Weather adapter
│   │   ├── features/
│   │   │   └── pipeline.py                   # Feature extraction for road segments
│   │   ├── geospatial/
│   │   │   └── road_network.py               # OSMnx OpenStreetMap road network & betweenness
│   │   ├── ml/
│   │   │   ├── classifier.py                 # Congestion classification model
│   │   │   └── train_evaluate.py             # Reproducible training & evaluation report
│   │   ├── models/
│   │   │   └── schemas.py                    # Complete Pydantic request/response models
│   │   ├── recommendations/
│   │   │   └── engine.py                     # Evidence-backed recommendation generator
│   │   └── services/
│   │       └── analysis.py                   # Pipeline orchestration & persistence
│   ├── tests/                                # Pytest test suite
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
- **Zero secret leakage**: Secrets remain exclusively in backend `.env`. The frontend key is restricted by HTTP referrer in Google Cloud Console.
- **Honest data provenance**: Telemetry failures or missing API credentials are never substituted with fabricated metrics; status indicators explicitly state data availability.
- **Civil engineering disclaimer**: All recommendations highlight uncertainties and mandate professional on-site engineering review before construction or capital commitments.

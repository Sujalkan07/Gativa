# Gativa Architecture Audit

**Audit scope:** source inspection of the `main` branch as available during this review.  
**Purpose:** document the current implementation and prepare a reproducible Archify-generated interactive map.  
**Application changes:** none. These files are documentation only.

## Important limitation

This audit was performed by reading repository files through GitHub. The Archify CLI/skill could not be executed in this ChatGPT session, so **the interactive Archify HTML and Archify-validated typed JSON have not yet been generated**. Use [ARCHIFY_RUN.md](./ARCHIFY_RUN.md) from a local Codex CLI session to generate those artifacts from the checked-out repository. Do not label the Mermaid overview as an Archify-generated artifact.

## Verified high-level architecture

1. **Frontend entry and routing**
   - `frontend/src/main.tsx` is listed in the repository README as the app entry; verify its current contents during local Archify run.
   - `frontend/src/App.tsx` defines `/` → `MapSelectionPage` and `/analysis/:analysisId` → `AnalysisDashboardPage`.
   - `frontend/src/pages/MapSelectionPage.tsx` maintains polygon/preset selection, validates the area (0.01–50 km²), converts coordinates to GeoJSON, calls `api.createAnalysis`, then navigates to the analysis route.
   - `frontend/src/api/client.ts` defines an Axios client with `VITE_API_BASE_URL` or `http://localhost:8000`, and wrappers for analysis, traffic, recommendation, export, simulation, congestion, and signal-candidate endpoints.
   - `frontend/src/pages/AnalysisDashboardPage.tsx` loads the analysis, traffic flow, and recommendations independently; it renders four tabs through dashboard components.

2. **Backend entry and HTTP API**
   - `backend/main.py` creates the FastAPI application, initializes SQLite, attempts MongoDB connection on startup, configures CORS, and mounts health, analysis, and simulation routers under `/api`.
   - `backend/app/api/analyses.py` exposes analysis creation/retrieval, traffic-flow/recommendation retrieval, and GeoJSON export.
   - `backend/app/api/simulations.py` exposes simulation lifecycle, comparison, congestion, baseline status, signal editing, and signal-candidate decisions.

3. **Analysis pipeline**
   - `backend/app/services/analysis.py` orchestrates polygon analysis and imports the road-network, TomTom, OpenWeather, and recommendation adapters.
   - `backend/app/geospatial/road_network.py` uses OSMnx, NetworkX, pyproj, and Shapely for OSM road-network retrieval/spatial processing and junction-control provenance.
   - `backend/app/data_ingestion/tomtom.py` implements TomTom Flow and Incident HTTP adapters and explicitly reports missing/invalid API-key and provider failures.
   - `backend/app/data_ingestion/openweather.py` implements the OpenWeather current-weather adapter with explicit unavailable/error coverage states.
   - `backend/app/features/pipeline.py` derives segment features including road geometry/attributes, network context, observed traffic, and weather (with default/imputed values when inputs are absent).
   - `backend/app/ml/classifier.py` defines a Random Forest classifier and training/validation logic, including an explicit flag for production-trained models.
   - `backend/app/recommendations/engine.py` ranks bottleneck candidates and produces intervention recommendations with evidence and engineering-review cautions.

4. **Persistence**
   - `backend/app/core/sqlite_store.py` creates SQLite tables for analyses, traffic flow, recommendations, OSM cache, congestion summaries, and signal-candidate decisions.
   - `backend/app/core/database.py` optionally connects to MongoDB. Its `get_persistence_mode()` returns `mongodb` when connected and `sqlite` otherwise. A comment says in-memory fallback on Mongo connection failure, but the shown mode function returns `sqlite`; verify every read/write fallback path before describing persistence as guaranteed.
   - `backend/main.py` calls `init_sqlite_db()` at startup and the Mongo connection routine also calls it.

5. **Simulation**
   - `backend/app/simulation/service.py` manages paired baseline and optimized sessions, builds each scenario separately, uses analysis road segments unless explicit synthetic-demo mode is enabled, and loads approved signal-candidate decisions.
   - `backend/app/simulation/network_builder.py` builds SUMO node/edge/route/config files and looks for `netconvert`; it attempts UTM projection and a plain-geographic fallback.
   - `backend/app/simulation/traci_manager.py` attempts to import TraCI from the configured SUMO tools path and marks it unavailable when import fails. It contains a synthetic corridor fallback only for synthetic-demo sessions.
   - `backend/app/simulation/scenario_comparator.py` compares measured baseline/optimized metrics and explicitly returns a pending comparison when both scenarios have no data and no steps have run.

## End-to-end user journey

1. User draws a polygon or selects a preset in `MapSelectionPage.tsx`.
2. Frontend validates polygon size and submits GeoJSON to `POST /api/analyses`.
3. The analysis router calls `run_analysis()` in `backend/app/services/analysis.py`.
4. The analysis service orchestrates OSM road extraction, sampled TomTom flow/incident retrieval, weather retrieval, bottleneck/recommendation generation, and persistence. TomTom calls are capped at 30 sampled segments per analysis in the visible service source.
5. Frontend navigates to `/analysis/{analysis_id}`; the dashboard requests analysis, traffic flow, and recommendations.
6. The user can view the four dashboard tabs and export the analysis as GeoJSON.
7. For simulation, the client prepares a simulation against the analysis. The backend builds separate baseline and optimized scenario work directories, starts/steps/stops sessions through the simulation service, and returns status/comparison/congestion/signal information.
8. The frontend renders simulation results in the simulation tab. End-to-end runtime behavior has **not** been executed in this audit.

## Dependencies and providers observed in source

| Dependency/provider | Evidence | What is verified |
|---|---|---|
| React Router | `frontend/src/App.tsx` | Two app routes and catch-all redirect |
| Axios | `frontend/src/api/client.ts` | HTTP client wrappers and base URL |
| FastAPI | `backend/main.py`, API routers | App and route mounting |
| OSMnx / OpenStreetMap | `backend/app/geospatial/road_network.py` | Source imports OSMnx; live request success not tested |
| NetworkX, pyproj, Shapely | `backend/app/geospatial/road_network.py` | Imports and geospatial calculations are present |
| TomTom Flow/Incidents/Reverse Geocoding | `tomtom.py`, `services/analysis.py` | HTTP adapter code exists; valid credentials and provider responses not tested |
| OpenWeather Current Weather | `openweather.py` | HTTP adapter code exists; valid credentials and provider responses not tested |
| SQLite | `sqlite_store.py` | Schema initialization code exists; durability under a running app not tested |
| MongoDB / Motor | `core/database.py` | Optional connection code exists; availability/configuration not tested |
| Eclipse SUMO / netconvert / TraCI | `network_builder.py`, `traci_manager.py` | Runtime discovery/import and fallback branches exist; native SUMO execution not tested |
| scikit-learn / NumPy / pandas | `ml/classifier.py`, `features/pipeline.py` | Model and feature code exists; training-data provenance and production model lifecycle require review |
| Leaflet / tile providers | README and frontend components | UI mapping is documented; inspect map component source and browser network behavior before claiming each tile provider is active |

## Known uncertainty / follow-up checks

- **Live external integration:** source code exists, but this review did not run the app with real API keys or verify provider responses.
- **OSM fallback authenticity:** inspect the remainder of `road_network.py` to document exact fallback conditions and ensure synthetic geometry cannot be mistaken for OSM-grounded results.
- **ML inference path:** classifier and feature-engineering modules exist; verify where the classifier is instantiated/called in the full analysis flow, whether model training happens per request, and what labels/training data are used.
- **Traffic coverage:** the analysis service samples at most 30 segments; do not describe TomTom values as a complete per-road network census.
- **Persistence fallback:** reconcile the Mongo connection failure log message with the actual persistence mode and every persistence read/write path.
- **Simulation mode:** native SUMO/TraCI requires local binaries and importability; determine exact runtime status from health/diagnostic responses rather than assuming native mode.
- **Simulation comparisons:** verify that baseline and optimized scenarios have both advanced before presenting comparison values as measured; a pending state is explicitly supported.
- **Tests/build:** no test suite, frontend lint, frontend build, or full application E2E flow was run during this repository-only review.
- **Generated Archify artifact:** still pending execution of the Archify skill and its validator in a local Codex environment.

## Diagram source

See [architecture.mmd](./architecture.mmd) for a source-backed Mermaid overview. It is intentionally a reviewable draft, not a substitute for Archify's typed source or validation receipt.

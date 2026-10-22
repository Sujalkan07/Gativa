# Deployment model

## Decision

Gativa is currently intended to run as a **single-instance, single-tenant, private service** for development and supervised engineering review. The browser UI and FastAPI API run on the same machine. The UI talks to the API through the Vite `/api` proxy during development.

The supported local development address is `http://127.0.0.1:5173` (UI); Vite proxies `/api` to `http://127.0.0.1:8000`. The API health endpoint is also available at `http://127.0.0.1:8000/api/health`. Both listeners are bound to loopback. Do not expose either development server to the public internet.

For a private hosted instance, put the UI and API behind a TLS reverse proxy with organization SSO/OIDC authentication. The proxy must protect both the UI and every `/api` route; CORS is not authentication. Keep the API reachable only through that proxy. Do not deploy the current app as an unauthenticated public service.

This is not a multi-tenant or horizontally scalable design. SUMO sessions live in the API process, so production should run one API worker and keep simulation requests routed to that process. A restart interrupts active simulations. Durable, resumable jobs and multi-worker support are roadmap work.

## Authentication and authorization

- Local loopback development: no login, because the listener is accessible only from the same machine.
- Private hosted service: require SSO/OIDC at the reverse proxy; forward only verified identity headers after stripping client-supplied copies. Restrict access to an approved engineering group.
- Do not treat CORS, an unguessable simulation ID, or a frontend-only gate as access control.
- Before adding public access or multiple tenants, implement API-level identity propagation and per-user ownership checks for analyses and simulations.

## Request and resource limits

The API currently enforces a maximum analysis area (`MAX_AREA_KM2`, default 50 km²), geocoding query bounds, simulation duration (60–3600 seconds), demand bounds (100–10,000 vehicles/hour), step batches (1–20), and a network cap of 1,000 road segments. These are application validation limits, not protection against request floods.

For a private hosted deployment, configure reverse-proxy limits before opening access:

| Operation | Initial perimeter limit | Additional guard |
| --- | ---: | --- |
| Analysis creation | 2 requests/minute and 10/hour per user | At most 2 concurrent analyses per instance |
| Geocoding | 30 requests/minute per user | Cache repeated queries; honor provider terms |
| Simulation preparation | 2 requests/minute per user | At most 2 active simulations per user and 4 per instance |
| Simulation step | 30 requests/minute per simulation | Keep the API's 1–20 step bound |

These are conservative starting values for a single-machine instance and should be tuned using observed latency, memory, provider quotas, and operator feedback. The repository does not currently enforce these perimeter limits itself.

## Persistence and recovery

- Local development: SQLite at `backend/data/gativa.db`; keep this file local and out of source control.
- Single-instance private deployment: mount a persistent disk for SQLite and simulation artifacts, schedule encrypted backups, test restore, and define retention before collecting operational data.
- SQLite is suitable only while writes are modest and the service has one API worker. Move durable analysis and job state to a managed database before scaling to multiple workers or instances.
- Active SUMO sessions are held in memory and are not recoverable after process restart. Treat an interrupted simulation as failed and rerun it; do not claim durable job execution yet.

## Secrets and configuration

- Keep `TOMTOM_API_KEY`, `OPENWEATHER_API_KEY`, database credentials, and proxy secrets in an ignored local `.env` for development or the deployment platform's secret manager for hosted environments.
- Never put server-side provider keys in `VITE_*` variables; Vite variables are shipped to browsers. The TomTom map tile key currently used by the frontend is therefore public client configuration and must be restricted by provider-side origin/quota controls. Do not reuse it as a server API credential.
- Use `backend/.env.example` as a template, rotate any credential that may have been committed or exposed, and avoid logging query strings or provider keys.
- Set explicit `CORS_ORIGINS`, `ENVIRONMENT`, provider keys, and persistent storage paths per environment. Production should fail closed on invalid security configuration.

## Local startup

From the repository root, start each service in its own terminal:

```powershell
cd backend
.\venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

```powershell
cd frontend
npm run dev -- --host 127.0.0.1
```

Open `http://127.0.0.1:5173`. The browser uses the same-origin Vite proxy for API calls. For native SUMO, install SUMO and ensure `SUMO_HOME` points to its installation so the backend can import TraCI and find `sumo`/`netconvert`. Otherwise the application reports and uses its explicitly estimated fallback mode.

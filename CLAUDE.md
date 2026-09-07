# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DT Lab — a Digital Twin web platform for power-distribution network simulation. Users load SimBench networks or convert OpenDSS networks (via pandapower), run timeseries simulations, and inspect voltage/loading violations.

## Three Services to Run

```bash
# 1. PostgreSQL (optional — app degrades gracefully without it)
docker run -d --name dtlab-postgres \
  -e POSTGRES_USER=simbench -e POSTGRES_PASSWORD=simbench -e POSTGRES_DB=simbench \
  -p 5432:5432 postgres:16

# 2. Backend (Python 3.10.11 exact)
cd Backend && uvicorn main:app --reload --host 0.0.0.0 --port 8000

# 3. Frontend
cd Frontend && npm run dev
```

- Backend API + Swagger docs: http://localhost:8000 / http://localhost:8000/docs
- Frontend: http://localhost:5173

## Backend Commands

```bash
cd Backend
pip install -r requirements.txt          # install deps
uvicorn main:app --reload --port 8000    # dev server
```

Create `Backend/.env`:
```
DATABASE_URL=postgresql+psycopg2://simbench:simbench@localhost:5432/simbench
JWT_SECRET_KEY=change-me-in-production
JWT_EXPIRE_HOURS=24
SEED_USER_PASSWORD=DtLab2025!
```

## Frontend Commands

```bash
cd Frontend
npm install
npm run dev        # dev server (Vite + TanStack Start)
npm run build      # production build
npm run lint       # ESLint
npm run format     # Prettier
```

## Architecture

### Backend (`Backend/`)

Routes are split into `routers/` by domain; `main.py` is just app wiring (lifespan, CORS, static mount, `include_router()`):

- **`main.py`** — `FastAPI()` app, `lifespan()` (DB init/seeding, in-memory device/edge-node registry preload), CORS, `/plots` static mount, registers all 8 routers.
- **`routers/opendss.py`** — OpenDSS conversion, timeseries simulation, and power-flow routes (`/convert/opendss*`, `run-opendss`, `run-powerflow`, `pf-plot`, `pf-violations`).
- **`routers/auth.py`** — `/auth/*` (login, register, me, change-password).
- **`routers/scenarios.py`** — `/scenarios` CRUD.
- **`routers/users.py`** — `/users` CRUD (admin only).
- **`routers/networks.py`** — `/`, `/runs*`, `/networks*` listing/detail/delete.
- **`routers/simulations.py`** — `/networks/{id}/run` (SimBench timeseries) and the result-query routes (`vm-pu`, `line-loading`, `trafo-loading`, `envelope`, `phases*`, `column*`).
- **`routers/devices.py`** — edge device registration/telemetry/WebSocket stream (`/devices*`).
- **`routers/edge_nodes.py`** — edge node listing, flexibility estimation, topology plot (`/edge-nodes*`).
- **`schemas.py`** — all Pydantic request models.
- **`shared_state.py`** — config constants (paths, thresholds, Nando/OpenDSS root) and the in-memory runtime dicts (`_devices`, `_edge_nodes`, `_telemetry`, `_ws_subs`) shared across routers — these are mutated in place, never reassigned, so importing them into multiple router modules keeps one shared object.
- **`opendss_helpers.py`** — OpenDSS-domain helper functions (pipeline subprocess runner, network stats, topology plot generation, validation-metrics parsing, power-flow violation counting).
- **`simulation_helpers.py`** — SimBench-domain helper functions (time-step/date validation, violation counting, result-file loading). Also used by `routers/opendss.py` where OpenDSS routes need the same violation-counting logic.
- **`db.py`** — optional PostgreSQL via SQLAlchemy. Every function returns `None`/`False` when the DB is unreachable; the app then falls back to `data/networks.json` on disk. Models: `NetworkRecord`, `SimulationRun`, `ScenarioRecord`, `UserRecord`, `EdgeDevice`, `EdgeNode`, `TelemetryReading`, `ValidationMetrics`.
- **`auth_utils.py`** — JWT creation/validation (`python-jose`), bcrypt password hashing, `get_current_user` / `require_admin` FastAPI dependencies.
- **`generate_networks.py`** — Plotly topology rendering helpers (`style_traces`, `build_plot_html`, `COLORS`, `compute_min_height`).
- **`generate_results.py`** — timeseries simulation runner for SimBench networks.
- **`agent.py`** — edge-node agent logic.

Simulation results are written to `Backend/data/results/{network_id}/{run_id}/` as Parquet files per timestep (subdirs `res_bus/`, `res_line/`, `res_trafo/`, and 3-phase equivalents `res_bus_3ph/` etc.).

### Conversion Pipeline (`Conversion/opendss_conversion/`)

OpenDSS → pandapower conversion pipeline. Invoked **as subprocesses** from `main.py` (`_run_nando_step()`). The backend sets `NANDO_NETWORK=1|2|3|4` and optionally `NANDO_SELECTED_DAY` env vars before calling each script. The four networks are:

| Key | Name |
|-----|------|
| 1 | Rural_SMR8 |
| 2 | Rural_KLO14 |
| 3 | Urban_HPK11 |
| 4 | Urban_CRE21 |

Converted files land in `Conversion/opendss_conversion/dss_files/net_{N}_{Name}/` as `net_pp.xlsx` (balanced) or `net_pp_3ph_ready.json` (unbalanced).

### Frontend (`Frontend/src/`)

TanStack Start (SSR-capable) with file-based routing.

- **`routes/`** — one file per page. Route params use TanStack's `$param` convention (e.g. `networks.$networkId.tsx`). The root route (`__root.tsx`) validates the JWT on every navigation and redirects unauthenticated users to `/`.
- **`lib/api.ts`** — central HTTP client. `apiFetch()` injects `Authorization: Bearer <token>` and auto-clears the token on 401. `API_BASE` is hardcoded to `http://127.0.0.1:8000`.
- **`lib/auth.ts`** — JWT stored in `localStorage` under key `dtlab.token`. Role decoded client-side from the JWT payload (backend is authoritative). Role-to-route permissions table is here. Auth change events dispatched as `"dtlab-auth-change"`.
- **`lib/`** — domain stores (e.g. `networks-store.ts`, `runs-store.ts`, `scenarios-store.ts`) wrap `apiFetch` calls and are seeded from the backend on login.
- **`lib/violations-overview.ts`** — computes violation statistics over CSV timeseries data.
- **`components/ui/`** — shadcn/ui primitives (auto-generated; do not edit manually).
- **`server/`** — TanStack Start server functions (`*.server.ts`, `*.functions.ts`).

### Shared Constants

The violation thresholds **must stay in sync** between:
- `Backend/main.py`: `V_LOWER = 0.94`, `V_UPPER = 1.06`, `LOAD_LIMIT = 100.0`
- `Frontend/src/lib/violations-overview.ts`: `V_LOWER = 0.94`, `V_UPPER = 1.06`, `LOAD_LIMIT = 100`

## Auth & Roles

Three roles: `admin`, `researcher`, `student`. Role-based route access is enforced in `lib/auth.ts` (client) and via `require_admin` dependency (server).

Default seeded credentials (password: `DtLab2025!`):
- `admin@dtlab.io` — Admin
- `elena.marchetti@dtlab.io` — Researcher
- (others seeded at first backend startup) — Student

## Key Design Decisions

- **DB is optional.** The backend starts and serves data with no PostgreSQL. `db.py` wraps every operation in a try/except; callers check for `None` returns.
- **In-memory edge device state.** `_devices`, `_edge_nodes`, `_telemetry` in `main.py` are plain dicts populated at startup from the DB. DB is a persistence side-effect.
- **Conversion pipeline as subprocesses.** All OpenDSS pipeline scripts run via `subprocess.run()` with the Nando root as cwd. Results are cached on disk; reconverting is skipped when output files already exist.
- **Frontend SSR.** The app uses `@tanstack/react-start` (SSR). `localStorage` is unavailable during SSR, so auth checks in `__root.tsx` guard with `typeof window === "undefined"`.

# Power System Simulation service

A web-based Digital Twin platform for power-network simulation using SimBench and OpenDSS/pandapower networks.

---

## Project Structure

```
DT/
├── Backend/        # FastAPI REST API + simulation engine
├── Frontend/       # React + Vite web application
└── Conversion/     # OpenDSS → pandapower conversion pipeline (opendss_conversion)
```

---

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Python | 3.10.11 (exact) | Backend & simulation pipeline |
| Node.js | 18+ | Frontend |
| Docker Desktop | latest | Runs the PostgreSQL database |

---

## 1 — Start the Database (Docker)

```bash
docker run -d \
  --name dtlab-postgres \
  -e POSTGRES_USER=simbench \
  -e POSTGRES_PASSWORD=simbench \
  -e POSTGRES_DB=simbench \
  -p 5432:5432 \
  postgres:16
```

> Default connection string: `postgresql+psycopg2://simbench:simbench@localhost:5432/simbench`  
> Configured in `Backend/.env` — edit if your credentials differ.

---

## 2 — Backend

### Install dependencies

```bash
cd Backend
pip install -r requirements.txt
```

Key packages:

| Package | Version | Purpose |
|---|---|---|
| `fastapi` | 0.136.1 | REST API framework |
| `uvicorn` | 0.46.0 | ASGI server |
| `pandapower` | 2.14.11 | Power flow simulation |
| `simbench` | 1.5.3 | SimBench network loader |
| `dss-python` | 0.12.1 | OpenDSS engine |
| `LightSim2Grid` | 0.10.3 | Fast power flow solver |
| `plotly` | 4.14.3 | Interactive topology plots |
| `SQLAlchemy` | 2.0.49 | Database ORM |
| `psycopg2` | 2.9.11 | PostgreSQL driver |
| `python-jose` | 3.5.0 | JWT authentication |
| `numpy` | 1.26.4 | Numerical computing |
| `pandas` | 2.3.3 | Data processing |

### Configure environment

Create or edit `Backend/.env`:

```env
DATABASE_URL=postgresql+psycopg2://simbench:simbench@localhost:5432/simbench
JWT_SECRET_KEY=change-me-in-production
JWT_EXPIRE_HOURS=24
SEED_USER_PASSWORD=DtLab2025!
```

### Run the backend

```bash
cd Backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

- API: **http://localhost:8000**
- Interactive docs: **http://localhost:8000/docs**

On first startup the backend automatically creates all database tables and seeds the default users.

---

## 3 — Frontend

### Install dependencies

```bash
cd Frontend
npm install
```

### Run the dev server

```bash
npm run dev
```

App available at **http://localhost:5173** (or the port printed in the terminal).

### Build for production

```bash
npm run build
```

Key packages:

| Package | Version | Purpose |
|---|---|---|
| `react` | 19.2.0 | UI framework |
| `@tanstack/react-router` | 1.168.0 | File-based routing |
| `@tanstack/react-query` | 5.83.0 | Server state |
| `tailwindcss` | 4.2.1 | Styling |
| `recharts` | 3.8.1 | Charts |
| `lucide-react` | 0.575.0 | Icons |
| `sonner` | 2.0.7 | Toast notifications |

---

## 4 — Conversion Pipeline

The `Conversion/` folder contains the OpenDSS → pandapower conversion pipeline (`opendss_conversion`). It is invoked automatically by the backend when a user runs a conversion from the UI.

No manual setup is required beyond the Backend dependencies.

---

## 5 — Kubernetes Deployment (Helm)

The `helm-chart/` folder deploys the whole stack (PostgreSQL, backend, frontend) to a Kubernetes cluster.

### Prerequisites

| Tool | Notes |
|---|---|
| Helm 3 | `helm version` |
| A reachable Kubernetes cluster | `kubectl cluster-info` |
| A container registry the cluster can pull from | e.g. Harbor — see below |

### Build and push the images

Backend build context is the **repo root** (it needs the sibling `Conversion/` folder — see `Backend/Dockerfile`). Frontend build context is the `Frontend/` folder itself.

```bash
docker build -f Backend/Dockerfile  -t <registry>/simulator/backend:1.0  .
docker build -f Frontend/Dockerfile -t <registry>/simulator/frontend:1.0 Frontend

docker push <registry>/simulator/backend:1.0
docker push <registry>/simulator/frontend:1.0
```

> If the registry is only reachable over plain HTTP, both the local Docker daemon (`insecure-registries` in its config) **and** every cluster node's containerd (`/etc/rancher/k3s/registries.yaml` for k3s) need to be configured for it — these are two separate configs.

### Configure `values.yaml`

Point `backend.image` / `frontend.image` at whatever you just pushed, and set real credentials:

```yaml
backend:
  image:
    repository: <registry>/simulator/backend
    tag: "1.0"
  jwtSecretKey: "<generate your own — don't ship the default>"

frontend:
  image:
    repository: <registry>/simulator/frontend
    tag: "1.0"
```

`backend.service.nodePort` / `frontend.service.nodePort` (defaults `30800` / `30300`) are how the browser reaches the app — NodePorts are **cluster-wide**, not per-namespace, so a second install anywhere on the same cluster needs different values here (`--set backend.service.nodePort=... --set frontend.service.nodePort=...`). The frontend derives the backend's URL automatically from whatever host the browser used plus this port — no IP is hardcoded anywhere in the chart.

### Install

```bash
kubectl create namespace dtlab
helm install dtlab ./helm-chart -n dtlab
```

- Frontend: `http://<any-node-ip>:<frontend nodePort>`
- Backend docs: `http://<any-node-ip>:<backend nodePort>/docs`

An initContainer seeds the backend's persistent volume with the image's default network data on first run only (PVCs, unlike Docker named volumes, start empty rather than inheriting the image's files).

### Upgrade / uninstall

```bash
helm upgrade dtlab ./helm-chart -n dtlab
helm uninstall dtlab -n dtlab
```

---

## Quick Start

```
1. docker run ...          ← PostgreSQL  (port 5432)
2. cd Backend && uvicorn main:app --reload --host 0.0.0.0 --port 8000
3. cd Frontend && npm run dev
```

Default login credentials (seeded on first backend startup):

| Email | Password | Role |
|---|---|---|
| admin@dtlab.io | DtLab2025! | Admin |
| elena.marchetti@dtlab.io | DtLab2025! | Researcher |
| (other seeded users) | DtLab2025! | Student |

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg2://simbench:simbench@localhost:5432/simbench` | PostgreSQL connection string |
| `JWT_SECRET_KEY` | `change-me-in-production` | JWT signing key |
| `JWT_EXPIRE_HOURS` | `24` | Token expiry in hours |
| `SEED_USER_PASSWORD` | `DtLab2025!` | Default password for seeded users |

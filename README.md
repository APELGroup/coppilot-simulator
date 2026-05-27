# Power System Simulation service

A web-based Digital Twin platform for power-network simulation using SimBench and OpenDSS/pandapower networks.

---

## Project Structure

```
DT/
├── Backend/        # FastAPI REST API + simulation engine
├── Frontend/       # React + Vite web application
└── Conversion/     # OpenDSS → pandapower conversion pipeline (Nando_final)
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
| `psycopg2-binary` | 2.9.12 | PostgreSQL driver |
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

The `Conversion/` folder contains the OpenDSS → pandapower conversion pipeline (`Nando_final`). It is invoked automatically by the backend when a user runs a conversion from the UI.

No manual setup is required beyond the Backend dependencies.

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

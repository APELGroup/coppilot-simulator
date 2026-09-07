"""
FastAPI app wiring: lifespan, middleware, static mount, and router registration.
Route handlers live in routers/ — see CLAUDE.md for the module layout.
"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from db import (
    init_db, seed_networks_from_file, seed_users,
    get_db_networks, update_network_loads, get_db_devices, get_db_edge_nodes,
)
from opendss_helpers import _count_dss_loads
from shared_state import DATA_FILE, PLOTS_DIR, NANDO_ROOT, NANDO_NETWORK_NAMES, _devices, _edge_nodes
from routers import opendss, auth, scenarios, users, networks, simulations, devices, edge_nodes


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Attempt PostgreSQL connection on startup; non-fatal if unavailable.
    # Runs in a worker thread because init_db()'s retry loop uses blocking
    # time.sleep, which would otherwise stall the event loop for the whole
    # retry window (see DB_CONNECT_RETRIES/DB_CONNECT_RETRY_DELAY in db.py).
    await asyncio.to_thread(init_db)
    # Seed networks table from JSON file if DB is available and table is empty.
    if DATA_FILE.exists():
        seed_networks_from_file(DATA_FILE)
    # Seed 5 hardcoded users if users table is empty.
    seed_users()
    # Back-fill load counts for OpenDSS networks saved before this fix.
    # _count_dss_loads reads 10_Loads.dss and is fast (no pandapower load needed).
    _existing = get_db_networks() or []
    for _nw in _existing:
        _nid = _nw.get("id", "")
        if not _nid.startswith("opendss-") or (_nw.get("loads") or 0) != 0:
            continue
        _parts = _nid.split("-")
        if len(_parts) != 3 or _parts[1] not in NANDO_NETWORK_NAMES:
            continue
        _nd = NANDO_ROOT / "dss_files" / f"net_{_parts[1]}_{NANDO_NETWORK_NAMES[_parts[1]]}"
        _dsl = _count_dss_loads(_nd)
        if _dsl > 0:
            update_network_loads(_nid, _dsl)
    # Load persisted edge devices and nodes into in-memory registry.
    for _dev in (get_db_devices() or []):
        _devices[_dev["id"]] = _dev
    for _node in (get_db_edge_nodes() or []):
        _edge_nodes[_node["id"]] = _node
    yield


app = FastAPI(title="SimBench Backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if PLOTS_DIR.exists():
    app.mount("/plots", StaticFiles(directory=PLOTS_DIR), name="plots")

app.include_router(opendss.router)
app.include_router(auth.router)
app.include_router(scenarios.router)
app.include_router(users.router)
app.include_router(networks.router)
app.include_router(simulations.router)
app.include_router(devices.router)
app.include_router(edge_nodes.router)

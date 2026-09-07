"""Run/network listing routes and the service info route."""
import json
import shutil

from fastapi import APIRouter, Depends, HTTPException

from auth_utils import get_current_user, require_admin
from db import (
    get_db_runs, get_latest_validation, get_db_networks, get_db_network,
    delete_network, delete_run,
)
from shared_state import DATA_FILE, PLOTS_DIR, RESULTS_DIR
from simulation_helpers import load_networks

router = APIRouter()


@router.get("/runs/{run_id}/validation")
def get_run_validation(run_id: str, _cu: dict = Depends(get_current_user)):
    runs = get_db_runs()
    if runs is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    run = next((r for r in runs if r["run_id"] == run_id), None)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    network_id = run["network_id"]
    parts = network_id.split("-")
    mode = parts[2] if len(parts) == 3 else "balanced"
    result = get_latest_validation(network_id, mode)
    if result is None:
        raise HTTPException(status_code=404, detail="No validation metrics for this run")
    return result


@router.get("/")
def root():
    networks = load_networks()
    return {
        "message": "SimBench backend is running",
        "data_file_exists": DATA_FILE.exists(),
        "plots_dir_exists": PLOTS_DIR.exists(),
        "results_dir_exists": RESULTS_DIR.exists(),
        "networks_loaded": len(networks),
        "first_network": networks[0] if networks else None,
        "endpoints": [
            "/runs",
            "/networks",
            "/networks/{network_id}",
            "/networks/{network_id}/run",
            "/networks/{network_id}/results/{run_id}/vm-pu",
            "/networks/{network_id}/results/{run_id}/line-loading",
            "/networks/{network_id}/results/{run_id}/trafo-loading",
        ],
    }


@router.get("/runs")
def list_runs(_cu: dict = Depends(get_current_user)):
    return get_db_runs() or []


@router.delete("/runs/{run_id}", status_code=204)
def delete_run_endpoint(run_id: str, network_id: str, _cu: dict = Depends(require_admin)):
    """
    Delete a simulation run: removes the DB record and the on-disk result files.
    Requires `network_id` as a query parameter so the results directory can be located.
    Non-fatal if DB is unavailable — the files are still deleted.
    """
    # Remove result files from disk
    run_dir = RESULTS_DIR / network_id / run_id
    if run_dir.exists():
        shutil.rmtree(run_dir)

    # Remove DB record (best-effort — returns False if DB is down, which is fine)
    deleted = delete_run(run_id)
    if not deleted and not run_dir.exists():
        # Neither DB nor files existed
        raise HTTPException(status_code=404, detail="Run not found")


@router.get("/networks")
def networks(_cu: dict = Depends(get_current_user)):
    return get_db_networks() or []


@router.get("/networks/{network_id}")
def network_detail(network_id: str, _cu: dict = Depends(get_current_user)):
    db_net = get_db_network(network_id)
    if db_net is not None:
        return db_net
    raise HTTPException(status_code=404, detail="Network not found")


@router.delete("/networks/{network_id}", status_code=204)
def delete_network_endpoint(network_id: str, _cu: dict = Depends(require_admin)):
    """
    Delete a network: removes the DB record and the entry in networks.json.
    Returns 204 on success. Raises 404 if the network is not found in either store.
    """
    # Remove from DB
    db_deleted = delete_network(network_id)

    # Remove from networks.json (filesystem fallback)
    json_deleted = False
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                all_networks = json.load(f)
            before = len(all_networks)
            all_networks = [n for n in all_networks if n.get("id") != network_id]
            if len(all_networks) < before:
                with open(DATA_FILE, "w", encoding="utf-8") as f:
                    json.dump(all_networks, f, indent=2, ensure_ascii=False)
                json_deleted = True
        except Exception:
            pass

    if not db_deleted and not json_deleted:
        raise HTTPException(status_code=404, detail="Network not found")

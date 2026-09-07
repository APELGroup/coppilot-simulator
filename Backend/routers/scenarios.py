"""Scenario CRUD routes."""
from datetime import datetime

from fastapi import APIRouter, Depends

from auth_utils import get_current_user
from db import get_db_scenarios, save_scenario, delete_scenario
from schemas import CreateScenarioRequest

router = APIRouter()


@router.get("/scenarios")
def list_scenarios(_cu: dict = Depends(get_current_user)):
    return get_db_scenarios() or []


@router.post("/scenarios", status_code=201)
def create_scenario_endpoint(request: CreateScenarioRequest, _cu: dict = Depends(get_current_user)):
    import time as _time
    scenario_id = request.id or f"scn-{int(_time.time() * 1000)}"
    result = save_scenario(
        id=scenario_id,
        name=request.name,
        network_id=request.network_id,
        sim_type=request.sim_type,
        mode=request.mode,
        horizon=request.horizon,
        timestep=request.timestep,
        created_by=request.created_by,
    )
    if result is None:
        result = {
            "id": scenario_id,
            "name": request.name,
            "networkId": request.network_id,
            "simType": request.sim_type,
            "mode": request.mode,
            "horizon": request.horizon,
            "timestep": request.timestep,
            "createdBy": request.created_by,
            "createdAt": datetime.now().strftime("%Y-%m-%d"),
        }
    return result


@router.delete("/scenarios/{scenario_id}", status_code=204)
def delete_scenario_endpoint(scenario_id: str, _cu: dict = Depends(get_current_user)):
    delete_scenario(scenario_id)

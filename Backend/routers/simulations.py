"""SimBench timeseries simulation routes and result-query routes."""
from datetime import datetime

import pandas as pd
import simbench as sb
import pandapower.timeseries as ts
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from auth_utils import get_current_user
from db import save_run
from schemas import RunRequest
from shared_state import RESULTS_DIR
from simulation_helpers import (
    network_exists, get_time_steps, get_run_id, compute_violation_counts,
    _KIND_TO_3PH_PATH, _load_result_df,
)

router = APIRouter()


@router.post("/networks/{network_id}/run")
def run_simulation(network_id: str, request: RunRequest, _cu: dict = Depends(get_current_user)):
    if not network_exists(network_id):
        raise HTTPException(status_code=404, detail="Network not found")

    if request.mode != "balanced":
        raise HTTPException(status_code=400, detail="Only balanced mode is supported for SimBench networks")

    try:
        net = sb.get_simbench_net(network_id)

        profiles = sb.get_absolute_values(
            net,
            profiles_instead_of_study_cases=True
        )

        sb.apply_const_controllers(net, profiles)

        time_steps = get_time_steps(
            year=request.year,
            horizon=request.horizon,
            month=request.month,
            day=request.day,
            steps_per_day=96
        )

        run_id = get_run_id(request)
        out_dir = RESULTS_DIR / network_id / run_id
        out_dir.mkdir(parents=True, exist_ok=True)

        ow = ts.OutputWriter(
            net,
            output_path=str(out_dir),
            output_file_type=".csv"
        )

        ow.log_variable("res_bus", "vm_pu")
        ow.log_variable("res_line", "loading_percent")

        has_trafo = len(net.trafo) > 0
        if has_trafo:
            ow.log_variable("res_trafo", "loading_percent")

        start_time = datetime.now()
        ts.run_timeseries(net, time_steps=time_steps)
        duration_seconds = (datetime.now() - start_time).total_seconds()

        v = compute_violation_counts(out_dir, has_trafo)

        # [DB-BACKED] Persist run metadata; CSV result files are still written to disk above.
        save_run(
            run_id=run_id,
            network_id=network_id,
            horizon=request.horizon,
            year=request.year,
            month=request.month,
            day=request.day,
            mode=request.mode,
            has_trafo=has_trafo,
            started_at=start_time,
            duration_seconds=duration_seconds,
            violations_under_voltage=v["under_voltage"],
            violations_over_voltage=v["over_voltage"],
            violations_line_overload=v["line_overload"],
            violations_trafo_overload=v["trafo_overload"],
            violations_total=v["total"],
            created_by=_cu.get("name"),
        )

        return {
            "status": "completed",
            "network_id": network_id,
            "horizon": request.horizon,
            "year": request.year,
            "month": request.month,
            "day": request.day,
            "mode": request.mode,
            "run_id": run_id,
            "started_at": start_time.isoformat(),
            "duration_seconds": duration_seconds,
            "violations": v,
            "results_available": True,
            "results": {
                "vm_pu":        f"/networks/{network_id}/results/{run_id}/vm-pu",
                "line_loading": f"/networks/{network_id}/results/{run_id}/line-loading",
                "trafo_loading": (
                    f"/networks/{network_id}/results/{run_id}/trafo-loading"
                    if has_trafo else None
                ),
            },
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/networks/{network_id}/results/{run_id}/vm-pu")
def get_vm_pu(network_id: str, run_id: str, _cu: dict = Depends(get_current_user)):
    file_path = RESULTS_DIR / network_id / run_id / "res_bus" / "vm_pu.csv"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="vm_pu not found")
    return FileResponse(file_path)


@router.get("/networks/{network_id}/results/{run_id}/line-loading")
def get_line_loading(network_id: str, run_id: str, _cu: dict = Depends(get_current_user)):
    file_path = RESULTS_DIR / network_id / run_id / "res_line" / "loading_percent.csv"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="line loading not found")
    return FileResponse(file_path)


@router.get("/networks/{network_id}/results/{run_id}/trafo-loading")
def get_trafo_loading(network_id: str, run_id: str, _cu: dict = Depends(get_current_user)):
    file_path = RESULTS_DIR / network_id / run_id / "res_trafo" / "loading_percent.csv"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="trafo loading not found")
    return FileResponse(file_path)


@router.get("/networks/{network_id}/results/{run_id}/{kind}/envelope")
def get_result_envelope(network_id: str, run_id: str, kind: str, _cu: dict = Depends(get_current_user)):
    """Return per-timestep min/mean/max across all components — much smaller than the full CSV."""
    df = _load_result_df(network_id, run_id, kind)
    return {
        "min":     [round(v, 6) for v in df.min(axis=1).tolist()],
        "mean":    [round(v, 6) for v in df.mean(axis=1).tolist()],
        "max":     [round(v, 6) for v in df.max(axis=1).tolist()],
        "columns": df.columns.tolist(),
        "n_rows":  len(df),
    }


@router.get("/networks/{network_id}/results/{run_id}/{kind}/phases")
def get_result_phases(network_id: str, run_id: str, kind: str, _cu: dict = Depends(get_current_user)):
    """Return per-phase per-timestep min/mean/max for unbalanced OpenDSS runs."""
    entries = _KIND_TO_3PH_PATH.get(kind)
    if not entries:
        raise HTTPException(status_code=400, detail=f"No phase data available for kind '{kind}'")
    result: dict[str, dict] = {}
    for phase, sub, fname in entries:
        path = RESULTS_DIR / network_id / run_id / sub / fname
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"Phase {phase.upper()} data not found ({sub}/{fname})")
        df = pd.read_csv(path, sep=";", index_col=0)
        result[phase] = {
            "mean":    [round(v, 6) for v in df.mean(axis=1).tolist()],
            "max":     [round(v, 6) for v in df.max(axis=1).tolist()],
            "min":     [round(v, 6) for v in df.min(axis=1).tolist()],
            "n_rows":  len(df),
            "columns": df.columns.tolist(),
        }
    return result


@router.get("/networks/{network_id}/results/{run_id}/{kind}/phases/column-summary")
def get_result_phases_column_summary(network_id: str, run_id: str, kind: str, _cu: dict = Depends(get_current_user)):
    """
    Return per-column (per-element) min/max aggregated across ALL timesteps and
    ALL phases, plus the timestep index (0-based) at which each element reached
    its worst min/max value.

    Shape: {
        columns: [str, ...],
        min:      [float, ...],
        max:      [float, ...],
        min_step: [int, ...],   # timestep index of the worst minimum per element
        max_step: [int, ...],   # timestep index of the worst maximum per element
        n_rows:   int,          # total number of timesteps
    }
    """
    entries = _KIND_TO_3PH_PATH.get(kind)
    if not entries:
        raise HTTPException(status_code=400, detail=f"No phase data available for kind '{kind}'")

    import numpy as np

    dfs: list[pd.DataFrame] = []
    columns: list = []

    for phase, sub, fname in entries:
        path = RESULTS_DIR / network_id / run_id / sub / fname
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"Phase {phase.upper()} data not found ({sub}/{fname})")
        df = pd.read_csv(path, sep=";", index_col=0)
        dfs.append(df)
        if not columns:
            columns = df.columns.tolist()

    # Stack phases along axis-0: shape (n_phases, n_timesteps, n_elements)
    arr = np.stack([df.values for df in dfs], axis=0)
    n_phases, n_timesteps, n_elements = arr.shape

    # Flatten phases × timesteps → one long axis for argmin/argmax
    arr_2d = arr.reshape(n_phases * n_timesteps, n_elements)  # (n_phases*n_timesteps, n_elements)

    col_min = arr_2d.min(axis=0)   # (n_elements,)
    col_max = arr_2d.max(axis=0)   # (n_elements,)

    # argmin/argmax give position in the flattened (phase, timestep) axis;
    # mod n_timesteps recovers the 0-based timestep index.
    min_step = (arr_2d.argmin(axis=0) % n_timesteps).tolist()
    max_step = (arr_2d.argmax(axis=0) % n_timesteps).tolist()

    return {
        "columns":  columns,
        "min":      [round(float(v), 6) for v in col_min],
        "max":      [round(float(v), 6) for v in col_max],
        "min_step": [int(s) for s in min_step],
        "max_step": [int(s) for s in max_step],
        "n_rows":   n_timesteps,
    }


@router.get("/networks/{network_id}/results/{run_id}/{kind}/phases/column/{col_name:path}")
def get_result_phases_column(network_id: str, run_id: str, kind: str, col_name: str, _cu: dict = Depends(get_current_user)):
    """Return per-phase time-series for a single component (unbalanced OpenDSS only)."""
    entries = _KIND_TO_3PH_PATH.get(kind)
    if not entries:
        raise HTTPException(status_code=400, detail=f"No phase data for kind '{kind}'")
    result: dict[str, list] = {}
    for phase, sub, fname in entries:
        path = RESULTS_DIR / network_id / run_id / sub / fname
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"Phase {phase.upper()} data not found")
        df = pd.read_csv(path, sep=";", index_col=0)
        # column names may be stored as integers; try int key first
        if col_name not in df.columns:
            try:
                col_key = int(col_name)
                if col_key not in df.columns:
                    raise HTTPException(status_code=404, detail=f"Column '{col_name}' not found in phase {phase.upper()}")
                result[phase] = [round(v, 6) for v in df[col_key].tolist()]
            except (ValueError, TypeError):
                raise HTTPException(status_code=404, detail=f"Column '{col_name}' not found in phase {phase.upper()}")
        else:
            result[phase] = [round(v, 6) for v in df[col_name].tolist()]
    return {"column": col_name, "a": result["a"], "b": result["b"], "c": result["c"]}


@router.get("/networks/{network_id}/results/{run_id}/{kind}/column/{col_name:path}")
def get_result_column(network_id: str, run_id: str, kind: str, col_name: str, _cu: dict = Depends(get_current_user)):
    """Return the time-series for a single component (bus / line / trafo)."""
    df = _load_result_df(network_id, run_id, kind)
    if col_name not in df.columns:
        raise HTTPException(status_code=404, detail=f"Column '{col_name}' not found")
    return {
        "column": col_name,
        "values": [round(v, 6) for v in df[col_name].tolist()],
    }

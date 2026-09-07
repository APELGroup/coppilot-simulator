"""Helper functions for SimBench timeseries simulation and result queries."""
import calendar
import json
from datetime import datetime
from pathlib import Path

import pandas as pd
from fastapi import HTTPException

from db import get_db_network
from schemas import RunRequest
from shared_state import DATA_FILE, RESULTS_DIR, V_LOWER, V_UPPER, LOAD_LIMIT


def load_networks():
    if not DATA_FILE.exists():
        return []
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def network_exists(network_id: str) -> bool:
    return get_db_network(network_id) is not None


def get_day_of_year(year: int, month: int, day: int):
    return sum(calendar.monthrange(year, m)[1] for m in range(1, month)) + day


def validate_month(year: int, month: int):
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="Invalid month")
    return calendar.monthrange(year, month)[1]


def validate_day(year: int, month: int, day: int):
    max_day = validate_month(year, month)
    if day < 1 or day > max_day:
        raise HTTPException(status_code=400, detail="Invalid day for selected month")


def get_time_steps(
    year: int,
    horizon: str,
    month: int,
    day: int | None = None,
    steps_per_day: int = 96,
):
    validate_month(year, month)

    if horizon == "day":
        if day is None:
            raise HTTPException(status_code=400, detail="Day is required for day horizon")
        validate_day(year, month, day)
        day_of_year = get_day_of_year(year, month, day)
        start = (day_of_year - 1) * steps_per_day
        return range(start, start + steps_per_day)

    if horizon == "week":
        if day is None:
            raise HTTPException(status_code=400, detail="Start day is required for week horizon")
        validate_day(year, month, day)
        day_of_year = get_day_of_year(year, month, day)
        days_in_year = 366 if calendar.isleap(year) else 365
        start_day = day_of_year
        end_day = min(day_of_year + 6, days_in_year)
        return range((start_day - 1) * steps_per_day, end_day * steps_per_day)

    if horizon == "month":
        days_before_month = sum(calendar.monthrange(year, m)[1] for m in range(1, month))
        days_in_month = calendar.monthrange(year, month)[1]
        start = days_before_month * steps_per_day
        return range(start, start + days_in_month * steps_per_day)

    raise HTTPException(status_code=400, detail="Invalid horizon")


def get_run_id(request: RunRequest) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if request.horizon == "day":
        return f"{request.year}-{request.month:02d}-{request.day:02d}_{stamp}"
    if request.horizon == "week":
        return f"{request.year}-{request.month:02d}-{request.day:02d}_week_{stamp}"
    if request.horizon == "month":
        return f"{request.year}-{request.month:02d}_{stamp}"
    return f"unknown_{stamp}"


def compute_violation_counts(out_dir: Path, has_trafo: bool, mode: str = "balanced") -> dict:
    """
    Scan the simulation CSVs and count per-asset violations using the same
    thresholds as the frontend.  One violation = one asset (bus / line / trafo)
    that breaches the limit at any timestep during the run.
    Returns a dict with under_voltage, over_voltage, line_overload,
    trafo_overload, and total keys.

    For unbalanced runs the 3-phase CSVs (res_bus_3ph, res_line_3ph,
    res_trafo_3ph) are used; the balanced res_bus/vm_pu.csv is not updated
    by pp_timeseries_3ph.py and would contain stale data from a previous run.
    """
    counts = dict(under_voltage=0, over_voltage=0,
                  line_overload=0, trafo_overload=0)
    try:
        if mode == "unbalanced":
            # ── 3-phase results ───────────────────────────────────────────────
            bus3_dir = out_dir / "res_bus_3ph"
            vm_phases = []
            for ph in ("vm_a_pu.csv", "vm_b_pu.csv", "vm_c_pu.csv"):
                p = bus3_dir / ph
                if p.exists():
                    vm_phases.append(pd.read_csv(p, sep=";", index_col=0))
            if vm_phases:
                vm_min = pd.concat([df.min() for df in vm_phases], axis=1).min(axis=1)
                vm_max = pd.concat([df.max() for df in vm_phases], axis=1).max(axis=1)
                counts["under_voltage"] = int((vm_min < V_LOWER).sum())
                counts["over_voltage"]  = int((vm_max > V_UPPER).sum())

            line3_dir = out_dir / "res_line_3ph"
            line_phases = []
            for ph in ("loading_a_percent.csv", "loading_b_percent.csv", "loading_c_percent.csv"):
                p = line3_dir / ph
                if p.exists():
                    line_phases.append(pd.read_csv(p, sep=";", index_col=0))
            if line_phases:
                line_max = pd.concat([df.max() for df in line_phases], axis=1).max(axis=1)
                counts["line_overload"] = int((line_max > LOAD_LIMIT).sum())

            if has_trafo:
                trafo3_dir = out_dir / "res_trafo_3ph"
                trafo_phases = []
                for ph in ("loading_a_percent.csv", "loading_b_percent.csv", "loading_c_percent.csv"):
                    p = trafo3_dir / ph
                    if p.exists():
                        trafo_phases.append(pd.read_csv(p, sep=";", index_col=0))
                if trafo_phases:
                    trafo_max = pd.concat([df.max() for df in trafo_phases], axis=1).max(axis=1)
                    counts["trafo_overload"] = int((trafo_max > LOAD_LIMIT).sum())
        else:
            # ── Balanced results ──────────────────────────────────────────────
            vm_path = out_dir / "res_bus" / "vm_pu.csv"
            if vm_path.exists():
                vm = pd.read_csv(vm_path, sep=";", index_col=0)
                counts["under_voltage"] = int((vm.min() < V_LOWER).sum())
                counts["over_voltage"]  = int((vm.max() > V_UPPER).sum())

            line_path = out_dir / "res_line" / "loading_percent.csv"
            if line_path.exists():
                line = pd.read_csv(line_path, sep=";", index_col=0)
                counts["line_overload"] = int((line.max() > LOAD_LIMIT).sum())

            if has_trafo:
                trafo_path = out_dir / "res_trafo" / "loading_percent.csv"
                if trafo_path.exists():
                    trafo = pd.read_csv(trafo_path, sep=";", index_col=0)
                    counts["trafo_overload"] = int((trafo.max() > LOAD_LIMIT).sum())

    except Exception as exc:
        # Non-fatal: return whatever was counted so far.
        import logging
        logging.getLogger(__name__).warning("Violation count failed: %s", exc)

    counts["total"] = sum(counts.values())
    return counts


_KIND_TO_PATH: dict[str, tuple[str, str]] = {
    "vm-pu":        ("res_bus",   "vm_pu.csv"),
    "line-loading": ("res_line",  "loading_percent.csv"),
    "trafo-loading":("res_trafo", "loading_percent.csv"),
}

_KIND_TO_3PH_PATH: dict[str, list[tuple[str, str, str]]] = {
    "vm-pu": [
        ("a", "res_bus_3ph",   "vm_a_pu.csv"),
        ("b", "res_bus_3ph",   "vm_b_pu.csv"),
        ("c", "res_bus_3ph",   "vm_c_pu.csv"),
    ],
    "line-loading": [
        ("a", "res_line_3ph",  "loading_a_percent.csv"),
        ("b", "res_line_3ph",  "loading_b_percent.csv"),
        ("c", "res_line_3ph",  "loading_c_percent.csv"),
    ],
    "trafo-loading": [
        ("a", "res_trafo_3ph", "loading_a_percent.csv"),
        ("b", "res_trafo_3ph", "loading_b_percent.csv"),
        ("c", "res_trafo_3ph", "loading_c_percent.csv"),
    ],
}


def _load_result_df(network_id: str, run_id: str, kind: str) -> pd.DataFrame:
    entry = _KIND_TO_PATH.get(kind)
    if not entry:
        raise HTTPException(status_code=400, detail=f"Unknown kind '{kind}'")
    sub, fname = entry
    path = RESULTS_DIR / network_id / run_id / sub / fname
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{kind} not found")
    return pd.read_csv(path, sep=";", index_col=0)

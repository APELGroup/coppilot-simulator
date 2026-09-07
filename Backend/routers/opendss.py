"""OpenDSS conversion, timeseries simulation, and power-flow routes."""
import os
import shutil
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from auth_utils import get_current_user
from db import save_network, save_run, save_validation_metrics
from schemas import (
    ConvertOpenDSSRequest, SimulateOpenDSSRequest, SaveOpenDSSRequest,
    OpenDSSRunRequest, PowerFlowRequest,
)
from shared_state import (
    NANDO_ROOT, NANDO_NETWORK_NAMES, PLOTS_DIR, RESULTS_DIR,
    _PLOT_HELPERS_AVAILABLE, compute_min_height, build_plot_html,
)
from opendss_helpers import (
    _run_nando_step, _network_stats_from_pp, _generate_opendss_plot,
    _apply_opendss_profiles_at_step, _compute_pf_violations,
    _parse_metric_global, _build_validation, _upsert_networks_json,
)
from simulation_helpers import compute_violation_counts

router = APIRouter()


# Conversion pipeline steps (relative to NANDO_ROOT).
# Balanced stops after step 3; unbalanced adds the 3-phase preparation step.
_CONVERSION_STEPS_BALANCED = [
    ("conversion/dss_files_creator.py",  "Generate DSS files from Excel"),
    ("conversion/dss_to_pp_mv_build.py", "Build MV pandapower network"),
    ("conversion/dss_to_pp_lv_build.py", "Add LV network (trafos + lines)"),
]
_CONVERSION_STEPS_UNBALANCED = _CONVERSION_STEPS_BALANCED + [
    ("fixes/prepare_net_for_3ph.py", "Prepare 3-phase parameters"),
]


@router.post("/convert/opendss")
def convert_opendss(request: ConvertOpenDSSRequest, _cu: dict = Depends(get_current_user)):
    """
    Run the OpenDSS → pandapower conversion pipeline for one of the 4 networks.
    Skips the pipeline entirely if the output file already exists (cached).
    Balanced mode: DSS file generation + MV build + LV build.
    Unbalanced mode: same + 3-phase parameter preparation.
    Returns network element counts on success.
    """
    if not NANDO_ROOT.exists():
        raise HTTPException(status_code=500, detail=f"Nando root not found: {NANDO_ROOT}")

    network_name = NANDO_NETWORK_NAMES[request.network]
    net_subdir = f"net_{request.network}_{network_name}"
    net_dir = NANDO_ROOT / "dss_files" / net_subdir
    net_xlsx = net_dir / "net_pp.xlsx"
    net_json = net_dir / "net_pp_3ph_ready.json"

    already_converted = (
        net_json.exists() if request.mode == "unbalanced" else net_xlsx.exists()
    )

    if already_converted:
        stats = _network_stats_from_pp(net_xlsx=net_xlsx, net_json=net_json, mode=request.mode, dss_dir=net_dir)
        network_id = f"opendss-{request.network}-{request.mode}"
        display_name = f"OpenDSS {network_name.replace('_', ' ')} – {request.mode.capitalize()}"
        plot_url, plot_height = _generate_opendss_plot(network_id, net_xlsx, net_json, request.mode, display_name)
        return {
            "status": "completed",
            "network": request.network,
            "network_name": network_name,
            "mode": request.mode,
            "duration_seconds": 0.0,
            "network_stats": stats,
            "cached": True,
            "plot_url": plot_url,
            "plot_height": plot_height or None,
        }

    steps = (
        _CONVERSION_STEPS_UNBALANCED
        if request.mode == "unbalanced"
        else _CONVERSION_STEPS_BALANCED
    )

    env = {**os.environ, "NANDO_NETWORK": request.network}
    start_time = datetime.now()

    for script_rel, label in steps:
        try:
            _run_nando_step(script_rel, label, env)
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    duration_seconds = (datetime.now() - start_time).total_seconds()

    stats = _network_stats_from_pp(net_xlsx=net_xlsx, net_json=net_json, mode=request.mode, dss_dir=net_dir)
    network_id = f"opendss-{request.network}-{request.mode}"
    display_name = f"OpenDSS {network_name.replace('_', ' ')} – {request.mode.capitalize()}"
    plot_url, plot_height = _generate_opendss_plot(network_id, net_xlsx, net_json, request.mode, display_name)

    return {
        "status": "completed",
        "network": request.network,
        "network_name": network_name,
        "mode": request.mode,
        "duration_seconds": round(duration_seconds, 2),
        "network_stats": stats,
        "cached": False,
        "plot_url": plot_url,
        "plot_height": plot_height or None,
    }


_SIMULATE_STEPS_BALANCED = [
    ("conversion/dss_files_creator.py",    "Regenerate load profiles for selected day"),
    ("nando_runs/nando_run_balanced.py",   "OpenDSS balanced timeseries"),
    ("panda_runs/pp_timeseries.py",        "pandapower balanced timeseries"),
    ("metrics/metrics_all_busses.py",      "Compare vm_pu (PP vs DSS)"),
    ("metrics/metrics_all_lines.py",       "Compare line loading (PP vs DSS)"),
    ("metrics/metric_trafo_loading.py",    "Compare trafo loading (PP vs DSS)"),
]

_SIMULATE_STEPS_UNBALANCED = [
    ("conversion/dss_files_creator.py",    "Regenerate load profiles for selected day"),
    ("nando_runs/nando_run_balanced.py",   "OpenDSS balanced timeseries (voltage reference)"),
    ("nando_runs/nando_run_unbalanced.py", "OpenDSS 3-phase timeseries"),
    ("panda_runs/pp_timeseries_3ph.py",   "pandapower 3-phase timeseries"),
    ("metrics/metrics_3ph_vm_pu.py",       "Compare bus voltages (3-phase)"),
    ("metrics/metrics_3ph_loading.py",     "Compare line+trafo loading (3-phase)"),
]


@router.post("/convert/opendss/simulate")
def simulate_opendss(request: SimulateOpenDSSRequest, _cu: dict = Depends(get_current_user)):
    """
    Run the OpenDSS and pandapower timeseries simulations for the chosen day,
    then compute comparison metrics (MAPE, max error, bias).
    Balanced: DSS balanced + PP balanced + metrics_all_busses.
    Unbalanced: DSS balanced (voltage ref) + DSS 3-ph + PP 3-ph + 3-ph metrics.
    """
    if not 1 <= request.day <= 365:
        raise HTTPException(status_code=400, detail="day must be between 1 and 365")

    if not NANDO_ROOT.exists():
        raise HTTPException(status_code=500, detail=f"Nando root not found: {NANDO_ROOT}")

    network_name = NANDO_NETWORK_NAMES[request.network]
    steps = (
        _SIMULATE_STEPS_UNBALANCED
        if request.mode == "unbalanced"
        else _SIMULATE_STEPS_BALANCED
    )

    # Compute validation window: each step is 30 min → 2 steps per hour
    n_validation_steps = request.validation_hours * 2
    validation_start_hhmm = "00:00"
    validation_end_h = request.validation_hours
    validation_end_hhmm = f"{validation_end_h:02d}:00" if validation_end_h < 24 else "23:30"

    env = {
        **os.environ,
        "NANDO_NETWORK": request.network,
        "NANDO_SELECTED_DAY": str(request.day),
        "NANDO_VALIDATION_HOURS": str(request.validation_hours),
        "NANDO_VALIDATION_STEPS": str(n_validation_steps),
    }
    start_time = datetime.now()

    for script_rel, label in steps:
        try:
            _run_nando_step(script_rel, label, env)
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    duration_seconds = (datetime.now() - start_time).total_seconds()

    net_subdir = f"net_{request.network}_{network_name}"
    metrics_dir = NANDO_ROOT / "metrics" / net_subdir

    if request.mode == "balanced":
        global_metrics = _parse_metric_global(metrics_dir / "metric_global.txt")
    else:
        vm_metrics   = _parse_metric_global(metrics_dir / "metric_3ph_global.txt")
        load_metrics = _parse_metric_global(metrics_dir / "metric_3ph_loading_global.txt")
        global_metrics = {**vm_metrics, **{f"loading_{k}": v for k, v in load_metrics.items()}}

    validation = _build_validation(metrics_dir, request.mode)

    network_id_str = f"opendss-{request.network}-{request.mode}"
    save_validation_metrics(
        network_id=network_id_str,
        mode=request.mode,
        day=request.day,
        validation=validation,
    )

    return {
        "status": "completed",
        "network": request.network,
        "network_name": network_name,
        "mode": request.mode,
        "day": request.day,
        "duration_seconds": round(duration_seconds, 2),
        "metrics": global_metrics,
        "validation": validation,
        "validation_hours": request.validation_hours,
        "n_timesteps": n_validation_steps,
        "validation_start": validation_start_hhmm,
        "validation_end": validation_end_hhmm,
    }


NANDO_NETWORK_TYPES = {"1": "Mixed", "2": "Mixed", "3": "Mixed", "4": "Mixed"}


@router.post("/convert/opendss/save")
def save_opendss_network(request: SaveOpenDSSRequest, _cu: dict = Depends(get_current_user)):
    """
    Persist a converted OpenDSS network into the database and networks.json
    so it appears in /networks and can be used in future simulations.
    Idempotent — re-saving the same network_id updates the existing record.
    """
    network_name = NANDO_NETWORK_NAMES[request.network]
    network_id = f"opendss-{request.network}-{request.mode}"

    net_subdir = f"net_{request.network}_{network_name}"
    net_dir = NANDO_ROOT / "dss_files" / net_subdir
    stats = _network_stats_from_pp(
        net_xlsx=net_dir / "net_pp.xlsx",
        net_json=net_dir / "net_pp_3ph_ready.json",
        mode=request.mode,
        dss_dir=net_dir,
    )
    if not stats:
        raise HTTPException(
            status_code=400,
            detail="Converted network files not found. Run the conversion first.",
        )

    status = "validated" if request.validation_day is not None else "converted"
    plot_filename = f"{network_id}.html"
    plot_url = f"/plots/{plot_filename}" if (PLOTS_DIR / plot_filename).exists() else None
    record = {
        "id":           network_id,
        "name":         f"OpenDSS {network_name.replace('_', ' ')} – {request.mode.capitalize()}",
        "voltage":      "66 kV / 22 kV / 0.4 kV",
        "type":         NANDO_NETWORK_TYPES[request.network],
        "status":       status,
        "created":      datetime.now().strftime("%Y-%m-%d"),
        "version":      "v1.0",
        "buses":        stats.get("buses"),
        "lines":        stats.get("lines"),
        "transformers": stats.get("transformers"),
        "loads":        stats.get("loads"),
        "plot_url":     plot_url,
        # stored in extra column
        "source":           "opendss",
        "mode":             request.mode,
        "validation_day":   request.validation_day,
        "metrics":          request.metrics,
        "created_by":       _cu.get("name", ""),
    }

    save_network(record)
    _upsert_networks_json(record)

    return {"status": "saved", "network_id": network_id, "network": record}


@router.post("/networks/{network_id}/run-opendss")
def run_opendss_simulation(network_id: str, request: OpenDSSRunRequest, _cu: dict = Depends(get_current_user)):
    """
    Run a pandapower timeseries simulation on a previously converted OpenDSS network.
    Regenerates load profiles for the requested day, runs the appropriate timeseries
    (balanced or 3-phase), copies results to the standard results directory, and
    returns the same shape as the SimBench run endpoint.
    """
    if not network_id.startswith("opendss-"):
        raise HTTPException(status_code=400, detail="Not an OpenDSS network")

    parts = network_id.split("-")   # ["opendss", "N", "balanced"|"unbalanced"]
    if len(parts) != 3 or parts[1] not in NANDO_NETWORK_NAMES:
        raise HTTPException(status_code=400, detail=f"Invalid OpenDSS network id: {network_id}")

    if not 1 <= request.day <= 365:
        raise HTTPException(status_code=400, detail="day must be between 1 and 365")

    network_num  = parts[1]
    mode         = parts[2]
    network_name = NANDO_NETWORK_NAMES[network_num]
    net_subdir   = f"net_{network_num}_{network_name}"
    net_dir      = NANDO_ROOT / "dss_files" / net_subdir

    expected_file = (net_dir / "net_pp_3ph_ready.json") if mode == "unbalanced" else (net_dir / "net_pp.xlsx")
    if not expected_file.exists():
        raise HTTPException(
            status_code=400,
            detail="Converted network not found. Run the conversion pipeline first.",
        )

    ts_script = "panda_runs/pp_timeseries_3ph.py" if mode == "unbalanced" else "panda_runs/pp_timeseries.py"
    steps = [
        ("conversion/dss_files_creator.py", "Regenerate load profiles for selected day"),
        (ts_script,                          f"pandapower {mode} timeseries"),
    ]

    env = {
        **os.environ,
        "NANDO_NETWORK":      network_num,
        "NANDO_SELECTED_DAY": str(request.day),
    }

    start_time = datetime.now()
    for script_rel, label in steps:
        try:
            _run_nando_step(script_rel, label, env)
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    duration = (datetime.now() - start_time).total_seconds()

    # Copy nando results to the standard backend results tree
    run_id  = f"day{request.day:03d}_{start_time.strftime('%Y%m%d-%H%M%S')}"
    src_dir = NANDO_ROOT / "results" / net_subdir
    out_dir = RESULTS_DIR / network_id / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    for sub in ["res_bus", "res_line", "res_trafo"]:
        src = src_dir / sub
        if src.exists():
            dst = out_dir / sub
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)

    if mode == "unbalanced":
        for sub in ["res_bus_3ph", "res_line_3ph", "res_trafo_3ph"]:
            src = src_dir / sub
            if src.exists():
                dst = out_dir / sub
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)

    has_trafo = (out_dir / "res_trafo_3ph" if mode == "unbalanced" else out_dir / "res_trafo").exists()
    v = compute_violation_counts(out_dir, has_trafo, mode=mode)

    save_run(
        run_id=run_id,
        network_id=network_id,
        horizon="day",
        year=2024,
        month=1,
        day=request.day,
        mode=mode,
        has_trafo=has_trafo,
        started_at=start_time,
        duration_seconds=duration,
        violations_under_voltage=v["under_voltage"],
        violations_over_voltage=v["over_voltage"],
        violations_line_overload=v["line_overload"],
        violations_trafo_overload=v["trafo_overload"],
        created_by=_cu.get("name"),
        violations_total=v["total"],
    )

    return {
        "status": "completed",
        "network_id": network_id,
        "run_id": run_id,
        "day": request.day,
        "mode": mode,
        "started_at": start_time.isoformat(),
        "duration_seconds": round(duration, 2),
        "violations": v,
        "results": {
            "vm_pu":        f"/networks/{network_id}/results/{run_id}/vm-pu",
            "line_loading": f"/networks/{network_id}/results/{run_id}/line-loading",
            "trafo_loading": (
                f"/networks/{network_id}/results/{run_id}/trafo-loading" if has_trafo else None
            ),
        },
    }


@router.post("/networks/{network_id}/run-powerflow")
def run_power_flow(
    network_id: str,
    request: PowerFlowRequest,
    _cu: dict = Depends(get_current_user),
):
    """
    Run a single-timestep balanced power flow on a SimBench or OpenDSS network.
    For SimBench networks the simbench profile is applied at the requested
    date+time (15-min resolution).  For OpenDSS networks the existing pandapower
    model is used at its current (nominal) loading.
    Saves pf_violations.json (always) and pf_plot.html (when plot helpers are
    available) to the results directory, then persists the run in the DB.
    """
    import logging as _log
    _logger = _log.getLogger(__name__)

    run_id     = f"pf_{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    out_dir    = RESULTS_DIR / network_id / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    start_time = datetime.now()

    # Initialise so they are always defined when save_run() is called
    net: object | None = None
    v: dict = {"under_voltage": 0, "over_voltage": 0, "line_overload": 0, "trafo_overload": 0, "total": 0}
    plot_url: str | None = None

    # ── 1. Load network + run power flow ─────────────────────────────────────
    try:
        import pandapower as pp

        if network_id.startswith("opendss-"):
            parts = network_id.split("-")
            if len(parts) != 3 or parts[1] not in NANDO_NETWORK_NAMES:
                raise HTTPException(status_code=400, detail=f"Invalid OpenDSS network id: {network_id}")
            network_num  = parts[1]
            mode         = parts[2]
            network_name = NANDO_NETWORK_NAMES[network_num]
            net_dir  = NANDO_ROOT / "dss_files" / f"net_{network_num}_{network_name}"
            net_xlsx = net_dir / "net_pp.xlsx"
            net_json = net_dir / "net_pp_3ph_ready.json"
            if mode == "unbalanced" and net_json.exists():
                net = pp.from_json(str(net_json))
            elif net_xlsx.exists():
                net = pp.from_excel(str(net_xlsx))
            else:
                raise HTTPException(
                    status_code=400,
                    detail="Converted network not found. Run the conversion pipeline first.",
                )
            # Apply DSS load profiles at the requested date+time (30-min resolution, 0-47).
            # ts_idx 0 = 00:00, 1 = 00:30, 2 = 01:00, … 47 = 23:30
            _t          = request.time.split(":")
            ts_idx      = int(_t[0]) * 2 + int(_t[1]) // 30
            dt_req      = datetime.strptime(request.date, "%Y-%m-%d")
            day_of_year = dt_req.timetuple().tm_yday          # 1-365
            _apply_opendss_profiles_at_step(net, net_dir, ts_idx, day_of_year)
        else:
            # SimBench — apply profiles at the requested date+time timestep
            import simbench as sb
            try:
                net = sb.get_simbench_net(network_id)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Cannot load SimBench network: {exc}")

            profiles = sb.get_absolute_values(net, profiles_instead_of_study_cases=True)
            dt_req   = datetime.strptime(f"{request.date} {request.time}", "%Y-%m-%d %H:%M")
            ts_idx   = (dt_req.timetuple().tm_yday - 1) * 96 + dt_req.hour * 4 + dt_req.minute // 15

            # get_absolute_values() returns {(element_type, param): DataFrame}
            # Each DataFrame has timesteps as rows and element indices as columns.
            for (element_type, param), profile_df in profiles.items():
                if (
                    isinstance(element_type, str)
                    and hasattr(net, element_type)
                    and not net[element_type].empty
                    and ts_idx in profile_df.index
                ):
                    row = profile_df.loc[ts_idx]  # Series: index = element indices
                    for el_idx, value in row.items():
                        if el_idx in net[element_type].index:
                            net[element_type].at[el_idx, param] = value

        # Always run balanced power flow — pf_res_plotly requires balanced results
        pp.runpp(net, numba=False)
        v = _compute_pf_violations(net)

        import json as _json
        (out_dir / "pf_violations.json").write_text(_json.dumps(v), encoding="utf-8")

    except HTTPException:
        raise
    except Exception as exc:
        _logger.exception("Power flow solve failed for network %s run %s", network_id, run_id)
        raise HTTPException(status_code=500, detail=f"Power flow failed: {exc}")

    # ── 2. Generate interactive plot (optional — failures do not abort the run) ─
    if _PLOT_HELPERS_AVAILABLE and net is not None:
        try:
            from pandapower.plotting.plotly import pf_res_plotly
            fig         = pf_res_plotly(net, auto_open=False)
            # Shrink all scatter (bus) markers
            if network_id.startswith("opendss-"):
                for trace in fig.data:
                    if trace.type == "scatter" and hasattr(trace, "marker") and trace.marker:
                        trace.marker.size = 5
                    if trace.type == "scatter" and hasattr(trace, "line") and trace.line:
                        trace.line.width = 1  # default is ~2, try 1–1.5
            plot_height = compute_min_height(fig)
            html        = build_plot_html(fig, run_id, plot_height, modebar_side="right")
            (out_dir / "pf_plot.html").write_text(html, encoding="utf-8")
            plot_url = f"/networks/{network_id}/results/{run_id}/pf-plot"
        except Exception:
            _logger.exception("pf_res_plotly failed for run %s — run saved without plot", run_id)

    # ── 3. Persist the run record ─────────────────────────────────────────────
    duration   = (datetime.now() - start_time).total_seconds()
    dt_parts   = request.date.split("-")
    pf_year, pf_month, pf_day = int(dt_parts[0]), int(dt_parts[1]), int(dt_parts[2])

    save_run(
        run_id=run_id,
        network_id=network_id,
        horizon="power_flow",          # sentinel — no timeseries window
        year=pf_year,
        month=pf_month,
        day=pf_day,
        mode="balanced",
        has_trafo=(net is not None and hasattr(net, "res_trafo") and not net.res_trafo.empty),
        started_at=start_time,
        duration_seconds=duration,
        violations_under_voltage=v["under_voltage"],
        violations_over_voltage=v["over_voltage"],
        violations_line_overload=v["line_overload"],
        violations_trafo_overload=v["trafo_overload"],
        violations_total=v["total"],
        created_by=_cu.get("name"),
    )

    return {
        "run_id":           run_id,
        "network_id":       network_id,
        "started_at":       start_time.isoformat(),
        "duration_seconds": round(duration, 2),
        "violations":       v,
        "plot_url":         plot_url,
    }


@router.get("/networks/{network_id}/results/{run_id}/pf-plot")
def get_pf_plot(network_id: str, run_id: str, _cu: dict = Depends(get_current_user)):
    """Serve the pf_res_plotly HTML for a power-flow run."""
    plot_path = RESULTS_DIR / network_id / run_id / "pf_plot.html"
    if not plot_path.exists():
        raise HTTPException(status_code=404, detail="Power flow plot not found")
    return FileResponse(str(plot_path), media_type="text/html")


@router.get("/networks/{network_id}/results/{run_id}/pf-violations")
def get_pf_violations(network_id: str, run_id: str, _cu: dict = Depends(get_current_user)):
    """Return the violation counts (4 categories + total) for a power-flow run."""
    viol_path = RESULTS_DIR / network_id / run_id / "pf_violations.json"
    if not viol_path.exists():
        raise HTTPException(status_code=404, detail="Violations data not found")
    import json as _json
    return _json.loads(viol_path.read_text(encoding="utf-8"))

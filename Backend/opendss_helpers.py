"""Helper functions for the OpenDSS conversion/simulation pipeline."""
import json
import os
import sys
import subprocess
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

from shared_state import (
    NANDO_ROOT, _RES_NPY, _COM_NPY, PLOTS_DIR, DATA_FILE,
    V_LOWER, V_UPPER, LOAD_LIMIT,
    style_traces, build_plot_html, COLORS, compute_min_height, _PLOT_HELPERS_AVAILABLE,
)


def _apply_opendss_profiles_at_step(net, net_dir: Path, ts_idx: int, day_of_year: int = 0) -> int:
    """
    Parse 09_LoadShapes.dss + 10_Loads.dss from net_dir, add load elements to
    *net*, and set each load's P/Q to its profile value at *ts_idx* (0-based,
    30-min resolution → 0..47 for one day).

    When *day_of_year* > 0 AND profiles/profile_map.json exists, reads the
    correct day's values directly from the .npy arrays — enabling any calendar
    day to be simulated, not just the day the CSVs were generated for.
    Falls back to CSVs (fixed day) if the map is absent.

    Returns the number of load elements created. Returns 0 if the DSS profile
    files are not present (network stays at whatever values net_pp.xlsx has).
    """
    import re
    import numpy as np
    import pandapower as _pp

    loadshapes_path = net_dir / "09_LoadShapes.dss"
    loads_path      = net_dir / "10_Loads.dss"

    if not loadshapes_path.exists() or not loads_path.exists():
        return 0  # DSS files not generated yet — leave nominal loading

    base_dir = str(net_dir)

    # ── 1. Parse load-shape name → CSV path ──────────────────────────────────
    shapes: dict[str, str | None] = {}   # shape_name → absolute CSV path or None
    cur_name: str | None = None

    def _set_csv(name: str, rel: str):
        rel = rel.strip().strip('"').strip("'")
        shapes[name] = os.path.normpath(os.path.join(base_dir, rel))

    with open(loadshapes_path, "r", encoding="utf-8", errors="ignore") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("!"):
                continue
            m = re.match(r"(?i)^new\s+loadshape\.([^\s]+)\s*(.*)", line)
            if m:
                cur_name = m.group(1)
                shapes[cur_name] = None
                mf = re.search(r"(?i)\b(?:file|csvfile)\s*=\s*([^\s)]+)", m.group(2))
                if mf:
                    _set_csv(cur_name, mf.group(1))
            elif cur_name and line.startswith("~"):
                mf = re.search(r"(?i)\b(?:file|csvfile)\s*=\s*([^\s)]+)", line)
                if mf:
                    _set_csv(cur_name, mf.group(1))
                    continue
                mf2 = re.search(r"(?i)mult\s*=\s*\([^)]*(?:file|csvfile)\s*=\s*([^\s)]+)", line)
                if mf2:
                    _set_csv(cur_name, mf2.group(1))

    # ── 2. Choose multiplier source: .npy fast path or CSV fallback ──────────
    map_path = net_dir / "profiles" / "profile_map.json"
    _use_npy = (
        day_of_year > 0
        and map_path.exists()
        and _RES_NPY.exists()
        and _COM_NPY.exists()
    )

    if _use_npy:
        _profile_map = json.loads(map_path.read_text(encoding="utf-8"))
        _res_npy = np.load(str(_RES_NPY))   # (342, 365, 48)
        _com_npy = np.load(str(_COM_NPY))   # (120, 365, 48)
        _day_idx = day_of_year - 1           # 0-indexed

        def _get_mult(shape_name: str | None) -> float:
            if not shape_name or shape_name not in _profile_map:
                return 1.0
            entry = _profile_map[shape_name]
            pidx  = entry["profile_idx"]
            arr   = _res_npy if entry["type"] == "res" else _com_npy
            if pidx >= arr.shape[0] or _day_idx >= arr.shape[1] or ts_idx >= arr.shape[2]:
                return 1.0
            return float(arr[pidx, _day_idx, ts_idx])
    else:
        # CSV fallback — uses whichever day the CSVs were generated for
        _mult_cache: dict[str, "pd.Series"] = {}

        def _get_mult(shape_name: str | None) -> float:  # type: ignore[misc]
            if not shape_name or shape_name not in shapes or not shapes[shape_name]:
                return 1.0
            csv_path = shapes[shape_name]
            if csv_path not in _mult_cache:
                try:
                    _mult_cache[csv_path] = pd.read_csv(csv_path, header=None).iloc[:, 0].astype(float)
                except Exception:
                    _mult_cache[csv_path] = pd.Series(dtype=float)
            series = _mult_cache[csv_path]
            return float(series.iloc[ts_idx]) if ts_idx < len(series) else 1.0

    # ── 2. Parse loads.dss → create elements in net at profile-scaled P/Q ────
    created = 0
    with open(loads_path, "r", encoding="utf-8", errors="ignore") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("!"):
                continue
            if not re.match(r"(?i)^new\s+load\.", line):
                continue
            m = re.match(r"(?i)^new\s+load\.([^\s]+)\s+(.*)$", line)
            if not m:
                continue

            load_name = m.group(1)
            kv: dict[str, str] = {}
            for part in re.split(r"\s+", m.group(2).strip()):
                if "=" in part:
                    k, v = part.split("=", 1)
                    kv[k.strip().lower()] = v.strip()

            bus_raw = kv.get("bus1", "").split(".")[0]   # strip phase suffixes
            if not bus_raw:
                continue
            hits = net.bus.index[net.bus["name"] == bus_raw].tolist()
            if not hits:
                continue
            bus_idx = hits[0]

            p_kw  = float(kv.get("kw", "0"))
            pf    = max(1e-6, min(0.999999, abs(float(kv.get("pf", "0.95")))))
            p_mw  = p_kw / 1000.0
            q_mvar = p_mw * float(np.tan(np.arccos(pf)))

            shape = kv.get("daily") or kv.get("yearly") or kv.get("duty")
            mult  = _get_mult(shape)

            _pp.create_load(
                net, bus=bus_idx,
                p_mw=p_mw * mult,
                q_mvar=q_mvar * mult,
                name=load_name,
                in_service=True,
            )
            created += 1

    return created


def _run_nando_step(script_rel: str, label: str, env: dict):
    """Run a single nando pipeline script as a subprocess. Raises on non-zero exit."""
    script = NANDO_ROOT / script_rel
    if not script.exists():
        raise RuntimeError(f"Pipeline script not found: {script}")
    # Force UTF-8 I/O so scripts with non-ASCII print statements don't fail on
    # Windows terminals that default to cp1252.
    # MPLBACKEND=Agg prevents matplotlib from opening GUI windows during subprocesses.
    utf8_env = {**env, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "MPLBACKEND": "Agg"}
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(NANDO_ROOT),
        env=utf8_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    print(f"\n========== {label} ==========")

    if result.stdout:
        print(result.stdout)

    if result.stderr:
        print(result.stderr)

    print(f"========== END {label} ==========\n")
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "")[-3000:]
        raise RuntimeError(f"Step '{label}' failed:\n{tail}")


def _count_dss_loads(net_dir: Path) -> int:
    """Count load elements in 10_Loads.dss (these are not stored in net_pp.*)."""
    import re as _re
    loads_path = net_dir / "10_Loads.dss"
    if not loads_path.exists():
        return 0
    count = 0
    with open(loads_path, "r", encoding="utf-8", errors="ignore") as _fh:
        for _line in _fh:
            if _re.match(r"(?i)^\s*new\s+load\.", _line):
                count += 1
    return count


def _network_stats_from_pp(net_xlsx: Path, net_json: Path, mode: str, dss_dir: Path | None = None) -> dict:
    """Load the converted pandapower network and return element counts.

    *dss_dir* should be the network's DSS directory (e.g. net_1_Rural_SMR8/).
    When provided the load count is read from 10_Loads.dss, because OpenDSS
    loads are not stored in net_pp.xlsx / net_pp.json.
    """
    import pandapower as pp
    try:
        if mode == "unbalanced" and net_json.exists():
            net = pp.from_json(str(net_json))
        elif net_xlsx.exists():
            net = pp.from_excel(str(net_xlsx))
        else:
            return {}
        loads = _count_dss_loads(dss_dir) if dss_dir is not None else len(net.load)
        return {
            "buses":        len(net.bus),
            "lines":        len(net.line),
            "transformers": len(net.trafo),
            "loads":        loads,
        }
    except Exception:
        return {}


def _generate_opendss_plot(network_id: str, net_xlsx: Path, net_json: Path, mode: str, display_name: str = "") -> tuple[str | None, int]:
    """
    Generate an interactive Plotly topology plot matching the SimBench appearance:
    responsive layout, branded legend, and network name annotation in the top-right.
    Returns (serve_url, height_px). Height is 0 when generation fails.
    Skips regeneration if the HTML + sidecar .height file already exist.
    """
    if not _PLOT_HELPERS_AVAILABLE:
        return None, 0
    plot_filename = f"{network_id}.html"
    plot_path = PLOTS_DIR / plot_filename
    height_path = PLOTS_DIR / f"{network_id}.height"


    try:
        import pandapower as pp
        from pandapower.plotting.plotly import simple_plotly

        if mode == "unbalanced" and net_json.exists():
            net = pp.from_json(str(net_json))
        elif net_xlsx.exists():
            net = pp.from_excel(str(net_xlsx))
        else:
            return None, 0

        # Set network name so simple_plotly can reference it.
        label = display_name or network_id
        net.name = label

        fig = simple_plotly(net, auto_open=False, showlegend=True, respect_switches=False)
        fig = style_traces(fig)

        # Shorten pandapower auto-generated trace names so the legend stays compact
        _name_map = {
            "external grid": "Ext. Grid",
            "bus": "Bus",
            "line": "Line",
            "switch": "Switch",
            "load": "Load",
        }
        for trace in fig.data:
            low = (trace.name or "").lower().strip()
            if low in _name_map:
                trace.name = _name_map[low]

        # Replace pandapower's trafo line traces (invisible for co-located buses)
        # with classified markers at the HV bus position.
        if not net.trafo.empty and not net.bus_geodata.empty:
            # Hide the existing invisible trafo line/edge traces
            for trace in fig.data:
                tname = (trace.name or "").lower()
                if any(k in tname for k in ("trafo", "transformer", "2w", "3w")):
                    trace.visible = False

            ext_grid_buses = set(net.ext_grid["bus"].astype(int).tolist()) if not net.ext_grid.empty else set()
            name_col = "name" if "name" in net.trafo.columns else None

            # Buckets: (xs, ys, texts) per type
            dist, reg, iso = ([], [], []), ([], [], []), ([], [], [])

            for idx, row in net.trafo.iterrows():
                hv = int(row["hv_bus"])
                if hv in ext_grid_buses or hv not in net.bus_geodata.index:
                    continue
                x = net.bus_geodata.at[hv, "x"]
                y = net.bus_geodata.at[hv, "y"]
                tname = (str(net.trafo.at[idx, name_col]) if name_col else str(idx)).lower()
                label = str(net.trafo.at[idx, name_col]) if name_col else str(idx)
                if tname.endswith("_regulator"):
                    reg[0].append(x); reg[1].append(y); reg[2].append(label)
                elif tname.endswith("_iso"):
                    iso[0].append(x); iso[1].append(y); iso[2].append(label)
                else:
                    dist[0].append(x); dist[1].append(y); dist[2].append(label)

            for (xs, ys, texts), name, color, symbol, msize in [
                (dist, "Dist. Trafo",  COLORS["trafo"],     "square",       6),
                (reg,  "Regulator",    COLORS["regulator"], "diamond",      10),
                (iso,  "Iso. Trafo",   COLORS["iso_trafo"], "square-cross", 10),
            ]:
                if xs:
                    full_name = name.replace("Dist. Trafo", "Distribution Transformer").replace("Iso. Trafo", "Isolation Transformer")
                    fig.add_trace(go.Scatter(
                        x=xs, y=ys, mode="markers", name=name,
                        marker=dict(symbol=symbol, color=color, size=msize,
                                    line=dict(color="#ffffff", width=1.5)),
                        text=texts,
                        hovertemplate=f"<b>{full_name} %{{text}}</b><extra></extra>",
                    ))

        # Capacitors — stored in net.shunt (bus, name, q_mvar columns)
        cap_df = net.shunt if (hasattr(net, "shunt") and not net.shunt.empty) else None
        if cap_df is not None and not net.bus_geodata.empty:
            bus_col = "bus" if "bus" in cap_df.columns else None
            name_col_c = "name" if "name" in cap_df.columns else None
            if bus_col:
                cxs, cys, ctexts = [], [], []
                for idx, row in cap_df.iterrows():
                    b = int(row[bus_col])
                    if b not in net.bus_geodata.index:
                        continue
                    cxs.append(net.bus_geodata.at[b, "x"])
                    cys.append(net.bus_geodata.at[b, "y"])
                    ctexts.append(str(row[name_col_c]) if name_col_c else str(idx))
                if cxs:
                    fig.add_trace(go.Scatter(
                        x=cxs, y=cys, mode="markers", name="Capacitor",
                        marker=dict(symbol="circle", color=COLORS["capacitor"], size=8,
                                    line=dict(color="#ffffff", width=1.5)),
                        text=ctexts,
                        hovertemplate="<b>Capacitor %{text}</b><extra></extra>",
                    ))
        plot_height = compute_min_height(fig)

        # Layout: responsive, transparent background, no in-plot title.
        fig.update_layout(
            autosize=True,
            width=None,
            height=None,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor=COLORS["bg_plot"],
            title=None,
            font=dict(
                family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
                color=COLORS["text_muted"], size=12,
            ),
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False, showline=False, fixedrange=False),
            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False, showline=False, fixedrange=False),
            hoverlabel=dict(
                bgcolor="#ffffff", bordercolor=COLORS["border"],
                font=dict(size=12, color=COLORS["text_strong"],
                          family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"),
            ),
            legend=dict(
                bgcolor="rgba(255,255,255,0.97)",
                bordercolor=COLORS["border"],
                borderwidth=1,
                font=dict(
                    size=11,
                    color=COLORS["text_strong"],
                    family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
                ),
                orientation="h",
                x=0.5,
                y=-0.04,
                xanchor="center",
                yanchor="top",
                itemsizing="constant",
                itemclick="toggleothers",
                itemdoubleclick="toggle",
                tracegroupgap=0,
            ),
            margin=dict(l=16, r=16, t=16, b=100),
        )

        html_content = build_plot_html(fig, label, plot_height)

        PLOTS_DIR.mkdir(parents=True, exist_ok=True)
        plot_path.write_text(html_content, encoding="utf-8")
        height_path.write_text(str(plot_height), encoding="utf-8")
        return f"/plots/{plot_filename}", plot_height
    except Exception as exc:
        import logging; logging.getLogger(__name__).warning("Plot generation failed for %s: %s", network_id, exc)
        return None, 0


def _parse_metric_global(path: Path) -> dict:
    """Parse metric_global.txt into a dict. Returns {} if file missing or malformed."""
    if not path.exists():
        return {}
    data = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            try:
                data[key.strip()] = float(val.strip())
            except ValueError:
                data[key.strip()] = val.strip()
    return data


def _safe_float(v) -> float | None:
    """Return a float or None for NaN/missing values."""
    try:
        f = float(v)
        return None if (f != f) else f   # NaN check
    except (TypeError, ValueError):
        return None


def _build_validation(metrics_dir: Path, mode: str) -> dict:
    """
    Build a structured validation dict from the per-element CSV files
    generated by the metrics scripts.

    Returns a dict with keys: bus_voltage, line_loading (unbalanced), trafo_loading (unbalanced).
    Any section whose source files are missing is omitted.
    """
    import pandas as pd

    validation: dict = {}

    # ── Bus voltage ────────────────────────────────────────────────────────────
    if mode == "balanced":
        gm = _parse_metric_global(metrics_dir / "metric_global.txt")
        bus_csv = metrics_dir / "metric_per_bus.csv"
        voltage: dict = {
            "matched":      _safe_float(gm.get("Matched buses")),
            "total_points": _safe_float(gm.get("Total points")),
            "mape":         _safe_float(gm.get("Global MAPE %")),
            "max_error":    _safe_float(gm.get("Global Max  %")),
            "bias":         _safe_float(gm.get("Global Bias %")),
            "by_phase":     {},
            "worst_buses":  [],
        }
        if bus_csv.exists():
            df = pd.read_csv(bus_csv)
            if not df.empty:
                voltage["worst_buses"] = (
                    df.head(10)[["bus_name", "MAPE_%", "Max_%", "MeanSigned_%"]]
                    .rename(columns={"MAPE_%": "mape", "Max_%": "max", "MeanSigned_%": "bias"})
                    .to_dict("records")
                )
    else:
        gm = _parse_metric_global(metrics_dir / "metric_3ph_global.txt")
        bus_csv = metrics_dir / "metric_3ph_per_bus.csv"
        voltage = {
            "matched":      _safe_float(gm.get("Matched (bus, phase) pairs")),
            "total_points": _safe_float(gm.get("Total comparison points")),
            "mape":         _safe_float(gm.get("Global MAPE  %")),
            "max_error":    _safe_float(gm.get("Global Max   %")),
            "bias":         _safe_float(gm.get("Global Bias  %")),
            "by_phase":     {},
            "worst_buses":  [],
        }
        if bus_csv.exists():
            df = pd.read_csv(bus_csv)
            if not df.empty:
                for ph, grp in df.groupby("phase"):
                    voltage["by_phase"][str(ph)] = {
                        "matched": int(len(grp)),
                        "mape":  _safe_float(grp["MAPE_%"].mean()),
                        "max":   _safe_float(grp["Max_%"].max()),
                        "bias":  _safe_float(grp["MeanSigned_%"].mean()),
                    }
                voltage["worst_buses"] = (
                    df.head(10)[["bus_name", "phase", "MAPE_%", "Max_%", "MeanSigned_%"]]
                    .rename(columns={"MAPE_%": "mape", "Max_%": "max", "MeanSigned_%": "bias"})
                    .to_dict("records")
                )

    validation["bus_voltage"] = voltage

    # ── Loading ────────────────────────────────────────────────────────────────
    import re as _re

    def _agg_from_df(df: pd.DataFrame, name_col: str, balanced: bool) -> dict:
        """Build the shared loading agg dict from a (possibly filtered) DataFrame."""
        agg: dict = {
            "matched_elements": int(df[name_col].nunique()),
            "mae":    _safe_float(df["mae"].mean()    if not balanced else df["MAE_pp"].mean()),
            "max_ae": _safe_float(df["max_ae"].max()  if not balanced else df["MaxAbs_pp"].max()),
            "mbe":    _safe_float(df["mbe"].mean()    if not balanced else df["Bias_pp"].mean()),
            "by_phase": {},
            "worst":  [],
        }
        if not balanced:
            for ph, grp in df.groupby("phase"):
                agg["by_phase"][str(ph)] = {
                    "matched": int(len(grp)),
                    "mae":    _safe_float(grp["mae"].mean()),
                    "max_ae": _safe_float(grp["max_ae"].max()),
                    "mbe":    _safe_float(grp["mbe"].mean()),
                }
            worst_rows = (
                df.nlargest(10, "max_ae")[["dss_name", "phase", "mae", "max_ae", "mbe"]]
                .to_dict("records")
            )
            agg["worst"] = [
                {k: (_safe_float(v) if k not in ("dss_name", "phase") else v)
                 for k, v in row.items()}
                for row in worst_rows
            ]
        else:
            worst_rows = df.nlargest(10, "MaxAbs_pp")
            agg["worst"] = [
                {
                    "dss_name": str(r[name_col]),
                    "phase":    "—",
                    "mae":      _safe_float(r["MAE_pp"]),
                    "max_ae":   _safe_float(r["MaxAbs_pp"]),
                    "mbe":      _safe_float(r["Bias_pp"]),
                }
                for _, r in worst_rows.iterrows()
            ]
        return agg

    if mode == "unbalanced":
        # Lines — split MV / LV by _lv suffix in element name (same rule as balanced script)
        line_csv = metrics_dir / "metric_3ph_line_loading_per_element.csv"
        if line_csv.exists():
            df = pd.read_csv(line_csv)
            if not df.empty:
                is_lv = df["dss_name"].str.contains(r"_lv", case=False, regex=True)
                for mask, out_key in [(~is_lv, "mv_line_loading"), (is_lv, "lv_line_loading")]:
                    sub = df[mask]
                    if not sub.empty:
                        validation[out_key] = _agg_from_df(sub, "dss_name", balanced=False)

        # Transformers
        trafo_csv = metrics_dir / "metric_3ph_trafo_loading_per_element.csv"
        if trafo_csv.exists():
            df = pd.read_csv(trafo_csv)
            if not df.empty:
                validation["trafo_loading"] = _agg_from_df(df, "dss_name", balanced=False)

    else:
        # Balanced: read Excel outputs from metrics_all_lines.py and metric_trafo_loading.py
        for xlsx_name, out_key in [
            ("mv_line_loading_metrics.xlsx", "mv_line_loading"),
            ("lv_line_loading_metrics.xlsx", "lv_line_loading"),
        ]:
            xlsx_path = metrics_dir / xlsx_name
            if not xlsx_path.exists():
                continue
            try:
                df = pd.read_excel(xlsx_path, sheet_name="summary", engine="openpyxl")
                df = df[~df["line_name"].astype(str).str.startswith("===")]
                if not df.empty:
                    validation[out_key] = _agg_from_df(df, "line_name", balanced=True)
            except Exception:
                pass

        # Transformers
        trafo_xlsx = metrics_dir / "trafo_loading_compare.xlsx"
        if trafo_xlsx.exists():
            try:
                df = pd.read_excel(trafo_xlsx, sheet_name="summary", engine="openpyxl")
                df = df[~df["trafo_name"].astype(str).str.startswith("===")]
                if not df.empty:
                    worst_trafos = df.nlargest(10, "MaxAbs_pp")
                    validation["trafo_loading"] = {
                        "matched_elements": len(df),
                        "mae":    _safe_float(df["MAE_pp"].mean()),
                        "rmse":   _safe_float(df["RMSE_pp"].mean()),
                        "max_ae": _safe_float(df["MaxAbs_pp"].max()),
                        "mbe":    _safe_float(df["Bias_pp"].mean()),
                        "by_phase": {},
                        "worst": [
                            {
                                "dss_name": str(r["trafo_name"]),
                                "phase":    "—",
                                "mae":      _safe_float(r["MAE_pp"]),
                                "rmse":     _safe_float(r["RMSE_pp"]),
                                "max_ae":   _safe_float(r["MaxAbs_pp"]),
                                "mbe":      _safe_float(r["Bias_pp"]),
                            }
                            for _, r in worst_trafos.iterrows()
                        ],
                    }
            except Exception:
                pass

    return validation


def _upsert_networks_json(record: dict) -> None:
    """Add or replace a network entry in data/networks.json (filesystem fallback)."""
    networks: list = []
    if DATA_FILE.exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            networks = json.load(f)
    networks = [n for n in networks if n.get("id") != record["id"]]
    networks.append(record)
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(networks, f, indent=2, ensure_ascii=False)


def _compute_pf_violations(net) -> dict:
    """Count threshold breaches in a single-timestep pandapower power-flow result."""
    under_v  = int((net.res_bus["vm_pu"] < V_LOWER).sum())
    over_v   = int((net.res_bus["vm_pu"] > V_UPPER).sum())
    line_ol  = int((net.res_line["loading_percent"] > LOAD_LIMIT).sum()) if not net.res_line.empty else 0
    trafo_ol = int((net.res_trafo["loading_percent"] > LOAD_LIMIT).sum()) if not net.res_trafo.empty else 0
    return {
        "under_voltage":  under_v,
        "over_voltage":   over_v,
        "line_overload":  line_ol,
        "trafo_overload": trafo_ol,
        "total": under_v + over_v + line_ol + trafo_ol,
    }

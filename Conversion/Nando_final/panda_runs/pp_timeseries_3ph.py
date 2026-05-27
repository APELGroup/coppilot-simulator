import os
import re
import sys

import numpy as np
import pandas as pd
import pandapower as pp

from pathlib import Path
from pandapower import from_excel
from pandapower.control import ConstControl, DiscreteTapControl
from pandapower.control.basic_controller import Controller
from pandapower.timeseries import OutputWriter, run_timeseries
from pandapower.timeseries.data_sources.frame_data import DFData
from pandapower.pf.runpp_3ph import runpp_3ph

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

from pandapower import from_json as _from_json, to_json as _to_json
_json = Path(str(config.NET_3PH_JSON))
_xlsx = Path(str(config.NET_3PH_XLSX))
if _json.exists() and (_json.stat().st_mtime >= _xlsx.stat().st_mtime if _xlsx.exists() else True):
    print("[CACHE] Loading 3ph pandapower network from JSON cache...")
    net = _from_json(str(_json))
else:
    print("[CACHE] Loading 3ph pandapower network from Excel (will cache as JSON)...")
    net = from_excel(str(_xlsx))
    _to_json(net, str(_json))


def parse_loadshapes_dss(loadshapes_path, base_dir):
    shapes = {}
    cur_name = None

    def set_csv(name, relpath):
        relpath = relpath.strip().strip('"').strip("'")
        csv_path = os.path.normpath(os.path.join(base_dir, relpath))
        shapes[name]["csv"] = csv_path

    with open(loadshapes_path, "r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("!") or line.lower().startswith(("rem", "comment")):
                continue

            m = re.match(r'(?i)^new\s+loadshape\.([^\s]+)\s*(.*)$', line)
            if m:
                cur_name = m.group(1)
                params = m.group(2) or ""

                npts = None
                interval = None
                n = re.search(r'(?i)\bnpts\s*=\s*([0-9]+)', params)
                if n:
                    npts = int(n.group(1))
                iv = re.search(r'(?i)\binterval\s*=\s*([0-9]*\.?[0-9]+)', params)
                if iv:
                    interval = float(iv.group(1))

                shapes[cur_name] = {"csv": None, "npts": npts, "interval": interval}

                mf = re.search(r'(?i)\b(?:file|csvfile)\s*=\s*([^\s\)]+)', params)
                if mf:
                    set_csv(cur_name, mf.group(1))
                continue

            if cur_name and line.startswith("~"):
                mf = re.search(r'(?i)\b(?:file|csvfile)\s*=\s*([^\s\)]+)', line)
                if mf:
                    set_csv(cur_name, mf.group(1))
                    continue

                mf2 = re.search(r'(?i)mult\s*=\s*\([^\)]*(?:file|csvfile)\s*=\s*([^\s\)]+)', line)
                if mf2:
                    set_csv(cur_name, mf2.group(1))
                    continue

    return shapes


def pf_to_q(p_mw, pf):
    pf_abs = max(1e-6, min(0.999999, abs(float(pf))))
    phi = np.arccos(pf_abs)
    q_mvar = p_mw * np.tan(phi)
    return q_mvar


def find_bus_index_by_name(net, bus_name):
    hits = net.bus.index[net.bus["name"] == bus_name].tolist()
    return hits[0] if hits else None


def parse_kv_pairs(s: str):
    out = {}
    parts = re.split(r'\s+', s.strip())
    for p in parts:
        if "=" in p:
            k, v = p.split("=", 1)
            out[k.strip().lower()] = v.strip()
    return out


def parse_bus_and_phases(bus1_value: str):
    raw = bus1_value.strip()
    parts = raw.split(".")
    bus_name = parts[0]

    phases = []
    for p in parts[1:]:
        if p in ("1", "2", "3"):
            phases.append(int(p))

    # Δεν κάνουμε default εδώ.
    # Το τι θα γίνει αν λείπουν suffixes θα το αποφασίσουμε
    # μέσα στην add_asymmetric_loads_from_dss() με βάση το phases=
    return bus_name, phases


def add_asymmetric_loads_from_dss(net, loads_path, loadshapes_map):
    created = []

    with open(loads_path, "r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("!") or line.lower().startswith("rem"):
                continue
            if not re.match(r'(?i)^new\s+load\.', line):
                continue

            m = re.match(r'(?i)^new\s+load\.([^\s]+)\s+(.*)$', line)
            if not m:
                continue

            load_name = m.group(1)
            params = parse_kv_pairs(m.group(2))

            bus1 = params.get("bus1", "")
            if not bus1:
                print(f"[WARN] Load {load_name}: λείπει το bus1")
                continue

            bus_name, phases = parse_bus_and_phases(bus1)

            phases_declared = int(float(params.get("phases", "1")))
            conn = (params.get("conn", "wye") or "wye").lower()

            p_kw = float(params.get("kw", "0"))
            pf = float(params.get("pf", "0.95"))
            shape_name = params.get("daily") or params.get("yearly") or params.get("duty")

            # Αν δεν βρέθηκαν phase suffixes στο bus1,
            # αποφασίζουμε με βάση το phases=
            if not phases:
                if phases_declared == 3:
                    phases = [1, 2, 3]
                    print(f"[WARN] Load {load_name}: δεν έχει phase suffixes στο bus1={bus1}, θεωρήθηκε 3φ από phases=3")
                elif phases_declared == 2:
                    print(f"[WARN] Load {load_name}: phases=2 αλλά δεν υπάρχουν suffixes στο bus1={bus1} -> skip")
                    continue
                elif phases_declared == 1:
                    print(f"[WARN] Load {load_name}: phases=1 αλλά δεν υπάρχει suffix στο bus1={bus1} -> skip")
                    continue
                else:
                    print(f"[WARN] Load {load_name}: άγνωστο phases={phases_declared} στο bus1={bus1} -> skip")
                    continue

            # consistency check
            if len(phases) != phases_declared:
                print(
                    f"[WARN] Load {load_name}: phases={phases_declared} αλλά bus1={bus1} "
                    f"-> parsed phases={phases}"
                )

            bus_idx = find_bus_index_by_name(net, bus_name)
            if bus_idx is None:
                print(f"[WARN] Δεν βρέθηκε bus στο net για load {load_name}: bus={bus_name}")
                continue

            p_mw = p_kw / 1000.0
            q_mvar = pf_to_q(p_mw, pf)

            p_a = p_b = p_c = 0.0
            q_a = q_b = q_c = 0.0

            if set(phases) == {1, 2, 3} and len(phases) == 3:
                p_a = p_b = p_c = p_mw / 3.0
                q_a = q_b = q_c = q_mvar / 3.0
            else:
                nph = len(phases)
                if nph == 0:
                    print(f"[WARN] Load {load_name}: δεν προέκυψε καμία φάση -> skip")
                    continue

                p_each = p_mw / nph
                q_each = q_mvar / nph

                for ph in phases:
                    if ph == 1:
                        p_a += p_each
                        q_a += q_each
                    elif ph == 2:
                        p_b += p_each
                        q_b += q_each
                    elif ph == 3:
                        p_c += p_each
                        q_c += q_each

            lidx = pp.create_asymmetric_load(
                net,
                bus=bus_idx,
                p_a_mw=p_a, p_b_mw=p_b, p_c_mw=p_c,
                q_a_mvar=q_a, q_b_mvar=q_b, q_c_mvar=q_c,
                name=load_name,
                type="delta" if conn == "delta" else "wye",
                in_service=True
            )

            created.append({
                "load_idx": lidx,
                "load_name": load_name,
                "bus1_raw": bus1,
                "bus_name": bus_name,
                "phases_declared": phases_declared,
                "phases": ".".join(map(str, phases)),
                "conn": conn,
                "p_a_base_mw": p_a,
                "p_b_base_mw": p_b,
                "p_c_base_mw": p_c,
                "q_a_base_mvar": q_a,
                "q_b_base_mvar": q_b,
                "q_c_base_mvar": q_c,
                "shape_name": shape_name
            })

    df = pd.DataFrame(created)
    if not df.empty:
        ok = df["shape_name"].isin(loadshapes_map.keys()).sum()
        print(f"[INFO] Δημιουργήθηκαν asymmetric loads: {len(df)} | με γνωστό shape: {ok}")

    return df


def read_multiplier_csv(csv_path):
    s = pd.read_csv(csv_path, header=None).iloc[:, 0].astype(float)
    return s


def build_phase_profiles_for_asymmetric_loads(df_loads, loadshapes_map, expected_npts=48):
    mult_cache = {}
    npts = expected_npts

    p_a_cols, p_b_cols, p_c_cols = {}, {}, {}
    q_a_cols, q_b_cols, q_c_cols = {}, {}, {}

    for row in df_loads.itertuples(index=False):
        lidx = row.load_idx
        shape = row.shape_name

        if shape not in loadshapes_map or not loadshapes_map[shape]["csv"]:
            mult = pd.Series([1.0] * npts)
        else:
            if shape not in mult_cache:
                csv_path = loadshapes_map[shape]["csv"]
                mult_cache[shape] = read_multiplier_csv(csv_path)
            mult = mult_cache[shape]

        if len(mult) != npts:
            mult = mult.reset_index(drop=True)
            if len(mult) > npts:
                mult = mult.iloc[:npts]
            else:
                mult = mult.reindex(range(npts), fill_value=mult.iloc[-1])

        p_a_cols[lidx] = row.p_a_base_mw * mult.values
        p_b_cols[lidx] = row.p_b_base_mw * mult.values
        p_c_cols[lidx] = row.p_c_base_mw * mult.values

        q_a_cols[lidx] = row.q_a_base_mvar * mult.values
        q_b_cols[lidx] = row.q_b_base_mvar * mult.values
        q_c_cols[lidx] = row.q_c_base_mvar * mult.values

    p_a_df = pd.DataFrame(p_a_cols); p_a_df.index.name = "time_step"
    p_b_df = pd.DataFrame(p_b_cols); p_b_df.index.name = "time_step"
    p_c_df = pd.DataFrame(p_c_cols); p_c_df.index.name = "time_step"

    q_a_df = pd.DataFrame(q_a_cols); q_a_df.index.name = "time_step"
    q_b_df = pd.DataFrame(q_b_cols); q_b_df.index.name = "time_step"
    q_c_df = pd.DataFrame(q_c_cols); q_c_df.index.name = "time_step"

    return p_a_df, p_b_df, p_c_df, q_a_df, q_b_df, q_c_df


def add_regulator_controllers_pp21411(
    net,
    name_contains="REGULATOR",
    vm_set_pu=1.02,
    band=0.01,
    side="lv",
    in_service_only=True
):
    vm_lower = vm_set_pu - band
    vm_upper = vm_set_pu + band

    created, skipped = 0, 0

    for tid, row in net.trafo.iterrows():
        name = str(row.get("name", ""))

        if name_contains.lower() not in name.lower():
            continue
        if in_service_only and not bool(row.get("in_service", True)):
            continue

        tap_min = row.get("tap_min", np.nan)
        tap_max = row.get("tap_max", np.nan)
        if not np.isfinite(tap_min) or not np.isfinite(tap_max) or tap_min == tap_max:
            skipped += 1
            continue

        if "tap_side" in net.trafo.columns:
            ts = row.get("tap_side", None)
            if ts is None or str(ts).strip() == "":
                net.trafo.at[tid, "tap_side"] = side

        if "tap_neutral" in net.trafo.columns:
            tn = row.get("tap_neutral", np.nan)
            if not np.isfinite(tn):
                net.trafo.at[tid, "tap_neutral"] = 0

        if "tap_pos" in net.trafo.columns:
            tp = row.get("tap_pos", np.nan)
            if not np.isfinite(tp):
                net.trafo.at[tid, "tap_pos"] = net.trafo.at[tid, "tap_neutral"]

        if "tap_step_percent" in net.trafo.columns:
            tsp = row.get("tap_step_percent", np.nan)
            if (not np.isfinite(tsp)) or float(tsp) == 0.0:
                net.trafo.at[tid, "tap_step_percent"] = 1.25

        DiscreteTapControl(
            net,
            tid=tid,
            vm_lower_pu=vm_lower,
            vm_upper_pu=vm_upper,
            side=side
        )
        created += 1

    print(f"[INFO] Controllers created: {created} | skipped(no tap range): {skipped}")


class DiscreteShuntVoltVarController(Controller):
    def __init__(self, net, sid, vm_on_pu=0.99, vm_off_pu=1.01, order=0, level=0, in_service=True):
        super().__init__(net, order=order, level=level, in_service=in_service)
        self.sid = int(sid)
        self.vm_on_pu = float(vm_on_pu)
        self.vm_off_pu = float(vm_off_pu)

        if self.vm_on_pu >= self.vm_off_pu:
            raise ValueError("vm_on_pu must be < vm_off_pu (hysteresis).")

        self.bus = int(net.shunt.at[self.sid, "bus"])
        self.q_nom = float(net.shunt.at[self.sid, "q_mvar"])
        self.on = True

    def initialize_control(self, net):
        self.on = bool(net.shunt.at[self.sid, "in_service"])
        self.q_nom = float(net.shunt.at[self.sid, "q_mvar"])

    def is_converged(self, net):
        vm = float(net.res_bus.at[self.bus, "vm_pu"])
        if self.on:
            return not (vm > self.vm_off_pu)
        else:
            return not (vm < self.vm_on_pu)

    def control_step(self, net):
        vm = float(net.res_bus.at[self.bus, "vm_pu"])

        if self.on and vm > self.vm_off_pu:
            net.shunt.at[self.sid, "in_service"] = False
            self.on = False

        elif (not self.on) and vm < self.vm_on_pu:
            net.shunt.at[self.sid, "in_service"] = True
            net.shunt.at[self.sid, "q_mvar"] = self.q_nom
            self.on = True


def add_cap_time_schedule_by_name(
    net,
    time_steps,
    name_prefix="mv_f0_l",
    resolution_min=30,
    on_time="10:00",
    off_time="23:00",
    include_23=False,
):
    def hhmm_to_step(hhmm: str) -> int:
        h, m = map(int, hhmm.split(":"))
        minutes = h * 60 + m
        if minutes % resolution_min != 0:
            raise ValueError(f"{hhmm} not aligned to {resolution_min}min")
        return minutes // resolution_min

    n = len(time_steps)
    on_s = hhmm_to_step(on_time)
    off_s = hhmm_to_step(off_time)

    sched = np.zeros(n, dtype=bool)
    end = min(off_s + (1 if include_23 else 0), n)
    sched[on_s:end] = True

    prof = pd.DataFrame(index=time_steps)
    created = 0

    for sid, row in net.shunt.iterrows():
        name = str(row.get("name", ""))
        if not name.lower().startswith(name_prefix.lower()):
            continue

        col = f"cap_in_service_{sid}"
        prof[col] = sched

        ConstControl(
            net,
            element="shunt",
            element_index=sid,
            variable="in_service",
            data_source=DFData(prof),
            profile_name=col
        )
        created += 1

    print(f"[INFO] Capacitor schedule controllers created: {created}")
    return prof


def attach_3ph_timeseries_controls(net, p_a_df, p_b_df, p_c_df, q_a_df, q_b_df, q_c_df):
    load_indices = list(p_a_df.columns)

    ConstControl(
        net, element="asymmetric_load", variable="p_a_mw",
        element_index=load_indices, data_source=DFData(p_a_df), profile_name=load_indices
    )
    ConstControl(
        net, element="asymmetric_load", variable="p_b_mw",
        element_index=load_indices, data_source=DFData(p_b_df), profile_name=load_indices
    )
    ConstControl(
        net, element="asymmetric_load", variable="p_c_mw",
        element_index=load_indices, data_source=DFData(p_c_df), profile_name=load_indices
    )

    ConstControl(
        net, element="asymmetric_load", variable="q_a_mvar",
        element_index=load_indices, data_source=DFData(q_a_df), profile_name=load_indices
    )
    ConstControl(
        net, element="asymmetric_load", variable="q_b_mvar",
        element_index=load_indices, data_source=DFData(q_b_df), profile_name=load_indices
    )
    ConstControl(
        net, element="asymmetric_load", variable="q_c_mvar",
        element_index=load_indices, data_source=DFData(q_c_df), profile_name=load_indices
    )


def runpp_3ph_wrapper(net, **kwargs):
    return runpp_3ph(net)


import os
import pandas as pd
from tqdm import tqdm

def run_ts_3ph_manual(net, npts=48, out_dir=None):
    if out_dir is None:
        out_dir = str(config.RESULTS_DIR)
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(os.path.join(out_dir, "res_bus_3ph"), exist_ok=True)
    os.makedirs(os.path.join(out_dir, "res_line_3ph"), exist_ok=True)
    os.makedirs(os.path.join(out_dir, "res_trafo_3ph"), exist_ok=True)

    # controllers ordered by level / order
    ctrl_df = net.controller.copy()
    ctrl_df = ctrl_df.sort_values(["level", "order"])

    bus_vm_a = {}
    bus_vm_b = {}
    bus_vm_c = {}

    line_loading_a = {}
    line_loading_b = {}
    line_loading_c = {}

    trafo_loading_a = {}
    trafo_loading_b = {}
    trafo_loading_c = {}

    for t in tqdm(range(npts)):
        # εφαρμόζουμε όλους τους ConstControls χειροκίνητα
        for _, row in ctrl_df.iterrows():
            ctrl = row["object"]
            if hasattr(ctrl, "time_step"):
                ctrl.time_step(net, t)

        # 3-phase power flow
        runpp_3ph(net)

        # -------- buses --------
        if hasattr(net, "res_bus_3ph") and not net.res_bus_3ph.empty:
            bus_vm_a[t] = net.res_bus_3ph["vm_a_pu"].copy()
            bus_vm_b[t] = net.res_bus_3ph["vm_b_pu"].copy()
            bus_vm_c[t] = net.res_bus_3ph["vm_c_pu"].copy()

        # -------- lines --------
        if hasattr(net, "res_line_3ph") and not net.res_line_3ph.empty:
            line_loading_a[t] = net.res_line_3ph["loading_a_percent"].copy()
            line_loading_b[t] = net.res_line_3ph["loading_b_percent"].copy()
            line_loading_c[t] = net.res_line_3ph["loading_c_percent"].copy()

        # -------- trafos --------
        if hasattr(net, "res_trafo_3ph") and not net.res_trafo_3ph.empty:
            trafo_loading_a[t] = net.res_trafo_3ph["loading_a_percent"].copy()
            trafo_loading_b[t] = net.res_trafo_3ph["loading_b_percent"].copy()
            trafo_loading_c[t] = net.res_trafo_3ph["loading_c_percent"].copy()

    # -------- save helper --------
    def save_ts_dict(ts_dict, filepath):
        if not ts_dict:
            print(f"[WARN] No data for {filepath}")
            return
        df = pd.DataFrame(ts_dict).T
        df.index.name = "time_step"
        df.to_csv(filepath, sep=";")

    # -------- export csv --------
    save_ts_dict(bus_vm_a, os.path.join(out_dir, "res_bus_3ph", "vm_a_pu.csv"))
    save_ts_dict(bus_vm_b, os.path.join(out_dir, "res_bus_3ph", "vm_b_pu.csv"))
    save_ts_dict(bus_vm_c, os.path.join(out_dir, "res_bus_3ph", "vm_c_pu.csv"))

    save_ts_dict(line_loading_a, os.path.join(out_dir, "res_line_3ph", "loading_a_percent.csv"))
    save_ts_dict(line_loading_b, os.path.join(out_dir, "res_line_3ph", "loading_b_percent.csv"))
    save_ts_dict(line_loading_c, os.path.join(out_dir, "res_line_3ph", "loading_c_percent.csv"))

    save_ts_dict(trafo_loading_a, os.path.join(out_dir, "res_trafo_3ph", "loading_a_percent.csv"))
    save_ts_dict(trafo_loading_b, os.path.join(out_dir, "res_trafo_3ph", "loading_b_percent.csv"))
    save_ts_dict(trafo_loading_c, os.path.join(out_dir, "res_trafo_3ph", "loading_c_percent.csv"))

    print("[OK] 3ph timeseries completed.")

# --- paths ---
base_dir        = str(config.LOADSHAPES_BASE_DIR)
loadshapes_path = str(config.LOADSHAPES_DSS)
loads_path      = str(config.LOADS_DSS)

# --- parse shapes ---
shapes = parse_loadshapes_dss(loadshapes_path, base_dir)

# --- clear old loads ---
if len(net.load):
    net.load.drop(net.load.index, inplace=True)

if hasattr(net, "asymmetric_load") and len(net.asymmetric_load):
    net.asymmetric_load.drop(net.asymmetric_load.index, inplace=True)

# --- create asymmetric loads ---
df_loads = add_asymmetric_loads_from_dss(net, loads_path, shapes)

SCALE_LOADS = 1.0

import os as _os
_npts = int(_os.environ.get("NANDO_VALIDATION_STEPS", "48"))

# --- build phase profiles ---
p_a_df, p_b_df, p_c_df, q_a_df, q_b_df, q_c_df = build_phase_profiles_for_asymmetric_loads(
    df_loads, shapes, expected_npts=_npts
)

for df in [p_a_df, p_b_df, p_c_df, q_a_df, q_b_df, q_c_df]:
    df *= SCALE_LOADS

# --- attach controls ---
attach_3ph_timeseries_controls(net, p_a_df, p_b_df, p_c_df, q_a_df, q_b_df, q_c_df)

# --- regulators ---
add_regulator_controllers_pp21411(
    net,
    name_contains="REGULATOR",
    vm_set_pu=1.04,
    band=0.01,
    side="lv"
)

# --- capacitor schedule ---
time_steps = list(range(_npts))  # configurable via NANDO_VALIDATION_STEPS
prof_caps = add_cap_time_schedule_by_name(
    net,
    time_steps=time_steps,
    name_prefix="mv_f0_l",
    on_time="10:00",
    off_time="23:00",
    include_23=False
)


run_ts_3ph_manual(
   net,
    npts=_npts,
    out_dir=str(config.RESULTS_DIR)
)

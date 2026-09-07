import pandapower as pp
import sys
from pandapower import from_excel, to_excel
from pandapower.plotting import pf_res_plotly
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

from pandapower import from_json as _from_json, to_json as _to_json
_xlsx = Path(str(config.NET_PP_XLSX))
_json = _xlsx.with_suffix(".json")
if _json.exists() and _json.stat().st_mtime >= _xlsx.stat().st_mtime:
    print("[CACHE] Loading pandapower network from JSON cache...")
    net = _from_json(str(_json))
else:
    print("[CACHE] Loading pandapower network from Excel (will cache as JSON)...")
    net = from_excel(str(_xlsx))
    _to_json(net, str(_json))

import pandapower as pp
from pandapower import from_excel
from pandapower.plotting import pf_res_plotly



import re
import os

import re, os

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

            # New Loadshape.NAME ...
            m = re.match(r'(?i)^new\s+loadshape\.([^\s]+)\s*(.*)$', line)
            if m:
                cur_name = m.group(1)
                params = m.group(2) or ""

                npts = None
                interval = None
                n = re.search(r'(?i)\bnpts\s*=\s*([0-9]+)', params)
                if n: npts = int(n.group(1))
                iv = re.search(r'(?i)\binterval\s*=\s*([0-9]*\.?[0-9]+)', params)
                if iv: interval = float(iv.group(1))

                shapes[cur_name] = {"csv": None, "npts": npts, "interval": interval}

                # Μερικές φορές το csv path μπορεί να είναι ήδη στην ίδια γραμμή
                mf = re.search(r'(?i)\b(?:file|csvfile)\s*=\s*([^\s\)]+)', params)
                if mf:
                    set_csv(cur_name, mf.group(1))
                continue

            # continuation γραμμή ~ ...
            if cur_name and line.startswith("~"):
                # Πιάνει file=... ή csvfile=...
                mf = re.search(r'(?i)\b(?:file|csvfile)\s*=\s*([^\s\)]+)', line)
                if mf:
                    set_csv(cur_name, mf.group(1))
                    continue

                # Πιάνει mult=(... file=... ) ακόμη κι αν έχει extra chars
                mf2 = re.search(r'(?i)mult\s*=\s*\([^\)]*(?:file|csvfile)\s*=\s*([^\s\)]+)', line)
                if mf2:
                    set_csv(cur_name, mf2.group(1))
                    continue

    return shapes
import pandas as pd
import numpy as np

def pf_to_q(p_mw, pf):
    # pf μπορεί να είναι αρνητικό/lead/lag σε κάποια formats. Εδώ παίρνουμε |pf| για μέτρο.
    pf_abs = max(1e-6, min(0.999999, abs(float(pf))))
    phi = np.arccos(pf_abs)
    q_mvar = p_mw * np.tan(phi)
    return q_mvar

def find_bus_index_by_name(net, bus_name):
    hits = net.bus.index[net.bus["name"] == bus_name].tolist()
    return hits[0] if hits else None

def parse_kv_pairs(s: str):
    # απλό kv parser (key=value) με split στα κενά
    out = {}
    parts = re.split(r'\s+', s.strip())
    for p in parts:
        if "=" in p:
            k, v = p.split("=", 1)
            out[k.strip().lower()] = v.strip()
    return out

def clean_bus1(bus1_value: str):
    # bus1=lv_f0_n123.1.2.3 -> κρατάμε μόνο το "lv_f0_n123"
    b = bus1_value.strip()
    b = b.split(".")[0]
    return b

def add_loads_from_dss(net, loads_path, loadshapes_map):
    """
    Δημιουργεί loads στο net και επιστρέφει DataFrame mapping:
    load_idx, load_name, bus_name, p_base_mw, q_base_mvar, shape_name
    """
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
                continue
            bus_name = clean_bus1(bus1)

            p_kw = float(params.get("kw", "0"))
            pf = float(params.get("pf", "0.95"))
            shape_name = params.get("daily") or params.get("yearly") or params.get("duty")  # συνήθως daily

            bus_idx = find_bus_index_by_name(net, bus_name)
            if bus_idx is None:
                # αν δεν βρεθεί bus, το κρατάμε για log αλλά δεν το φτιάχνουμε
                print(f"[WARN] Δεν βρέθηκε bus στο net για load {load_name}: bus={bus_name}")
                continue

            p_mw = p_kw / 1000.0
            q_mvar = pf_to_q(p_mw, pf)

            lidx = pp.create_load(
                net,
                bus=bus_idx,
                p_mw=p_mw,
                q_mvar=q_mvar,
                name=load_name,
                in_service=True
            )

            created.append({
                "load_idx": lidx,
                "load_name": load_name,
                "bus_name": bus_name,
                "p_base_mw": p_mw,
                "q_base_mvar": q_mvar,
                "shape_name": shape_name
            })

    df = pd.DataFrame(created)
    # προαιρετικά: πόσα loads έχουν shape που υπάρχει όντως στο map
    if not df.empty:
        ok = df["shape_name"].isin(loadshapes_map.keys()).sum()
        print(f"[INFO] Δημιουργήθηκαν loads: {len(df)} | με γνωστό shape: {ok}")
    return df
def read_multiplier_csv(csv_path):
    # περιμένουμε 1 στήλη, 48 γραμμές
    s = pd.read_csv(csv_path, header=None).iloc[:, 0].astype(float)
    return s

def build_pq_profiles_for_loads(df_loads, loadshapes_map, expected_npts=48):
    """
    Επιστρέφει:
      p_df: index=time_step, columns=load_idx (τιμές p_mw)
      q_df: index=time_step, columns=load_idx (τιμές q_mvar)
    """
    # cache multipliers ανά shape
    mult_cache = {}

    # βρες κοινό μήκος (συνήθως 48)
    npts = expected_npts

    p_cols = {}
    q_cols = {}

    for row in df_loads.itertuples(index=False):
        lidx = row.load_idx
        shape = row.shape_name

        if shape not in loadshapes_map or not loadshapes_map[shape]["csv"]:
            # αν δεν έχει shape, κρατάμε σταθερό (mult=1)
            mult = pd.Series([1.0]*npts)
        else:
            if shape not in mult_cache:
                csv_path = loadshapes_map[shape]["csv"]
                mult_cache[shape] = read_multiplier_csv(csv_path)
            mult = mult_cache[shape]

        # ασφάλεια μήκους
        if len(mult) != npts:
            mult = mult.reset_index(drop=True)
            if len(mult) > npts:
                mult = mult.iloc[:npts]
            else:
                mult = mult.reindex(range(npts), fill_value=mult.iloc[-1])

        p_cols[lidx] = row.p_base_mw * mult.values
        q_cols[lidx] = row.q_base_mvar * mult.values

    p_df = pd.DataFrame(p_cols)
    q_df = pd.DataFrame(q_cols)
    p_df.index.name = "time_step"
    q_df.index.name = "time_step"
    return p_df, q_df
from pandapower.control import ConstControl
from pandapower.timeseries import DFData, run_timeseries
from pandapower.timeseries.output_writer import OutputWriter

def attach_timeseries_controls(net, p_df, q_df):
    p_ds = DFData(p_df)
    q_ds = DFData(q_df)

    load_indices = list(p_df.columns)

    # p_mw control
    ConstControl(
        net, element="load", variable="p_mw",
        element_index=load_indices,
        data_source=p_ds, profile_name=load_indices
    )

    # q_mvar control
    ConstControl(
        net, element="load", variable="q_mvar",
        element_index=load_indices,
        data_source=q_ds, profile_name=load_indices
    )
import numpy as np
from pandapower.control import DiscreteTapControl

def add_regulator_controllers_pp21411(
    net,
    name_contains="REGULATOR",
    vm_set_pu=1.02,
    band=0.01,        # +/- band γύρω από vm_set
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

        # πρέπει να υπάρχει tap range
        tap_min = row.get("tap_min", np.nan)
        tap_max = row.get("tap_max", np.nan)
        if not np.isfinite(tap_min) or not np.isfinite(tap_max) or tap_min == tap_max:
            skipped += 1
            continue

        # αν tap_side κενό, βάλε
        if "tap_side" in net.trafo.columns:
            ts = row.get("tap_side", None)
            if ts is None or str(ts).strip() == "":
                net.trafo.at[tid, "tap_side"] = side

        # αν tap_neutral NaN, βάλε 0
        if "tap_neutral" in net.trafo.columns:
            tn = row.get("tap_neutral", np.nan)
            if not np.isfinite(tn):
                net.trafo.at[tid, "tap_neutral"] = 0

        # αν tap_pos NaN, βάλε neutral
        if "tap_pos" in net.trafo.columns:
            tp = row.get("tap_pos", np.nan)
            if not np.isfinite(tp):
                net.trafo.at[tid, "tap_pos"] = net.trafo.at[tid, "tap_neutral"]

        # αν tap_step_percent λείπει/0, βάλε default
        if "tap_step_percent" in net.trafo.columns:
            tsp = row.get("tap_step_percent", np.nan)
            if (not np.isfinite(tsp)) or float(tsp) == 0.0:
                net.trafo.at[tid, "tap_step_percent"] = 1.25

        # ✅ DiscreteTapControl (PP 2.14.11 compatible)
        DiscreteTapControl(
            net,
            tid=tid,
            vm_lower_pu=vm_lower,
            vm_upper_pu=vm_upper,
            side=side
        )
        created += 1

    print(f"[INFO] Controllers created: {created} | skipped(no tap range): {skipped}")
import numpy as np
from pandapower.control.basic_controller import Controller

class DiscreteShuntVoltVarController(Controller):
    """
    Simple ON/OFF capacitor switching based on local bus voltage.
    - Turns ON if vm_pu < vm_on_pu
    - Turns OFF if vm_pu > vm_off_pu
    Uses hysteresis (vm_on_pu < vm_off_pu) to avoid chattering.
    """

    def __init__(self, net, sid, vm_on_pu=0.99, vm_off_pu=1.01, order=0, level=0, in_service=True):
        super().__init__(net, order=order, level=level, in_service=in_service)
        self.sid = int(sid)
        self.vm_on_pu = float(vm_on_pu)
        self.vm_off_pu = float(vm_off_pu)

        # basic validation
        if self.vm_on_pu >= self.vm_off_pu:
            raise ValueError("vm_on_pu must be < vm_off_pu (hysteresis).")

        # cache bus index
        self.bus = int(net.shunt.at[self.sid, "bus"])

        # remember original q_mvar (positive for capacitor in pandapower is typically +q injection)
        self.q_nom = float(net.shunt.at[self.sid, "q_mvar"])

        # internal state (True=ON)
        self.on = True

    def initialize_control(self, net):
        # determine initial state from current shunt q
        self.on = bool(net.shunt.at[self.sid, "in_service"])
        # keep original q as nominal
        self.q_nom = float(net.shunt.at[self.sid, "q_mvar"])

    def is_converged(self, net):
        # We decide action each iteration; convergence means "no change needed"
        vm = float(net.res_bus.at[self.bus, "vm_pu"])
        if self.on:
            # if ON, we would switch OFF only if vm > vm_off
            return not (vm > self.vm_off_pu)
        else:
            # if OFF, we would switch ON only if vm < vm_on
            return not (vm < self.vm_on_pu)

    def control_step(self, net):
        vm = float(net.res_bus.at[self.bus, "vm_pu"])

        if self.on and vm > self.vm_off_pu:
            # switch OFF
            net.shunt.at[self.sid, "in_service"] = False
            self.on = False

        elif (not self.on) and vm < self.vm_on_pu:
            # switch ON
            net.shunt.at[self.sid, "in_service"] = True
            # ensure nominal q restored
            net.shunt.at[self.sid, "q_mvar"] = self.q_nom
            self.on = True
import numpy as np
import pandas as pd
from pandapower.control import ConstControl
from pandapower.timeseries.data_sources.frame_data import DFData


def add_cap_time_schedule_by_name(
    net,
    time_steps,
    name_prefix="mv_f0_l",
    resolution_min=30,
    on_time="10:00",
    off_time="23:00",
    include_23=False,  # False => OFF από 23:00 και μετά
):
    def hhmm_to_step(hhmm: str) -> int:
        h, m = map(int, hhmm.split(":"))
        minutes = h*60 + m
        if minutes % resolution_min != 0:
            raise ValueError(f"{hhmm} not aligned to {resolution_min}min")
        return minutes // resolution_min

    n = len(time_steps)
    on_s  = hhmm_to_step(on_time)   # 10:00 -> 20
    off_s = hhmm_to_step(off_time)  # 23:00 -> 46

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




def run_ts(net, npts=48, out_dir="ts_results"):
    ow = OutputWriter(net, time_steps=range(npts), output_path=out_dir, output_file_type=".csv")
    ow.log_variable("res_bus", "vm_pu")
    ow.log_variable("res_line", "loading_percent")
    ow.log_variable("res_trafo", "loading_percent")
    ow.log_variable("res_load", "p_mw")
    ow.log_variable("shunt", "in_service")
    run_timeseries(net, time_steps=range(npts))
# --- paths ---
base_dir        = str(config.LOADSHAPES_BASE_DIR)
loadshapes_path = str(config.LOADSHAPES_DSS)
loads_path      = str(config.LOADS_DSS)
'''
net.line.loc[net.line.std_type == "lc_247-3ph", "max_i_ka"] = 0.60  # ή 0.30
net.std_types["line"]["lc_248-3ph"]["max_i_ka"] = 0.60
net.line.loc[net.line.std_type == "lc_248-3ph", "max_i_ka"] = 0.60  # ή 0.30
net.std_types["line"]["lc_248-3ph"]["max_i_ka"] = 0.60
'''
# --- parse shapes ---
shapes = parse_loadshapes_dss(loadshapes_path, base_dir)

# --- create loads in net ---
df_loads = add_loads_from_dss(net, loads_path, shapes)
SCALE_LOADS = 1
# --- build profiles (P,Q) ---
p_df, q_df = build_pq_profiles_for_loads(df_loads, shapes, expected_npts=48)
p_df *= SCALE_LOADS
q_df *= SCALE_LOADS
# --- attach controls ---
attach_timeseries_controls(net, p_df, q_df)


add_regulator_controllers_pp21411(
    net,
    name_contains="REGULATOR",
    vm_set_pu=1.04,
    band=0.01,
    side="lv"
)

import os as _os
_npts = int(_os.environ.get("NANDO_VALIDATION_STEPS", "48"))
time_steps = list(range(_npts))  # 30min; configurable via NANDO_VALIDATION_STEPS

prof_caps = add_cap_time_schedule_by_name(
    net,
    time_steps=time_steps,
    name_prefix="mv_f0_l",
    on_time="10:00",
    off_time="23:00",
    include_23=False
)
from pandapower.plotting import simple_plotly


# --- run timeseries ---
run_ts(net, npts=_npts, out_dir=str(config.RESULTS_DIR))



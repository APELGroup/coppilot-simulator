
import sys
import math
import re
from pathlib import Path

import pandapower as pp
from pandapower.pf.runpp_3ph import runpp_3ph

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

# =========================
# PATHS  (from config.py)
# =========================
BASE          = config.DSS_DIR
NET_XLSX      = str(config.NET_PP_XLSX)

CIRCUIT_DSS   = config.CIRCUIT_DSS
LINECODES_DSS = config.LINECODES_DSS
LOADS_DSS     = config.LOADS_DSS

OUT_XLSX = config.NET_3PH_XLSX
OUT_JSON = config.NET_3PH_JSON

# =========================
# HELPERS
# =========================
UNITS_TO_KM = {
    "km": 1.0,
    "m": 1e-3,
    "ft": 0.0003048,
    "kft": 0.3048,
    "mi": 1.609344,
}

def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")

def clean_lines(text: str):
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("!"):
            continue
        out.append(line)
    return out

def get_param(cmd: str, key: str, default=None):
    m = re.search(rf'(?i)\b{re.escape(key)}\s*=\s*(\[[^\]]*\]|"[^"]*"|\'[^\']*\'|[^\s]+)', cmd)
    if not m:
        return default
    val = m.group(1).strip().strip('"').strip("'")
    return val

def parse_array(val):
    if val is None:
        return []
    s = val.strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    parts = re.split(r"[,\s]+", s.strip())
    return [p for p in parts if p]

def bus_base(bus1: str) -> str:
    # mv_f0_lv0_f0_c0.1   -> mv_f0_lv0_f0_c0
    # mv_f0_n1070.1.2.3   -> mv_f0_n1070
    return re.sub(r"(\.\d+)+$", "", bus1.strip())

def bus_phase(bus1: str):
    m = re.search(r"\.(\d)$", bus1.strip())
    return int(m.group(1)) if m else None

def kvar_from_kw_pf(kw: float, pf: float) -> float:
    pf = float(pf)
    if abs(pf) >= 1.0:
        return 0.0
    q = abs(kw) * math.tan(math.acos(abs(pf)))
    return q if pf >= 0 else -q

def ensure_trafo_zero_seq_columns(net):
    cols = {
        "vector_group": None,
        "vk0_percent": math.nan,
        "vkr0_percent": math.nan,
        "mag0_percent": math.nan,
        "mag0_rx": math.nan,
        "si0_hv_partial": math.nan,
    }
    for c, default in cols.items():
        if c not in net.trafo.columns:
            net.trafo[c] = default

def ensure_ext_grid_3ph_columns(net):
    cols = {
        "s_sc_max_mva": math.nan,
        "s_sc_min_mva": math.nan,
        "rx_max": math.nan,
        "rx_min": math.nan,
        "r0x0_max": math.nan,
        "x0x_max": math.nan,
    }
    for c, default in cols.items():
        if c not in net.ext_grid.columns:
            net.ext_grid[c] = default

def add_zero_seq_line_std_types_from_dss(net, linecodes_path: Path, f_hz: float = 50.0):
    txt = read_text(linecodes_path)
    n_ok = 0
    n_missing = 0

    for line in clean_lines(txt):
        if not re.match(r"(?i)^new\s+linecode\.", line):
            continue

        mname = re.search(r"(?i)^new\s+linecode\.([^\s]+)", line)
        if not mname:
            continue
        lc_name = mname.group(1).strip()

        if lc_name not in net.std_types["line"]:
            n_missing += 1
            continue

        r0 = get_param(line, "r0")
        x0 = get_param(line, "x0")
        b0 = get_param(line, "b0")
        units = (get_param(line, "units", "km") or "km").lower()

        km_per_unit = UNITS_TO_KM.get(units, 1.0)

        if r0 is not None:
            net.std_types["line"][lc_name]["r0_ohm_per_km"] = float(r0) / km_per_unit
        if x0 is not None:
            net.std_types["line"][lc_name]["x0_ohm_per_km"] = float(x0) / km_per_unit
        if b0 is not None:
            # OpenDSS b0: micro-Siemens / unit length  -> pandapower c0_nf_per_km
            b0_us_per_unit = float(b0)
            B0_S_per_km = (b0_us_per_unit * 1e-6) / km_per_unit
            c0_nf_per_km = (B0_S_per_km / (2.0 * math.pi * f_hz)) * 1e9
            net.std_types["line"][lc_name]["c0_nf_per_km"] = c0_nf_per_km

        n_ok += 1

    # copy std_type zero-sequence fields into net.line dataframe
    pp.add_zero_impedance_parameters(net)
    return n_ok, n_missing

def set_ext_grid_from_dss_source(net, circuit_path: Path):
    txt = read_text(circuit_path)

    r1 = get_param(txt, "R1")
    x1 = get_param(txt, "X1")
    r0 = get_param(txt, "R0")
    x0 = get_param(txt, "X0")
    basekv = get_param(txt, "basekv")

    if None in (r1, x1, r0, x0, basekv):
        raise ValueError("rom 01_Circuit.dss")

    r1 = float(r1)
    x1 = float(x1)
    r0 = float(r0)
    x0 = float(x0)
    vll_kv = float(basekv)

    z1 = math.hypot(r1, x1)
    ssc_mva = (vll_kv ** 2) / z1
    rx = r1 / x1 if abs(x1) > 1e-12 else 0.0
    x0x = x0 / x1 if abs(x1) > 1e-12 else 1.0
    r0x0 = r0 / x0 if abs(x0) > 1e-12 else 0.0

    ensure_ext_grid_3ph_columns(net)
    eg = net.ext_grid.index[0]
    net.ext_grid.at[eg, "s_sc_max_mva"] = ssc_mva
    net.ext_grid.at[eg, "s_sc_min_mva"] = ssc_mva
    net.ext_grid.at[eg, "rx_max"] = rx
    net.ext_grid.at[eg, "rx_min"] = rx
    net.ext_grid.at[eg, "x0x_max"] = x0x
    net.ext_grid.at[eg, "r0x0_max"] = r0x0

def fill_trafo_zero_sequence_assumptions(net):
    """
    Minimal assumptions to make the existing equivalent 2-winding trafos runnable in runpp_3ph.

    Important for pandapower 3-phase solver:
    - only supported vector groups are used here
    - 66/22 source transformer -> YNyn
    - 22/22 equivalent ISO / regulator transformers -> Dyn
    - 22/0.4 MV/LV transformers -> Dyn
    - zero-sequence leakage is approximated by positive-sequence leakage for a first runnable model
    """
    ensure_trafo_zero_seq_columns(net)

    supported = {"YNyn", "Dyn", "Yzn"}

    # Read split_phase flag if it was set during LV build (windings=3 center-tap trafos)
    has_split_phase_col = "split_phase" in net.trafo.columns

    for tidx, row in net.trafo.iterrows():
        hv = float(row["vn_hv_kv"])
        lv = float(row["vn_lv_kv"])
        is_split = bool(row["split_phase"]) if has_split_phase_col else False

        # 66/22 source trafo
        if abs(hv - 66.0) < 1e-6 and abs(lv - 22.0) < 1e-6:
            vector_group    = "YNyn"
            si0_hv_partial  = 0.9
            mag0_percent    = 100.0

        # 22/22 ISO / regulator equivalents collapsed to 2-winding trafos
        elif abs(hv - 22.0) < 1.0 and abs(lv - 22.0) < 1.0:
            vector_group    = "Dyn"
            si0_hv_partial  = 0.9
            mag0_percent    = 100.0

        # 22 kV / LV distribution trafos  (covers 0.4, 0.416, 0.433 kV variants)
        elif abs(hv - 22.0) < 1.0 and lv < 1.0:
            vector_group = "Dyn"
            if is_split:
                # pandapower's runpp_3ph cannot correctly model split-phase
                # center-tap trafos.  Using mag0=0 / si0=0 causes za=0 →
                # singular admittance matrix → solver failure every timestep.
                # Use standard Dyn assumptions so the solver stays numerically
                # stable (results for these trafos are excluded from metrics anyway).
                si0_hv_partial = 0.9
                mag0_percent   = 100.0
            else:
                # Standard 3-phase Dyn or single-phase Wye-Wye (SWER) trafo.
                # Zero-seq circulates within the transformer (delta or wye core).
                si0_hv_partial = 0.9
                mag0_percent   = 100.0

        # fallback: keep only supported groups
        else:
            current_vg = row.get("vector_group", None)
            vector_group = current_vg if (isinstance(current_vg, str) and current_vg in supported) else "Dyn"
            si0_hv_partial = 0.9
            mag0_percent   = 100.0

        net.trafo.at[tidx, "vector_group"]   = vector_group
        net.trafo.at[tidx, "vk0_percent"]    = float(row["vk_percent"])
        net.trafo.at[tidx, "vkr0_percent"]   = float(row["vkr_percent"])
        net.trafo.at[tidx, "mag0_percent"]   = mag0_percent
        net.trafo.at[tidx, "mag0_rx"]        = 0.0
        net.trafo.at[tidx, "si0_hv_partial"] = si0_hv_partial

    bad = net.trafo.loc[~net.trafo["vector_group"].isin(supported), ["name", "vn_hv_kv", "vn_lv_kv", "vector_group"]]
    if len(bad):
        raise ValueError(
            "Unsupported transformer vector groups remain after filling assumptions:"
            + bad.to_string(index=False)
        )

def add_asymmetric_loads_from_dss(net, loads_path: Path):
    txt = read_text(loads_path)
    bus_lookup = {str(name): idx for idx, name in net.bus["name"].astype(str).items()}

    # remove balanced loads if they already exist
    if "load" in net and len(net.load):
        net.load.drop(net.load.index, inplace=True)

    created = 0
    skipped = 0

    for line in clean_lines(txt):
        if not re.match(r"(?i)^new\s+load\.", line):
            continue

        name_match = re.search(r"(?i)^new\s+load\.([^\s]+)", line)
        if not name_match:
            skipped += 1
            continue
        name = name_match.group(1).strip()

        enabled = (get_param(line, "enabled", "true") or "true").lower()
        if enabled in {"false", "no", "0"}:
            continue

        bus1 = get_param(line, "bus1")
        phases = int(float(get_param(line, "phases", "1")))
        kw = float(get_param(line, "kw", "0"))
        pf = float(get_param(line, "pf", "0.95"))
        conn = (get_param(line, "conn", "wye") or "wye").lower()

        base_bus = bus_base(bus1)
        pp_bus = bus_lookup.get(base_bus)

        if pp_bus is None:
            skipped += 1
            continue

        qkvar = kvar_from_kw_pf(kw, pf)
        p_mw = kw / 1000.0
        q_mvar = qkvar / 1000.0

        p_a = p_b = p_c = 0.0
        q_a = q_b = q_c = 0.0

        if phases == 3:
            p_each = p_mw / 3.0
            q_each = q_mvar / 3.0
            p_a = p_b = p_c = p_each
            q_a = q_b = q_c = q_each
        else:
            ph = bus_phase(bus1)
            if ph == 1:
                p_a, q_a = p_mw, q_mvar
            elif ph == 2:
                p_b, q_b = p_mw, q_mvar
            elif ph == 3:
                p_c, q_c = p_mw, q_mvar
            else:
                # fallback if phase suffix missing
                p_a, q_a = p_mw, q_mvar

        pp.create_asymmetric_load(
            net,
            bus=pp_bus,
            p_a_mw=p_a, p_b_mw=p_b, p_c_mw=p_c,
            q_a_mvar=q_a, q_b_mvar=q_b, q_c_mvar=q_c,
            name=name,
            type="delta" if conn == "delta" else "wye",
            in_service=True
        )
        created += 1

    return created, skipped


# =========================
# MAIN
# =========================
def main():
    net = pp.from_excel(str(NET_XLSX))

    print(f"[INFO] Loaded net: {NET_XLSX}")
    print(f"[INFO] Buses={len(net.bus)}  Lines={len(net.line)}  Trafos={len(net.trafo)}")

    n_lc_ok, n_lc_missing = add_zero_seq_line_std_types_from_dss(net, LINECODES_DSS, f_hz=float(net.f_hz))
    print(f"[INFO] Linecodes with zero-seq added: {n_lc_ok}")
    if n_lc_missing:
        print(f"[WARN] Linecodes missing in net.std_types['line']: {n_lc_missing}")

    set_ext_grid_from_dss_source(net, CIRCUIT_DSS)
    print("[INFO] External grid 3ph short-circuit / zero-sequence parameters filled from 01_Circuit.dss")

    fill_trafo_zero_sequence_assumptions(net)
    print("[INFO] Transformer vector groups and zero-sequence assumptions filled")


    print("[INFO] Running runpp_3ph...")
    runpp_3ph(
        net,
        calculate_voltage_angles=True,
        trafo_model="t",
        check_connectivity=True,
    )
    print("[OK] runpp_3ph converged")

    pp.to_excel(net, str(OUT_XLSX))


if __name__ == "__main__":
    main()

import re
import sys
import math
import pandas as pd
import pandapower as pp
from pandapower import from_json
from pandapower.plotting import pf_res_plotly, simple_plotly
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

# ========= PATHS (from config.py) =========
BASE         = str(config.DSS_DIR)
MV_JSON      = str(config.MV_NET_XLSX)
LV_TX_DSS    = str(config.LV_TX_DSS)
LV_LINES_DSS = str(config.LV_LINES_DSS)
# ==========================================

F_HZ = 50.0  # (δεν το χρειαζόμαστε πλέον για linecodes, αλλά το κρατάμε γενικά)


# ---------------- Helpers ----------------
def _parse_dss_array(val: str):
    val = val.strip()
    if val.startswith("[") and val.endswith("]"):
        inner = val[1:-1].strip()
        parts = re.split(r"[,\s]+", inner)
        return [p for p in parts if p != ""]
    return [val]

def _clean_bus_name(bus: str) -> str:
    # remove node suffixes .1.2.3 etc
    return bus.split(".")[0].strip()

def _to_km(length: float, units: str) -> float:
    u = units.lower()
    if u in ("m", "meter", "meters", "metre", "metres"):
        return length / 1000.0
    if u in ("km", "kilometer", "kilometers", "kilometre", "kilometres"):
        return length
    if u in ("ft", "feet"):
        return length * 0.0003048
    if u in ("mi", "mile", "miles"):
        return length * 1.60934
    raise ValueError(f"Unknown units={units}")

def _kv_ln_to_ll(kv_ln: float) -> float:
    return kv_ln * math.sqrt(3)

def _infer_lv_kv_for_pp(phases: int, kv_lv_raw: float) -> float:
    """
    Για positive-sequence pandapower:
    - phases=3: το LV kV στο DSS είναι συνήθως LL (π.χ. 0.433) -> κρατάμε
    - phases=1: το 0.24/0.25 είναι συνήθως LN -> το κάνουμε LL (x√3)
    """
    if phases == 1:
        return _kv_ln_to_ll(kv_lv_raw)
    return kv_lv_raw

def ensure_bus(net, name: str, vn_kv: float):
    found = net.bus.index[net.bus["name"] == name]
    if len(found):
        return int(found[0])
    return pp.create_bus(net, vn_kv=vn_kv, name=name)

def _parse_keyvals(params: str):
    kv = {}
    for m in re.finditer(r"(\w+)\s*=\s*(\[[^\]]*\]|[^\s]+)", params):
        kv[m.group(1).lower()] = m.group(2)
    return kv

def _ensure_bus_geodata(net):
    if net.bus_geodata is None or len(net.bus_geodata) == 0:
        net.bus_geodata = pd.DataFrame(index=net.bus.index, columns=["x", "y"])
    else:
        for idx in net.bus.index:
            if idx not in net.bus_geodata.index:
                net.bus_geodata.loc[idx, ["x", "y"]] = [None, None]
def create_trafo3w_compat(net, **kwargs):
    """
    pandapower versions differ in signature of create_transformer3w_from_parameters.
    Try the common signatures automatically.
    """
    try:
        # Signature A (many versions): vk_hv_mv_percent, vk_hv_lv_percent, vk_mv_lv_percent, ...
        return pp.create_transformer3w_from_parameters(net=net, **kwargs)
    except TypeError as e1:
        # Signature B (older/other): vk_hv_percent, vk_mv_percent, vk_lv_percent, ...
        # We map from pairwise to per-winding if needed.
        msg = str(e1)
        needs_alt = ("vk_hv_percent" in msg or "vk_mv_percent" in msg or "vk_lv_percent" in msg)
        if not needs_alt:
            raise

        # Build a new kwargs set for Signature B
        alt = dict(kwargs)

        # If user passed pairwise fields, convert them:
        # We'll use hv_mv for hv, hv_lv for mv, mv_lv for lv as a reasonable approximation.
        if "vk_hv_mv_percent" in alt and "vk_hv_percent" not in alt:
            alt["vk_hv_percent"] = alt["vk_hv_mv_percent"]
        if "vk_hv_lv_percent" in alt and "vk_mv_percent" not in alt:
            alt["vk_mv_percent"] = alt["vk_hv_lv_percent"]
        if "vk_mv_lv_percent" in alt and "vk_lv_percent" not in alt:
            alt["vk_lv_percent"] = alt["vk_mv_lv_percent"]

        if "vkr_hv_mv_percent" in alt and "vkr_hv_percent" not in alt:
            alt["vkr_hv_percent"] = alt["vkr_hv_mv_percent"]
        if "vkr_hv_lv_percent" in alt and "vkr_mv_percent" not in alt:
            alt["vkr_mv_percent"] = alt["vkr_hv_lv_percent"]
        if "vkr_mv_lv_percent" in alt and "vkr_lv_percent" not in alt:
            alt["vkr_lv_percent"] = alt["vkr_mv_lv_percent"]

        # Remove pairwise keys if present (older signature won't accept them)
        for k in [
            "vk_hv_mv_percent","vk_hv_lv_percent","vk_mv_lv_percent",
            "vkr_hv_mv_percent","vkr_hv_lv_percent","vkr_mv_lv_percent",
            "shift_mv_degree","shift_lv_degree",  # some versions use different names
            "shift_mv_degree","shift_lv_degree"
        ]:
            alt.pop(k, None)

        return pp.create_transformer3w_from_parameters(net=net, **alt)

def propagate_lv_busbar_coords_from_hv(net):
    """
    Copy HV bus geodata -> LV busbar geodata (if LV missing).
    (Για να έχουν coords τα mv_f0_lv*_busbar χωρίς LV BusCoords)
    """
    _ensure_bus_geodata(net)

    def copy_xy(src, dst):
        if src not in net.bus_geodata.index or dst not in net.bus_geodata.index:
            return
        sx, sy = net.bus_geodata.at[src, "x"], net.bus_geodata.at[src, "y"]
        if pd.isna(sx) or pd.isna(sy):
            return
        dx, dy = net.bus_geodata.at[dst, "x"], net.bus_geodata.at[dst, "y"]
        if pd.isna(dx) or pd.isna(dy):
            net.bus_geodata.at[dst, "x"] = sx
            net.bus_geodata.at[dst, "y"] = sy

    if len(net.trafo):
        for _, t in net.trafo.iterrows():
            copy_xy(int(t.hv_bus), int(t.lv_bus))

    if len(net.trafo3w):
        for _, t in net.trafo3w.iterrows():
            copy_xy(int(t.hv_bus), int(t.mv_bus))
            copy_xy(int(t.hv_bus), int(t.lv_bus))

LV_VN_KV = 0.4  # όλα LV trafos/buses στα 0.4 kV

def _tap_to_pos_5steps(tap: float, neutral: int = 3, step_pu: float = 0.025) -> int:
    """
    5 taps: positions 1..5, neutral=3, step=2.5% (0.025 pu)
    tap=1.0 -> pos 3
    tap=1.025 -> pos 4
    tap=0.975 -> pos 2
    """
    try:
        tap = float(tap)
    except Exception:
        return neutral
    pos = int(round((tap - 1.0) / step_pu)) + neutral
    return max(1, min(5, pos))
# ---------------- LV Transformers ----------------
import re
import pandapower as pp
import numpy as np
def kv_get_float(kv: dict, *keys: str, default: float = 0.0) -> float:
    """
    Try multiple possible keys (case-insensitive).
    Also tries variants removing leading '%' from the requested keys.
    """
    # build lookup table lowercase -> original key
    lut = {str(k).strip().lower(): k for k in kv.keys()}

    for key in keys:
        k1 = str(key).strip().lower()
        k2 = k1[1:] if k1.startswith("%") else "%" + k1  # both with and without %
        for cand in (k1, k2):
            if cand in lut:
                try:
                    return float(kv[lut[cand]])
                except Exception:
                    pass
    return float(default)
def add_mv_lv_transformer_from_dss_line(net, line: str):
    """
    Map ALL LV distribution transformers to 2-winding pandapower trafos:
    - Ignores DSS 'windings' count (3-winding split-phase -> 2-winding)
    - LV kV derived from DSS kvs[1] via _infer_lv_kv_for_pp:
        phases=3: use LL directly (e.g. 0.433 kV)
        phases=1: LN -> LL (e.g. 0.24*sqrt(3)=0.416 kV, 0.25*sqrt(3)=0.433 kV)
    - Off-load tap: 5 positions, neutral=3, step=2.5%, tap_pos from DSS 'tap'
    - vkr_percent from %loadloss
    - pfe_kw from %noloadloss
    - i0_percent from %imag (fallback 2.0 %)
    """
    line = line.strip()
    if not line.lower().startswith("new transformer."):
        return None

    m = re.match(r"New\s+Transformer\.([^\s]+)\s+(.*)$", line, flags=re.IGNORECASE)
    if not m:
        return None

    name = m.group(1).strip()
    kv = _parse_keyvals(m.group(2).strip())

    # --- Parse fields we need ---
    phases = int(kv.get("phases", "3"))

    windings = int(kv.get("windings", "2"))
    split_phase = (windings == 3)  # center-tap (split-phase): third winding is neutral leg

    buses = _parse_dss_array(kv.get("buses", ""))
    if len(buses) < 2:
        return None

    conns = _parse_dss_array(kv.get("conns", "[wye wye]"))

    kvs_raw = _parse_dss_array(kv.get("kvs", ""))
    kvas_raw = _parse_dss_array(kv.get("kvas", ""))

    if len(kvs_raw) < 2 or len(kvas_raw) < 1:
        return None

    kvs = [float(x) for x in kvs_raw]
    kvas = [float(x) for x in kvas_raw]

    # Series impedance magnitude (OpenDSS xhl is already in % on transformer base)
    xhl = float(kv.get("xhl", "2.5"))

    # Losses (in % of transformer kVA base in OpenDSS)
    noload = kv_get_float(kv, "%noloadloss", "noloadloss", default=0.0)
    loadloss = kv_get_float(kv, "%loadloss", "loadloss", default=0.0)

    # Magnetizing current (% of rated current) in OpenDSS is %imag (if present)
    # Some files may use "imag" or "%imag"
    imag = None
    imag = kv_get_float(kv, "%imag", "imag", default=np.nan)
    imag = None if np.isnan(imag) else imag

    tap_val = kv.get("tap", "1.0")

    MV_VN_KV = 22.0
    # Derive LV voltage from DSS: for phases=1 (LN values), convert to LL equivalent
    lv_kv_pp = _infer_lv_kv_for_pp(phases, kvs[1])

    # --- Buses ---
    hv_bus_name = _clean_bus_name(buses[0])
    lv_bus_name = _clean_bus_name(buses[1])

    b_hv = ensure_bus(net, hv_bus_name, vn_kv=MV_VN_KV)
    net.bus.at[b_hv, "vn_kv"] = MV_VN_KV

    b_lv = ensure_bus(net, lv_bus_name, vn_kv=lv_kv_pp)
    net.bus.at[b_lv, "vn_kv"] = lv_kv_pp

    sn_mva = float(kvas[0]) / 1000.0

    # Phase shift (delta-wye)
    shift = 30.0 if (len(conns) >= 2 and conns[0].lower() == "delta" and conns[1].lower() == "wye") else 0.0

    # -------------------------
    # FIXED: map losses correctly
    # -------------------------
    # Core losses in kW:
    # %noloadloss is percent of kVA base → kW = (%/100)*kVA
    pfe_kw = (noload / 100.0) * float(kvas[0])

    # Copper losses parameter in pandapower:
    # vkr_percent is the short-circuit voltage component due to resistance (%)
    # Use %loadloss if available; otherwise try r% if exists.
    vkr_percent = loadloss

    # Some datasets provide "r%" instead of %loadloss
    if (vkr_percent == 0.0) and ("r%" in kv):
        try:
            vkr_percent = float(kv.get("r%"))
        except Exception:
            pass

    # Magnetizing current in pandapower:
    # i0_percent should come from %imag (NOT from %noloadloss)
    I0_DEFAULT = 2.0  # safe default for small MV/LV distribution trafos
    i0_percent = imag if imag is not None else I0_DEFAULT

    # Create transformer
    tidx = pp.create_transformer_from_parameters(
        net,
        hv_bus=b_hv,
        lv_bus=b_lv,
        sn_mva=sn_mva,
        vn_hv_kv=MV_VN_KV,
        vn_lv_kv=lv_kv_pp,
        vk_percent=xhl,
        vkr_percent=vkr_percent,
        pfe_kw=pfe_kw,
        i0_percent=i0_percent,
        shift_degree=shift,
        name=name
    )

    # Off-load tap settings
    net.trafo.at[tidx, "tap_side"] = "lv"
    net.trafo.at[tidx, "tap_min"] = 1
    net.trafo.at[tidx, "tap_max"] = 5
    net.trafo.at[tidx, "tap_neutral"] = 3
    net.trafo.at[tidx, "tap_step_percent"] = 2.5
    net.trafo.at[tidx, "tap_pos"] = _tap_to_pos_5steps(tap_val, neutral=3, step_pu=0.025)
    net.trafo.at[tidx, "tap_phase_shifter"] = False
    # Mark center-tap (split-phase) trafos: DSS windings=3 has a neutral leg
    # that acts as an explicit solid ground (center tap). Used in prepare_net_for_3ph.py
    # to set correct zero-sequence parameters.
    net.trafo.at[tidx, "split_phase"] = split_phase




def add_all_lv_transformers(net, path: str):
    created = []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            s = raw.strip()
            if not s or s.startswith("!") or s.startswith("//"):
                continue
            if s.lower().startswith("new transformer."):
                out = add_mv_lv_transformer_from_dss_line(net, s)
                if out:
                    created.append(out)
    return created


# ---------------- LV Lines (use std_type already in net) ----------------
def assert_std_line_type_exists(net, type_name: str):
    std = net.std_types.get("line", {})
    if type_name not in std:
        raise KeyError(
            f"Line std_type '{type_name}' not found in net.std_types['line'].\n"
            f"Available examples: {list(std.keys())[:20]}"
        )
import math

def hv_kv_for_pp(phases: int, hv_kv_raw: float, hv_bus_vn_kv: float, tol: float = 0.2):
    """
    If phases=1 and hv_kv_raw looks like LN value for a LL bus, convert it.
    Example: 12.7 LN on a 22 kV LL bus -> 12.7*sqrt(3) ~= 22
    """
    if phases == 1:
        hv_ll = hv_kv_raw * math.sqrt(3)
        if abs(hv_ll - hv_bus_vn_kv) <= tol:
            return hv_bus_vn_kv
        return hv_ll  # fallback: still convert to LL
    return hv_kv_raw

def add_lv_line_from_dss_line(net, line: str):
    line = line.strip()
    if not line.lower().startswith("new line."):
        return None

    m = re.match(r"New\s+Line\.([^\s]+)\s+(.*)$", line, flags=re.IGNORECASE)
    if not m:
        return None

    name = m.group(1).strip()
    kv = _parse_keyvals(m.group(2).strip())

    b1_name = _clean_bus_name(kv["bus1"])
    b2_name = _clean_bus_name(kv["bus2"])

    length_km = _to_km(float(kv.get("length", "0")), kv.get("units", "km"))
    linecode = kv.get("linecode", "").strip()
    assert_std_line_type_exists(net, linecode)

    # --- pick a reference vn_kv from an existing bus (prefer busbar if exists) ---
    def get_existing_vn(bus_name):
        idxs = net.bus.index[net.bus["name"] == bus_name]
        if len(idxs):
            return float(net.bus.at[int(idxs[0]), "vn_kv"])
        return None

    vn_ref = None
    # prefer busbar side if present
    if b1_name.endswith("_busbar"):
        vn_ref = get_existing_vn(b1_name)
    if vn_ref is None and b2_name.endswith("_busbar"):
        vn_ref = get_existing_vn(b2_name)
    # otherwise use any existing side
    if vn_ref is None:
        vn_ref = get_existing_vn(b1_name) or get_existing_vn(b2_name)
    # final fallback (only if neither exists yet)
    if vn_ref is None:
        vn_ref = 0.433

    # ensure buses with vn_ref (if created now)
    b1 = ensure_bus(net, b1_name, vn_kv=vn_ref)
    b2 = ensure_bus(net, b2_name, vn_kv=vn_ref)

    # if they already existed but differ slightly, normalize to vn_ref (tolerance)
    tol = 1e-6
    if abs(float(net.bus.at[b1, "vn_kv"]) - vn_ref) > tol:
        net.bus.at[b1, "vn_kv"] = vn_ref
    if abs(float(net.bus.at[b2, "vn_kv"]) - vn_ref) > tol:
        net.bus.at[b2, "vn_kv"] = vn_ref

    lidx = pp.create_line(
        net,
        from_bus=b1,
        to_bus=b2,
        length_km=length_km,
        std_type=linecode,
        name=name
    )
    return lidx



def add_all_lv_lines(net, path: str):
    created = []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            s = raw.strip()
            if not s or s.startswith("!") or s.startswith("//"):
                continue
            if s.lower().startswith("new line."):
                lidx = add_lv_line_from_dss_line(net, s)
                if lidx is not None:
                    created.append(lidx)
    return created


from pandapower import to_excel,from_excel
# ================== MAIN ==================
def main():
    net = from_excel(MV_JSON)
    tx_created = add_all_lv_transformers(net, LV_TX_DSS)
    lines_created = add_all_lv_lines(net, LV_LINES_DSS)
    propagate_lv_busbar_coords_from_hv(net)
    to_excel(net, str(config.NET_PP_XLSX))

if __name__ == "__main__":
    net = main()

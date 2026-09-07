import re
import sys
import numpy as np
import pandapower as pp
import csv
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

BUSCOORDS_PATH = str(config.BUSCOORDS_CSV)

def load_buscoords(path):
    coords = {}
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        reader = csv.reader(f)
        header = next(reader, None)

        # Αν έχει header τύπου: Bus, X, Y
        # ή αν δεν έχει, πάλι το πιάνουμε
        for row in reader:
            if not row or len(row) < 3:
                continue
            bus = row[0].strip().strip('"')
            try:
                x = float(row[1])
                y = float(row[2])
            except:
                continue
            coords[bus] = (x, y)
    return coords

coords = load_buscoords(BUSCOORDS_PATH)


# =========================
# 0) Create empty network
# =========================
net = pp.create_empty_network(name="from_opendss_manual")


# =========================
# 1) Source bus + geodata
# =========================
b_source = pp.create_bus(net, index=1, vn_kv=66.0, name="sourcebus")


# =========================
# 2) External grid
# =========================
pp.create_ext_grid(net, bus=b_source, vm_pu=1.04, name="Grid_66kV")


# =========================
# 3) LineCodes -> std_types["line"]
# =========================
LINECODES_PATH = str(config.LINECODES_DSS)

UNIT_TO_KM = {
    "km": 1.0,
    "m": 1e-3,
}

def parse_kv_pairs(s: str) -> dict:
    # πιάνει key=value (χωρίς να χαλάει αν υπάρχουν τελείες αλλού)
    return {
        k.lower(): v.strip('"')
        for k, v in re.findall(r'(\w+)\s*=\s*("[^"]+"|\S+)', s)
    }

def to_float(x):
    try:
        return float(x)
    except Exception:
        return None

loaded = 0
skipped = 0

with open(LINECODES_PATH, "r", encoding="utf-8", errors="ignore") as f:
    for raw in f:
        line = raw.strip()

        # skip comments/empty
        if not line or line.startswith("!") or line.lower().startswith("rem"):
            continue

        # only "New Linecode.xxx ..."
        if not line.lower().startswith("new linecode."):
            continue

        m = re.match(r'new\s+linecode\.([^\s]+)\s+(.*)', line, re.I)
        if not m:
            skipped += 1
            continue

        name = m.group(1).strip()
        params = parse_kv_pairs(m.group(2))

        units = params.get("units", "km").lower()
        if units not in UNIT_TO_KM:
            skipped += 1
            continue

        km_per_unit = UNIT_TO_KM[units]

        r1 = to_float(params.get("r1"))
        x1 = to_float(params.get("x1"))
        b1 = to_float(params.get("b1"))         # OpenDSS: μS / unit-length (συνήθως)
        normamp = to_float(params.get("normamp", 0))

        if r1 is None or x1 is None:
            skipped += 1
            continue

        # Ω/km
        r_ohm_per_km = r1 / km_per_unit
        x_ohm_per_km = x1 / km_per_unit

        # b1 (μS/unit) -> C (nF/km) με f=50Hz:
        # B_S_per_km = (b1*1e-6) / (km_per_unit)
        # C_F_per_km = B / (2πf)
        # C_nF_per_km = *1e9
        if b1 is not None:
            B_S_per_km = (b1 * 1e-6) / km_per_unit
            c_nf_per_km = (B_S_per_km / (2 * np.pi * 50.0)) * 1e9
        else:
            c_nf_per_km = 0.0

        max_i_ka = (normamp / 1000.0) if normamp else 1.0

        data = {
            "r_ohm_per_km": float(r_ohm_per_km),
            "x_ohm_per_km": float(x_ohm_per_km),
            "c_nf_per_km": float(c_nf_per_km),
            "max_i_ka": float(max_i_ka),
            "type": "ol"
        }

        # add / overwrite std type
        pp.create_std_type(net, data, name=name, element="line", overwrite=True)
        loaded += 1


import re
import pandapower as pp

MV_LINES_PATH =  str(config.MV_LINES_DSS)

UNIT_TO_KM = {
    "km": 1.0,
    "m": 1e-3,
    "mi": 1.609344,
    "kft": 0.3048,
    "ft": 0.0003048
}

def clean_bus(bus: str) -> str:
    return bus.split(".")[0].strip('"')

def parse_kv_pairs(s: str) -> dict:
    return {
        k.lower(): v.strip('"')
        for k, v in re.findall(r'(\w+)\s*=\s*("[^"]+"|\S+)', s)
    }

# ======================================================
# BUS MAP + INDEX COUNTER
# ======================================================
bus_map = {row["name"]: idx for idx, row in net.bus.iterrows()}

MV_BUS_START_INDEX = 1
next_mv_bus_index = max(
    [i for i in bus_map.values() if i >= MV_BUS_START_INDEX],
    default=MV_BUS_START_INDEX - 1
) + 1


def get_or_create_mv_bus(bus_name: str, vn_kv: float = 22.0) -> int:
    global next_mv_bus_index

    if bus_name in bus_map:
        return bus_map[bus_name]

    idx = next_mv_bus_index
    next_mv_bus_index += 1

    b = pp.create_bus(net, index=idx, vn_kv=vn_kv, name=bus_name)
    bus_map[bus_name] = b

    # --- geodata από BusCoords.csv (με "clear" name) ---
    if bus_name in coords:
        x, y = coords[bus_name]
        net.bus_geodata.loc[b, ["x", "y"]] = [x, y]

    return b


# ======================================================
# BUILD MV BUSES + LINES
# ======================================================
buses_created = 0
lines_created = 0
skipped = 0
SWITCH_LEN_KM = 0.001
SWITCH_TOL = 1e-9  # ανοχή για float

with open(MV_LINES_PATH, "r", encoding="utf-8", errors="ignore") as f:
    for raw in f:
        line = raw.strip()

        if not line or line.startswith("!") or line.lower().startswith("rem"):
            continue
        if not re.match(r'(?i)^new\s+line\.', line):
            continue

        m = re.match(r'(?i)^new\s+line\.([^\s]+)\s+(.*)$', line)
        if not m:
            skipped += 1
            continue

        line_name = m.group(1)
        params = parse_kv_pairs(m.group(2))

        if "bus1" not in params or "bus2" not in params:
            skipped += 1
            continue

        bus1 = clean_bus(params["bus1"])
        bus2 = clean_bus(params["bus2"])

        before = len(bus_map)
        fb = get_or_create_mv_bus(bus1)
        tb = get_or_create_mv_bus(bus2)
        after = len(bus_map)
        buses_created += (after - before)

        length = float(params.get("length", 0.0))
        units = params.get("units", "km").lower()
        if units not in UNIT_TO_KM:
            skipped += 1
            continue

        length_km = length * UNIT_TO_KM[units]
        linecode = params.get("linecode")

        if linecode not in net.std_types["line"]:
            raise KeyError(f"Linecode '{linecode}' δεν υπάρχει στα std_types")
        # otherwise, normal line
        pp.create_line(
            net,
            from_bus=fb,
            to_bus=tb,
            length_km=length_km,
            std_type=linecode,
            name=line_name
        )
        lines_created += 1

from pandapower.plotting import simple_plotly

# --- Parse hv/lv bus από το 02_MV_NetTx.dss ---
_mv_nettx_hv_bus = None
_mv_nettx_lv_bus = None
with open(str(config.MV_NETTX_DSS), "r", encoding="utf-8", errors="ignore") as _f:
    for _raw in _f:
        _m = re.match(
            r'(?i)^new\s+transformer\.\S+\s+.*buses\s*=\s*\[([^,\]]+),\s*([^\]]+)\]', _raw.strip()
        )
        if _m:
            _mv_nettx_hv_bus = _m.group(1).strip().lower()
            _mv_nettx_lv_bus = _m.group(2).strip().lower()
            break
if _mv_nettx_hv_bus is None or _mv_nettx_lv_bus is None:
    raise RuntimeError("Δεν βρέθηκε transformer στο 02_MV_NetTx.dss")
hv_bus = bus_map[_mv_nettx_hv_bus]
lv_bus = get_or_create_mv_bus(_mv_nettx_lv_bus)

# source bus geodata: ίδια coords με τον lv_bus του transformer
if _mv_nettx_lv_bus in coords:
    _sx, _sy = coords[_mv_nettx_lv_bus]
    net.bus_geodata.loc[b_source, ["x", "y"]] = [_sx, _sy]

sn_mva = 100000 / 1000  # 100 MVA
vn_hv_kv = 66.0
vn_lv_kv = 22


vkr_percent = 1
vk_percent  = 5 


# OpenDSS: %noloadloss -> core losses in % of rated S
pfe_kw = (0.0001 / 100.0) * 100000  # = 0.1 kW
 # ✅ απευθείας

pp.create_transformer_from_parameters(
    net,
    hv_bus=hv_bus,
    lv_bus=lv_bus,
    sn_mva=sn_mva,
    vn_hv_kv=vn_hv_kv,
    vn_lv_kv=vn_lv_kv,
    vk_percent=vk_percent,
    vkr_percent=vkr_percent,
    pfe_kw=pfe_kw,
    i0_percent=0.0,
    shift_degree=30.0,
    name="SMR8"
)
import re
import pandapower as pp

def _strip_dss_nodes(bus: str) -> str:
    """
    "mv_f0_n3435.1.0" -> "mv_f0_n3435"
    "mv_f0_n3666.1.2" -> "mv_f0_n3666"
    """
    b = bus.strip().strip('"').strip("'")
    return b.split(".")[0]  # κρατάει μόνο το base bus name

def _parse_list(s: str):
    """
    παίρνει string τύπου: "[a b c]" ή "a,b,c" ή "a b c" και επιστρέφει λίστα tokens
    """
    s = s.strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1].strip()
    s = s.replace(",", " ")
    return [t for t in s.split() if t]

def _parse_transformer_line(raw_line: str):
    """
    Parses a DSS line like:
    New Transformer.BUNGARRA_ISO buses=[mv... mv... mv...] phases=1 windings=3 conns=[Delta Wye Wye]
    kVs=[22 12.7 12.7] kVAs=[100 100 100] xhl=1 %noloadloss=0.01 %loadloss=0.01
    Returns (name, params_dict) or (None, None)
    """
    line = raw_line.strip()
    if not line or line.startswith("!") or line.lower().startswith("rem"):
        return None, None
    m = re.match(r'(?i)^new\s+transformer\.([^\s]+)\s+(.*)$', line)
    if not m:
        return None, None

    name = m.group(1)
    rest = m.group(2)

    # μικρός parser key=value που κρατάει [] blocks intact
    # π.χ. buses=[a b c] conns=[Delta Wye Wye]
    tokens = re.findall(r'(?i)(%?\w+)\s*=\s*(\[[^\]]*\]|"[^"]*"|\'[^\']*\'|[^\s]+)', rest)
    params = {k.lower(): v for k, v in tokens}
    return name, params

def _get_float_anykey(p: dict, *keys: str, default: float = 0.0) -> float:
    """
    Robust float fetch from dict p:
    - case-insensitive
    - tries key with/without leading '%'
    """
    lut = {str(k).strip().lower(): k for k in p.keys()}

    for key in keys:
        k1 = str(key).strip().lower()
        k2 = k1[1:] if k1.startswith("%") else "%" + k1
        for cand in (k1, k2):
            if cand in lut:
                try:
                    return float(p[lut[cand]])
                except Exception:
                    pass
    return float(default)


def create_iso_transformers_from_dss(
    net,
    dss_path: str,
    get_or_create_mv_bus,   # function(name:str)->bus_index
    mv_vn_kv: float = 22.0,
    default_vk_percent: float = 1.0,
    default_vkr_percent: float = 0.01,
):
    """
    Reads a .dss and for each Transformer.* with name containing 'ISO' creates a 2-winding trafo (MV/MV) in pandapower.
    Adds correct pfe_kw mapping from OpenDSS %noloadloss:

        pfe_kw = (%noloadloss/100) * Sn_kVA

    Note: i0_percent remains 0 because %imag is typically not provided in this dataset.
    """
    created = 0
    skipped = 0

    with open(dss_path, "r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            name, p = _parse_transformer_line(raw)
            if not name:
                continue

            if "iso" not in name.lower():
                continue

            if "buses" not in p:
                skipped += 1
                continue

            buses = _parse_list(p["buses"])
            if len(buses) < 2:
                skipped += 1
                continue

            hv_bus_name = _strip_dss_nodes(buses[0])
            lv_bus_name = _strip_dss_nodes(buses[1])

            hv_bus = get_or_create_mv_bus(hv_bus_name)
            lv_bus = get_or_create_mv_bus(lv_bus_name)

            net.bus.at[hv_bus, "vn_kv"] = mv_vn_kv
            net.bus.at[lv_bus, "vn_kv"] = mv_vn_kv

            # -------------------------
            # Rating (kVAs)
            # -------------------------
            sn_mva = None
            sn_kva = None
            if "kvas" in p:
                kva_list = _parse_list(p["kvas"])
                if len(kva_list) >= 1:
                    try:
                        sn_kva = float(kva_list[0])
                        sn_mva = sn_kva / 1000.0
                    except Exception:
                        sn_kva = None
                        sn_mva = None

            if sn_mva is None:
                sn_mva = 0.1   # 100 kVA fallback
                sn_kva = 100.0

            # -------------------------
            # Short-circuit voltage (vk%)
            # -------------------------
            vk_percent = default_vk_percent
            if "xhl" in p:
                try:
                    vk_percent = float(p["xhl"])
                except Exception:
                    vk_percent = default_vk_percent

            # -------------------------
            # Copper losses component (vkr%)
            # IMPORTANT: parser may store '%loadloss' as 'loadloss'
            # -------------------------
            vkr_percent = _get_float_anykey(p, "%loadloss", "loadloss", default=default_vkr_percent)

            # -------------------------
            # Core losses (pfe_kw) from %noloadloss
            # -------------------------
            noloadloss_pct = _get_float_anykey(p, "%noloadloss", "noloadloss", default=0.0)
            pfe_kw = (noloadloss_pct / 100.0) * float(sn_kva)

            # Create MV/MV transformer (ratio 1.0)
            pp.create_transformer_from_parameters(
                net,
                hv_bus=hv_bus,
                lv_bus=lv_bus,
                sn_mva=sn_mva,
                vn_hv_kv=mv_vn_kv,
                vn_lv_kv=mv_vn_kv,
                vk_percent=vk_percent,
                vkr_percent=vkr_percent,
                pfe_kw=pfe_kw,
                i0_percent=0.1,     # no %imag available -> keep neutral for comparison
                shift_degree=0.0,
                name=name
            )
            created += 1

    return created, skipped
REGULATORS_DSS_PATH = str(config.REGS_DSS)
if config.REGS_DSS.exists():
    created_iso, skipped_iso = create_iso_transformers_from_dss(
        net=net,
        dss_path=REGULATORS_DSS_PATH,
        get_or_create_mv_bus=get_or_create_mv_bus,
        mv_vn_kv=22.0
    )
else:
    created_iso, skipped_iso = 0, 0

import re
import math
import pandapower as pp

def _strip_dss_nodes(bus: str) -> str:
    """ 'mv_f0_n1089.1' -> 'mv_f0_n1089', 'Jumper_X.1.2' -> 'Jumper_X' """
    return bus.strip().strip('"').strip("'").split(".")[0]

def _parse_kv_pairs_simple(s: str) -> dict:
    """key=value parser που κρατάει tokens, χρήσιμο για Reactor/Regcontrol lines"""
    tokens = re.findall(r'(?i)(%?\w+)\s*=\s*(\[[^\]]*\]|"[^"]*"|\'[^\']*\'|[^\s]+)', s)
    return {k.lower(): v for k, v in tokens}

def _parse_new_obj(line: str, obj: str):
    m = re.match(rf'(?i)^new\s+{obj}\.([^\s]+)\s+(.*)$', line.strip())
    if not m:
        return None, None
    return m.group(1), m.group(2)

def _extract_transformer_wdg_blocks(transformer_line: str):
    """
    Extracts winding blocks like:
      wdg=1 Bus=... kV=12.7 kVA=2.0
      wdg=2 Bus=... kV=1.27 kVA=2.0
    Returns dict wdg_idx -> dict with bus, kv, kva
    """
    blocks = {}
    # βρίσκει κάθε "wdg=NUM ... (μέχρι πριν το επόμενο wdg= ή end)"
    for m in re.finditer(r'(?i)\bwdg\s*=\s*(\d+)\b(.*?)(?=\bwdg\s*=\s*\d+\b|$)', transformer_line):
        wdg = int(m.group(1))
        tail = m.group(2)

        bus_m = re.search(r'(?i)\bbus\s*=\s*([^\s]+)', tail)
        kv_m  = re.search(r'(?i)\bkv\s*=\s*([0-9]*\.?[0-9]+)', tail)
        kva_m = re.search(r'(?i)\bkva\s*=\s*([0-9]*\.?[0-9]+)', tail)

        blocks[wdg] = {
            "bus": bus_m.group(1) if bus_m else None,
            "kv": float(kv_m.group(1)) if kv_m else None,
            "kva": float(kva_m.group(1)) if kva_m else None,
        }
    return blocks

import re
import math
import pandapower as pp

def _base_reg_name(name: str) -> str:
    # AVENEL_REGULATOR_A -> AVENEL_REGULATOR
    return re.sub(r'(?i)_[abc]$', '', name.strip())

def _strip_dss_nodes(bus: str) -> str:
    return bus.strip().strip('"').strip("'").split(".")[0]

def _parse_kv_pairs_simple(s: str) -> dict:
    tokens = re.findall(r'(?i)(%?\w+)\s*=\s*(\[[^\]]*\]|"[^"]*"|\'[^\']*\'|[^\s]+)', s)
    return {k.lower(): v.strip('"').strip("'") for k, v in tokens}

def _extract_transformer_wdg_blocks(transformer_line: str):
    blocks = {}
    for m in re.finditer(r'(?i)\bwdg\s*=\s*(\d+)\b(.*?)(?=\bwdg\s*=\s*\d+\b|$)', transformer_line):
        wdg = int(m.group(1))
        tail = m.group(2)
        bus_m = re.search(r'(?i)\bbus\s*=\s*([^\s]+)', tail)
        kv_m  = re.search(r'(?i)\bkv\s*=\s*([0-9]*\.?[0-9]+)', tail)
        kva_m = re.search(r'(?i)\bkva\s*=\s*([0-9]*\.?[0-9]+)', tail)
        blocks[wdg] = {
            "bus": bus_m.group(1) if bus_m else None,
            "kv": float(kv_m.group(1)) if kv_m else None,
            "kva": float(kva_m.group(1)) if kva_m else None,
        }
    return blocks

def build_mv_regulators_from_dss_one_per_set(
    net,
    dss_path: str,
    get_or_create_mv_bus,      # fn(name)->bus_index
    mv_vn_kv: float = 22.0,
    default_vk_percent: float = 1.0,
    default_vkr_percent: float = 0.01,
    sn_mva_overrides: dict | None = None,   # {"NAGAMBIE_REGULATOR": 5.0, "AVENEL_REGULATOR": 2.5}
    create_controllers: bool = True,
):
    """
    1 regulator per set (no _A/_B/_C), modeled as MV/MV trafo with taps.
    Tap settings are read from the DSS transformer line (numtaps/mintap/maxtap/tap or tap0).

    Returns: (created, skipped, controllers)
    """
    import re
    import pandapower as pp

    if sn_mva_overrides is None:
        sn_mva_overrides = {}

    def _base_reg_name(name: str) -> str:
        return re.sub(r'(?i)_[abc]$', '', name.strip())

    def _strip_dss_nodes(bus: str) -> str:
        return bus.strip().strip('"').strip("'").split(".")[0]

    def _parse_kv_pairs_simple(s: str) -> dict:
        tokens = re.findall(r'(?i)(%?\w+)\s*=\s*(\[[^\]]*\]|"[^"]*"|\'[^\']*\'|[^\s]+)', s)
        return {k.lower(): v.strip('"').strip("'") for k, v in tokens}

    def _parse_new_obj(line: str, obj: str):
        m = re.match(rf'(?i)^new\s+{obj}\.([^\s]+)\s+(.*)$', line.strip())
        if not m:
            return None, None
        return m.group(1), m.group(2)

    def _extract_transformer_wdg_blocks(transformer_line: str):
        """
        Extracts winding blocks like:
          wdg=1 Bus=... kV=12.7 kVA=2.0
          wdg=2 Bus=... kV=1.27 kVA=2.0
        Returns dict wdg_idx -> dict with bus, kv, kva
        """
        blocks = {}
        for m in re.finditer(r'(?i)\bwdg\s*=\s*(\d+)\b(.*?)(?=\bwdg\s*=\s*\d+\b|$)', transformer_line):
            wdg = int(m.group(1))
            tail = m.group(2)

            bus_m = re.search(r'(?i)\bbus\s*=\s*([^\s]+)', tail)
            kv_m  = re.search(r'(?i)\bkv\s*=\s*([0-9]*\.?[0-9]+)', tail)
            kva_m = re.search(r'(?i)\bkva\s*=\s*([0-9]*\.?[0-9]+)', tail)

            blocks[wdg] = {
                "bus": bus_m.group(1) if bus_m else None,
                "kv": float(kv_m.group(1)) if kv_m else None,
                "kva": float(kva_m.group(1)) if kva_m else None,
            }
        return blocks

    # Jumper base -> upstream/downstream MV bus base
    jumper_in = {}   # base -> mv_f0_nXXXX
    jumper_out = {}

    # transformer_name -> full line
    trafo_lines = {}

    # transformer_name -> regcontrol params
    regctrl = {}

    # regulator base name -> total 3-phase kVA (from '! regulator_kva=SID VALUE' comments)
    reg_kva_total = {}

    # ---------------- Parse DSS file ----------------
    with open(dss_path, "r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.lower().startswith("rem"):
                continue

            # parse regulator_kva metadata comment
            if line.startswith("!"):
                kva_m = re.match(r'!\s*regulator_kva=(\S+)\s+([0-9.]+)', line)
                if kva_m:
                    reg_kva_total[kva_m.group(1).lower()] = float(kva_m.group(2))
                continue

            # --- Reactors (jumpers) ---
            rname, rrest = _parse_new_obj(line, "reactor")
            if rname:
                rp = _parse_kv_pairs_simple(rrest)
                if "bus1" in rp and "bus2" in rp:
                    b1 = _strip_dss_nodes(rp["bus1"])
                    b2 = _strip_dss_nodes(rp["bus2"])

                    base = re.sub(r'(?i)_(e|o)$', '', rname)  # Jumper_..._E/O -> Jumper_...
                    if rname.lower().endswith("_e"):
                        mv = b1 if b1.lower().startswith("mv_") else (b2 if b2.lower().startswith("mv_") else None)
                        if mv:
                            jumper_in[base] = mv
                    elif rname.lower().endswith("_o"):
                        mv = b1 if b1.lower().startswith("mv_") else (b2 if b2.lower().startswith("mv_") else None)
                        if mv:
                            jumper_out[base] = mv
                continue

            # --- Transformer ---
            tname, trest = _parse_new_obj(line, "transformer")
            if tname:
                trafo_lines[tname] = line  # collect all; filter by regctrl in 2nd pass
                continue

            # --- Regcontrol ---
            cname, crest = _parse_new_obj(line, "regcontrol")
            if cname:
                cp = _parse_kv_pairs_simple(crest)
                if "transformer" in cp:
                    regctrl[cp["transformer"]] = cp
                continue

    # ---------------- Filter: keep only transformers referenced by a Regcontrol ----------------
    reg_trafo_names = set(regctrl.keys())  # transformer names that have a Regcontrol
    # also accept Regcontrols stored under their control name (already mapped via cp["transformer"])
    reg_trafo_lines = {k: v for k, v in trafo_lines.items() if k in reg_trafo_names}

    # ---------------- Group by base regulator name ----------------
    groups = {}
    for tname, tline in reg_trafo_lines.items():
        base = _base_reg_name(tname)
        groups.setdefault(base, []).append((tname, tline))

    created = 0
    skipped = 0
    controllers = 0

    # ---------------- Build one trafo per group ----------------
    for base, items in groups.items():
        rep_name, rep_line = items[0]  # representative

        # get jumper mapping from winding bus (wdg=1 bus=Jumper_...)
        wdg = _extract_transformer_wdg_blocks(rep_line)
        w1_bus = wdg.get(1, {}).get("bus")
        w2_bus = wdg.get(2, {}).get("bus")
        if not w1_bus or not w2_bus:
            skipped += 1
            continue

        jumper_base = _strip_dss_nodes(w1_bus)

        # Try both with and without _A/_B/_C in case jumpers are stored differently
        jumper_candidates = [jumper_base, re.sub(r'(?i)_[abc]$', '', jumper_base)]
        jumper_key = next((jc for jc in jumper_candidates if jc in jumper_in and jc in jumper_out), None)
        if jumper_key is None:
            skipped += 1
            continue

        up_mv = jumper_in[jumper_key]
        dn_mv = jumper_out[jumper_key]

        hv_bus = get_or_create_mv_bus(up_mv)
        lv_bus = get_or_create_mv_bus(dn_mv)
        net.bus.at[hv_bus, "vn_kv"] = mv_vn_kv
        net.bus.at[lv_bus, "vn_kv"] = mv_vn_kv

        # impedance from transformer line
        tp = _parse_kv_pairs_simple(rep_line.split(None, 3)[-1])

        vk_percent = default_vk_percent
        vkr_percent = default_vkr_percent
        if "xhl" in tp:
            try: vk_percent = float(tp["xhl"])
            except: pass
        if "%loadloss" in tp:
            try: vkr_percent = float(tp["%loadloss"])
            except: pass

        # sn_mva priority: manual override > DSS comment kva_total/1000 > stub kva/1000
        if base in sn_mva_overrides:
            sn_mva = float(sn_mva_overrides[base])
        elif base.lower() in reg_kva_total:
            sn_mva = reg_kva_total[base.lower()] / 1000.0
        else:
            kva = wdg.get(1, {}).get("kva") or wdg.get(2, {}).get("kva")
            sn_mva = (float(kva) / 1000.0) if kva else 1.0

        tid = pp.create_transformer_from_parameters(
            net,
            hv_bus=hv_bus,
            lv_bus=lv_bus,
            sn_mva=sn_mva,
            vn_hv_kv=mv_vn_kv,
            vn_lv_kv=mv_vn_kv,
            vk_percent=vk_percent,
            vkr_percent=vkr_percent,
            pfe_kw=0.0,
            i0_percent=0.0,
            shift_degree=0.0,
            name=base  # ✅ one regulator, no _A/_B/_C
        )
        created += 1

        # -----------------------------
        # ✅ Tap settings FROM DSS
        # -----------------------------
        # numtaps => positions -half..+half (e.g. 16 -> -8..+8)
        try:
            numtaps = int(float(tp.get("numtaps", "16")))
        except Exception:
            numtaps = 16
        half = max(1, numtaps // 2)

        tap_min = -half
        tap_max = half
        tap_neutral = 0

        # Initial tap from DSS: use tap= or tap0= (your old logic assumed [-1..+1])
        tap_raw = tp.get("tap", tp.get("tap0", "0.0"))
        try:
            tap_raw_f = float(tap_raw)
        except Exception:
            tap_raw_f = 0.0

        # Map [-1..+1] -> [-half..+half]
        tap_pos = int(round(tap_raw_f * half))
        tap_pos = max(tap_min, min(tap_max, tap_pos))

        # tap step percent computed from mintap/maxtap and ratio kv2/kv1
        try:
            mintap = float(tp.get("mintap", "-1.0"))
            maxtap = float(tp.get("maxtap", "1.0"))
        except Exception:
            mintap, maxtap = -1.0, 1.0

        kv1 = wdg.get(1, {}).get("kv")
        kv2 = wdg.get(2, {}).get("kv")
        if kv1 and kv2 and numtaps > 0:
            ratio = float(kv2) / float(kv1)  # e.g. 1.27/12.7 = 0.1
            span_pu = (maxtap - mintap) * ratio
            tap_step_percent = (span_pu / numtaps) * 100.0
        else:
            tap_step_percent = 1.25

        net.trafo.at[tid, "tap_side"] = "lv"
        net.trafo.at[tid, "tap_min"] = tap_min
        net.trafo.at[tid, "tap_max"] = tap_max
        net.trafo.at[tid, "tap_neutral"] = tap_neutral
        net.trafo.at[tid, "tap_step_percent"] = float(tap_step_percent)
        net.trafo.at[tid, "tap_pos"] = tap_pos
        net.trafo.at[tid, "tap_phase_shifter"] = False

        # -----------------------------
        # Optional: Controller from Regcontrol (one per set)
        # -----------------------------
        if create_controllers:
            rc = regctrl.get(rep_name)
            if rc:
                try:
                    vreg = float(rc.get("vreg", "100.0"))
                    band = float(rc.get("band", "3.0"))
                    ptr = float(rc.get("ptratio", "127.0"))
                    v_target = vreg * ptr
                    band_v = band * ptr
                    band_pu = band_v / v_target if v_target > 0 else 0.03
                    tol = max(0.005, band_pu / 2.0)

                    from pandapower.control import DiscreteTapControl
                    DiscreteTapControl(net, tid=tid, vm_set_pu=1.0, side="lv", tol=tol)
                    controllers += 1
                except Exception:
                    pass

    return created, skipped, controllers
if config.REGS_DSS.exists():
    created, skipped, ctrls = build_mv_regulators_from_dss_one_per_set(
        net,
        dss_path=REGULATORS_DSS_PATH,
        get_or_create_mv_bus=get_or_create_mv_bus,
        mv_vn_kv=22.0,
        sn_mva_overrides=config.REG_SN_MVA_OVERRIDES,
        create_controllers=True
    )
else:
    created, skipped, ctrls = 0, 0, 0

MV_CAPACITORS_PATH = str(config.CAPS_DSS)

def create_mv_capacitors_from_dss(net, dss_path: str, get_or_create_mv_bus):
    created = 0
    skipped = 0

    with open(dss_path, "r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("!") or line.lower().startswith("rem"):
                continue

            m = re.match(r'(?i)^new\s+capacitor\.([^\s]+)\s+(.*)$', line)
            if not m:
                continue

            cap_name = m.group(1)
            rest = m.group(2)

            # parse key=value (κρατάει απλά tokens)
            tokens = re.findall(r'(?i)(\w+)\s*=\s*("[^"]*"|\'[^\']*\'|[^\s]+)', rest)
            params = {k.lower(): v.strip('"').strip("'") for k, v in tokens}

            if "bus1" not in params or "kvar" not in params:
                skipped += 1
                continue

            bus1 = params["bus1"].split(".")[0]  # mv_f0_n2817.1.2.3 -> mv_f0_n2817
            bus_idx = get_or_create_mv_bus(bus1)

            try:
                kvar = float(params["kvar"])
            except:
                skipped += 1
                continue

            q_mvar = kvar / 1000.0  # kvar -> Mvar

            pp.create_shunt(
                net,
                bus=bus_idx,
                q_mvar=q_mvar,   # capacitor injection
                p_mw=0.0,
                name=cap_name
            )
            created += 1

    return created, skipped
if config.CAPS_DSS.exists():
    created_caps, skipped_caps = create_mv_capacitors_from_dss(
        net,
        dss_path=MV_CAPACITORS_PATH,
        get_or_create_mv_bus=get_or_create_mv_bus
    )
else:
    created_caps, skipped_caps = 0, 0

def replace_short_lines_with_switches(
    net,
    length_threshold_km=0.001,
    switch_type="CB",
    close_switch=True,
    only_in_service=True,
):
    """
    Replace all lines with length_km <= length_threshold_km by bus-bus switches.
    """

    # mask for in_service lines
    if only_in_service and "in_service" in net.line.columns:
        mask = net.line["in_service"]
    else:
        mask = True

    short_lines = net.line[
        (net.line["length_km"] <= length_threshold_km) & mask
    ]

    created_switches = []

    for idx, row in short_lines.iterrows():
        fb = int(row["from_bus"])
        tb = int(row["to_bus"])

        # disable line
        net.line.at[idx, "in_service"] = False

        # create bus-bus switch
        sw = pp.create_switch(
            net,
            bus=fb,
            element=tb,
            et="b",   # bus-bus
            closed=close_switch,
            type=switch_type,
            name=f"SW_{row['name']}" if "name" in net.line.columns else f"SW_line_{idx}"
        )
        created_switches.append(sw)

    return short_lines.index.tolist(), created_switches
bad_idx, sw_idx = replace_short_lines_with_switches(
    net,
    length_threshold_km=0.001
)
from pandapower import to_excel

if __name__ == "__main__":
    to_excel(net, str(config.MV_NET_XLSX))



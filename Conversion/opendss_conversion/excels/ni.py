import re
import numpy as np
import pandas as pd
from pandapower import from_excel

# =========================================================
# PATHS
# =========================================================
NET_XLSX = r"C:\Users\anton\Desktop\nando_pp\excels\net_pp_3ph_ready.xlsx"

PP_VM_A_CSV = r"C:\Users\anton\Desktop\nando_pp\results\res_bus_3ph\vm_a_pu.csv"
PP_VM_B_CSV = r"C:\Users\anton\Desktop\nando_pp\results\res_bus_3ph\vm_b_pu.csv"
PP_VM_C_CSV = r"C:\Users\anton\Desktop\nando_pp\results\res_bus_3ph\vm_c_pu.csv"

DSS_XLSX = r"C:\Users\anton\Desktop\nando_pp\excels\Vdata_48steps.xlsx"
DSS_SHEET = "Voltages"

OUT_XLSX = r"C:\Users\anton\Desktop\nando_pp\metrics\vm_phase_aware_compare.xlsx"

SEP = ";"

# =========================================================
# HELPERS
# =========================================================
def norm_name(s):
    if pd.isna(s):
        return None
    s = str(s).strip().lower()
    s = re.sub(r"\s+", "", s)
    return s

def parse_dss_bus_phase(col):
    m = re.match(r"^(.*)\.(1|2|3)$", str(col).strip())
    if not m:
        return None, None
    return m.group(1), m.group(2)

def load_pp_phase_csv(path, sep=";"):
    df = pd.read_csv(path, sep=sep)

    keep_cols = []
    for c in df.columns:
        cs = str(c).strip()
        if re.fullmatch(r"\d+", cs):
            keep_cols.append(cs)

    if not keep_cols:
        raise ValueError(f"Δεν βρέθηκαν numeric bus-index columns στο {path}")

    df = df[keep_cols].copy()
    df.columns = [int(c) for c in df.columns]
    df.reset_index(drop=True, inplace=True)
    return df

def calc_metrics(diff):
    diff = pd.Series(diff).dropna()
    if len(diff) == 0:
        return {
            "N": 0,
            "MAE_pu": np.nan,
            "RMSE_pu": np.nan,
            "MAX_ABS_DIFF_pu": np.nan,
            "MEAN_SIGNED_DIFF_pu": np.nan,
            "MAE_pp": np.nan,
            "MAX_ABS_DIFF_pp": np.nan,
        }

    absdiff = diff.abs()
    return {
        "N": int(len(diff)),
        "MAE_pu": float(absdiff.mean()),
        "RMSE_pu": float(np.sqrt((diff**2).mean())),
        "MAX_ABS_DIFF_pu": float(absdiff.max()),
        "MEAN_SIGNED_DIFF_pu": float(diff.mean()),
        "MAE_pp": float(absdiff.mean() * 100.0),
        "MAX_ABS_DIFF_pp": float(absdiff.max() * 100.0),
    }

# =========================================================
# 1) LOAD NET
# =========================================================
net = from_excel(NET_XLSX)

if "name" not in net.bus.columns:
    raise ValueError("Το net.bus δεν έχει στήλη 'name'.")

if "vn_kv" not in net.bus.columns:
    raise ValueError("Το net.bus δεν έχει στήλη 'vn_kv'.")

bus_map = net.bus[["name", "vn_kv"]].copy()
bus_map["name_norm"] = bus_map["name"].apply(norm_name)
bus_map["pp_bus_idx"] = bus_map.index

name_to_idx = (
    bus_map.dropna(subset=["name_norm"])
           .drop_duplicates(subset=["name_norm"], keep="first")
           .set_index("name_norm")["pp_bus_idx"]
           .to_dict()
)

# =========================================================
# 2) LOAD PP RESULTS
# =========================================================
pp_a = load_pp_phase_csv(PP_VM_A_CSV, sep=SEP)
pp_b = load_pp_phase_csv(PP_VM_B_CSV, sep=SEP)
pp_c = load_pp_phase_csv(PP_VM_C_CSV, sep=SEP)

n_pp = len(pp_a)
if len(pp_b) != n_pp or len(pp_c) != n_pp:
    raise ValueError("Τα pp phase csv δεν έχουν ίδιο αριθμό timesteps.")

phase_to_pp = {
    "1": ("a", pp_a),
    "2": ("b", pp_b),
    "3": ("c", pp_c),
}

# =========================================================
# 3) LOAD DSS VDATA
# =========================================================
dss = pd.read_excel(DSS_XLSX, sheet_name=DSS_SHEET)
dss.reset_index(drop=True, inplace=True)

n_dss = len(dss)
if n_dss != n_pp:
    print(f"[WARNING] Διαφορετικός αριθμός timesteps: DSS={n_dss}, PP={n_pp}")
    n_steps = min(n_dss, n_pp)
    dss = dss.iloc[:n_steps].copy()
    pp_a = pp_a.iloc[:n_steps].copy()
    pp_b = pp_b.iloc[:n_steps].copy()
    pp_c = pp_c.iloc[:n_steps].copy()
else:
    n_steps = n_dss

phase_to_pp = {
    "1": ("a", pp_a),
    "2": ("b", pp_b),
    "3": ("c", pp_c),
}

valid_dss_cols = []
for c in dss.columns:
    base_bus, ph = parse_dss_bus_phase(c)
    if base_bus is not None:
        valid_dss_cols.append(c)

if not valid_dss_cols:
    raise ValueError("Δεν βρέθηκαν DSS columns της μορφής bus.phase")

dss = dss[valid_dss_cols].copy()

# =========================================================
# 4) MATCH + CONVERT DSS VOLTS -> PU
# =========================================================
rows = []

for col in dss.columns:
    dss_base_bus, dss_phase = parse_dss_bus_phase(col)
    dss_base_bus_norm = norm_name(dss_base_bus)

    if dss_base_bus_norm not in name_to_idx:
        continue

    pp_bus_idx = name_to_idx[dss_base_bus_norm]
    pp_phase_label, pp_df = phase_to_pp[dss_phase]

    if pp_bus_idx not in pp_df.columns:
        continue

    vn_kv = float(net.bus.at[pp_bus_idx, "vn_kv"])

    # Υποθέτουμε ότι το DSS Vdata είναι phase-to-neutral volts
    vbase_ph_n_volts = 230.9

    dss_vals_volts = pd.to_numeric(dss[col], errors="coerce")
    dss_vals_pu = dss_vals_volts / vbase_ph_n_volts
    pp_vals = pd.to_numeric(pp_df[pp_bus_idx], errors="coerce")

    for t in range(n_steps):
        dss_v_volts = dss_vals_volts.iloc[t]
        dss_v_pu = dss_vals_pu.iloc[t]
        pp_v = pp_vals.iloc[t]

        if pd.isna(dss_v_volts) or pd.isna(dss_v_pu) or pd.isna(pp_v):
            continue

        diff = pp_v - dss_v_pu

        rows.append({
            "time_step": t,
            "bus_name": dss_base_bus,
            "bus_name_norm": dss_base_bus_norm,
            "dss_phase": dss_phase,
            "pp_phase": pp_phase_label,
            "pp_bus_idx": pp_bus_idx,
            "vn_kv": vn_kv,
            "vbase_ph_n_volts": float(vbase_ph_n_volts),
            "dss_vm_volts": float(dss_v_volts),
            "dss_vm_pu": float(dss_v_pu),
            "pp_vm_pu": float(pp_v),
            "diff_pu": float(diff),
            "abs_diff_pu": float(abs(diff)),
            "abs_diff_pp": float(abs(diff) * 100.0),
        })

matched = pd.DataFrame(rows)

if matched.empty:
    raise ValueError("Δεν βρέθηκαν κοινά matched bus-phase σημεία μεταξύ DSS και pandapower.")

# =========================================================
# 5) METRICS
# =========================================================
global_metrics = pd.DataFrame([calc_metrics(matched["diff_pu"])])
global_metrics.insert(0, "scope", "GLOBAL")

phase_metrics = []
for ph in ["1", "2", "3"]:
    sub = matched.loc[matched["dss_phase"] == ph]
    m = calc_metrics(sub["diff_pu"])
    m["scope"] = f"PHASE_{ph}"
    phase_metrics.append(m)

phase_metrics = pd.DataFrame(phase_metrics)

per_bus = []
for bus_name, g in matched.groupby("bus_name"):
    m = calc_metrics(g["diff_pu"])
    m["bus_name"] = bus_name
    per_bus.append(m)

per_bus = pd.DataFrame(per_bus)
per_bus = per_bus[
    ["bus_name", "N", "MAE_pu", "RMSE_pu", "MAX_ABS_DIFF_pu",
     "MEAN_SIGNED_DIFF_pu", "MAE_pp", "MAX_ABS_DIFF_pp"]
].sort_values(["MAE_pp", "MAX_ABS_DIFF_pp"], ascending=False)

# =========================================================
# 6) DEBUG
# =========================================================
debug_rows = []
for col in dss.columns:
    base_bus, ph = parse_dss_bus_phase(col)
    nn = norm_name(base_bus)
    found_bus = nn in name_to_idx
    pp_idx = name_to_idx.get(nn, np.nan)
    pp_has_col = False
    vn_kv = np.nan
    vbase_ph_n_volts = 230.9

    if found_bus:
        _, pp_df = phase_to_pp[ph]
        pp_has_col = pp_idx in pp_df.columns
        vn_kv = float(net.bus.at[pp_idx, "vn_kv"])
        vbase_ph_n_volts = 230.9

    debug_rows.append({
        "dss_bus_name": base_bus,
        "dss_phase": ph,
        "name_norm": nn,
        "found_in_pp_net": found_bus,
        "pp_bus_idx": pp_idx,
        "pp_phase_column_exists": pp_has_col,
        "vn_kv": vn_kv,
        "vbase_ph_n_volts": vbase_ph_n_volts,
    })

debug_df = pd.DataFrame(debug_rows).drop_duplicates()

# =========================================================
# 7) EXPORT
# =========================================================
with pd.ExcelWriter(OUT_XLSX, engine="openpyxl") as writer:
    matched.to_excel(writer, sheet_name="matched_points", index=False)
    global_metrics.to_excel(writer, sheet_name="global_metrics", index=False)
    phase_metrics.to_excel(writer, sheet_name="phase_metrics", index=False)
    per_bus.to_excel(writer, sheet_name="per_bus_metrics", index=False)
    debug_df.to_excel(writer, sheet_name="debug_matching", index=False)

print("\n=== DONE ===")
print(f"Matched points: {len(matched)}")
print(f"Unique buses matched: {matched['bus_name'].nunique()}")
print(f"Output: {OUT_XLSX}")

print("\n=== GLOBAL METRICS ===")
print(global_metrics.to_string(index=False))

print("\n=== PHASE METRICS ===")
print(phase_metrics.to_string(index=False))

print("\n=== TOP 10 WORST BUSES ===")
print(per_bus.head(10).to_string(index=False))
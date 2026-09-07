import sys
import os
import pandas as pd
import numpy as np
from pathlib import Path
from pandapower import from_excel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

# =========================
# PATHS  (from config.py)
# =========================
NET_XLSX   = str(config.NET_PP_XLSX)
PP_VM_CSV  = str(config.RESULTS_RES_BUS / "vm_pu.csv")
DSS_VM_CSV = str(config.DSS_VM_MEAN_PU_CSV)

config.METRICS_OUT_DIR.mkdir(parents=True, exist_ok=True)

SEP = ";"   # separator του PP csv
EPS = 1e-9

# =========================
# 1) Load net
# =========================
net = from_excel(NET_XLSX)
net.bus["name"] = net.bus["name"].astype(str).str.strip()

# =========================
# 2) Read PP vm_pu
# columns = bus indices
# =========================
pp = pd.read_csv(PP_VM_CSV, sep=SEP, engine="python", encoding="latin1")

if "time_step" in pp.columns:
    pp = pp.set_index("time_step")
else:
    pp = pp.set_index(pp.columns[0])

pp.index = pd.to_numeric(pp.index.astype(str).str.strip(), errors="coerce")
pp.columns = pp.columns.astype(str).str.strip()
pp = pp.apply(pd.to_numeric, errors="coerce")
pp = pp.loc[~pp.index.isna()].sort_index()

# =========================
# 3) Read OpenDSS mean-per-bus vm_pu CSV
# columns = bus names
# =========================
dss = pd.read_csv(DSS_VM_CSV)

if "timestep" in dss.columns:
    dss = dss.set_index("timestep")
else:
    dss = dss.set_index(dss.columns[0])

dss.index = pd.to_numeric(dss.index.astype(str).str.strip(), errors="coerce")
dss.columns = dss.columns.astype(str).str.strip()
dss = dss.apply(pd.to_numeric, errors="coerce")
dss = dss.loc[~dss.index.isna()].sort_index()

# =========================
# 4) Common timesteps
# =========================
common_idx = pp.index.intersection(dss.index)

if len(common_idx) == 0:
    print("PP index head :", pp.index[:10].tolist())
    print("DSS index head:", dss.index[:10].tolist())
    raise ValueError("Δεν υπάρχουν κοινά timesteps μεταξύ PP και OpenDSS.")

pp = pp.loc[common_idx]
dss = dss.loc[common_idx]

# =========================
# 5) Mapping: DSS bus name -> PP bus index
# =========================
dss_bus_names = set(dss.columns)

name_to_idx = {}
for idx, name in net.bus["name"].items():
    if name in dss_bus_names:
        name_to_idx[name] = idx

matched_names = sorted(name_to_idx.keys())

if len(matched_names) == 0:
    print("DSS cols sample:", list(dss.columns[:20]))
    print("net.bus['name'] sample:", net.bus["name"].head(20).tolist())
    raise ValueError("Δεν βρέθηκε κανένα κοινό bus name μεταξύ pandapower net και OpenDSS csv.")

# =========================
# 6) Compute per-bus metrics
# =========================
rows = []
all_abs = []
all_sgn = []

for name in matched_names:
    idx = name_to_idx[name]
    pp_col = str(idx)   # PP columns are bus indices as strings

    if pp_col not in pp.columns:
        continue

    s_pp = pp[pp_col]
    s_dss = dss[name]

    tmp = pd.concat([s_pp, s_dss], axis=1, keys=["pp", "dss"]).dropna()
    if tmp.empty:
        continue

    err_pct = 100.0 * (tmp["pp"] - tmp["dss"]) / (tmp["dss"].abs() + EPS)
    abs_err_pct = err_pct.abs()
    abs_diff_pu = (tmp["pp"] - tmp["dss"]).abs()

    rows.append({
        "bus_name": name,
        "pp_bus_idx": int(idx),
        "N": int(len(tmp)),
        "MAPE_%": float(abs_err_pct.mean()),
        "Max_%": float(abs_err_pct.max()),
        "MeanSigned_%": float(err_pct.mean()),
        "MAE_pu": float(abs_diff_pu.mean()),
        "MaxAbsDiff_pu": float(abs_diff_pu.max()),
    })

    all_abs.append(abs_err_pct.to_numpy())
    all_sgn.append(err_pct.to_numpy())

per_bus = pd.DataFrame(rows)

if per_bus.empty:
    raise ValueError("Δεν βρέθηκε κανένα bus με διαθέσιμα δεδομένα και στα δύο αρχεία.")

per_bus = per_bus.sort_values("MAPE_%", ascending=False).reset_index(drop=True)

# =========================
# 7) Global metrics
# =========================
all_abs = np.concatenate(all_abs) if len(all_abs) else np.array([])
all_sgn = np.concatenate(all_sgn) if len(all_sgn) else np.array([])

global_mape = float(np.mean(all_abs)) if all_abs.size else np.nan
global_max  = float(np.max(all_abs)) if all_abs.size else np.nan
global_bias = float(np.mean(all_sgn)) if all_sgn.size else np.nan

# weighted by number of points (already effectively global above)
matched_buses = int(per_bus.shape[0])
total_points = int(all_abs.size)

# =========================
# 8) Save outputs
# =========================
per_bus_csv = str(config.METRIC_PER_BUS)
global_txt  = str(config.METRIC_GLOBAL_TXT)

per_bus.to_csv(per_bus_csv, index=False)

with open(global_txt, "w", encoding="utf-8") as f:
    f.write(f"Matched buses: {matched_buses}\n")
    f.write(f"Total points: {total_points}\n")
    f.write(f"Global MAPE %: {global_mape:.6f}\n")
    f.write(f"Global Max  %: {global_max:.6f}\n")
    f.write(f"Global Bias %: {global_bias:.6f}\n")

print("Saved:")
print(per_bus_csv)
print(global_txt)

print("\n=== GLOBAL ===")
print("Matched buses:", matched_buses)
print("Total points  :", total_points)
print("Global MAPE % :", round(global_mape, 6))
print("Global Max  % :", round(global_max, 6))
print("Global Bias % :", round(global_bias, 6))

print("\n=== TOP 10 WORST ===")
print(per_bus.head(10).to_string(index=False))
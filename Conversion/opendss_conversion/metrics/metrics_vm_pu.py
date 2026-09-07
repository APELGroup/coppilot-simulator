import sys
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

DSS_XLSX   = str(config.DSS_VM_PU_XLSX)
DSS_SHEET  = "vm_pu"

SEP = ";"   # separator του PP csv


def main():
    # =========================
    # 1) Load net + read PP vm_pu (columns = bus index)
    # =========================
    net = from_excel(NET_XLSX)
    net.bus["name"] = net.bus["name"].astype(str)

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
    # 2) Read DSS excel (columns = bus name)
    # =========================
    dss = pd.read_excel(DSS_XLSX, sheet_name=DSS_SHEET, engine="openpyxl")

    if "timestep" in dss.columns:
        dss = dss.set_index("timestep")
    else:
        dss = dss.set_index(dss.columns[0])

    dss.index = pd.to_numeric(dss.index.astype(str).str.strip(), errors="coerce")
    dss.columns = dss.columns.astype(str).str.strip()
    dss = dss.apply(pd.to_numeric, errors="coerce")
    dss = dss.loc[~dss.index.isna()].sort_index()

    # =========================
    # 3) Find common timesteps
    # =========================
    common_idx = pp.index.intersection(dss.index)
    if len(common_idx) == 0:
        print("PP index head:", pp.index[:10].tolist())
        print("DSS index head:", dss.index[:10].tolist())
        raise ValueError("Δεν υπάρχουν κοινά timesteps μεταξύ PP και DSS.")

    pp  = pp.loc[common_idx]
    dss = dss.loc[common_idx]

    # =========================
    # 4) Build mapping: DSS bus name -> PP column (bus index as string)
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
        raise ValueError("Δεν βρέθηκε κανένα κοινό bus name μεταξύ net και DSS excel.")

    # =========================
    # 5) Compute per-bus metrics
    # =========================
    eps = 1e-9
    rows = []
    all_abs = []
    all_sgn = []

    for name in matched_names:
        idx = name_to_idx[name]
        pp_col = str(idx)

        if pp_col not in pp.columns:
            continue

        s_pp  = pp[pp_col]
        s_dss = dss[name]

        tmp = pd.concat([s_pp, s_dss], axis=1, keys=["pp", "dss"]).dropna()
        if tmp.empty:
            continue

        pct = 100.0 * (tmp["pp"] - tmp["dss"]) / (tmp["dss"].abs() + eps)
        apct = pct.abs()

        rows.append({
            "bus_name": name,
            "pp_bus_idx": idx,
            "N": int(len(tmp)),
            "MAPE_%": float(apct.mean()),
            "Max_%": float(apct.max()),
            "MeanSigned_%": float(pct.mean()),
        })

        all_abs.append(apct.to_numpy())
        all_sgn.append(pct.to_numpy())

    per_bus = pd.DataFrame(rows)

    if per_bus.empty:
        raise ValueError("Μετά το mapping δεν βγήκε κανένα bus με διαθέσιμα δεδομένα και στα δύο.")

    per_bus = per_bus.sort_values("MAPE_%", ascending=False)

    all_abs = np.concatenate(all_abs) if len(all_abs) else np.array([])
    all_sgn = np.concatenate(all_sgn) if len(all_sgn) else np.array([])

    global_mape = float(np.mean(all_abs)) if all_abs.size else np.nan
    global_max  = float(np.max(all_abs))  if all_abs.size else np.nan
    global_bias = float(np.mean(all_sgn)) if all_sgn.size else np.nan

    # =========================
    # 6) Save
    # =========================
    per_bus.to_csv(str(config.METRIC_PER_BUS), index=False)

    with open(str(config.METRIC_GLOBAL_TXT), "w", encoding="utf-8") as f:
        f.write(f"Matched buses: {int(per_bus.shape[0])}\n")
        f.write(f"Total points: {int(all_abs.size)}\n")
        f.write(f"Global MAPE %: {global_mape:.6f}\n")
        f.write(f"Global Max  %: {global_max:.6f}\n")
        f.write(f"Global Bias %: {global_bias:.6f}\n")

    print(f"Global MAPE: {global_mape:.4f}%  |  Max: {global_max:.4f}%  |  Bias: {global_bias:.4f}%")
    print(f"Saved: {config.METRIC_PER_BUS}")
    print(f"Saved: {config.METRIC_GLOBAL_TXT}")


if __name__ == "__main__":
    main()

print("Saved: metric_per_bus.csv, metric_global.txt")
print("\n=== GLOBAL ===")
print("Matched buses:", per_bus.shape[0])
print("Global MAPE %:", round(global_mape, 6))
print("Global Max  %:", round(global_max, 6))
print("Global Bias %:", round(global_bias, 6))

print("\n=== TOP 10 WORST ===")
print(per_bus.head(10))
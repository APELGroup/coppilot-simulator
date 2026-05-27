"""
metrics_3ph_vm_pu.py
────────────────────
Συγκρίνει τα 3-phase αποτελέσματα pandapower (res_bus_3ph/vm_a_pu.csv κ.λπ.)
με τα αποτελέσματα OpenDSS (Vdata_all_buses_clean.csv).

DSS format  : index=timestep, columns='bus_name.1' / '.2' / '.3', τιμές σε Volts
PP  format  : index=time_step, columns=bus_index (str), τιμές σε pu, sep=';'
              ξεχωριστό αρχείο ανά φάση (vm_a_pu.csv, vm_b_pu.csv, vm_c_pu.csv)

Μετατροπή DSS → pu : V / (vn_kv * 1000 / sqrt(3))  (LN base)
Φάση mapping       : .1 → A,  .2 → B,  .3 → C
"""

import sys
import math
import pandas as pd
import numpy as np
from pathlib import Path
from pandapower import from_excel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

# =========================
# PATHS
# =========================
NET_XLSX   = str(config.NET_PP_XLSX)
DSS_CSV    = str(config.DSS_VDATA_CLEAN)
PP_A_CSV   = str(config.RESULTS_RES_BUS_3PH / "vm_a_pu.csv")
PP_B_CSV   = str(config.RESULTS_RES_BUS_3PH / "vm_b_pu.csv")
PP_C_CSV   = str(config.RESULTS_RES_BUS_3PH / "vm_c_pu.csv")

SEP = ";"   # separator των PP 3ph CSVs


def _load_pp_phase(csv_path: str) -> pd.DataFrame:
    """Φορτώνει ένα vm_X_pu.csv (sep=';', index=time_step, columns=bus_index)."""
    df = pd.read_csv(csv_path, sep=SEP, engine="python", encoding="latin1", index_col=0)
    df.index = pd.to_numeric(df.index.astype(str).str.strip(), errors="coerce")
    df.columns = df.columns.astype(str).str.strip()
    df = df.apply(pd.to_numeric, errors="coerce")
    return df.loc[~df.index.isna()].sort_index()


def main():
    # ── 1) Φόρτωση net (για bus name→index και vn_kv) ────────────────────────
    net = from_excel(NET_XLSX)
    net.bus["name"] = net.bus["name"].astype(str)

    # bus_name → (index, vn_kv)
    bus_info = {
        row["name"]: (idx, float(row["vn_kv"]))
        for idx, row in net.bus.iterrows()
    }

    # ── 2) Φόρτωση PP 3ph αποτελεσμάτων ──────────────────────────────────────
    pp_a = _load_pp_phase(PP_A_CSV)
    pp_b = _load_pp_phase(PP_B_CSV)
    pp_c = _load_pp_phase(PP_C_CSV)

    pp_by_phase = {"1": pp_a, "2": pp_b, "3": pp_c}   # DSS .1/.2/.3

    # ── 3) Φόρτωση DSS αρχείου (Volts) ────────────────────────────────────────
    dss_raw = pd.read_csv(DSS_CSV, index_col=0)
    dss_raw.index = pd.to_numeric(dss_raw.index.astype(str).str.strip(), errors="coerce")
    dss_raw = dss_raw.loc[~dss_raw.index.isna()].sort_index()

    # ── 4) Κοινά timesteps ────────────────────────────────────────────────────
    common_idx = pp_a.index
    for df in [pp_b, pp_c, dss_raw]:
        common_idx = common_idx.intersection(df.index)

    if len(common_idx) == 0:
        raise ValueError("Δεν υπάρχουν κοινά timesteps μεταξύ PP και DSS.")

    pp_a   = pp_a.loc[common_idx]
    pp_b   = pp_b.loc[common_idx]
    pp_c   = pp_c.loc[common_idx]
    pp_by_phase = {"1": pp_a, "2": pp_b, "3": pp_c}
    dss_raw = dss_raw.loc[common_idx]

    # ── 5) Υπολογισμός metrics ανά (bus, phase) ───────────────────────────────
    eps = 1e-9
    rows = []
    all_abs, all_sgn = [], []

    for col in dss_raw.columns:
        # col format: "bus_name.1" / "bus_name.2" / "bus_name.3"
        parts = col.rsplit(".", 1)
        if len(parts) != 2:
            continue
        bus_name, phase = parts[0], parts[1]
        if phase not in ("1", "2", "3"):
            continue
        if bus_name not in bus_info:
            continue

        bus_idx, vn_kv = bus_info[bus_name]
        pp_df = pp_by_phase[phase]
        pp_col = str(bus_idx)

        if pp_col not in pp_df.columns:
            continue

        # DSS Volts → pu  (LN base voltage)
        base_v_ln = (vn_kv * 1000.0) / math.sqrt(3)
        s_dss_pu = dss_raw[col] / base_v_ln

        s_pp = pp_df[pp_col]

        tmp = pd.concat([s_pp, s_dss_pu], axis=1, keys=["pp", "dss"]).dropna()
        if tmp.empty:
            continue

        pct  = 100.0 * (tmp["pp"] - tmp["dss"]) / (tmp["dss"].abs() + eps)
        apct = pct.abs()

        phase_letter = {"1": "A", "2": "B", "3": "C"}[phase]
        rows.append({
            "bus_name":    bus_name,
            "phase":       phase_letter,
            "pp_bus_idx":  bus_idx,
            "vn_kv":       vn_kv,
            "N":           int(len(tmp)),
            "MAPE_%":      float(apct.mean()),
            "Max_%":       float(apct.max()),
            "MeanSigned_%": float(pct.mean()),
        })
        all_abs.append(apct.to_numpy())
        all_sgn.append(pct.to_numpy())

    # ── 6) Αποτελέσματα ───────────────────────────────────────────────────────
    per_bus = pd.DataFrame(rows)

    if per_bus.empty:
        raise ValueError(
            "Δεν βρέθηκε κανένα κοινό (bus, phase) μεταξύ PP 3ph και DSS clean.\n"
            "Έλεγξε ότι τα res_bus_3ph/*.csv και το Vdata_all_buses_clean.csv υπάρχουν."
        )

    per_bus = per_bus.sort_values("MAPE_%", ascending=False)

    all_abs = np.concatenate(all_abs) if all_abs else np.array([])
    all_sgn = np.concatenate(all_sgn) if all_sgn else np.array([])

    global_mape = float(np.mean(all_abs)) if all_abs.size else np.nan
    global_max  = float(np.max(all_abs))  if all_abs.size else np.nan
    global_bias = float(np.mean(all_sgn)) if all_sgn.size else np.nan

    # per-phase global summary
    phase_summary = (
        per_bus.groupby("phase")[["MAPE_%", "Max_%", "MeanSigned_%"]]
        .mean()
        .round(4)
    )

    # ── 7) Αποθήκευση ─────────────────────────────────────────────────────────
    out_csv = str(config.METRIC_3PH_PER_BUS)
    out_txt = str(config.METRIC_3PH_GLOBAL_TXT)

    config.METRICS_OUT_DIR.mkdir(parents=True, exist_ok=True)

    per_bus.to_csv(out_csv, index=False)

    with open(out_txt, "w", encoding="utf-8") as f:
        f.write(f"Matched (bus, phase) pairs : {int(per_bus.shape[0])}\n")
        f.write(f"Total comparison points    : {int(all_abs.size)}\n")
        f.write(f"Global MAPE  % : {global_mape:.6f}\n")
        f.write(f"Global Max   % : {global_max:.6f}\n")
        f.write(f"Global Bias  % : {global_bias:.6f}\n\n")
        f.write("Per-phase averages:\n")
        f.write(phase_summary.to_string())
        f.write("\n")

    print(f"\nGlobal MAPE : {global_mape:.4f}%  |  Max : {global_max:.4f}%  |  Bias : {global_bias:.4f}%")
    print("\nPer-phase averages:")
    print(phase_summary.to_string())
    print(f"\nSaved: {out_csv}")
    print(f"Saved: {out_txt}")


if __name__ == "__main__":
    main()

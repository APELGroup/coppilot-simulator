import re
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
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

SEP = ";"

# =========================================================
# USER SETTINGS
# =========================================================
TARGET_BUS = "mv_f0_lv585_f0_c0"   # βαλε εδω το bus name
TARGET_PHASE = "1"                 # "1", "2", or "3"

# αν θες fixed base για LV:
USE_FIXED_LV_BASE = True
LV_BASE_VOLTS = 230.9

# =========================================================
# HELPERS
# =========================================================
def norm_name(s):
    if pd.isna(s):
        return None
    s = str(s).strip().lower()
    s = re.sub(r"\s+", "", s)
    return s

def load_pp_phase_csv(path, sep=";"):
    df = pd.read_csv(path, sep=sep)

    keep_cols = []
    for c in df.columns:
        if str(c).strip().isdigit():
            keep_cols.append(c)

    if not keep_cols:
        raise ValueError(f"Δεν βρέθηκαν numeric bus-index columns στο {path}")

    df = df[keep_cols].copy()
    df.columns = [int(c) for c in df.columns]
    df.reset_index(drop=True, inplace=True)
    return df

# =========================================================
# LOAD NET
# =========================================================
net = from_excel(NET_XLSX)

if "name" not in net.bus.columns:
    raise ValueError("Το net.bus δεν έχει στήλη 'name'")

if "vn_kv" not in net.bus.columns:
    raise ValueError("Το net.bus δεν έχει στήλη 'vn_kv'")

net.bus["name_norm"] = net.bus["name"].apply(norm_name)

target_norm = norm_name(TARGET_BUS)

matches = net.bus.index[net.bus["name_norm"] == target_norm].tolist()
if not matches:
    raise ValueError(f"Το bus '{TARGET_BUS}' δεν βρέθηκε στο pandapower net")

pp_bus_idx = matches[0]
vn_kv = float(net.bus.at[pp_bus_idx, "vn_kv"])

# =========================================================
# SELECT PP PHASE FILE
# =========================================================
pp_a = load_pp_phase_csv(PP_VM_A_CSV, sep=SEP)
pp_b = load_pp_phase_csv(PP_VM_B_CSV, sep=SEP)
pp_c = load_pp_phase_csv(PP_VM_C_CSV, sep=SEP)

phase_to_pp = {
    "1": ("a", pp_a),
    "2": ("b", pp_b),
    "3": ("c", pp_c),
}

if TARGET_PHASE not in phase_to_pp:
    raise ValueError("Η phase πρέπει να είναι '1', '2' ή '3'")

pp_phase_label, pp_df = phase_to_pp[TARGET_PHASE]

if pp_bus_idx not in pp_df.columns:
    raise ValueError(
        f"Το pp bus index {pp_bus_idx} δεν υπάρχει στο phase file για phase {TARGET_PHASE}"
    )

pp_series = pd.to_numeric(pp_df[pp_bus_idx], errors="coerce").reset_index(drop=True)

# =========================================================
# LOAD DSS
# =========================================================
dss = pd.read_excel(DSS_XLSX, sheet_name=DSS_SHEET)

dss_col = f"{TARGET_BUS}.{TARGET_PHASE}"
if dss_col not in dss.columns:
    raise ValueError(f"Η DSS στήλη '{dss_col}' δεν βρέθηκε στο Excel")

dss_volts = pd.to_numeric(dss[dss_col], errors="coerce").reset_index(drop=True)

# =========================================================
# DSS VOLTS -> PU
# =========================================================
if USE_FIXED_LV_BASE and vn_kv < 1.0:
    vbase_ph_n_volts = LV_BASE_VOLTS
else:
    vbase_ph_n_volts = vn_kv * 1000.0 / np.sqrt(3.0)

dss_pu = dss_volts / vbase_ph_n_volts

# =========================================================
# ALIGN LENGTHS
# =========================================================
n = min(len(pp_series), len(dss_pu))
pp_series = pp_series.iloc[:n]
dss_pu = dss_pu.iloc[:n]
dss_volts = dss_volts.iloc[:n]

time_steps = np.arange(n)

# =========================================================
# INFO
# =========================================================
print("=== BUS INFO ===")
print("TARGET_BUS        :", TARGET_BUS)
print("TARGET_PHASE      :", TARGET_PHASE)
print("PP phase label    :", pp_phase_label)
print("PP bus idx        :", pp_bus_idx)
print("vn_kv             :", vn_kv)
print("vbase_ph_n_volts  :", vbase_ph_n_volts)
print("DSS column        :", dss_col)
print()

print("=== FIRST 10 VALUES ===")
debug_df = pd.DataFrame({
    "time_step": time_steps,
    "dss_volts": dss_volts,
    "dss_pu": dss_pu,
    "pp_pu": pp_series,
    "diff_pu": pp_series - dss_pu
})
print(debug_df.head(10).to_string(index=False))

# =========================================================
# PLOT
# =========================================================
plt.figure(figsize=(12, 6))
plt.plot(time_steps, pp_series, label=f"pandapower phase {pp_phase_label} (pu)")
plt.plot(time_steps, dss_pu, label=f"OpenDSS phase {TARGET_PHASE} (pu)")
plt.xlabel("Time step")
plt.ylabel("Voltage (pu)")
plt.title(f"Voltage comparison for {TARGET_BUS} - phase {TARGET_PHASE}")
plt.grid(True)
plt.legend()
plt.tight_layout()
plt.show()
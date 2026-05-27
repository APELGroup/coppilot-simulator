import sys
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from pathlib import Path
from pandapower import from_excel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

# =========================
# SETTINGS
# =========================
NET_XLSX = str(config.NET_PP_XLSX)

# Pandapower trafo results (from pp timeseries export)
PP_TRAFO_CSV = str(config.RESULTS_RES_TRAFO / "loading_percent.csv")

# OpenDSS trafo results
DSS_XLSX  = str(config.DSS_TRAFO_LOADING_XLSX)
DSS_SHEET = config.DSS_TRAFO_LOADING_SHEET

# Trafo name from net.trafo["name"]
TRAFO_NAME = "mv_f0_lv_O_NEILL_20"   # <-- ΒΑΛΕ ΕΔΩ

# time axis (30min, 48 steps)
START_DATETIME = "2021-01-01 00:00"
PERIODS = 48
FREQ = "30min"
idx_date = pd.date_range(START_DATETIME, periods=PERIODS, freq=FREQ)

# plot formatting
hours = mdates.HourLocator(interval=4)
h_fmt = mdates.DateFormatter("%H:%M")

# =========================
# 1) Pandapower: trafo name -> trafo index -> column in loading_percent.csv
# =========================
net = from_excel(NET_XLSX)
net.trafo["name"] = net.trafo["name"].astype(str)

matches = net.trafo.index[net.trafo["name"].str.lower() == TRAFO_NAME.lower()].tolist()
if not matches:
    suggestions = net.trafo["name"][net.trafo["name"].str.contains(TRAFO_NAME, case=False, na=False)].head(30).tolist()
    raise KeyError(
        f"Trafo name '{TRAFO_NAME}' δεν βρέθηκε στο net.trafo['name'].\n"
        f"Παρόμοια names: {suggestions}"
    )
trafo_idx = matches[0]

pp = pd.read_csv(PP_TRAFO_CSV, sep=";", engine="python")
if "time_step" in pp.columns:
    pp = pp.set_index("time_step")
else:
    pp = pp.set_index(pp.columns[0])
pp = pp.apply(pd.to_numeric, errors="coerce")

pp_col = str(trafo_idx)
if pp_col not in pp.columns:
    if trafo_idx in pp.columns:
        pp_col = trafo_idx
    else:
        raise KeyError(
            f"Στο pandapower res_trafo/loading_percent.csv δεν υπάρχει στήλη για trafo index {trafo_idx}.\n"
            f"Διαθέσιμες στήλες (πρώτες 30): {list(pp.columns[:30])}"
        )

y_pp = pp[pp_col].dropna()
x_pp = idx_date[:len(y_pp)] if len(y_pp) <= len(idx_date) else pd.RangeIndex(len(y_pp))

# =========================
# 2) OpenDSS: read excel (column name matches TRAFO_NAME case-insensitive)
# =========================
dss = pd.read_excel(DSS_XLSX, sheet_name=DSS_SHEET)

# index = timestep (ή timestamp)
if "timestamp" in dss.columns:
    dss["timestamp"] = pd.to_datetime(dss["timestamp"], errors="coerce")
    dss = dss.set_index("timestamp")
elif "timestep" in dss.columns:
    dss = dss.set_index("timestep")
else:
    first = dss.columns[0]
    if str(first).lower().startswith("unnamed"):
        dss = dss.set_index(first)

dss = dss.apply(pd.to_numeric, errors="coerce")

# find DSS column case-insensitive
dss_col = None
for c in dss.columns:
    if str(c).strip().lower() == TRAFO_NAME.strip().lower():
        dss_col = c
        break

if dss_col is None:
    close = [c for c in dss.columns if TRAFO_NAME.lower() in str(c).lower()]
    raise KeyError(
        f"Trafo '{TRAFO_NAME}' δεν βρέθηκε στο OpenDSS excel columns.\n"
        f"Παρόμοια columns: {close[:30]}"
    )

y_dss = dss[dss_col].dropna()
x_dss = idx_date[:len(y_dss)] if len(y_dss) <= len(idx_date) else pd.RangeIndex(len(y_dss))

# =========================
# 3) Plot both together
# =========================
plt.rcParams["font.size"] = 10
fig, ax = plt.subplots(dpi=150, figsize=(9, 3.3))

ax.plot(x_pp, y_pp, linewidth=2, label="Pandapower ")
ax.plot(x_dss, y_dss, linewidth=2, linestyle="--", label="OpenDSS ")

ax.axhline(100, linewidth=1, linestyle=":", label="100% line")

# x formatting (only if datetime axis)
ax.xaxis.set_major_locator(hours)
ax.xaxis.set_major_formatter(h_fmt)

ax.set_xlabel("Time of the day")
ax.set_ylabel("Transformer utilisation [%]")
ax.set_title(f"{TRAFO_NAME}  |  PP trafo_idx={trafo_idx}  |  DSS col='{dss_col}'")

ax.grid(color="grey", linestyle="-", linewidth=0.2)
ax.legend(loc="best")
plt.tight_layout()
plt.show()

# =========================
# 4) Min/Max prints
# =========================
def _minmax(series, label):
    mn = float(series.min())
    mx = float(series.max())
    mn_i = series.idxmin()
    mx_i = series.idxmax()
    print(f"--- {label} ---")
    print(f"Min %: {mn:.2f} at {mn_i}")
    print(f"Max %: {mx:.2f} at {mx_i}")

print("===== TRAFO RESULTS (overlay) =====")
print(f"Trafo name (PP): {TRAFO_NAME}")
print(f"Pandapower trafo index: {trafo_idx}")
print(f"OpenDSS column used: {dss_col}")
_minmax(y_pp, "Pandapower")
_minmax(y_dss, "OpenDSS")
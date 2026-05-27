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

# Pandapower line results (from pp timeseries export)
PP_LINE_CSV = str(config.RESULTS_RES_LINE / "loading_percent.csv")

# OpenDSS line results
DSS_XLSX  = str(config.DSS_MV_LINE_LOADING_XLSX)
DSS_SHEET = config.DSS_MV_LINE_LOADING_SHEET

# Line name from net.line["name"]
LINE_NAME = "mv_f0_l479"   # <-- ΒΑΛΕ ΕΔΩ τη γραμμή που θες

# time axis (30min, 48 steps)
START_DATETIME = "2021-01-01 00:00"
PERIODS = 48
FREQ = "30min"
idx_date = pd.date_range(START_DATETIME, periods=PERIODS, freq=FREQ)

# plot formatting
hours = mdates.HourLocator(interval=4)
h_fmt = mdates.DateFormatter("%H:%M")

# =========================
# 1) Pandapower: line name -> line index -> column in loading_percent.csv
# =========================
net = from_excel(NET_XLSX)
net.line["name"] = net.line["name"].astype(str)

matches = net.line.index[net.line["name"].str.lower() == LINE_NAME.lower()].tolist()
if not matches:
    suggestions = net.line["name"][net.line["name"].str.contains(LINE_NAME, case=False, na=False)].head(30).tolist()
    raise KeyError(
        f"Line name '{LINE_NAME}' δεν βρέθηκε στο net.line['name'].\n"
        f"Παρόμοια names: {suggestions}"
    )
line_idx = matches[0]

pp = pd.read_csv(PP_LINE_CSV, sep=";", engine="python")
if "time_step" in pp.columns:
    pp = pp.set_index("time_step")
else:
    pp = pp.set_index(pp.columns[0])
pp = pp.apply(pd.to_numeric, errors="coerce")

pp_col = str(line_idx)
if pp_col not in pp.columns:
    if line_idx in pp.columns:
        pp_col = line_idx
    else:
        raise KeyError(
            f"Στο pandapower res_line/loading_percent.csv δεν υπάρχει στήλη για line index {line_idx}.\n"
            f"Διαθέσιμες στήλες (πρώτες 30): {list(pp.columns[:30])}"
        )

y_pp = pp[pp_col].dropna()
x_pp = idx_date[:len(y_pp)] if len(y_pp) <= len(idx_date) else pd.RangeIndex(len(y_pp))

# =========================
# 2) OpenDSS: read excel (column name matches LINE_NAME case-insensitive)
# =========================
dss = pd.read_excel(DSS_XLSX, sheet_name=DSS_SHEET, index_col=0)
# index should already be timestamp, but try to parse just in case
try:
    dss.index = pd.to_datetime(dss.index, errors="coerce")
except:
    pass

dss = dss.apply(pd.to_numeric, errors="coerce")

# find DSS column case-insensitive
dss_col = None
for c in dss.columns:
    if str(c).strip().lower() == LINE_NAME.strip().lower():
        dss_col = c
        break

if dss_col is None:
    close = [c for c in dss.columns if LINE_NAME.lower() in str(c).lower()]
    raise KeyError(
        f"Line '{LINE_NAME}' δεν βρέθηκε στο OpenDSS excel columns.\n"
        f"Παρόμοια columns: {close[:30]}"
    )

y_dss = dss[dss_col].dropna()
x_dss = idx_date[:len(y_dss)] if len(y_dss) <= len(idx_date) else pd.RangeIndex(len(y_dss))

# =========================
# 3) Plot both together
# =========================
plt.rcParams["font.size"] = 10
fig, ax = plt.subplots(dpi=150, figsize=(9, 3.3))

ax.plot(x_pp, y_pp, linewidth=2, label="Pandapower")
ax.plot(x_dss, y_dss, linewidth=2, linestyle="--", label="OpenDSS")

ax.axhline(100, linewidth=1, linestyle=":", label="100% line")

ax.xaxis.set_major_locator(hours)
ax.xaxis.set_major_formatter(h_fmt)

ax.set_xlabel("Time of the day")
ax.set_ylabel("Line utilisation [%]")
ax.set_title(f"{LINE_NAME}")

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

print("===== LINE RESULTS (overlay) =====")
print(f"Line name (PP): {LINE_NAME}")
print(f"Pandapower line index: {line_idx}")
print(f"OpenDSS column used: {dss_col}")
_minmax(y_pp, "Pandapower")
_minmax(y_dss, "OpenDSS")
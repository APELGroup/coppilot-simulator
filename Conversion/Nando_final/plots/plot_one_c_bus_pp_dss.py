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
NET_XLSX  = str(config.NET_PP_XLSX)
PP_VM_CSV = str(config.RESULTS_RES_BUS / "vm_pu.csv")

DSS_XLSX  = str(config.DSS_VM_PU_XLSX)
DSS_SHEET = config.DSS_VM_PU_SHEET

BUS_NAME = "mv_f0_lv273_f0_c0"   # bus name from net.bus["name"]

# time axis (30min, 48 steps)
START_DATETIME = "2021-01-01 00:00"
PERIODS = 48
FREQ = "30min"
idx_date = pd.date_range(START_DATETIME, periods=PERIODS, freq=FREQ)

# limits
V_UP  = 1.10
V_LOW = 0.94

# plot formatting
hours = mdates.HourLocator(interval=4)
h_fmt = mdates.DateFormatter("%H:%M")

# =========================
# 1) Pandapower: bus name -> bus index -> column in vm_pu.csv
# =========================
net = from_excel(NET_XLSX)
net.bus["name"] = net.bus["name"].astype(str)

matches = net.bus.index[net.bus["name"].str.lower() == BUS_NAME.lower()].tolist()
if not matches:
    suggestions = net.bus["name"][net.bus["name"].str.contains(BUS_NAME, case=False, na=False)].head(20).tolist()
    raise KeyError(
        f"Bus name '{BUS_NAME}' δεν βρέθηκε στο net.bus['name'].\n"
        f"Παρόμοια names: {suggestions}"
    )
bus_idx = matches[0]

pp = pd.read_csv(PP_VM_CSV, sep=";", engine="python")
if "time_step" in pp.columns:
    pp = pp.set_index("time_step")
else:
    pp = pp.set_index(pp.columns[0])
pp = pp.apply(pd.to_numeric, errors="coerce")

pp_col = str(bus_idx)
if pp_col not in pp.columns:
    if bus_idx in pp.columns:
        pp_col = bus_idx
    else:
        raise KeyError(
            f"Στο pandapower vm_pu.csv δεν υπάρχει στήλη για bus index {bus_idx}.\n"
            f"Διαθέσιμες στήλες (πρώτες 30): {list(pp.columns[:30])}"
        )

y_pp = pp[pp_col].dropna()
x_pp = idx_date[:len(y_pp)] if len(y_pp) <= len(idx_date) else pd.RangeIndex(len(y_pp))

# =========================
# 2) OpenDSS: read excel (column name = BUS_NAME)
# =========================
dss = pd.read_excel(DSS_XLSX, sheet_name=DSS_SHEET)

if "timestep" in dss.columns:
    dss = dss.set_index("timestep")
else:
    first = dss.columns[0]
    if str(first).lower().startswith("unnamed"):
        dss = dss.set_index(first)

dss = dss.apply(pd.to_numeric, errors="coerce")

if BUS_NAME not in dss.columns:
    close = [c for c in dss.columns if BUS_NAME.lower() in str(c).lower()]
    raise KeyError(
        f"Bus '{BUS_NAME}' δεν βρέθηκε στο OpenDSS excel columns.\n"
        f"Παρόμοια columns: {close[:20]}"
    )

y_dss = dss[BUS_NAME].dropna()
x_dss = idx_date[:len(y_dss)] if len(y_dss) <= len(idx_date) else pd.RangeIndex(len(y_dss))

# =========================
# 3) Plot both together
# =========================
plt.rcParams["font.size"] = 10
fig, ax = plt.subplots(dpi=150, figsize=(9, 3.3))

ax.plot(x_pp, y_pp, linewidth=2, label="Pandapower")
ax.plot(x_dss, y_dss, linewidth=2, linestyle="--", label="OpenDSS")

# limits lines
ax.axhline(V_LOW, linewidth=1, linestyle=":", label=f"V_LOW={V_LOW}")
ax.axhline(V_UP,  linewidth=1, linestyle=":", label=f"V_UP={V_UP}")

# x formatting (only if datetime index)
if isinstance(x_pp, pd.DatetimeIndex) or isinstance(x_dss, pd.DatetimeIndex):
    ax.xaxis.set_major_locator(hours)
    ax.xaxis.set_major_formatter(h_fmt)

ax.set_xlabel("Time of the day")
ax.set_ylabel("Voltage [pu]")
ax.set_title(f"{BUS_NAME}")

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
    print(f"Min pu: {mn:.4f} at {mn_i}")
    print(f"Max pu: {mx:.4f} at {mx_i}")

print("===== BUS RESULTS (overlay) =====")
print(f"Bus name: {BUS_NAME}")
print(f"Pandapower bus index: {bus_idx}")
_minmax(y_pp, "Pandapower")
_minmax(y_dss, "OpenDSS")
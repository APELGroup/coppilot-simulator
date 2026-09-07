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
VM_PATH  = str(config.RESULTS_RES_BUS / "vm_pu.csv")


BUS_NAME = "mv_f0_lv585_f0_c0"   # <<<<<<<<<<<<<< ΒΑΛΕ ΕΔΩ ΤΟ BUS NAME ΑΠΟ net.bus["name"]

# time axis (30min, 48 steps)
idx_date = pd.date_range("2021-01-01 00:00", periods=48, freq="30min")
hours = mdates.HourLocator(interval=4)
h_fmt = mdates.DateFormatter("%H:%M")

V_UP  = 1.1
V_LOW = 0.94 

# =========================
# 1) Load pandapower net and find the bus index for BUS_NAME
# =========================
net = from_excel(NET_XLSX)
net.bus["name"] = net.bus["name"].astype(str)

matches = net.bus.index[net.bus["name"].str.lower() == BUS_NAME.lower()].tolist()
if not matches:
    # helpful suggestions
    suggestions = net.bus["name"][net.bus["name"].str.contains(BUS_NAME, case=False, na=False)].head(20).tolist()
    raise KeyError(
        f"Bus name '{BUS_NAME}' δεν βρέθηκε στο net.bus['name'].\n"
        f"Παρόμοια names: {suggestions}"
    )
bus_idx = matches[0]  # if duplicates exist, take first

# =========================
# 2) Read vm_pu.csv and pick only this bus column
# =========================
df = pd.read_csv(VM_PATH, sep=";", engine="python")

# index = time_step
if "time_step" in df.columns:
    df = df.set_index("time_step")
else:
    df = df.set_index(df.columns[0])

df = df.apply(pd.to_numeric, errors="coerce")

col = str(bus_idx)
if col not in df.columns:
    # sometimes columns are ints not strings
    if bus_idx in df.columns:
        col = bus_idx
    else:
        raise KeyError(
            f"Στο vm_pu.csv δεν υπάρχει στήλη για bus index {bus_idx}.\n"
            f"Διαθέσιμες στήλες (πρώτες 30): {list(df.columns[:30])}"
        )

y = df[col]

# fix x-axis length if needed
x = idx_date[:len(y)]

# =========================
# 3) Plot ONLY this bus
# =========================
plt.rcParams["font.size"] = 10
fig, ax = plt.subplots(dpi=150, figsize=(8, 3))

ax.plot(x, y, linewidth=2)

ax.xaxis.set_major_locator(hours)
ax.xaxis.set_major_formatter(h_fmt)

ax.set_xlabel("Time of the day")
ax.set_ylabel("Voltage [pu]")
ax.set_title(f"{BUS_NAME} - Pandapower ")

ax.grid(color="grey", linestyle="-", linewidth=0.2)


plt.tight_layout()
plt.show()

# =========================
# 4) Min/Max for this bus
# =========================
min_val = float(y.min())
max_val = float(y.max())
min_t = y.idxmin()
max_t = y.idxmax()

print("----- BUS RESULTS -----")
print(f"Bus name: {BUS_NAME}")
print(f"Bus index: {bus_idx}")
print(f"Min pu: {min_val:.4f} at time_step {min_t}")
print(f"Max pu: {max_val:.4f} at time_step {max_t}")

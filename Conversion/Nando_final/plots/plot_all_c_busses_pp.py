import sys
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from pathlib import Path
from pandapower import from_excel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

net = from_excel(str(config.NET_PP_XLSX))
vm_path = str(config.RESULTS_RES_BUS / "vm_pu.csv")

# -----------------------
# 1) Πάρε customer bus indices από το net
# -----------------------
net.bus["name"] = net.bus["name"].astype(str)
customer_bus_indices = net.bus[
    net.bus["name"].str.contains(r"_c\d+", case=False, na=False)
].index.tolist()

customer_cols_set = set(map(str, customer_bus_indices))

# -----------------------
# 2) Διάβασε vm_pu.csv
# -----------------------
df = pd.read_csv(vm_path, sep=";", engine="python")

if "time_step" in df.columns:
    df = df.set_index("time_step")
else:
    df = df.set_index(df.columns[0])

df = df.apply(pd.to_numeric, errors="coerce")

# -----------------------
# 3) Κράτα μόνο customer buses
# -----------------------
cols = [c for c in df.columns if str(c) in customer_cols_set]
df = df[cols]

print("Customer buses found in results:", len(cols))

# καθάρισμα: πέτα όσα είναι όλα NaN
df_pu = df.apply(pd.to_numeric, errors="coerce").dropna(axis=1, how="all")

# -----------------------
# 4) Mean voltage ανά timestep (mean curve)
# -----------------------
mean_per_timestep = df_pu.mean(axis=1, skipna=True)

# -----------------------
# 5) Time axis (30min resolution)
# -----------------------
idx_date = pd.date_range("2021-01-01 00:00", "2021-01-01 23:30", freq="30min")
hours = mdates.HourLocator(interval=4)
h_fmt = mdates.DateFormatter("%H:%M")

# Αν το index του df είναι time_step 0..47, κάνε align με idx_date
# (αν έχει άλλο μήκος, κόβουμε στο min)
n = min(len(idx_date), len(df_pu))
idx_date = idx_date[:n]
df_pu = df_pu.iloc[:n, :]
mean_per_timestep = mean_per_timestep.iloc[:n]

# -----------------------
# 6) Plot ΟΛΟΥΣ + mean curve
# -----------------------
plt.rcParams["font.size"] = 10
fig, ax = plt.subplots(dpi=150, figsize=(8, 3))

for col in df_pu.columns:
    ax.plot(idx_date, df_pu[col], alpha=0.2)

# mean voltage (pu) γραμμή
ax.plot(idx_date, mean_per_timestep, linewidth=2.2, color="black", label="Mean (customers)")

ax.xaxis.set_major_locator(hours)
ax.xaxis.set_major_formatter(h_fmt)

ax.set_xlabel("Time of the day")
ax.set_ylabel("Voltage [pu]")
ax.grid(color="grey", linestyle="-", linewidth=0.2)

# Voltage limits in pu (230 V base)
ax.axhline(y=253.0 / 230.0, linestyle="--")  # upper limit
ax.axhline(y=216.0 / 230.0, linestyle="--")  # lower limit

ax.legend(loc="best", frameon=True)
plt.tight_layout()
plt.show()

# -----------------------
# 7) Global stats
# -----------------------
global_min_value = df_pu.min().min()
global_max_value = df_pu.max().max()

min_bus = df_pu.min().idxmin()
max_bus = df_pu.max().idxmax()

min_time = df_pu[min_bus].idxmin()
max_time = df_pu[max_bus].idxmax()

global_mean_value = df_pu.stack(dropna=True).mean()
mean_min_value = mean_per_timestep.min()
mean_max_value = mean_per_timestep.max()

print("----- GLOBAL RESULTS (Customer Buses) -----")
print(f"Minimum pu: {global_min_value:.4f}")
print(f"  -> Bus: {min_bus}")
print(f"  -> Time step: {min_time}")

print(f"\nMaximum pu: {global_max_value:.4f}")
print(f"  -> Bus: {max_bus}")
print(f"  -> Time step: {max_time}")

print("\n----- MEAN VOLTAGE (Customers) -----")
print(f"Global mean pu (all buses & timesteps): {global_mean_value:.4f}")
print(f"Mean curve min pu: {mean_min_value:.4f} (time_step={mean_per_timestep.idxmin()})")
print(f"Mean curve max pu: {mean_max_value:.4f} (time_step={mean_per_timestep.idxmax()})")
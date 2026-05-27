import sys
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
from pandapower import from_excel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

# =========================
# CONFIG
# =========================
NET_XLSX          = str(config.NET_PP_XLSX)
TRAFO_LOADING_CSV = str(config.RESULTS_RES_TRAFO / "loading_percent.csv")


TIME_RES_HOURS = 0.5   # 30 min resolution

# =========================
# 0) Load network
# =========================
net = from_excel(NET_XLSX)

# =========================
# 1) Read loading_percent.csv
# =========================
df = pd.read_csv(TRAFO_LOADING_CSV, sep=";", engine="python")

if "time_step" in df.columns:
    df = df.set_index("time_step")
else:
    df = df.set_index(df.columns[0])

df = df.apply(pd.to_numeric, errors="coerce")
df.columns = df.columns.astype(int)

print("Trafos found in results:", len(df.columns))

# =========================
# 2) Keep ONLY trafos that exist in net
# =========================
trafo_indices = net.trafo.index.to_numpy()
trafo_indices = [i for i in trafo_indices if i in df.columns]

# =========================
# 3) REMOVE regulators
# =========================
# βρίσκουμε indices trafos που είναι regulators

if len(trafo_indices) == 0:
    raise RuntimeError("Δεν βρέθηκαν trafos μετά την αφαίρεση regulators.")

df_all = df[trafo_indices]

# =========================
# 4) Time axis
# =========================
t_hours = df_all.index.to_numpy() * TIME_RES_HOURS

# =========================
# 5) Plot ALL trafos (no regs)
# =========================
plt.figure()

for col in df_all.columns:
    plt.plot(t_hours, df_all[col], linewidth=0.7)

plt.xlabel("Time (hours)")
plt.ylabel("Loading (%)")
plt.title(f"Trafo Loading - All Trafos (No Regulators) ({len(df_all.columns)} trafos)")
plt.grid(True)
plt.show()

# =========================
# 6) GLOBAL MIN / MAX
# =========================
global_min_value = df_all.min().min()
global_max_value = df_all.max().max()

min_trafo = df_all.min().idxmin()
max_trafo = df_all.max().idxmax()

min_time = df_all[min_trafo].idxmin()
max_time = df_all[max_trafo].idxmax()

print("----- GLOBAL RESULTS (No Regulators) -----")
print(f"Minimum loading: {global_min_value:.2f} %")
print(f"  -> Trafo index: {min_trafo}")
print(f"  -> Time step: {min_time}")
print(f"  -> Time (hours): {min_time * TIME_RES_HOURS:.2f}")

print(f"\nMaximum loading: {global_max_value:.2f} %")
print(f"  -> Trafo index: {max_trafo}")
print(f"  -> Time step: {max_time}")
print(f"  -> Time (hours): {max_time * TIME_RES_HOURS:.2f}")
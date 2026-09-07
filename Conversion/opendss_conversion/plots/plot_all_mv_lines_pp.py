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
NET_XLSX    = str(config.NET_PP_XLSX)
LOADING_CSV = str(config.RESULTS_RES_LINE / "loading_percent.csv")

TIME_RES_HOURS = 0.5   # 30 min
MV_KV = 22.0           # MV voltage level

# =========================
# 0) Load network
# =========================
net = from_excel(NET_XLSX)

# =========================
# 1) Read loading_percent.csv
# =========================
df = pd.read_csv(LOADING_CSV, sep=";", engine="python")

if "time_step" in df.columns:
    df = df.set_index("time_step")
else:
    df = df.set_index(df.columns[0])

df = df.apply(pd.to_numeric, errors="coerce")

# Οι στήλες είναι indices -> κάνε τις int
df.columns = df.columns.astype(int)

print("Lines found in results:", len(df.columns))

# =========================
# 2) Βρες MV–MV lines από net.line (με indices)
# =========================
vn_from = net.bus.vn_kv.loc[net.line.from_bus].to_numpy()
vn_to   = net.bus.vn_kv.loc[net.line.to_bus].to_numpy()

mv_mask = (vn_from == MV_KV) & (vn_to == MV_KV)

mv_line_indices = net.line.index[mv_mask].to_numpy()

# κράτα μόνο όσες υπάρχουν στο CSV
mv_line_indices = [i for i in mv_line_indices if i in df.columns]

print("MV lines kept:", len(mv_line_indices))

if len(mv_line_indices) == 0:
    raise RuntimeError("Δεν βρέθηκαν MV lines που να ταιριάζουν με τα indices του CSV.")

df_mv = df[mv_line_indices]

# =========================
# 3) Time axis
# =========================
t_hours = df_mv.index.to_numpy() * TIME_RES_HOURS

# =========================
# 4) Plot ONLY MV lines
# =========================
plt.figure()

for col in df_mv.columns:
    plt.plot(t_hours, df_mv[col], linewidth=0.7)

plt.xlabel("Time (hours)")
plt.ylabel("Loading (%)")
plt.title(f"Line Loading - MV Only ({len(df_mv.columns)} lines)")
plt.grid(True)
plt.show()

# =========================
# 5) GLOBAL MIN / MAX
# =========================
global_min_value = df_mv.min().min()
global_max_value = df_mv.max().max()

min_line = df_mv.min().idxmin()
max_line = df_mv.max().idxmax()

min_time = df_mv[min_line].idxmin()
max_time = df_mv[max_line].idxmax()

print("----- GLOBAL RESULTS (MV Lines) -----")
print(f"Minimum loading: {global_min_value:.2f} %")
print(f"  -> Line index: {min_line}")
print(f"  -> Time step: {min_time}")
print(f"  -> Time (hours): {min_time * TIME_RES_HOURS:.2f}")

print(f"\nMaximum loading: {global_max_value:.2f} %")
print(f"  -> Line index: {max_line}")
print(f"  -> Time step: {max_time}")
print(f"  -> Time (hours): {max_time * TIME_RES_HOURS:.2f}")

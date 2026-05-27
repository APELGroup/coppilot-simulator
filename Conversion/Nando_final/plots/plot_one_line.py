import os
import re
import sys
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from pathlib import Path
from pandapower import from_excel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

# =========================
# SETTINGS
# =========================
NET_XLSX    = str(config.NET_PP_XLSX)
PP_LINE_CSV = str(config.RESULTS_RES_LINE / "loading_percent.csv")
DSS_CSV     = str(config.DSS_LINE_LOADING_CSV)
OUT_DIR     = str(config.PLOTS_DIR / "selected_lines_loading")

# Γραμμές που θες να γίνουν plot
TARGET_LINES = [
    "mv_f0_lv603_f0_l1_ls"
    
]

START_DATETIME = "2021-01-01 00:00"
PERIODS = 48
FREQ = "30min"
SHOW_PLOTS = True   # True αν θες να ανοίγουν και στην οθόνη

# =========================
# HELPERS
# =========================
def norm_name(x: str) -> str:
    s = str(x).strip().lower()
    s = re.sub(r"^line\.", "", s)
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s

def safe_filename(x: str) -> str:
    s = str(x).strip()
    s = re.sub(r'[<>:"/\\\\|?*]+', "_", s)
    s = s.replace(" ", "_")
    return s

# =========================
# PREP
# =========================
os.makedirs(OUT_DIR, exist_ok=True)
idx_date = pd.date_range(START_DATETIME, periods=PERIODS, freq=FREQ)

hours = mdates.HourLocator(interval=4)
h_fmt = mdates.DateFormatter("%H:%M")

# =========================
# LOAD NETWORK
# =========================
net = from_excel(NET_XLSX)
net.line["name"] = net.line["name"].astype(str)

# =========================
# READ PP CSV
# =========================
pp = pd.read_csv(PP_LINE_CSV, sep=";", engine="python")

if "time_step" in pp.columns:
    pp = pp.set_index("time_step")
else:
    pp = pp.set_index(pp.columns[0])

pp = pp.apply(pd.to_numeric, errors="coerce")
pp.columns = [str(c).strip() for c in pp.columns]

# =========================
# READ DSS CSV
# =========================
dss = pd.read_csv(DSS_CSV)

time_col_found = None
for c in dss.columns:
    if str(c).strip().lower() in ["time", "timestamp", "datetime"]:
        time_col_found = c
        break

if time_col_found is not None:
    dss = dss.set_index(time_col_found)
else:
    dss = dss.set_index(dss.columns[0])

try:
    dss.index = pd.to_datetime(dss.index, errors="coerce")
except Exception:
    pass

dss = dss.apply(pd.to_numeric, errors="coerce")
dss.columns = [str(c).strip() for c in dss.columns]

# =========================
# BUILD MAPS
# =========================
# pandapower: normalized line name -> (real line name, pp result column)
pp_map = {}
for line_idx, row in net.line.iterrows():
    if "in_service" in net.line.columns and not bool(row["in_service"]):
        continue

    pp_col = str(line_idx)
    if pp_col not in pp.columns:
        continue

    line_name = str(row["name"]).strip()
    pp_map[norm_name(line_name)] = (line_name, pp_col)

# OpenDSS: normalized dss column -> real dss column
dss_map = {}
for c in dss.columns:
    dss_map[norm_name(c)] = c

# =========================
# PLOT ONLY TARGET LINES
# =========================
for target in TARGET_LINES:
    k = norm_name(target)

    if k not in pp_map:
        print(f"[SKIP] Δεν βρέθηκε στο pandapower: {target}")
        continue

    if k not in dss_map:
        print(f"[SKIP] Δεν βρέθηκε στο OpenDSS: {target}")
        continue

    line_name, pp_col = pp_map[k]
    dss_col = dss_map[k]

    y_pp = pp[pp_col].to_numpy(dtype=float)
    y_dss = dss[dss_col].to_numpy(dtype=float)

    n = min(len(y_pp), len(y_dss), len(idx_date))
    if n == 0:
        print(f"[SKIP] Δεν υπάρχουν δεδομένα για: {target}")
        continue

    x = idx_date[:n]
    y_pp = y_pp[:n]
    y_dss = y_dss[:n]

    plt.rcParams["font.size"] = 10
    fig, ax = plt.subplots(figsize=(9, 3.5), dpi=150)

    ax.plot(x, y_pp, linewidth=2, label="Pandapower")
    ax.plot(x, y_dss, linewidth=2, linestyle="--", label="OpenDSS")
    ax.axhline(100, linewidth=1, linestyle=":", label="100%")

    ax.xaxis.set_major_locator(hours)
    ax.xaxis.set_major_formatter(h_fmt)

    ax.set_xlabel("Time of the day")
    ax.set_ylabel("Loading [%]")
    ax.set_title(line_name)
    ax.grid(color="grey", linestyle="-", linewidth=0.2)
    ax.legend(loc="best")

    plt.tight_layout()

    out_png = os.path.join(OUT_DIR, f"{safe_filename(line_name)}.png")
    plt.savefig(out_png, bbox_inches="tight")

    print(f"[OK] Saved: {out_png}")
    print(f"     PP col : {pp_col}")
    print(f"     DSS col: {dss_col}")

    if SHOW_PLOTS:
        plt.show()
    else:
        plt.close(fig)
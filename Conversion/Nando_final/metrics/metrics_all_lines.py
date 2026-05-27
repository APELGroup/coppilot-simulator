import sys
import pandas as pd
import numpy as np
import re
from pathlib import Path
from pandapower import from_excel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

# =========================
# PATHS / SETTINGS  (from config.py)
# =========================
NET_XLSX      = str(config.NET_PP_XLSX)
PP_LINE_CSV   = str(config.RESULTS_RES_LINE / "loading_percent.csv")
DSS_CSV       = str(config.DSS_LINE_LOADING_CSV)
OUT_XLSX_MV   = str(config.METRICS_OUT_DIR / "mv_line_loading_metrics.xlsx")
OUT_XLSX_LV   = str(config.METRICS_OUT_DIR / "lv_line_loading_metrics.xlsx")

config.METRICS_OUT_DIR.mkdir(parents=True, exist_ok=True)
SEP = ";"


# =========================
# NAME NORMALIZER
# =========================
def norm_name(x: str) -> str:
    s = str(x).strip().lower()
    s = re.sub(r"^line\.", "", s)
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s


# =========================
# BUILD PP NAME MAP
# =========================
def build_pp_name_map(net, pp_columns):
    mapping = {}

    for line_idx, row in net.line.iterrows():
        if "in_service" in net.line.columns and not bool(row["in_service"]):
            continue

        pp_col = str(line_idx)
        if pp_col not in pp_columns:
            continue

        mapping[pp_col] = str(row["name"]).strip()

    return mapping


# =========================
# LOAD NETWORK
# =========================
net = from_excel(NET_XLSX)
net.line["name"] = net.line["name"].astype(str)


# =========================
# READ PP loading_percent.csv
# =========================
pp = pd.read_csv(PP_LINE_CSV, sep=SEP, engine="python")

if "time_step" in pp.columns:
    pp = pp.set_index("time_step")
else:
    pp = pp.set_index(pp.columns[0])

pp = pp.apply(pd.to_numeric, errors="coerce")
pp.columns = [str(c).strip() for c in pp.columns]


# =========================
# READ DSS all-lines CSV
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

dss = dss.apply(pd.to_numeric, errors="coerce")
dss.columns = [str(c).strip() for c in dss.columns]


# =========================
# BUILD NAME MAPS
# =========================
pp_name_map = build_pp_name_map(net, pp.columns)

pp_norm_map = {}
for pp_col, pp_name in pp_name_map.items():
    k = norm_name(pp_name)
    if k not in pp_norm_map:
        pp_norm_map[k] = pp_col

dss_norm_map = {}
for dss_col in dss.columns:
    k = norm_name(dss_col)
    if k not in dss_norm_map:
        dss_norm_map[k] = dss_col


# =========================
# MATCH COMMON LINES + METRICS
# =========================
rows = []

common_keys = sorted(set(pp_norm_map.keys()) & set(dss_norm_map.keys()))

for k in common_keys:
    pp_col = pp_norm_map[k]
    dss_col = dss_norm_map[k]

    line_name = pp_name_map[pp_col]

    s_pp = pp[pp_col].to_numpy(dtype=float)
    s_dss = dss[dss_col].to_numpy(dtype=float)

    n = min(len(s_pp), len(s_dss))
    if n == 0:
        continue

    a_pp = s_pp[:n]
    a_dss = s_dss[:n]

    mask = (~np.isnan(a_pp)) & (~np.isnan(a_dss))
    if not np.any(mask):
        continue

    diff_pp = a_pp[mask] - a_dss[mask]

    rows.append({
        "line_name": line_name,
        "pp_line_idx": pp_col,
        "dss_col": str(dss_col),
        "N": int(diff_pp.size),
        "MAE_pp": float(np.mean(np.abs(diff_pp))),
        "Bias_pp": float(np.mean(diff_pp)),
        "MaxAbs_pp": float(np.max(np.abs(diff_pp))),
        "is_lv": bool(re.search(r'_lv', line_name, re.IGNORECASE)),
    })


# =========================
# SUMMARY – split MV / LV
# =========================
IS_LV = re.compile(r'_lv', re.IGNORECASE)

summary_cols = ["line_name", "pp_line_idx", "dss_col", "N", "MAE_pp", "Bias_pp", "MaxAbs_pp"]

all_df = pd.DataFrame(rows)

def build_summary(df):
    if df.empty:
        return pd.DataFrame(columns=summary_cols)
    df = df[summary_cols].copy()
    df = df.sort_values("MAE_pp", ascending=False).reset_index(drop=True)
    global_row = pd.DataFrame([{
        "line_name": "=== GLOBAL MEAN (all matched lines) ===",
        "pp_line_idx": "",
        "dss_col": "",
        "N": int(df["N"].sum()),
        "MAE_pp": float(df["MAE_pp"].mean()),
        "Bias_pp": float(df["Bias_pp"].mean()),
        "MaxAbs_pp": float(df["MaxAbs_pp"].max()),
    }], columns=summary_cols)
    return pd.concat([global_row, df], ignore_index=True)

mv_rows = all_df[~all_df["is_lv"]] if not all_df.empty else all_df
lv_rows = all_df[all_df["is_lv"]]  if not all_df.empty else all_df

summary_mv = build_summary(mv_rows)
summary_lv = build_summary(lv_rows)


# =========================
# EXPORT – two files
# =========================
with pd.ExcelWriter(OUT_XLSX_MV, engine="openpyxl") as writer:
    summary_mv.to_excel(writer, index=False, sheet_name="summary")

with pd.ExcelWriter(OUT_XLSX_LV, engine="openpyxl") as writer:
    summary_lv.to_excel(writer, index=False, sheet_name="summary")

print("DONE")
print(f"MV matched: {len(mv_rows)}  → {OUT_XLSX_MV}")
print(f"LV matched: {len(lv_rows)}  → {OUT_XLSX_LV}")